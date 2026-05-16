import csv
from pathlib import Path


CSV_COLUMNS = [
    "Тип источника",
    "ID источника",
    "Название источника",

    "ID поля",
    "Название поля",
    "Названия поля по языкам",

    "ID типа поля",
    "Тип поля",

    "Формула",
    "Формула в одну строку",

    "ID группы полей",
    "ID справочника",

    "Опции поля",
    "Значения списка",
    "Поля справочника",

    "ID типа результата формулы",
    "Тип результата формулы",

    "Разделитель",
    "Количество знаков после запятой",

    "JSON поля",
    "JSON поля в одну строку",
]


def save_to_csv(rows: list[dict], filename: Path) -> None:
    filename.parent.mkdir(exist_ok=True)

    try:
        with open(filename, "w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=CSV_COLUMNS, delimiter=";")
            writer.writeheader()
            writer.writerows(rows)
    except PermissionError as error:
        raise RuntimeError(
            "Не удалось сохранить CSV-файл.\n"
            "Скорее всего, он уже открыт в Excel или другой программе.\n"
            "Закройте файл и попробуйте выгрузить ещё раз.\n\n"
            f"Файл:\n{filename}"
        ) from error
