# Planfix Field Exporter

## Русский

Небольшое настольное приложение для просмотра пользовательских полей Planfix.

### Возможности

- просмотр полей объектов Planfix;
- просмотр полей шаблонов задач Planfix;
- выбор объекта или шаблона из полного списка;
- просмотр результата в таблице приложения;
- выбор столбцов, которые нужно показать;
- фильтрация и сортировка таблицы;
- копирование отдельных значений из таблицы;
- сохранение выбранного набора столбцов в CSV;
- локальный индекс формул Planfix: вычисляемые поля задач/контактов и
  текстовые поля записей справочников;
- быстрый поиск использований выбранного поля в формулах по локальному индексу;
- хранение токена доступа в системном хранилище секретов Windows;
- графический интерфейс на Tkinter.

### Где хранятся данные

- обычные настройки приложения:
  `AppData\Roaming\PlanfixTools\Planfix Field Exporter\settings.json`;
- токен доступа:
  в системном хранилище секретов Windows;
- CSV-выгрузки:
  по умолчанию `Документы\Planfix Field Exporter`, либо выбранная пользователем папка.
- локальный индекс формул:
  `<Папка выгрузок>\formula_index`;
- результаты поиска по формулам:
  `<Папка выгрузок>\formula_search\<timestamp>`.

При обновлении индекса формул приложение выполняет read-only запросы к Planfix
с паузой не менее `1.25` секунды между любыми HTTP-запросами.

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

Консольная версия по-прежнему сохраняет результат в CSV.

### Руководство пользователя

Подробное руководство на русском языке:

```text
docs/user-guide.ru.md
```

---

## English

A small desktop application for viewing Planfix custom fields.

### Features

- view custom fields of Planfix objects;
- view custom fields of Planfix task templates;
- choose an object or task template from the complete list;
- view the result in an in-app table;
- choose which columns should be visible;
- filter and sort the table;
- copy individual values from the table;
- save the selected column set to CSV;
- local Planfix formula index for task/contact calculated fields and text
  fields in directory entries;
- fast local search for usages of the selected field in formulas;
- store the access token in the Windows system credential store;
- Tkinter-based graphical interface.

### Data locations

- application settings:
  `AppData\Roaming\PlanfixTools\Planfix Field Exporter\settings.json`;
- access token:
  stored in the Windows system credential store;
- CSV exports:
  `Documents\Planfix Field Exporter` by default, or a user-selected folder.
- local formula index:
  `<Exports folder>\formula_index`;
- formula search results:
  `<Exports folder>\formula_search\<timestamp>`.

Formula index updates use read-only Planfix requests with at least `1.25`
seconds between any two HTTP requests.

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

The console version still saves the result to CSV.
