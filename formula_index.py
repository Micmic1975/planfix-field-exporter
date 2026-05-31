import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from formula_search import (
    CALCULATED_FIELD_TYPE_ID,
    FormulaReference,
    FormulaSearchCancelled,
    FormulaSearchError,
    FormulaSearchIssue,
    FormulaSearchProgress,
    FormulaUsage,
    ProgressCallback,
    RateLimitedPlanfixClient,
    CancellationCheck,
    default_progress_callback,
    directory_text_fields,
    extract_customfield_value,
    extract_entry_name,
    extract_formula_references,
    load_customfields_with_formulas,
    load_directories,
    load_directory_details,
    load_directory_entries,
    match_selected_field,
    save_formula_search_outputs,
    selected_field_names,
    source_label_for_object_type,
    write_json,
)


FORMULA_INDEX_VERSION = 1
INDEX_FILE_NAME = "formula_index.json"
INDEX_STATUS_FILE_NAME = "index_status.json"
INDEX_ERRORS_FILE_NAME = "index_errors.json"


class FormulaIndexError(RuntimeError):
    pass


class FormulaIndexStopped(RuntimeError):
    def __init__(
        self,
        entries: list["FormulaIndexEntry"],
        output_dir: Path,
        message: str = "Обновление индекса остановлено пользователем.",
    ) -> None:
        super().__init__(message)
        self.entries = entries
        self.output_dir = output_dir
        self.message = message


@dataclass
class FormulaIndexEntry:
    formula_source_type: str
    formula_source_label: str
    calculated_field_id: Any
    calculated_field_name: str
    calculated_field_object_type: Any
    formula: str
    references: list[FormulaReference]
    directory_id: Any = ""
    directory_name: str = ""
    directory_entry_key: Any = ""
    directory_entry_name: str = ""
    directory_field_id: Any = ""
    directory_field_name: str = ""


def formula_index_files(output_dir: Path) -> dict[str, Path]:
    return {
        "index": output_dir / INDEX_FILE_NAME,
        "status": output_dir / INDEX_STATUS_FILE_NAME,
        "errors": output_dir / INDEX_ERRORS_FILE_NAME,
    }


def write_formula_index_outputs(
    *,
    output_dir: Path,
    entries: list[FormulaIndexEntry],
    issues: list[FormulaSearchIssue],
    status: str,
    checked_items: int,
    total_items: int,
    skipped_directories_count: int = 0,
    message: str = "",
) -> None:
    files = formula_index_files(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        files["index"],
        {
            "version": FORMULA_INDEX_VERSION,
            "savedAt": datetime.now().isoformat(timespec="seconds"),
            "entries": [asdict(entry) for entry in entries],
        },
    )
    write_json(files["errors"], [asdict(issue) for issue in issues])
    write_json(
        files["status"],
        {
            "version": FORMULA_INDEX_VERSION,
            "status": status,
            "savedAt": datetime.now().isoformat(timespec="seconds"),
            "entriesCount": len(entries),
            "errorsCount": len(issues),
            "checkedItems": checked_items,
            "totalItems": total_items,
            "skippedDirectoriesCount": skipped_directories_count,
            "message": message,
            "indexFile": str(files["index"]),
            "errorsFile": str(files["errors"]),
        },
    )


def load_formula_index_status(output_dir: Path) -> dict[str, Any]:
    status_file = formula_index_files(output_dir)["status"]
    if not status_file.exists():
        return {}

    with open(status_file, "r", encoding="utf-8") as file:
        status = json.load(file)

    return status if isinstance(status, dict) else {}


def _formula_reference_from_json(data: dict[str, Any]) -> FormulaReference:
    return FormulaReference(
        raw=str(data.get("raw", "")),
        decoded=str(data.get("decoded", "")),
        segments=[str(segment) for segment in data.get("segments", []) or []],
        quoted_segments=[
            bool(value) for value in data.get("quoted_segments", []) or []
        ],
    )


def _formula_index_entry_from_json(data: dict[str, Any]) -> FormulaIndexEntry:
    references = [
        _formula_reference_from_json(reference)
        for reference in data.get("references", []) or []
        if isinstance(reference, dict)
    ]
    return FormulaIndexEntry(
        formula_source_type=str(data.get("formula_source_type", "")),
        formula_source_label=str(data.get("formula_source_label", "")),
        calculated_field_id=data.get("calculated_field_id", ""),
        calculated_field_name=str(data.get("calculated_field_name", "")),
        calculated_field_object_type=data.get("calculated_field_object_type", ""),
        formula=str(data.get("formula", "")),
        references=references,
        directory_id=data.get("directory_id", ""),
        directory_name=str(data.get("directory_name", "")),
        directory_entry_key=data.get("directory_entry_key", ""),
        directory_entry_name=str(data.get("directory_entry_name", "")),
        directory_field_id=data.get("directory_field_id", ""),
        directory_field_name=str(data.get("directory_field_name", "")),
    )


def load_formula_index(output_dir: Path) -> list[FormulaIndexEntry]:
    index_file = formula_index_files(output_dir)["index"]
    if not index_file.exists():
        raise FormulaIndexError(
            "Локальный индекс формул ещё не создан. "
            "Сначала обновите индекс формул."
        )

    with open(index_file, "r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        raise FormulaIndexError("Файл индекса формул имеет неожиданный формат.")

    version = data.get("version")
    if version != FORMULA_INDEX_VERSION:
        raise FormulaIndexError(
            "Версия локального индекса формул не поддерживается. "
            "Обновите индекс."
        )

    entries = data.get("entries", [])
    if not isinstance(entries, list):
        raise FormulaIndexError("В индексе формул не найден список entries.")

    return [
        _formula_index_entry_from_json(entry)
        for entry in entries
        if isinstance(entry, dict)
    ]


def _append_field_index_entries(
    entries: list[FormulaIndexEntry],
    formula_fields: list[dict[str, Any]],
    *,
    formula_source_type: str,
    progress: ProgressCallback,
    output_file: str,
    checked_offset: int,
    total_items: int,
    last_request_at: str = "",
) -> int:
    checked = checked_offset
    for formula_field in formula_fields:
        checked += 1
        formula = str(formula_field.get("formula", "") or "")
        references = extract_formula_references(formula)
        if references:
            object_type = formula_field.get("objectType")
            entries.append(
                FormulaIndexEntry(
                    formula_source_type=formula_source_type,
                    formula_source_label=source_label_for_object_type(object_type),
                    calculated_field_id=formula_field.get("id", ""),
                    calculated_field_name=str(formula_field.get("name", "")),
                    calculated_field_object_type=object_type,
                    formula=formula,
                    references=references,
                )
            )

        progress(
            FormulaSearchProgress(
                stage=f"Индексация формул: {formula_source_type}",
                checked_fields=checked,
                total_fields=total_items,
                matches_found=len(entries),
                last_request_at=last_request_at,
                output_file=output_file,
                message=f"Проверено поле {formula_field.get('id', '')}",
            )
        )

    return checked


def _append_directory_index_entries(
    entries: list[FormulaIndexEntry],
    *,
    directory: dict[str, Any],
    text_fields: list[dict[str, Any]],
    directory_entries: list[dict[str, Any]],
    progress: ProgressCallback,
    output_file: str,
    checked_offset: int,
    total_items: int,
    last_request_at: str = "",
) -> int:
    checked = checked_offset
    directory_id = directory.get("id", "")
    directory_name = str(directory.get("name", ""))

    for entry in directory_entries:
        entry_key = entry.get("key", "")
        entry_name = extract_entry_name(entry)

        for text_field in text_fields:
            checked += 1
            value = extract_customfield_value(entry, text_field.get("id"))
            if value not in (None, ""):
                formula = str(value)
                references = extract_formula_references(formula)
                if references:
                    entries.append(
                        FormulaIndexEntry(
                            formula_source_type="текстовое поле записи справочника",
                            formula_source_label="справочник",
                            calculated_field_id="",
                            calculated_field_name="",
                            calculated_field_object_type=2,
                            formula=formula,
                            references=references,
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
                    stage=f"Индексация справочника: {directory_name}",
                    checked_fields=checked,
                    total_fields=total_items,
                    matches_found=len(entries),
                    last_request_at=last_request_at,
                    output_file=output_file,
                    message=f"Запись {entry_key}, поле {text_field.get('name', '')}",
                )
            )

    return checked


def build_formula_index(
    config: dict[str, Any],
    *,
    output_dir: Path,
    progress_callback: ProgressCallback | None = None,
    include_directory_text_fields: bool = True,
    directory_ids: list[Any] | None = None,
    excluded_directory_ids: list[Any] | set[Any] | None = None,
    max_directory_pages: int | None = None,
    max_directory_entry_pages: int | None = None,
    cancellation_check: CancellationCheck | None = None,
) -> tuple[list[FormulaIndexEntry], Path]:
    progress = progress_callback or default_progress_callback
    output_dir.mkdir(parents=True, exist_ok=True)
    files = formula_index_files(output_dir)
    entries: list[FormulaIndexEntry] = []
    issues: list[FormulaSearchIssue] = []
    checked_items = 0
    total_items = 0
    skipped_directories_count = 0

    progress(
        FormulaSearchProgress(
            stage="Старт обновления индекса",
            output_file=str(files["index"]),
            message="Локальный индекс формул будет пересобран",
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
        total_items = len(task_calculated_fields) + len(contact_calculated_fields)

        checked_items = _append_field_index_entries(
            entries,
            task_calculated_fields,
            formula_source_type="пользовательские поля задач",
            progress=progress,
            output_file=str(files["index"]),
            checked_offset=checked_items,
            total_items=total_items,
            last_request_at=client.last_request_at,
        )
        checked_items = _append_field_index_entries(
            entries,
            contact_calculated_fields,
            formula_source_type="пользовательские поля контактов",
            progress=progress,
            output_file=str(files["index"]),
            checked_offset=checked_items,
            total_items=total_items,
            last_request_at=client.last_request_at,
        )
        write_formula_index_outputs(
            output_dir=output_dir,
            entries=entries,
            issues=issues,
            status="running",
            checked_items=checked_items,
            total_items=total_items,
            skipped_directories_count=skipped_directories_count,
            message="Индекс вычисляемых полей сохранён, справочники ещё обрабатываются.",
        )

        directories: list[dict[str, Any]] = []
        excluded_directory_id_set = {
            str(directory_id)
            for directory_id in (excluded_directory_ids or [])
            if str(directory_id).strip()
        }

        if include_directory_text_fields:
            if directory_ids:
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
                                checked_fields=checked_items,
                                total_fields=total_items,
                                matches_found=len(entries),
                                last_request_at=client.last_request_at,
                                output_file=str(files["index"]),
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
                            checked_fields=checked_items,
                            total_fields=total_items,
                            matches_found=len(entries),
                            last_request_at=client.last_request_at,
                            output_file=str(files["index"]),
                            message=(
                                "Не удалось загрузить список справочников, "
                                "индекс продолжается без них"
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
                raise FormulaSearchCancelled("Обновление индекса остановлено пользователем.")

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
                        checked_fields=checked_items,
                        total_fields=total_items,
                        matches_found=len(entries),
                        last_request_at=client.last_request_at,
                        output_file=str(files["index"]),
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

            try:
                directory_entries = load_directory_entries(
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
                        checked_fields=checked_items,
                        total_fields=total_items,
                        matches_found=len(entries),
                        last_request_at=client.last_request_at,
                        output_file=str(files["index"]),
                        message=(
                            "Пропускаю справочник "
                            f"{directory.get('id', '')} "
                            f"{directory.get('name', '')}: {error}"
                        ),
                    )
                )
                continue

            total_items += len(directory_entries) * len(text_fields)
            checked_items = _append_directory_index_entries(
                entries,
                directory=directory,
                text_fields=text_fields,
                directory_entries=directory_entries,
                progress=progress,
                output_file=str(files["index"]),
                checked_offset=checked_items,
                total_items=total_items,
                last_request_at=client.last_request_at,
            )
            write_formula_index_outputs(
                output_dir=output_dir,
                entries=entries,
                issues=issues,
                status="running",
                checked_items=checked_items,
                total_items=total_items,
                skipped_directories_count=skipped_directories_count,
                message=(
                    "Индекс частично сохранён после справочника "
                    f"{directory.get('id', '')}."
                ),
            )

        write_formula_index_outputs(
            output_dir=output_dir,
            entries=entries,
            issues=issues,
            status="completed_with_errors" if issues else "completed",
            checked_items=checked_items,
            total_items=checked_items,
            skipped_directories_count=skipped_directories_count,
            message=(
                f"Индекс обновлён. Ошибок справочников: {len(issues)}."
                if issues
                else "Индекс обновлён полностью."
            ),
        )
        progress(
            FormulaSearchProgress(
                stage="Индекс обновлён с ошибками" if issues else "Индекс обновлён",
                checked_fields=checked_items,
                total_fields=checked_items,
                matches_found=len(entries),
                output_file=str(files["index"]),
                message=(
                    f"Записей в индексе: {len(entries)}, ошибок: {len(issues)}"
                ),
            )
        )
    except FormulaSearchCancelled as error:
        write_formula_index_outputs(
            output_dir=output_dir,
            entries=entries,
            issues=issues,
            status="stopped",
            checked_items=checked_items,
            total_items=total_items,
            skipped_directories_count=skipped_directories_count,
            message=str(error),
        )
        progress(
            FormulaSearchProgress(
                stage="Обновление индекса остановлено",
                checked_fields=checked_items,
                total_fields=total_items,
                matches_found=len(entries),
                output_file=str(files["index"]),
                message="Сохранён частичный индекс",
            )
        )
        raise FormulaIndexStopped(entries, output_dir, str(error)) from error

    return entries, output_dir


def find_usages_in_index(
    selected_field: dict[str, Any],
    entries: list[FormulaIndexEntry],
    *,
    progress_callback: ProgressCallback | None = None,
    output_file: str = "",
    cancellation_check: CancellationCheck | None = None,
) -> list[FormulaUsage]:
    progress = progress_callback or default_progress_callback
    selected_names = selected_field_names(selected_field)
    selected_field_id = selected_field.get("id")
    selected_field_name = selected_field.get("name", "")
    usages: list[FormulaUsage] = []
    total = len(entries)

    for index, entry in enumerate(entries, start=1):
        if cancellation_check is not None and cancellation_check():
            raise FormulaSearchCancelled("Поиск по локальному индексу остановлен.")

        for reference in entry.references:
            match = match_selected_field(selected_names, reference)
            if match is None:
                continue

            confidence, matched_segment, matched_segment_index = match
            usages.append(
                FormulaUsage(
                    confidence=confidence,
                    formula_source_type=entry.formula_source_type,
                    formula_source_label=entry.formula_source_label,
                    calculated_field_id=entry.calculated_field_id,
                    calculated_field_name=entry.calculated_field_name,
                    calculated_field_object_type=entry.calculated_field_object_type,
                    selected_field_id=selected_field_id,
                    selected_field_name=str(selected_field_name),
                    matched_reference=reference.raw,
                    matched_segment=matched_segment,
                    matched_segment_index=matched_segment_index,
                    formula=entry.formula,
                    reference_segments=reference.segments,
                    directory_id=entry.directory_id,
                    directory_name=entry.directory_name,
                    directory_entry_key=entry.directory_entry_key,
                    directory_entry_name=entry.directory_entry_name,
                    directory_field_id=entry.directory_field_id,
                    directory_field_name=entry.directory_field_name,
                )
            )

        progress(
            FormulaSearchProgress(
                stage="Поиск по локальному индексу",
                checked_fields=index,
                total_fields=total,
                matches_found=len(usages),
                output_file=output_file,
                message=f"Проверена запись индекса {index}/{total}",
            )
        )

    return usages


def search_formula_index(
    selected_field: dict[str, Any],
    *,
    index_entries: list[FormulaIndexEntry],
    output_dir: Path,
    progress_callback: ProgressCallback | None = None,
    cancellation_check: CancellationCheck | None = None,
) -> tuple[list[FormulaUsage], Path]:
    progress = progress_callback or default_progress_callback
    output_dir.mkdir(parents=True, exist_ok=True)
    selected_field_file = output_dir / "selected_field.json"
    results_csv_file = output_dir / "results.csv"
    write_json(selected_field_file, selected_field)
    progress(
        FormulaSearchProgress(
            stage="Старт локального поиска",
            output_file=str(selected_field_file),
            message="Выбранное поле сохранено, Planfix API не используется",
        )
    )

    try:
        usages = find_usages_in_index(
            selected_field,
            index_entries,
            progress_callback=progress,
            output_file=str(results_csv_file),
            cancellation_check=cancellation_check,
        )
    except FormulaSearchCancelled as error:
        save_formula_search_outputs(
            selected_field=selected_field,
            usages=[],
            issues=[],
            output_dir=output_dir,
            status="stopped",
            checked_fields=0,
            total_fields=len(index_entries),
            message=str(error),
        )
        raise

    save_formula_search_outputs(
        selected_field=selected_field,
        usages=usages,
        issues=[],
        output_dir=output_dir,
        status="completed_from_index",
        checked_fields=len(index_entries),
        total_fields=len(index_entries),
        message="Результаты получены из локального индекса формул.",
    )
    progress(
        FormulaSearchProgress(
            stage="Локальный поиск завершён",
            checked_fields=len(index_entries),
            total_fields=len(index_entries),
            matches_found=len(usages),
            output_file=str(results_csv_file),
            message="Результаты сохранены",
        )
    )
    return usages, output_dir
