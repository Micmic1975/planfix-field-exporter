import json

import requests


TASK_TEMPLATE_FIELDS_PARAM = ",".join(
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
        "options",
        "formula",
        "viewResult",
        "delimiter",
        "numberOfDecimalPlaces",
    ]
)


def load_all_pages(
    fetch_page,
    items_key: str,
    page_size: int = 100,
) -> list[dict]:
    all_items = []
    offset = 0

    while True:
        data = fetch_page(offset, page_size)
        items = data.get(items_key, [])

        if not isinstance(items, list):
            raise RuntimeError(
                f"В ответе Planfix не найден массив {items_key}.\n"
                f"{json.dumps(data, ensure_ascii=False, indent=2)}"
            )

        all_items.extend(items)

        if len(items) < page_size:
            break

        offset += page_size

    return all_items


def planfix_get(config: dict, path: str, params: dict | None = None) -> dict:
    url = f"{config['base_url']}{path}"

    headers = {
        "Authorization": f"Bearer {config['token']}",
        "Accept": "application/json",
    }

    response = requests.get(url, headers=headers, params=params, timeout=60)

    if response.status_code != 200:
        raise RuntimeError(
            f"Ошибка Planfix API: {response.status_code}\n"
            f"URL: {response.url}\n"
            f"Ответ: {response.text}"
        )

    return response.json()


def planfix_post(config: dict, path: str, payload: dict | None = None) -> dict:
    url = f"{config['base_url']}{path}"

    headers = {
        "Authorization": f"Bearer {config['token']}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    response = requests.post(url, headers=headers, json=payload or {}, timeout=60)

    if response.status_code != 200:
        raise RuntimeError(
            f"Ошибка Planfix API: {response.status_code}\n"
            f"URL: {response.url}\n"
            f"Ответ: {response.text}"
        )

    return response.json()


def get_object_list(config: dict) -> list[dict]:
    def fetch_page(offset: int, page_size: int) -> dict:
        data = planfix_post(
            config,
            "/object/list",
            payload={
                "offset": offset,
                "pageSize": page_size,
                "fields": "id,name",
            },
        )

        if data.get("result") != "success":
            raise RuntimeError(
                "Planfix вернул неуспешный результат при получении списка объектов:\n"
                f"{json.dumps(data, ensure_ascii=False, indent=2)}"
            )

        return data

    return load_all_pages(fetch_page, "objects")


def check_connection(config: dict) -> None:
    data = planfix_post(
        config,
        "/object/list",
        payload={
            "offset": 0,
            "pageSize": 1,
            "fields": "id,name",
        },
    )

    if data.get("result") != "success":
        raise RuntimeError(
            "Planfix вернул неуспешный результат при проверке настроек:\n"
            f"{json.dumps(data, ensure_ascii=False, indent=2)}"
        )


def get_task_template_list(config: dict) -> list[dict]:
    def fetch_page(offset: int, page_size: int) -> dict:
        data = planfix_get(
            config,
            "/task/templates",
            params={
                "offset": offset,
                "pageSize": page_size,
                "fields": "id,name",
            },
        )

        if data.get("result") != "success":
            raise RuntimeError(
                "Planfix вернул неуспешный результат при получении списка шаблонов задач:\n"
                f"{json.dumps(data, ensure_ascii=False, indent=2)}"
            )

        return data

    return load_all_pages(fetch_page, "templates")


def get_object_data(config: dict, api_object_id: int) -> dict:
    data = planfix_get(config, f"/object/{api_object_id}")

    if data.get("result") != "success":
        raise RuntimeError(
            "Planfix вернул неуспешный результат:\n"
            f"{json.dumps(data, ensure_ascii=False, indent=2)}"
        )

    return data


def get_task_template_data(config: dict, template_id: int) -> dict:
    data = planfix_get(
        config,
        f"/customfield/task/{template_id}",
        params={
            "fields": TASK_TEMPLATE_FIELDS_PARAM
        },
    )

    if data.get("result") != "success":
        raise RuntimeError(
            "Planfix вернул неуспешный результат:\n"
            f"{json.dumps(data, ensure_ascii=False, indent=2)}"
        )

    return data
