from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from formula_search import FormulaSearchError, search_formula_usages
from planfix_export_fields_interactive import load_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only поиск использований выбранного поля в формулах "
            "вычисляемых полей Planfix и текстовых полях записей справочников."
        )
    )
    parser.add_argument("--field-id", required=True, help="ID выбранного поля.")
    parser.add_argument("--field-name", required=True, help="Название выбранного поля.")
    parser.add_argument(
        "--object-type",
        type=int,
        default=None,
        help="objectType выбранного поля, если известен.",
    )
    parser.add_argument(
        "--no-directory-text-fields",
        action="store_true",
        help="Не искать в текстовых полях записей справочников.",
    )
    parser.add_argument(
        "--directory-id",
        action="append",
        default=None,
        help=(
            "Ограничить поиск указанным справочником. "
            "Можно указать несколько раз."
        ),
    )
    parser.add_argument(
        "--exclude-directory-id",
        action="append",
        default=None,
        help=(
            "Исключить справочник из поиска. "
            "Можно указать несколько раз."
        ),
    )
    parser.add_argument(
        "--max-directory-pages",
        type=int,
        default=None,
        help="Ограничить количество страниц списка справочников.",
    )
    parser.add_argument(
        "--max-directory-entry-pages",
        type=int,
        default=None,
        help="Ограничить количество страниц записей каждого справочника.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    selected_field = {
        "id": args.field_id,
        "name": args.field_name,
    }
    if args.object_type is not None:
        selected_field["objectType"] = args.object_type

    try:
        usages, output_dir = search_formula_usages(
            load_config(),
            selected_field,
            include_directory_text_fields=not args.no_directory_text_fields,
            directory_ids=args.directory_id,
            excluded_directory_ids=args.exclude_directory_id,
            max_directory_pages=args.max_directory_pages,
            max_directory_entry_pages=args.max_directory_entry_pages,
        )
    except FormulaSearchError as error:
        print(f"Ошибка поиска: {error}", file=sys.stderr)
        raise SystemExit(1) from error

    print(f"Готово. Найдено совпадений: {len(usages)}")
    print(f"Результаты сохранены: {output_dir}")


if __name__ == "__main__":
    main()
