import json

from planfix_client import get_object_data, get_task_template_data


FIELD_TYPE_NAMES = {
    0: "Строка",
    1: "Число",
    2: "Текст",
    3: "Дата",
    4: "Время",
    5: "Дата и время",
    6: "Период времени",
    7: "Чекбокс",
    8: "Список",
    9: "Запись справочника",
    10: "Контакт",
    11: "Сотрудник",
    12: "Контрагент",
    13: "Группа, сотрудник или контакт",
    14: "Список пользователей",
    15: "Набор значений справочника",
    16: "Задача",
    17: "Набор задач",
    20: "Набор значений",
    21: "Файлы",
    22: "Проект",
    23: "Итоги аналитик",
    24: "Вычисляемые поля",
    25: "Местоположение",
    26: "Сумма подзадач",
    27: "Поле результата AI",
    28: "Дата с временным интервалом",
    29: "Суммарное поле",
}


def make_one_line(value: str) -> str:
    if value is None:
        return ""

    return " ".join(str(value).replace("\r", "\n").split())


def deduplicate_fields(fields: list[dict]) -> list[dict]:
    result = []
    seen_ids = set()

    for field in fields:
        if not field:
            continue

        field_id = field.get("id")

        if field_id in seen_ids:
            continue

        seen_ids.add(field_id)
        result.append(field)

    return result


def get_object_fields(config: dict, api_object_id: int) -> list[dict]:
    data = get_object_data(config, api_object_id)
    custom_field_data = data.get("object", {}).get("customFieldData", [])

    fields = []

    for item in custom_field_data:
        field = item.get("field")
        if field:
            fields.append(field)

    return deduplicate_fields(fields)


def get_task_template_fields(config: dict, template_id: int) -> list[dict]:
    data = get_task_template_data(config, template_id)
    fields = data.get("customfields", [])

    return deduplicate_fields(fields)


def normalize_options(options: list[dict]) -> str:
    if not options:
        return ""

    return ", ".join(option.get("name", "") for option in options)


def normalize_names(names: dict) -> str:
    if not names:
        return ""

    return json.dumps(names, ensure_ascii=False, separators=(",", ":"))


def normalize_enum_values(enum_values) -> str:
    if not enum_values:
        return ""

    return json.dumps(enum_values, ensure_ascii=False, separators=(",", ":"))


def normalize_directory_fields(directory_fields) -> str:
    if not directory_fields:
        return ""

    return json.dumps(directory_fields, ensure_ascii=False, separators=(",", ":"))


def normalize_source_type(source_type: str) -> str:
    if source_type == "object":
        return "Объект"

    if source_type == "task_template":
        return "Шаблон задачи"

    return source_type


def normalize_field(
    source_type: str,
    source_id: int,
    source_name: str,
    field: dict,
) -> dict:
    field_type = field.get("type")
    options = field.get("options") or []
    view_result = field.get("viewResult") or {}

    formula = field.get("formula", "")
    formula_one_line = make_one_line(formula)

    raw_json = json.dumps(field, ensure_ascii=False, indent=2)
    raw_json_one_line = json.dumps(field, ensure_ascii=False, separators=(",", ":"))

    return {
        "Тип источника": normalize_source_type(source_type),
        "ID источника": source_id,
        "Название источника": source_name,

        "ID поля": field.get("id", ""),
        "Название поля": field.get("name", ""),
        "Названия поля по языкам": normalize_names(field.get("names", {})),

        "ID типа поля": field_type,
        "Тип поля": FIELD_TYPE_NAMES.get(field_type, ""),

        "Формула": formula,
        "Формула в одну строку": formula_one_line,

        "ID группы полей": field.get("groupId", ""),
        "ID справочника": field.get("directoryId", ""),

        "Опции поля": normalize_options(options),
        "Значения списка": normalize_enum_values(field.get("enumValues", "")),
        "Поля справочника": normalize_directory_fields(field.get("directoryFields", "")),

        "ID типа результата формулы": view_result.get("id", ""),
        "Тип результата формулы": view_result.get("name", ""),

        "Разделитель": field.get("delimiter", ""),
        "Количество знаков после запятой": field.get("numberOfDecimalPlaces", ""),

        "JSON поля": raw_json,
        "JSON поля в одну строку": raw_json_one_line,
    }


def get_fields_by_source(config: dict, source_type: str, source_id: int) -> list[dict]:
    if source_type == "object":
        return get_object_fields(config, source_id)

    if source_type == "task_template":
        return get_task_template_fields(config, source_id)

    raise RuntimeError(
        "Неизвестный тип источника.\n"
        "Допустимые значения:\n"
        "- object\n"
        "- task_template"
    )
