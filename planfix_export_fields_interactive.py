import json
import sys
from pathlib import Path

from csv_export import save_to_csv
from field_exporter import get_fields_by_source, normalize_field, normalize_source_type
from planfix_client import get_object_list, get_task_template_list
from settings import (
    get_exports_dir,
    has_complete_settings,
    load_account,
    load_token,
    make_named_output_filename,
)


BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.json"


def load_legacy_config() -> dict:
    if not CONFIG_FILE.exists():
        raise RuntimeError(
            f"Не найден файл настроек: {CONFIG_FILE}\n"
            "Создай рядом со скриптом файл config.json с содержимым:\n"
            '{\n'
            '  "account": "engineering",\n'
            '  "token": "ВАШ_ТОКЕН"\n'
            '}'
        )

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as file:
            config = json.load(file)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"Ошибка в формате config.json:\n{error}"
        )

    account = str(config.get("account", "")).strip()
    token = str(config.get("token", "")).strip()

    if not account:
        raise RuntimeError("В config.json не заполнен параметр account.")

    if not token:
        raise RuntimeError("В config.json не заполнен параметр token.")

    if token.lower().startswith("bearer "):
        raise RuntimeError(
            "В config.json в параметре token нужно указывать только сам токен, "
            "без слова Bearer."
        )

    try:
        token.encode("latin-1")
    except UnicodeEncodeError:
        raise RuntimeError(
            "В config.json в параметре token есть недопустимые символы. "
            "Скорее всего, там русские буквы или лишний текст."
        )

    return {
        "account": account,
        "token": token,
        "base_url": f"https://{account}.planfix.ru/rest",
    }


def load_config() -> dict:
    if has_complete_settings():
        account = load_account()

        if not account:
            raise RuntimeError("Не удалось прочитать сохранённый аккаунт Planfix.")

        token = load_token(account)

        if not token:
            raise RuntimeError("Не удалось прочитать сохранённый токен Planfix.")

        return {
            "account": account,
            "token": token,
            "base_url": f"https://{account}.planfix.ru/rest",
        }

    return load_legacy_config()


def print_object_table(objects: list[dict]) -> None:
    if not objects:
        print("Список объектов пуст.")
        return

    number_width = max(len(str(len(objects))), 1)
    id_width = max(
        len("API ID объекта"),
        max(len(str(item.get("id", ""))) for item in objects),
    )

    print()
    print("Список объектов Planfix")
    print("-" * 100)
    print(
        f"{'№'.ljust(number_width)}  "
        f"{'API ID объекта'.ljust(id_width)}  "
        f"Название объекта"
    )
    print(
        f"{'-' * number_width}  "
        f"{'-' * id_width}  "
        f"{'-' * 60}"
    )

    for index, item in enumerate(objects, start=1):
        object_id = str(item.get("id", ""))
        object_name = item.get("name", "")

        print(
            f"{str(index).ljust(number_width)}  "
            f"{object_id.ljust(id_width)}  "
            f"{object_name}"
        )

    print("-" * 100)


def print_task_template_table(templates: list[dict]) -> None:
    if not templates:
        print("Список шаблонов задач пуст.")
        return

    number_width = max(len(str(len(templates))), 1)
    id_width = max(
        len("ID шаблона"),
        max(len(str(item.get("id", ""))) for item in templates),
    )

    print()
    print("Список шаблонов задач Planfix")
    print("-" * 100)
    print(
        f"{'№'.ljust(number_width)}  "
        f"{'ID шаблона'.ljust(id_width)}  "
        f"Название шаблона"
    )
    print(
        f"{'-' * number_width}  "
        f"{'-' * id_width}  "
        f"{'-' * 60}"
    )

    for index, item in enumerate(templates, start=1):
        template_id = str(item.get("id", ""))
        template_name = item.get("name", "")

        print(
            f"{str(index).ljust(number_width)}  "
            f"{template_id.ljust(id_width)}  "
            f"{template_name}"
        )

    print("-" * 100)


def select_object_from_list(config: dict) -> tuple[int, str]:
    print()
    print("Получаю список объектов Planfix...")

    objects = get_object_list(config)

    if not objects:
        raise RuntimeError("Planfix вернул пустой список объектов.")

    print_object_table(objects)

    while True:
        user_input = input("Введите номер объекта из списка: ").strip()

        try:
            selected_index = int(user_input)
        except ValueError:
            print("Нужно ввести номер строки из списка.")
            continue

        if selected_index < 1 or selected_index > len(objects):
            print(f"Нужно ввести число от 1 до {len(objects)}.")
            continue

        selected_object = objects[selected_index - 1]
        api_object_id = selected_object.get("id")
        object_name = selected_object.get("name", "")

        if not api_object_id:
            raise RuntimeError("У выбранного объекта не найден API ID.")

        return int(api_object_id), object_name


def select_task_template_from_list(config: dict) -> tuple[int, str]:
    print()
    print("Получаю список шаблонов задач Planfix...")

    templates = get_task_template_list(config)

    if not templates:
        raise RuntimeError("Planfix вернул пустой список шаблонов задач.")

    print_task_template_table(templates)

    while True:
        user_input = input("Введите номер шаблона из списка: ").strip()

        try:
            selected_index = int(user_input)
        except ValueError:
            print("Нужно ввести номер строки из списка.")
            continue

        if selected_index < 1 or selected_index > len(templates):
            print(f"Нужно ввести число от 1 до {len(templates)}.")
            continue

        selected_template = templates[selected_index - 1]
        template_id = selected_template.get("id")
        template_name = selected_template.get("name", "")

        if not template_id:
            raise RuntimeError("У выбранного шаблона не найден ID.")

        return int(template_id), template_name


def ask_source_type() -> str:
    print()
    print("Откуда получить список полей?")
    print("1 — Объект")
    print("2 — Шаблон задачи")
    print()

    while True:
        user_input = input("Введите 1 или 2: ").strip()

        if user_input == "1":
            return "object"

        if user_input == "2":
            return "task_template"

        print("Некорректный ввод. Нужно ввести 1 или 2.")


def main() -> None:
    try:
        config = load_config()

        print("Выгрузка пользовательских полей Planfix")
        print("-------------------------------------")
        print(f"Аккаунт Planfix: {config['account']}")

        source_type = ask_source_type()

        if source_type == "object":
            source_id, source_name = select_object_from_list(config)
        else:
            source_id, source_name = select_task_template_from_list(config)

        print()
        print("Параметры выгрузки:")
        print(f"Тип источника: {normalize_source_type(source_type)}")
        print(f"ID источника: {source_id}")
        if source_name:
            print(f"Название источника: {source_name}")
        print()

        fields = get_fields_by_source(config, source_type, source_id)

        rows = [
            normalize_field(source_type, source_id, source_name, field)
            for field in fields
        ]

        output_file = make_named_output_filename(
            source_type,
            source_id,
            source_name,
        )
        save_to_csv(rows, output_file)

        print("Готово.")
        print(f"Тип источника: {normalize_source_type(source_type)}")
        print(f"ID источника: {source_id}")
        if source_name:
            print(f"Название источника: {source_name}")
        print(f"Полей выгружено: {len(rows)}")
        print(f"Файл: {output_file}")

    except KeyboardInterrupt:
        print()
        print("Работа прервана пользователем.")
        sys.exit(1)

    except Exception as error:
        print()
        print("Ошибка:")
        print(error)
        sys.exit(1)


if __name__ == "__main__":
    main()
