import json
import re
from pathlib import Path

import keyring
from keyring.errors import KeyringError
from platformdirs import user_config_dir, user_documents_dir


APP_NAME = "Planfix Field Exporter"
APP_AUTHOR = "PlanfixTools"
SETTINGS_FILENAME = "settings.json"
TOKEN_SERVICE_NAME = "Planfix Field Exporter"


def get_settings_dir() -> Path:
    return Path(
        user_config_dir(
            appname=APP_NAME,
            appauthor=APP_AUTHOR,
            roaming=True,
        )
    )


def get_settings_file() -> Path:
    return get_settings_dir() / SETTINGS_FILENAME


def get_exports_dir() -> Path:
    return Path(user_documents_dir()) / APP_NAME


def make_output_filename(source_type: str, source_id: int) -> Path:
    return get_exports_dir() / f"planfix_{source_type}_{source_id}_fields.csv"


def sanitize_filename_part(value: str) -> str:
    cleaned_value = str(value).strip()

    if not cleaned_value:
        return "without_name"

    cleaned_value = re.sub(r'[<>:"/\\|?*]', "_", cleaned_value)
    cleaned_value = re.sub(r"\s+", " ", cleaned_value)
    cleaned_value = re.sub(r"_+", "_", cleaned_value)
    cleaned_value = cleaned_value.rstrip(". ")

    return cleaned_value or "without_name"


def make_named_output_filename(
    source_type: str,
    source_id: int,
    source_name: str,
) -> Path:
    safe_source_name = sanitize_filename_part(source_name)
    return get_exports_dir() / (
        f"planfix_{source_type}_{source_id}_{safe_source_name}_fields.csv"
    )


def normalize_account(account: str) -> str:
    return str(account).strip()


def normalize_token(token: str) -> str:
    return str(token).strip()


def validate_account(account: str) -> str:
    cleaned_account = normalize_account(account)

    if not cleaned_account:
        raise ValueError("Аккаунт Planfix не может быть пустым.")

    return cleaned_account


def validate_token(token: str) -> str:
    cleaned_token = normalize_token(token)

    if not cleaned_token:
        raise ValueError("Токен доступа не может быть пустым.")

    if cleaned_token.lower().startswith("bearer "):
        raise ValueError(
            "Нужно указывать только сам токен, без слова Bearer."
        )

    try:
        cleaned_token.encode("latin-1")
    except UnicodeEncodeError as error:
        raise ValueError(
            "В токене есть недопустимые символы. "
            "Скорее всего, там русские буквы или лишний текст."
        ) from error

    return cleaned_token


def load_account() -> str | None:
    settings_file = get_settings_file()

    if not settings_file.exists():
        return None

    try:
        with open(settings_file, "r", encoding="utf-8") as file:
            data = json.load(file)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"Ошибка в формате файла настроек:\n{error}"
        ) from error

    if not isinstance(data, dict):
        raise RuntimeError(
            "Файл настроек должен содержать JSON-объект."
        )

    account = normalize_account(data.get("account", ""))
    return account or None


def save_account(account: str) -> None:
    cleaned_account = validate_account(account)
    settings_dir = get_settings_dir()
    settings_dir.mkdir(parents=True, exist_ok=True)

    with open(get_settings_file(), "w", encoding="utf-8") as file:
        json.dump(
            {"account": cleaned_account},
            file,
            ensure_ascii=False,
            indent=2,
        )


def load_token(account: str) -> str | None:
    cleaned_account = normalize_account(account)

    if not cleaned_account:
        return None

    try:
        token = keyring.get_password(TOKEN_SERVICE_NAME, cleaned_account)
    except KeyringError as error:
        raise RuntimeError(
            "Не удалось прочитать токен из системного хранилища секретов."
        ) from error

    if token is None:
        return None

    cleaned_token = normalize_token(token)
    return cleaned_token or None


def save_token(account: str, token: str) -> None:
    cleaned_account = validate_account(account)
    cleaned_token = validate_token(token)

    try:
        keyring.set_password(
            TOKEN_SERVICE_NAME,
            cleaned_account,
            cleaned_token,
        )
    except KeyringError as error:
        raise RuntimeError(
            "Не удалось сохранить токен в системное хранилище секретов."
        ) from error


def has_complete_settings() -> bool:
    account = load_account()

    if not account:
        return False

    return load_token(account) is not None
