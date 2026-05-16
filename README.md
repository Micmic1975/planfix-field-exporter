# Planfix Field Exporter

## Русский

Небольшое настольное приложение для выгрузки пользовательских полей Planfix в CSV.

### Возможности

- выгрузка полей объектов Planfix;
- выгрузка полей шаблонов задач Planfix;
- выбор объекта или шаблона из полного списка;
- сохранение CSV-файлов в папку `Документы\Planfix Field Exporter`;
- хранение токена доступа в системном хранилище секретов Windows;
- графический интерфейс на Tkinter.

### Где хранятся данные

- обычные настройки приложения:
  `AppData\Roaming\PlanfixTools\Planfix Field Exporter\settings.json`;
- токен доступа:
  в системном хранилище секретов Windows;
- CSV-выгрузки:
  `Документы\Planfix Field Exporter`.

### Запуск из исходников

1. Установите Python.
2. Создайте и активируйте виртуальное окружение.
3. Установите зависимости:

   ```bash
   pip install -r requirements.txt
   ```

4. Запустите приложение:

   ```bash
   python app.py
   ```

При первом запуске введите аккаунт Planfix и токен доступа, затем нажмите **Сохранить настройки**.

### Консольная версия

В проекте пока сохранён файл `planfix_export_fields_interactive.py` — это старая консольная версия.

Если вы хотите использовать именно её:

1. скопируйте `config.example.json` в `config.json`;
2. заполните свои значения;
3. запустите:

   ```bash
   python planfix_export_fields_interactive.py
   ```

`config.json` исключён из Git и не должен публиковаться.

### Руководство пользователя

Подробное руководство на русском языке:

```text
docs/user-guide.ru.md
```

---

## English

A small desktop application for exporting Planfix custom fields to CSV.

### Features

- export custom fields of Planfix objects;
- export custom fields of Planfix task templates;
- choose an object or task template from the complete list;
- save CSV files to `Documents\Planfix Field Exporter`;
- store the access token in the Windows system credential store;
- Tkinter-based graphical interface.

### Data locations

- application settings:
  `AppData\Roaming\PlanfixTools\Planfix Field Exporter\settings.json`;
- access token:
  stored in the Windows system credential store;
- CSV exports:
  `Documents\Planfix Field Exporter`.

### Run from source

1. Install Python.
2. Create and activate a virtual environment.
3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Run the application:

   ```bash
   python app.py
   ```

On the first launch, enter your Planfix account and access token, then click **Save settings**.

### Console version

The project still contains `planfix_export_fields_interactive.py`, the older console-based version.

If you want to use it:

1. copy `config.example.json` to `config.json`;
2. fill in your own values;
3. run:

   ```bash
   python planfix_export_fields_interactive.py
   ```

`config.json` is excluded from Git and must not be published.
