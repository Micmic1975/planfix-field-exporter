"""Read-only Planfix custom field probe.

Скрипт делает только read-only запросы к Planfix REST API и сохраняет ответы
в output/planfix_probe. Все запросы проходят через rate limit 1.25 секунды.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import requests


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from planfix_export_fields_interactive import load_config

SWAGGER_PATH = ROOT_DIR / "inputs" / "swagger.json"
OUTPUT_ROOT = ROOT_DIR / "output" / "planfix_probe"
MIN_REQUEST_INTERVAL_SECONDS = 1.25

DOCUMENTED_CUSTOM_FIELD_FIELDS = [
    "id",
    "name",
    "names",
    "type",
    "objectType",
    "groupId",
    "directoryId",
    "directoryFields",
    "enumValues",
]
MAIN_CUSTOM_FIELD_FIELDS = DOCUMENTED_CUSTOM_FIELD_FIELDS + ["mainValue"]
PROJECT_CONFIRMED_EXTRA_FIELDS = [
    "formula",
    "viewResult",
    "delimiter",
    "numberOfDecimalPlaces",
]


class ProbeError(RuntimeError):
    """Ошибка разведочного скрипта без вывода токена."""


@dataclass
class Progress:
    stage: str
    processed_pages: int = 0
    processed_entities: int = 0
    last_request_at: str = ""
    output_file: Path | None = None
    message: str = ""


def print_progress(progress: Progress) -> None:
    output_file = str(progress.output_file) if progress.output_file else "-"
    last_request_at = progress.last_request_at or "-"
    print(
        "[progress] "
        f"этап={progress.stage}; "
        f"страниц={progress.processed_pages}; "
        f"сущностей={progress.processed_entities}; "
        f"последний_запрос={last_request_at}; "
        f"output={output_file}; "
        f"{progress.message}",
        flush=True,
    )


class SwaggerGuard:
    def __init__(self, swagger_path: Path) -> None:
        self.swagger_path = swagger_path
        with open(swagger_path, "r", encoding="utf-8") as file:
            self.swagger = json.load(file)
        self.paths = self.swagger.get("paths", {})

    def require_endpoint(self, method: str, path: str) -> None:
        methods = self.paths.get(path)
        if not isinstance(methods, dict) or method.lower() not in methods:
            raise ProbeError(
                f"Endpoint не подтвержден в inputs/swagger.json: {method.upper()} {path}"
            )


class RateLimitedPlanfixClient:
    def __init__(
        self,
        config: dict[str, Any],
        progress_callback: Callable[[Progress], None],
        min_interval_seconds: float = MIN_REQUEST_INTERVAL_SECONDS,
    ) -> None:
        self.config = config
        self.progress_callback = progress_callback
        self.min_interval_seconds = min_interval_seconds
        self.last_request_monotonic: float | None = None
        self.last_request_at = ""

    def _wait_before_request(self) -> None:
        if self.last_request_monotonic is None:
            return

        elapsed = time.monotonic() - self.last_request_monotonic
        remaining = self.min_interval_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        stage: str,
    ) -> dict[str, Any]:
        self._wait_before_request()

        url = f"{self.config['base_url']}{path}"
        headers = {
            "Authorization": f"Bearer {self.config['token']}",
            "Accept": "application/json",
        }
        if method.upper() == "POST":
            headers["Content-Type"] = "application/json"

        self.last_request_monotonic = time.monotonic()
        self.last_request_at = datetime.now().isoformat(timespec="seconds")
        self.progress_callback(
            Progress(
                stage=stage,
                last_request_at=self.last_request_at,
                message=f"Отправляю {method.upper()} {path}",
            )
        )

        try:
            response = requests.request(
                method.upper(),
                url,
                headers=headers,
                params=params,
                json=payload,
                timeout=60,
            )
        except requests.RequestException as error:
            raise ProbeError(
                f"Ошибка сети при запросе {method.upper()} {path}: {error}"
            ) from error

        if response.status_code != 200:
            response_text = response.text[:2000]
            raise ProbeError(
                f"Planfix вернул HTTP {response.status_code} для "
                f"{method.upper()} {path}.\nОтвет:\n{response_text}"
            )

        try:
            data = response.json()
        except ValueError as error:
            raise ProbeError(
                f"Planfix вернул не JSON для {method.upper()} {path}."
            ) from error

        if data.get("result") != "success":
            raise ProbeError(
                f"Planfix вернул неуспешный результат для {method.upper()} {path}:\n"
                f"{json.dumps(data, ensure_ascii=False, indent=2)[:2000]}"
            )

        return data

    def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        stage: str,
    ) -> dict[str, Any]:
        return self.request("GET", path, params=params, stage=stage)

    def post(
        self,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        stage: str,
    ) -> dict[str, Any]:
        return self.request("POST", path, payload=payload or {}, stage=stage)


def fields_param(fields: list[str]) -> str:
    return ",".join(fields)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def save_response(
    output_dir: Path,
    relative_name: str,
    data: dict[str, Any],
    progress_callback: Callable[[Progress], None],
    *,
    stage: str,
    processed_pages: int = 0,
    processed_entities: int = 0,
    last_request_at: str = "",
) -> Path:
    output_file = output_dir / relative_name
    write_json(output_file, data)
    progress_callback(
        Progress(
            stage=stage,
            processed_pages=processed_pages,
            processed_entities=processed_entities,
            last_request_at=last_request_at,
            output_file=output_file,
            message="Ответ сохранен",
        )
    )
    return output_file


def list_items_key(data: dict[str, Any], key: str, path: str) -> list[dict[str, Any]]:
    items = data.get(key, [])
    if not isinstance(items, list):
        raise ProbeError(f"В ответе {path} не найден массив `{key}`.")
    return [item for item in items if isinstance(item, dict)]


def probe_paged_endpoint(
    client: RateLimitedPlanfixClient,
    guard: SwaggerGuard,
    output_dir: Path,
    *,
    method: str,
    path: str,
    items_key: str,
    stage: str,
    max_pages: int,
    payload_base: dict[str, Any] | None = None,
    params_base: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    guard.require_endpoint(method, path)
    all_items: list[dict[str, Any]] = []

    for page_number in range(max_pages):
        offset = page_number * 100
        if method.upper() == "GET":
            params = dict(params_base or {})
            params.update({"offset": offset, "pageSize": 100})
            data = client.get(path, params=params, stage=stage)
        else:
            payload = dict(payload_base or {})
            payload.update({"offset": offset, "pageSize": 100})
            data = client.post(path, payload=payload, stage=stage)

        items = list_items_key(data, items_key, path)
        all_items.extend(items)
        save_response(
            output_dir,
            f"pages/{safe_name(path)}_page_{page_number + 1}.json",
            data,
            print_progress,
            stage=stage,
            processed_pages=page_number + 1,
            processed_entities=len(all_items),
            last_request_at=client.last_request_at,
        )

        if len(items) < 100:
            break

    return all_items


def safe_name(value: str) -> str:
    return value.strip("/").replace("/", "__").replace("{", "").replace("}", "")


def customfield_probe_fields(include_formula_probe: bool, is_main: bool = False) -> str:
    fields = list(MAIN_CUSTOM_FIELD_FIELDS if is_main else DOCUMENTED_CUSTOM_FIELD_FIELDS)
    if include_formula_probe:
        fields.extend(PROJECT_CONFIRMED_EXTRA_FIELDS)
    return fields_param(fields)


def probe_customfield_endpoint(
    client: RateLimitedPlanfixClient,
    guard: SwaggerGuard,
    output_dir: Path,
    *,
    path: str,
    stage: str,
    include_formula_probe: bool,
    is_main: bool = False,
) -> dict[str, Any]:
    guard.require_endpoint("GET", path)
    data = client.get(
        path,
        params={
            "fields": customfield_probe_fields(
                include_formula_probe=include_formula_probe,
                is_main=is_main,
            )
        },
        stage=stage,
    )
    save_response(
        output_dir,
        f"customfields/{safe_name(path)}.json",
        data,
        print_progress,
        stage=stage,
        processed_entities=len(data.get("customfields", [])),
        last_request_at=client.last_request_at,
    )
    return data


def probe_simple_get_endpoint(
    client: RateLimitedPlanfixClient,
    guard: SwaggerGuard,
    output_dir: Path,
    *,
    path: str,
    stage: str,
    output_name: str,
) -> dict[str, Any]:
    guard.require_endpoint("GET", path)
    data = client.get(path, stage=stage)
    save_response(
        output_dir,
        output_name,
        data,
        print_progress,
        stage=stage,
        last_request_at=client.last_request_at,
    )
    return data


def probe_scoped_customfields(
    client: RateLimitedPlanfixClient,
    guard: SwaggerGuard,
    output_dir: Path,
    *,
    path_template: str,
    ids: list[Any],
    stage: str,
    max_scoped_entities: int,
    include_formula_probe: bool,
) -> None:
    guard.require_endpoint("GET", path_template)
    for index, entity_id in enumerate(ids[:max_scoped_entities], start=1):
        path = path_template.replace("{id}", str(entity_id))
        data = client.get(
            path,
            params={
                "fields": customfield_probe_fields(
                    include_formula_probe=include_formula_probe,
                )
            },
            stage=stage,
        )
        save_response(
            output_dir,
            f"scoped_customfields/{safe_name(path_template)}_{entity_id}.json",
            data,
            print_progress,
            stage=stage,
            processed_entities=index,
            last_request_at=client.last_request_at,
        )


def extract_ids(items: list[dict[str, Any]]) -> list[Any]:
    ids = []
    for item in items:
        item_id = item.get("id")
        if item_id not in (None, ""):
            ids.append(item_id)
    return ids


def run_probe(args: argparse.Namespace) -> Path:
    guard = SwaggerGuard(SWAGGER_PATH)
    config = load_config()
    client = RateLimitedPlanfixClient(config, print_progress)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = OUTPUT_ROOT / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)

    metadata = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "swagger_path": str(SWAGGER_PATH),
        "min_request_interval_seconds": MIN_REQUEST_INTERVAL_SECONDS,
        "max_pages": args.max_pages,
        "max_scoped_entities": args.max_scoped_entities,
        "include_formula_probe": args.include_formula_probe,
        "account": config.get("account", ""),
        "note": "Токен доступа намеренно не сохраняется.",
    }
    write_json(output_dir / "metadata.json", metadata)
    print_progress(
        Progress(
            stage="Старт разведки",
            output_file=output_dir / "metadata.json",
            message="Метаданные сохранены",
        )
    )

    probe_simple_get_endpoint(
        client,
        guard,
        output_dir,
        path="/customfield/type",
        stage="Типы пользовательских полей",
        output_name="customfields/customfield__type.json",
    )

    for path, title, is_main in [
        ("/customfield/task", "Пользовательские поля задач", False),
        ("/customfield/contact", "Пользовательские поля контактов", False),
        ("/customfield/project", "Пользовательские поля проектов", False),
        ("/customfield/user", "Пользовательские поля сотрудников", False),
        ("/customfield/main", "Основные пользовательские поля", True),
    ]:
        probe_customfield_endpoint(
            client,
            guard,
            output_dir,
            path=path,
            stage=title,
            include_formula_probe=args.include_formula_probe,
            is_main=is_main,
        )

    objects = probe_paged_endpoint(
        client,
        guard,
        output_dir,
        method="POST",
        path="/object/list",
        items_key="objects",
        stage="Список объектов задач",
        max_pages=args.max_pages,
        payload_base={"fields": "id,name"},
    )
    task_templates = probe_paged_endpoint(
        client,
        guard,
        output_dir,
        method="GET",
        path="/task/templates",
        items_key="templates",
        stage="Список шаблонов задач",
        max_pages=args.max_pages,
        params_base={"fields": "id,name"},
    )
    contacts = probe_paged_endpoint(
        client,
        guard,
        output_dir,
        method="POST",
        path="/contact/list",
        items_key="contacts",
        stage="Список контактов и компаний",
        max_pages=args.max_pages,
        payload_base={"fields": "id,name,midname,lastname,isCompany", "prefixedId": True},
    )
    projects = probe_paged_endpoint(
        client,
        guard,
        output_dir,
        method="POST",
        path="/project/list",
        items_key="projects",
        stage="Список проектов",
        max_pages=args.max_pages,
        payload_base={"fields": "id,name"},
    )
    users = probe_paged_endpoint(
        client,
        guard,
        output_dir,
        method="POST",
        path="/user/list",
        items_key="users",
        stage="Список сотрудников",
        max_pages=args.max_pages,
        payload_base={"fields": "id,name,midname,lastname", "prefixedId": True},
    )
    directories = probe_paged_endpoint(
        client,
        guard,
        output_dir,
        method="POST",
        path="/directory/list",
        items_key="directories",
        stage="Список справочников",
        max_pages=args.max_pages,
        payload_base={"fields": "id,name,group"},
    )
    datatags = probe_paged_endpoint(
        client,
        guard,
        output_dir,
        method="POST",
        path="/datatag/list",
        items_key="dataTags",
        stage="Список аналитик",
        max_pages=args.max_pages,
        payload_base={"fields": "id,name,group,fields"},
    )

    scoped_sources = [
        ("/customfield/task/{id}", extract_ids(task_templates), "Поля конкретных шаблонов задач"),
        ("/customfield/contact/{id}", extract_ids(contacts), "Поля конкретных контактов"),
        ("/customfield/project/{id}", extract_ids(projects), "Поля конкретных проектов"),
        ("/customfield/user/{id}", extract_ids(users), "Поля конкретных сотрудников"),
        ("/customfield/directory/{id}", extract_ids(directories), "Поля конкретных справочников"),
        ("/customfield/datatag/{id}", extract_ids(datatags), "Поля конкретных аналитик"),
    ]

    for path_template, ids, stage in scoped_sources:
        if not ids:
            print_progress(
                Progress(
                    stage=stage,
                    output_file=output_dir,
                    message="Нет id для scoped-проверки",
                )
            )
            continue
        probe_scoped_customfields(
            client,
            guard,
            output_dir,
            path_template=path_template,
            ids=ids,
            stage=stage,
            max_scoped_entities=args.max_scoped_entities,
            include_formula_probe=args.include_formula_probe,
        )

    summary = {
        "objects": len(objects),
        "task_templates": len(task_templates),
        "contacts": len(contacts),
        "projects": len(projects),
        "users": len(users),
        "directories": len(directories),
        "datatags": len(datatags),
    }
    write_json(output_dir / "summary.json", summary)
    print_progress(
        Progress(
            stage="Завершено",
            output_file=output_dir / "summary.json",
            message="Сводка сохранена",
        )
    )
    return output_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only разведка пользовательских полей Planfix. "
            "Использует сохраненные настройки приложения или legacy config.json."
        )
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=1,
        help="Сколько страниц списков сущностей читать. По умолчанию 1.",
    )
    parser.add_argument(
        "--max-scoped-entities",
        type=int,
        default=2,
        help="Сколько сущностей каждого типа проверять scoped endpoints. По умолчанию 2.",
    )
    parser.add_argument(
        "--include-formula-probe",
        action="store_true",
        help=(
            "Явно запросить formula/viewResult/delimiter/numberOfDecimalPlaces. "
            "Эти поля не документированы в swagger для /customfield/* и нужны "
            "только для проверки реальных ответов API."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.max_pages < 1:
        raise ProbeError("--max-pages должен быть больше 0.")
    if args.max_scoped_entities < 0:
        raise ProbeError("--max-scoped-entities не может быть меньше 0.")

    output_dir = run_probe(args)
    print(f"Готово. Результаты сохранены: {output_dir}")


if __name__ == "__main__":
    main()
