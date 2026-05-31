import csv
import html
import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import requests


MIN_REQUEST_INTERVAL_SECONDS = 1.25
MAX_REQUEST_ATTEMPTS = 3
RETRYABLE_HTTP_STATUSES = {500, 502, 503, 504}
CALCULATED_FIELD_TYPE_ID = 24
FORMULA_FIELDS_PARAM = ",".join(
    [
        "id",
        "name",
        "names",
        "type",
        "objectType",
        "groupId",
        "directoryId",
        "directoryFields",
        "enumValues",
        "formula",
        "viewResult",
        "delimiter",
        "numberOfDecimalPlaces",
    ]
)
OUTPUT_COLUMNS = [
    "Уверенность",
    "Где найдено",
    "ID вычисляемого поля",
    "Название вычисляемого поля",
    "ID справочника",
    "Название справочника",
    "Ключ записи справочника",
    "Название записи справочника",
    "ID текстового поля справочника",
    "Название текстового поля справочника",
    "Найденная ссылка",
    "Совпавший сегмент",
    "Формула",
    "Тип источника формулы",
    "objectType",
    "ID выбранного поля",
    "Название выбранного поля",
    "Индекс совпавшего сегмента",
    "Сегменты ссылки",
]


class FormulaSearchError(RuntimeError):
    pass


class FormulaSearchCancelled(RuntimeError):
    pass


class FormulaSearchStopped(RuntimeError):
    def __init__(
        self,
        usages: list["FormulaUsage"],
        output_dir: Path,
        message: str = "Поиск остановлен пользователем.",
    ) -> None:
        super().__init__(message)
        self.usages = usages
        self.output_dir = output_dir
        self.message = message


@dataclass
class FormulaSearchProgress:
    stage: str
    checked_fields: int = 0
    total_fields: int = 0
    matches_found: int = 0
    last_request_at: str = ""
    output_file: str = ""
    message: str = ""


@dataclass
class FormulaReference:
    raw: str
    decoded: str
    segments: list[str]
    quoted_segments: list[bool]


@dataclass
class FormulaUsage:
    confidence: str
    formula_source_type: str
    formula_source_label: str
    calculated_field_id: Any
    calculated_field_name: str
    calculated_field_object_type: Any
    selected_field_id: Any
    selected_field_name: str
    matched_reference: str
    matched_segment: str
    matched_segment_index: int
    formula: str
    reference_segments: list[str]
    directory_id: Any = ""
    directory_name: str = ""
    directory_entry_key: Any = ""
    directory_entry_name: str = ""
    directory_field_id: Any = ""
    directory_field_name: str = ""


@dataclass
class FormulaSearchIssue:
    scope: str
    endpoint: str
    message: str
    directory_id: Any = ""
    directory_name: str = ""
    offset: Any = ""
    attempts: int = MAX_REQUEST_ATTEMPTS
    last_request_at: str = ""


ProgressCallback = Callable[[FormulaSearchProgress], None]
CancellationCheck = Callable[[], bool]


def default_progress_callback(progress: FormulaSearchProgress) -> None:
    print(
        "[progress] "
        f"этап={progress.stage}; "
        f"проверено={progress.checked_fields}/{progress.total_fields}; "
        f"найдено={progress.matches_found}; "
        f"последний_запрос={progress.last_request_at or '-'}; "
        f"output={progress.output_file or '-'}; "
        f"{progress.message}",
        flush=True,
    )


class RateLimitedPlanfixClient:
    def __init__(
        self,
        config: dict[str, Any],
        progress_callback: ProgressCallback | None = None,
        cancellation_check: CancellationCheck | None = None,
        min_interval_seconds: float = MIN_REQUEST_INTERVAL_SECONDS,
    ) -> None:
        self.config = config
        self.progress_callback = progress_callback or default_progress_callback
        self.cancellation_check = cancellation_check
        self.min_interval_seconds = min_interval_seconds
        self.last_request_monotonic: float | None = None
        self.last_request_at = ""

    def _raise_if_cancelled(self) -> None:
        if self.cancellation_check is not None and self.cancellation_check():
            raise FormulaSearchCancelled("Поиск остановлен пользователем.")

    def _wait_before_request(self) -> None:
        if self.last_request_monotonic is None:
            return

        elapsed = time.monotonic() - self.last_request_monotonic
        remaining = self.min_interval_seconds - elapsed
        while remaining > 0:
            self._raise_if_cancelled()
            sleep_for = min(remaining, 0.1)
            time.sleep(sleep_for)
            elapsed = time.monotonic() - self.last_request_monotonic
            remaining = self.min_interval_seconds - elapsed

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        stage: str,
    ) -> dict[str, Any]:
        url = f"{self.config['base_url']}{path}"
        headers = {
            "Authorization": f"Bearer {self.config['token']}",
            "Accept": "application/json",
        }
        if method == "POST":
            headers["Content-Type"] = "application/json"

        last_error = ""
        for attempt in range(1, MAX_REQUEST_ATTEMPTS + 1):
            self._raise_if_cancelled()
            self._wait_before_request()
            self._raise_if_cancelled()

            self.last_request_monotonic = time.monotonic()
            self.last_request_at = datetime.now().isoformat(timespec="seconds")
            retry_suffix = (
                ""
                if attempt == 1
                else f" (повтор {attempt}/{MAX_REQUEST_ATTEMPTS})"
            )
            self.progress_callback(
                FormulaSearchProgress(
                    stage=stage,
                    last_request_at=self.last_request_at,
                    message=f"Отправляю {method} {path}{retry_suffix}",
                )
            )

            try:
                request_json = payload or {}
                if method != "POST":
                    request_json = None
                response = requests.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    json=request_json,
                    timeout=60,
                )
            except requests.RequestException as error:
                last_error = f"Ошибка сети при запросе {method} {path}: {error}"
                if attempt < MAX_REQUEST_ATTEMPTS:
                    self.progress_callback(
                        FormulaSearchProgress(
                            stage=stage,
                            last_request_at=self.last_request_at,
                            message=(
                                "Временная ошибка сети, повторяю запрос: "
                                f"{error}"
                            ),
                        )
                    )
                    continue
                raise FormulaSearchError(last_error) from error

            if response.status_code != 200:
                last_error = (
                    f"Planfix вернул HTTP {response.status_code} для {method} {path}.\n"
                    f"Ответ:\n{response.text[:2000]}"
                )
                if (
                    response.status_code in RETRYABLE_HTTP_STATUSES
                    and attempt < MAX_REQUEST_ATTEMPTS
                ):
                    self.progress_callback(
                        FormulaSearchProgress(
                            stage=stage,
                            last_request_at=self.last_request_at,
                            message=(
                                f"Временный HTTP {response.status_code}, "
                                "повторяю запрос"
                            ),
                        )
                    )
                    continue
                raise FormulaSearchError(last_error)

            try:
                data = response.json()
            except ValueError as error:
                raise FormulaSearchError(
                    f"Planfix вернул не JSON для {method} {path}."
                ) from error

            if data.get("result") != "success":
                last_error = (
                    f"Planfix вернул неуспешный результат для {method} {path}:\n"
                    f"{json.dumps(data, ensure_ascii=False, indent=2)[:2000]}"
                )
                if attempt < MAX_REQUEST_ATTEMPTS:
                    self.progress_callback(
                        FormulaSearchProgress(
                            stage=stage,
                            last_request_at=self.last_request_at,
                            message="Planfix вернул ошибку API, повторяю запрос",
                        )
                    )
                    continue
                raise FormulaSearchError(last_error)

            return data

        raise FormulaSearchError(last_error or f"Не удалось выполнить {method} {path}.")

    def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        stage: str,
    ) -> dict[str, Any]:
        return self._request_json(
            "GET",
            path,
            params=params,
            stage=stage,
        )

    def post(
        self,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        stage: str,
    ) -> dict[str, Any]:
        return self._request_json(
            "POST",
            path,
            payload=payload,
            stage=stage,
        )


def normalize_formula_text(value: Any) -> str:
    return " ".join(str(value).replace("\r", "\n").split())


def normalize_reference_segment(value: str) -> str:
    normalized = html.unescape(value)
    normalized = normalize_formula_text(normalized)

    if len(normalized) >= 2 and normalized[0] == '"' and normalized[-1] == '"':
        normalized = normalized[1:-1]
        normalized = normalize_formula_text(normalized)

    return normalized


def split_reference_path(value: str) -> tuple[list[str], list[bool]]:
    segments: list[str] = []
    quoted_segments: list[bool] = []
    current: list[str] = []
    in_quotes = False
    segment_had_outer_quotes = False

    for char in value:
        if char == '"':
            stripped_current = "".join(current).strip()
            if not in_quotes and not stripped_current:
                segment_had_outer_quotes = True
            in_quotes = not in_quotes
            current.append(char)
            continue

        if char == "." and not in_quotes:
            raw_segment = "".join(current)
            segments.append(normalize_reference_segment(raw_segment))
            quoted_segments.append(segment_had_outer_quotes)
            current = []
            segment_had_outer_quotes = False
            continue

        current.append(char)

    raw_segment = "".join(current)
    segments.append(normalize_reference_segment(raw_segment))
    quoted_segments.append(segment_had_outer_quotes)

    return segments, quoted_segments


def extract_formula_references(formula: str) -> list[FormulaReference]:
    references = []
    for match in re.finditer(r"\{\{(.*?)\}\}", formula or "", flags=re.DOTALL):
        raw = match.group(0)
        inner = match.group(1)
        decoded = html.unescape(inner).strip()
        segments, quoted_segments = split_reference_path(decoded)
        references.append(
            FormulaReference(
                raw=raw,
                decoded=decoded,
                segments=segments,
                quoted_segments=quoted_segments,
            )
        )
    return references


def selected_field_names(selected_field: dict[str, Any]) -> list[str]:
    names = []
    primary_name = normalize_reference_segment(str(selected_field.get("name", "")))
    if primary_name:
        names.append(primary_name)

    localized_names = selected_field.get("names")
    if isinstance(localized_names, dict):
        for value in localized_names.values():
            normalized = normalize_reference_segment(str(value))
            if normalized:
                names.append(normalized)

    result = []
    seen = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        result.append(name)
    return result


def reference_segment_parts(segment: str) -> list[str]:
    parts = []
    for part in str(segment).split("/"):
        normalized = normalize_reference_segment(part)
        if normalized:
            parts.append(normalized)
    return parts


def match_selected_field(
    selected_names: list[str],
    reference: FormulaReference,
) -> tuple[str, str, int] | None:
    if not selected_names:
        return None

    selected_set = set(selected_names)
    selected_casefold = {name.casefold(): name for name in selected_names}

    for index, segment in enumerate(reference.segments[1:], start=1):
        if segment in selected_set:
            confidence = (
                "exact_quoted_segment"
                if index < len(reference.quoted_segments)
                and reference.quoted_segments[index]
                else "exact_segment"
            )
            return confidence, segment, index

        if segment.casefold() in selected_casefold:
            return "casefold_segment", segment, index

        for part in reference_segment_parts(segment):
            if part in selected_set:
                return "exact_slash_part", part, index

            if part.casefold() in selected_casefold:
                return "casefold_slash_part", part, index

    return None


def source_label_for_object_type(object_type: Any) -> str:
    return {
        0: "задача",
        1: "контакт",
        2: "справочник",
        3: "проект",
        4: "аналитика",
        5: "основное поле",
        6: "сотрудник",
    }.get(object_type, str(object_type))


def extract_customfield_value(entry: dict[str, Any], field_id: Any) -> Any:
    for item in entry.get("customFieldData", []) or []:
        field = item.get("field", {})
        if str(field.get("id")) == str(field_id):
            return item.get("value")
    return ""


def extract_entry_name(entry: dict[str, Any]) -> str:
    if entry.get("name"):
        return str(entry.get("name", ""))

    fallback_name = ""
    for item in entry.get("customFieldData", []) or []:
        field = item.get("field", {})
        field_name = str(field.get("name", "")).casefold()
        value = str(item.get("stringValue") or item.get("value") or "")
        if not value:
            continue

        if field_name == "наименование":
            return value

        if field_name.startswith("наименование"):
            return value

        if not fallback_name and "наименование" in field_name:
            fallback_name = value

    return fallback_name


def directory_entry_fields_param(directory: dict[str, Any]) -> str:
    field_ids = [
        str(field.get("id"))
        for field in directory.get("fields", []) or []
        if isinstance(field, dict) and field.get("id")
    ]
    return ",".join(
        ["directory", "key", "parentKey", "archived", "isGroup"] + field_ids
    )


def load_directory_entry_details(
    client: RateLimitedPlanfixClient,
    *,
    directory: dict[str, Any],
    entry_key: Any,
) -> dict[str, Any]:
    directory_id = directory.get("id")
    data = client.get(
        f"/directory/{directory_id}/entry/{entry_key}",
        params={"fields": directory_entry_fields_param(directory)},
        stage=f"Загрузка записи справочника {directory_id}/{entry_key}",
    )
    entry = data.get("entry", {})
    if not isinstance(entry, dict):
        raise FormulaSearchError(
            f"В ответе /directory/{directory_id}/entry/{entry_key} не найден entry."
        )
    return entry


def enrich_directory_usage_entry_names(
    client: RateLimitedPlanfixClient,
    *,
    directory: dict[str, Any],
    usages: list[FormulaUsage],
    issues: list[FormulaSearchIssue],
    progress_callback: ProgressCallback,
    output_file: str,
) -> None:
    missing_keys = {
        usage.directory_entry_key
        for usage in usages
        if usage.directory_entry_key not in ("", None) and not usage.directory_entry_name
    }
    entry_names: dict[Any, str] = {}

    for entry_key in missing_keys:
        try:
            entry = load_directory_entry_details(
                client,
                directory=directory,
                entry_key=entry_key,
            )
            entry_names[entry_key] = extract_entry_name(entry)
        except FormulaSearchError as error:
            issues.append(
                FormulaSearchIssue(
                    scope="directory_entry_details",
                    endpoint=f"/directory/{directory.get('id')}/entry/{entry_key}",
                    directory_id=directory.get("id", ""),
                    directory_name=str(directory.get("name", "")),
                    message=str(error),
                    last_request_at=client.last_request_at,
                )
            )
            progress_callback(
                FormulaSearchProgress(
                    stage="Ошибка записи справочника",
                    matches_found=len(usages),
                    last_request_at=client.last_request_at,
                    output_file=output_file,
                    message=(
                        "Не удалось дозагрузить название записи "
                        f"{directory.get('id', '')}/{entry_key}: {error}"
                    ),
                )
            )

    for usage in usages:
        if not usage.directory_entry_name and usage.directory_entry_key in entry_names:
            usage.directory_entry_name = entry_names[usage.directory_entry_key]


def load_customfields_with_formulas(
    client: RateLimitedPlanfixClient,
    path: str,
    stage: str,
) -> list[dict[str, Any]]:
    data = client.get(
        path,
        params={"fields": FORMULA_FIELDS_PARAM},
        stage=stage,
    )
    customfields = data.get("customfields", [])
    if not isinstance(customfields, list):
        raise FormulaSearchError(f"В ответе {path} не найден массив customfields.")
    return [field for field in customfields if isinstance(field, dict)]


def load_directories(
    client: RateLimitedPlanfixClient,
    *,
    max_pages: int | None = None,
) -> list[dict[str, Any]]:
    directories: list[dict[str, Any]] = []
    page_number = 0

    while True:
        if max_pages is not None and page_number >= max_pages:
            break

        offset = page_number * 100
        data = client.post(
            "/directory/list",
            payload={
                "offset": offset,
                "pageSize": 100,
                "fields": "id,name,group,fields",
            },
            stage="Загрузка списка справочников",
        )
        items = data.get("directories", [])
        if not isinstance(items, list):
            raise FormulaSearchError("В ответе /directory/list не найден массив directories.")

        directories.extend(item for item in items if isinstance(item, dict))
        page_number += 1

        if len(items) < 100:
            break

    return directories


def load_directory_details(
    client: RateLimitedPlanfixClient,
    directory_id: Any,
) -> dict[str, Any]:
    data = client.get(
        f"/directory/{directory_id}",
        params={"fields": "id,name,group,fields"},
        stage=f"Загрузка справочника {directory_id}",
    )
    directory = data.get("directory", {})
    if not isinstance(directory, dict):
        raise FormulaSearchError(f"В ответе /directory/{directory_id} не найден directory.")
    return directory


def directory_text_fields(
    client: RateLimitedPlanfixClient,
    directory: dict[str, Any],
) -> list[dict[str, Any]]:
    fields = directory.get("fields")

    if not isinstance(fields, list):
        directory = load_directory_details(client, directory.get("id"))
        fields = directory.get("fields", [])

    return [
        field
        for field in fields
        if isinstance(field, dict) and field.get("type") == 2 and field.get("id")
    ]


def load_directory_entries(
    client: RateLimitedPlanfixClient,
    *,
    directory_id: Any,
    text_fields: list[dict[str, Any]],
    max_pages: int | None = None,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    page_number = 0
    text_field_ids = [str(field.get("id")) for field in text_fields if field.get("id")]
    fields_param = ",".join(
        ["directory", "key", "parentKey", "name", "archived", "isGroup"] + text_field_ids
    )

    while True:
        if max_pages is not None and page_number >= max_pages:
            break

        offset = page_number * 100
        try:
            data = client.post(
                f"/directory/{directory_id}/entry/list",
                payload={
                    "offset": offset,
                    "pageSize": 100,
                    "fields": fields_param,
                    "entriesOnly": True,
                },
                stage=f"Загрузка записей справочника {directory_id}",
            )
        except FormulaSearchError as error:
            raise FormulaSearchError(
                f"Не удалось загрузить записи справочника {directory_id} "
                f"на offset={offset}: {error}"
            ) from error
        items = data.get("directoryEntries", [])
        if not isinstance(items, list):
            raise FormulaSearchError(
                f"В ответе /directory/{directory_id}/entry/list "
                "не найден массив directoryEntries."
            )

        entries.extend(item for item in items if isinstance(item, dict))
        page_number += 1

        if len(items) < 100:
            break

    return entries


def find_usages_in_fields(
    selected_field: dict[str, Any],
    formula_fields: list[dict[str, Any]],
    *,
    formula_source_type: str,
    progress_callback: ProgressCallback | None = None,
    output_file: str = "",
    checked_offset: int = 0,
    total_fields: int | None = None,
    initial_matches: int = 0,
    last_request_at: str = "",
) -> list[FormulaUsage]:
    progress = progress_callback or default_progress_callback
    selected_names = selected_field_names(selected_field)
    selected_field_id = selected_field.get("id")
    selected_field_name = selected_field.get("name", "")
    total = total_fields if total_fields is not None else len(formula_fields)
    usages: list[FormulaUsage] = []
    matches_found = initial_matches

    for index, formula_field in enumerate(formula_fields, start=1):
        checked_fields = checked_offset + index
        formula = str(formula_field.get("formula", "") or "")
        for reference in extract_formula_references(formula):
            match = match_selected_field(selected_names, reference)
            if match is None:
                continue

            confidence, matched_segment, matched_segment_index = match
            matches_found += 1
            object_type = formula_field.get("objectType")
            source_label = source_label_for_object_type(object_type)
            usages.append(
                FormulaUsage(
                    confidence=confidence,
                    formula_source_type=formula_source_type,
                    formula_source_label=source_label,
                    calculated_field_id=formula_field.get("id", ""),
                    calculated_field_name=str(formula_field.get("name", "")),
                    calculated_field_object_type=object_type,
                    selected_field_id=selected_field_id,
                    selected_field_name=str(selected_field_name),
                    matched_reference=reference.raw,
                    matched_segment=matched_segment,
                    matched_segment_index=matched_segment_index,
                    formula=formula,
                    reference_segments=reference.segments,
                )
            )

        progress(
            FormulaSearchProgress(
                stage=f"Проверка формул: {formula_source_type}",
                checked_fields=checked_fields,
                total_fields=total,
                matches_found=matches_found,
                last_request_at=last_request_at,
                output_file=output_file,
                message=f"Проверено поле {formula_field.get('id', '')}",
            )
        )

    return usages


def find_usages_in_directory_entries(
    selected_field: dict[str, Any],
    *,
    directory: dict[str, Any],
    text_fields: list[dict[str, Any]],
    entries: list[dict[str, Any]],
    progress_callback: ProgressCallback | None = None,
    output_file: str = "",
    checked_offset: int = 0,
    total_fields: int | None = None,
    initial_matches: int = 0,
    last_request_at: str = "",
) -> list[FormulaUsage]:
    progress = progress_callback or default_progress_callback
    selected_names = selected_field_names(selected_field)
    selected_field_id = selected_field.get("id")
    selected_field_name = selected_field.get("name", "")
    total_text_values = len(entries) * len(text_fields)
    total = total_fields if total_fields is not None else total_text_values
    checked = checked_offset
    matches_found = initial_matches
    usages: list[FormulaUsage] = []
    directory_id = directory.get("id", "")
    directory_name = str(directory.get("name", ""))

    for entry in entries:
        entry_key = entry.get("key", "")
        entry_name = extract_entry_name(entry)

        for text_field in text_fields:
            checked += 1
            value = extract_customfield_value(entry, text_field.get("id"))
            if value in (None, ""):
                progress(
                    FormulaSearchProgress(
                        stage=f"Проверка справочника: {directory_name}",
                        checked_fields=checked,
                        total_fields=total,
                        matches_found=matches_found,
                        last_request_at=last_request_at,
                        output_file=output_file,
                        message=(
                            f"Запись {entry_key}, поле "
                            f"{text_field.get('name', '')}: пусто"
                        ),
                    )
                )
                continue

            text_value = str(value)
            for reference in extract_formula_references(text_value):
                match = match_selected_field(selected_names, reference)
                if match is None:
                    continue

                confidence, matched_segment, matched_segment_index = match
                matches_found += 1
                usages.append(
                    FormulaUsage(
                        confidence=confidence,
                        formula_source_type="текстовое поле записи справочника",
                        formula_source_label="справочник",
                        calculated_field_id="",
                        calculated_field_name="",
                        calculated_field_object_type=2,
                        selected_field_id=selected_field_id,
                        selected_field_name=str(selected_field_name),
                        matched_reference=reference.raw,
                        matched_segment=matched_segment,
                        matched_segment_index=matched_segment_index,
                        formula=text_value,
                        reference_segments=reference.segments,
                        directory_id=directory_id,
                        directory_name=directory_name,
                        directory_entry_key=entry_key,
                        directory_entry_name=entry_name,
                        directory_field_id=text_field.get("id", ""),
                        directory_field_name=str(text_field.get("name", "")),
                    )
                )

            progress(
                FormulaSearchProgress(
                    stage=f"Проверка справочника: {directory_name}",
                    checked_fields=checked,
                    total_fields=total,
                    matches_found=matches_found,
                    last_request_at=last_request_at,
                    output_file=output_file,
                    message=f"Запись {entry_key}, поле {text_field.get('name', '')}",
                )
            )

    return usages


def usage_to_output_row(usage: FormulaUsage) -> dict[str, Any]:
    return {
        "Уверенность": usage.confidence,
        "Где найдено": usage.formula_source_label,
        "ID вычисляемого поля": usage.calculated_field_id,
        "Название вычисляемого поля": usage.calculated_field_name,
        "ID справочника": usage.directory_id,
        "Название справочника": usage.directory_name,
        "Ключ записи справочника": usage.directory_entry_key,
        "Название записи справочника": usage.directory_entry_name,
        "ID текстового поля справочника": usage.directory_field_id,
        "Название текстового поля справочника": usage.directory_field_name,
        "Найденная ссылка": usage.matched_reference,
        "Совпавший сегмент": usage.matched_segment,
        "Формула": usage.formula,
        "Тип источника формулы": usage.formula_source_type,
        "objectType": usage.calculated_field_object_type,
        "ID выбранного поля": usage.selected_field_id,
        "Название выбранного поля": usage.selected_field_name,
        "Индекс совпавшего сегмента": usage.matched_segment_index,
        "Сегменты ссылки": json.dumps(
            usage.reference_segments,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def write_csv(path: Path, usages: list[FormulaUsage]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=OUTPUT_COLUMNS, delimiter=";")
        writer.writeheader()
        for usage in usages:
            writer.writerow(usage_to_output_row(usage))


def save_formula_search_outputs(
    *,
    selected_field: dict[str, Any],
    usages: list[FormulaUsage],
    issues: list[FormulaSearchIssue] | None = None,
    output_dir: Path,
    status: str,
    checked_fields: int,
    total_fields: int,
    skipped_directories_count: int = 0,
    message: str = "",
) -> None:
    results_json_file = output_dir / "results.json"
    results_csv_file = output_dir / "results.csv"
    errors_json_file = output_dir / "errors.json"
    run_status_file = output_dir / "run_status.json"
    issues = issues or []

    write_json(results_json_file, [asdict(usage) for usage in usages])
    write_csv(results_csv_file, usages)
    write_json(errors_json_file, [asdict(issue) for issue in issues])
    write_json(
        run_status_file,
        {
            "status": status,
            "savedAt": datetime.now().isoformat(timespec="seconds"),
            "selectedField": selected_field,
            "checkedFields": checked_fields,
            "totalFields": total_fields,
            "matchesFound": len(usages),
            "errorsCount": len(issues),
            "skippedDirectoriesCount": skipped_directories_count,
            "message": message,
            "resultsJson": str(results_json_file),
            "resultsCsv": str(results_csv_file),
            "errorsJson": str(errors_json_file),
        },
    )


def create_formula_search_output_dir(root_dir: Path | None = None) -> Path:
    base_dir = root_dir or Path(__file__).resolve().parent
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return base_dir / "output" / "formula_search" / timestamp


def search_formula_usages(
    config: dict[str, Any],
    selected_field: dict[str, Any],
    *,
    output_dir: Path | None = None,
    progress_callback: ProgressCallback | None = None,
    include_directory_text_fields: bool = True,
    directory_ids: list[Any] | None = None,
    excluded_directory_ids: list[Any] | set[Any] | None = None,
    max_directory_pages: int | None = None,
    max_directory_entry_pages: int | None = None,
    cancellation_check: CancellationCheck | None = None,
) -> tuple[list[FormulaUsage], Path]:
    progress = progress_callback or default_progress_callback
    output_dir = output_dir or create_formula_search_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)

    selected_field_file = output_dir / "selected_field.json"
    results_json_file = output_dir / "results.json"
    results_csv_file = output_dir / "results.csv"
    usages: list[FormulaUsage] = []
    issues: list[FormulaSearchIssue] = []
    checked_offset = 0
    total_fields = 0
    skipped_directories_count = 0

    write_json(selected_field_file, selected_field)
    progress(
        FormulaSearchProgress(
            stage="Старт поиска",
            output_file=str(selected_field_file),
            message="Выбранное поле сохранено",
        )
    )

    try:
        client = RateLimitedPlanfixClient(
            config,
            progress_callback=progress,
            cancellation_check=cancellation_check,
        )
        task_fields = load_customfields_with_formulas(
            client,
            "/customfield/task",
            "Загрузка вычисляемых полей задач",
        )
        contact_fields = load_customfields_with_formulas(
            client,
            "/customfield/contact",
            "Загрузка вычисляемых полей контактов",
        )

        task_calculated_fields = [
            field
            for field in task_fields
            if field.get("type") == CALCULATED_FIELD_TYPE_ID and field.get("formula")
        ]
        contact_calculated_fields = [
            field
            for field in contact_fields
            if field.get("type") == CALCULATED_FIELD_TYPE_ID and field.get("formula")
        ]

        directory_scan_plan: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
        directory_text_value_count = 0
        excluded_directory_id_set = {
            str(directory_id)
            for directory_id in (excluded_directory_ids or [])
            if str(directory_id).strip()
        }

        if include_directory_text_fields:
            if directory_ids:
                directories = []
                for directory_id in directory_ids:
                    try:
                        directories.append(load_directory_details(client, directory_id))
                    except FormulaSearchError as error:
                        issues.append(
                            FormulaSearchIssue(
                                scope="directory_details",
                                endpoint=f"/directory/{directory_id}",
                                directory_id=directory_id,
                                message=str(error),
                                last_request_at=client.last_request_at,
                            )
                        )
                        progress(
                            FormulaSearchProgress(
                                stage="Ошибка справочника",
                                checked_fields=checked_offset,
                                total_fields=total_fields,
                                matches_found=len(usages),
                                last_request_at=client.last_request_at,
                                output_file=str(results_json_file),
                                message=(
                                    f"Пропускаю справочник {directory_id}: {error}"
                                ),
                            )
                        )
            else:
                try:
                    directories = load_directories(
                        client,
                        max_pages=max_directory_pages,
                    )
                except FormulaSearchError as error:
                    directories = []
                    issues.append(
                        FormulaSearchIssue(
                            scope="directory_list",
                            endpoint="/directory/list",
                            message=str(error),
                            last_request_at=client.last_request_at,
                        )
                    )
                    progress(
                        FormulaSearchProgress(
                            stage="Ошибка списка справочников",
                            checked_fields=checked_offset,
                            total_fields=total_fields,
                            matches_found=len(usages),
                            last_request_at=client.last_request_at,
                            output_file=str(results_json_file),
                            message=(
                                "Не удалось загрузить список справочников, "
                                "продолжаю без справочников"
                            ),
                        )
                    )

            if excluded_directory_id_set:
                before_count = len(directories)
                directories = [
                    directory
                    for directory in directories
                    if str(directory.get("id")) not in excluded_directory_id_set
                ]
                skipped_directories_count = before_count - len(directories)

            for directory in directories:
                if cancellation_check is not None and cancellation_check():
                    raise FormulaSearchCancelled("Поиск остановлен пользователем.")

                try:
                    text_fields = directory_text_fields(client, directory)
                except FormulaSearchError as error:
                    issues.append(
                        FormulaSearchIssue(
                            scope="directory_fields",
                            endpoint=f"/directory/{directory.get('id')}",
                            directory_id=directory.get("id", ""),
                            directory_name=str(directory.get("name", "")),
                            message=str(error),
                            last_request_at=client.last_request_at,
                        )
                    )
                    progress(
                        FormulaSearchProgress(
                            stage="Ошибка справочника",
                            checked_fields=checked_offset,
                            total_fields=total_fields,
                            matches_found=len(usages),
                            last_request_at=client.last_request_at,
                            output_file=str(results_json_file),
                            message=(
                                "Пропускаю справочник "
                                f"{directory.get('id', '')} "
                                f"{directory.get('name', '')}: {error}"
                            ),
                        )
                    )
                    continue
                if not text_fields:
                    continue

                directory_scan_plan.append((directory, text_fields))

        total_fields = len(task_calculated_fields) + len(contact_calculated_fields)
        progress(
            FormulaSearchProgress(
                stage="Подготовка поиска",
                checked_fields=0,
                total_fields=total_fields,
                output_file=str(output_dir),
                message=(
                    "Найдено вычисляемых полей: "
                    f"задачи={len(task_calculated_fields)}, "
                    f"контакты={len(contact_calculated_fields)}, "
                    f"справочников пропущено={skipped_directories_count}"
                ),
            )
        )

        task_usages = find_usages_in_fields(
            selected_field,
            task_calculated_fields,
            formula_source_type="пользовательские поля задач",
            progress_callback=progress,
            output_file=str(results_json_file),
            checked_offset=0,
            total_fields=total_fields,
            last_request_at=client.last_request_at,
        )
        contact_usages = find_usages_in_fields(
            selected_field,
            contact_calculated_fields,
            formula_source_type="пользовательские поля контактов",
            progress_callback=progress,
            output_file=str(results_json_file),
            checked_offset=len(task_calculated_fields),
            total_fields=total_fields,
            initial_matches=len(task_usages),
            last_request_at=client.last_request_at,
        )
        usages = task_usages + contact_usages
        checked_offset = len(task_calculated_fields) + len(contact_calculated_fields)

        directory_usages: list[FormulaUsage] = []
        if include_directory_text_fields:
            for directory, text_fields in directory_scan_plan:
                if cancellation_check is not None and cancellation_check():
                    raise FormulaSearchCancelled("Поиск остановлен пользователем.")

                try:
                    entries = load_directory_entries(
                        client,
                        directory_id=directory.get("id"),
                        text_fields=text_fields,
                        max_pages=max_directory_entry_pages,
                    )
                except FormulaSearchError as error:
                    issues.append(
                        FormulaSearchIssue(
                            scope="directory_entries",
                            endpoint=f"/directory/{directory.get('id')}/entry/list",
                            directory_id=directory.get("id", ""),
                            directory_name=str(directory.get("name", "")),
                            message=str(error),
                            last_request_at=client.last_request_at,
                        )
                    )
                    progress(
                        FormulaSearchProgress(
                            stage="Ошибка записей справочника",
                            checked_fields=checked_offset,
                            total_fields=total_fields,
                            matches_found=len(usages),
                            last_request_at=client.last_request_at,
                            output_file=str(results_json_file),
                            message=(
                                "Пропускаю справочник "
                                f"{directory.get('id', '')} "
                                f"{directory.get('name', '')}: {error}"
                            ),
                        )
                    )
                    continue
                directory_text_value_count += len(entries) * len(text_fields)
                current_total = total_fields + directory_text_value_count
                found = find_usages_in_directory_entries(
                    selected_field,
                    directory=directory,
                    text_fields=text_fields,
                    entries=entries,
                    progress_callback=progress,
                    output_file=str(results_json_file),
                    checked_offset=checked_offset,
                    total_fields=current_total,
                    initial_matches=len(usages) + len(directory_usages),
                    last_request_at=client.last_request_at,
                )
                enrich_directory_usage_entry_names(
                    client,
                    directory=directory,
                    usages=found,
                    issues=issues,
                    progress_callback=progress,
                    output_file=str(results_json_file),
                )
                directory_usages.extend(found)
                usages.extend(found)
                checked_offset += len(entries) * len(text_fields)

        save_formula_search_outputs(
            selected_field=selected_field,
            usages=usages,
            issues=issues,
            output_dir=output_dir,
            status="completed_with_errors" if issues else "completed",
            checked_fields=checked_offset,
            total_fields=checked_offset,
            skipped_directories_count=skipped_directories_count,
            message=(
                f"Результаты сохранены. Ошибок справочников: {len(issues)}."
                if issues
                else "Результаты сохранены полностью."
            ),
        )
        progress(
            FormulaSearchProgress(
                stage="Завершено с ошибками" if issues else "Завершено",
                checked_fields=checked_offset,
                total_fields=checked_offset,
                matches_found=len(usages),
                output_file=str(results_csv_file),
                message=(
                    f"Результаты сохранены, ошибок справочников: {len(issues)}"
                    if issues
                    else "Результаты сохранены"
                ),
            )
        )
    except FormulaSearchCancelled as error:
        save_formula_search_outputs(
            selected_field=selected_field,
            usages=usages,
            issues=issues,
            output_dir=output_dir,
            status="stopped",
            checked_fields=checked_offset,
            total_fields=total_fields,
            skipped_directories_count=skipped_directories_count,
            message=str(error),
        )
        progress(
            FormulaSearchProgress(
                stage="Остановлено",
                checked_fields=checked_offset,
                total_fields=total_fields,
                matches_found=len(usages),
                output_file=str(results_csv_file),
                message="Сохранены частичные результаты",
            )
        )
        raise FormulaSearchStopped(usages, output_dir, str(error)) from error

    return usages, output_dir
