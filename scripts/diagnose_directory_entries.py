"""Read-only diagnostic for Planfix directory entry list requests.

Скрипт помогает понять, на каком наборе полей или offset падает
/directory/{id}/entry/list. Все HTTP-запросы идут с паузой минимум 1.25 секунды.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from planfix_export_fields_interactive import load_config


SWAGGER_PATH = ROOT_DIR / "inputs" / "swagger.json"
OUTPUT_ROOT = ROOT_DIR / "output" / "directory_diagnostics"
MIN_REQUEST_INTERVAL_SECONDS = 1.25
BASE_ENTRY_FIELDS = "directory,key,parentKey,name,archived,isGroup"


class DiagnosticError(RuntimeError):
    pass


@dataclass
class RequestResult:
    label: str
    method: str
    path: str
    status_code: int | None
    ok: bool
    requested_at: str
    params: dict[str, Any] | None = None
    payload: dict[str, Any] | None = None
    response_preview: Any = None
    entries_count: int | None = None
    error: str = ""


class SwaggerGuard:
    def __init__(self, swagger_path: Path) -> None:
        with open(swagger_path, "r", encoding="utf-8") as file:
            self.swagger = json.load(file)

    def require_endpoint(self, method: str, path: str) -> None:
        methods = self.swagger.get("paths", {}).get(path)
        if not isinstance(methods, dict) or method.lower() not in methods:
            raise DiagnosticError(
                f"Endpoint не подтвержден в inputs/swagger.json: {method.upper()} {path}"
            )


class DiagnosticClient:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.last_request_monotonic: float | None = None

    def _wait_before_request(self) -> None:
        if self.last_request_monotonic is None:
            return

        elapsed = time.monotonic() - self.last_request_monotonic
        remaining = MIN_REQUEST_INTERVAL_SECONDS - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def request(
        self,
        method: str,
        path: str,
        *,
        label: str,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> RequestResult:
        self._wait_before_request()

        requested_at = datetime.now().isoformat(timespec="seconds")
        print(
            "[progress] "
            f"этап={label}; "
            f"последний_запрос={requested_at}; "
            f"payload={json.dumps(payload or params or {}, ensure_ascii=False)}",
            flush=True,
        )

        headers = {
            "Authorization": f"Bearer {self.config['token']}",
            "Accept": "application/json",
        }
        if method.upper() == "POST":
            headers["Content-Type"] = "application/json"

        self.last_request_monotonic = time.monotonic()
        try:
            response = requests.request(
                method.upper(),
                f"{self.config['base_url']}{path}",
                headers=headers,
                params=params,
                json=payload,
                timeout=60,
            )
        except requests.RequestException as error:
            return RequestResult(
                label=label,
                method=method.upper(),
                path=path,
                status_code=None,
                ok=False,
                requested_at=requested_at,
                params=params,
                payload=payload,
                error=str(error),
            )

        try:
            response_data: Any = response.json()
        except ValueError:
            response_data = response.text[:2000]

        entries = None
        if isinstance(response_data, dict) and isinstance(
            response_data.get("directoryEntries"),
            list,
        ):
            entries = len(response_data["directoryEntries"])

        return RequestResult(
            label=label,
            method=method.upper(),
            path=path,
            status_code=response.status_code,
            ok=response.status_code == 200
            and isinstance(response_data, dict)
            and response_data.get("result") == "success",
            requested_at=requested_at,
            params=params,
            payload=payload,
            response_preview=response_data,
            entries_count=entries,
        )


def text_fields_from_directory(directory: dict[str, Any]) -> list[dict[str, Any]]:
    fields = directory.get("fields", [])
    if not isinstance(fields, list):
        return []

    return [
        field
        for field in fields
        if isinstance(field, dict) and field.get("type") == 2 and field.get("id")
    ]


def build_entry_payload(offset: int, page_size: int, fields: str) -> dict[str, Any]:
    return {
        "offset": offset,
        "pageSize": page_size,
        "fields": fields,
        "entriesOnly": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory_id")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument(
        "--max-text-fields",
        type=int,
        default=None,
        help="Ограничить количество проверяемых текстовых полей.",
    )
    args = parser.parse_args()

    guard = SwaggerGuard(SWAGGER_PATH)
    guard.require_endpoint("GET", "/directory/{id}")
    guard.require_endpoint("POST", "/directory/{id}/entry/list")

    output_dir = OUTPUT_ROOT / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{args.directory_id}"
    output_dir.mkdir(parents=True, exist_ok=True)
    report_file = output_dir / "diagnostic_report.json"

    config = load_config()
    client = DiagnosticClient(config)
    path = f"/directory/{args.directory_id}"
    entry_path = f"/directory/{args.directory_id}/entry/list"
    results: list[RequestResult] = []

    directory_result = client.request(
        "GET",
        path,
        label="Загрузка структуры справочника",
        params={"fields": "id,name,group,fields"},
    )
    results.append(directory_result)

    directory = {}
    if isinstance(directory_result.response_preview, dict):
        directory = directory_result.response_preview.get("directory", {}) or {}

    text_fields = text_fields_from_directory(directory)
    if args.max_text_fields is not None:
        text_fields = text_fields[: args.max_text_fields]

    base_result = client.request(
        "POST",
        entry_path,
        label="Первая страница: только базовые поля",
        payload=build_entry_payload(
            args.offset,
            args.page_size,
            BASE_ENTRY_FIELDS,
        ),
    )
    results.append(base_result)

    if text_fields:
        all_text_field_ids = ",".join(str(field["id"]) for field in text_fields)
        all_fields_result = client.request(
            "POST",
            entry_path,
            label="Первая страница: все текстовые поля",
            payload=build_entry_payload(
                args.offset,
                args.page_size,
                f"{BASE_ENTRY_FIELDS},{all_text_field_ids}",
            ),
        )
        results.append(all_fields_result)

    for index, field in enumerate(text_fields, start=1):
        result = client.request(
            "POST",
            entry_path,
            label=f"Текстовое поле {index}/{len(text_fields)}: {field.get('name', '')}",
            payload=build_entry_payload(
                args.offset,
                args.page_size,
                f"{BASE_ENTRY_FIELDS},{field['id']}",
            ),
        )
        results.append(result)

    report = {
        "directory_id": args.directory_id,
        "directory": {
            "id": directory.get("id"),
            "name": directory.get("name"),
            "group": directory.get("group"),
        },
        "offset": args.offset,
        "page_size": args.page_size,
        "text_fields": text_fields,
        "results": [asdict(result) for result in results],
    }
    with open(report_file, "w", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)

    failures = [result for result in results if not result.ok]
    print(
        "[done] "
        f"output={report_file}; "
        f"текстовых_полей={len(text_fields)}; "
        f"проверок={len(results)}; "
        f"ошибок={len(failures)}",
        flush=True,
    )

    if failures:
        for failure in failures:
            print(
                "[failure] "
                f"{failure.label}; "
                f"status={failure.status_code}; "
                f"payload={json.dumps(failure.payload or {}, ensure_ascii=False)}; "
                f"response={json.dumps(failure.response_preview, ensure_ascii=False)[:500]}",
                flush=True,
            )
        raise SystemExit(2)


if __name__ == "__main__":
    main()
