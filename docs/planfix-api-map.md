# Карта Planfix API для поиска использований полей

Источник истины: `inputs/swagger.json`.

В этом документе зафиксированы только возможности API, подтвержденные
`inputs/swagger.json` или текущим кодом проекта. Все пункты с пометкой
"требует проверки через API" нельзя использовать как факт до получения
реального read-only ответа Planfix.

## Подтвержденные типы полей

`GET /customfield/type` возвращает `customFieldTypes`.

Подтвержденный тип вычисляемого поля:

- `24` = `Calculated field` / `Вычисляемое поле`

Текущий проект также использует `24` как тип вычисляемого поля в
`field_exporter.py`.

## Подтвержденная схема пользовательского поля

Схема `CustomField` в swagger подтверждает эти свойства:

- `id`
- `name`
- `names`
- `type`
- `objectType`
- `groupId`
- `directoryId`
- `directoryFields`
- `enumValues`
- `mainValue` для основных полей

Подтвержденные `objectType`:

- `0` = задача
- `1` = контакт
- `2` = справочник
- `3` = проект
- `4` = аналитика
- `5` = основное поле
- `6` = сотрудник

## Доступность формулы

Важное ограничение: `inputs/swagger.json` не перечисляет `formula`,
`viewResult`, `delimiter` и `numberOfDecimalPlaces` как документированные поля
для `/customfield/*`.

Текущий проект уже запрашивает эти поля для пользовательских полей шаблонов
задач в `planfix_client.py` через `TASK_TEMPLATE_FIELDS_PARAM`.

Следовательно:

- `formula` подтверждена текущим кодом проекта для чтения пользовательских
  полей шаблонов задач.
- Доступность `formula` для контактов, проектов, справочников, аналитик,
  основных полей и сотрудников требует проверки через реальный API.
- Синтаксис формулы и синтаксис ссылок на поля внутри формулы нельзя считать
  известным до проверки реальных ответов Planfix.

## Подтвержденные endpoints пользовательских полей

Все endpoints ниже поддерживают параметр `fields`, если не указано иное.

### Общие пользовательские поля

- `GET /customfield/task` — пользовательские поля задач
- `GET /customfield/contact` — пользовательские поля контактов
- `GET /customfield/project` — пользовательские поля проектов
- `GET /customfield/user` — пользовательские поля сотрудников
- `GET /customfield/main` — основные пользовательские поля

### Пользовательские поля конкретных сущностей

- `GET /customfield/task/{id}` — поля конкретной задачи или шаблона задачи
- `GET /customfield/contact/{id}` — поля конкретного контакта
- `GET /customfield/project/{id}` — поля конкретного проекта
- `GET /customfield/user/{id}` — поля конкретного сотрудника
- `GET /customfield/directory/{id}` — поля конкретного справочника
- `GET /customfield/datatag/{id}` — поля конкретной аналитики

Точное бизнес-значение `{id}` для scoped endpoints требует проверки через API
по каждому типу сущности. Текущее приложение использует
`/customfield/task/{id}` с id шаблонов задач.

## Подтвержденные endpoints списков сущностей

Эти endpoints дают id и названия сущностей, пользовательские поля которых
может понадобиться проверять.

### Объекты задач и шаблоны задач

- `POST /object/list`
  - тело запроса поддерживает `offset`, `pageSize`
- `GET /object/{id}`
  - схема ответа содержит `object.customFieldData`
- `GET /task/templates`
  - параметры запроса: `offset`, `pageSize`, `sourceId`, `fields`

### Контакты и шаблоны контактов

- `POST /contact/list`
  - тело запроса поддерживает `offset`, `pageSize`, `filterId`, `filters`,
    `isCompany`, `onlyChanged`, `prefixedId`, `fields`, `sourceId`
- `GET /contact/templates`
  - параметры запроса: `offset`, `pageSize`, `isCompany`, `sourceId`, `fields`
- `GET /contact/{id}`
  - схема ответа содержит `contact.customFieldData`

### Проекты и шаблоны проектов

- `POST /project/list`
  - тело запроса поддерживает `offset`, `pageSize`, `fields`, `sourceId`,
    `filters`
- `GET /project/templates`
  - параметры запроса включают `fields`
- `GET /project/{id}`
  - схема ответа содержит `project.customFieldData`

### Сотрудники

- `POST /user/list`
  - тело запроса поддерживает `offset`, `pageSize`, `onlyActive`,
    `prefixedId`, `fields`, `sourceId`, `filters`
- `GET /user/{id}`
  - схема ответа содержит `user.customFieldData`

### Справочники и аналитики

- `POST /directory/list`
  - тело запроса поддерживает `groupId`, `offset`, `pageSize`, `fields`
- `GET /directory/{id}`
  - схема ответа содержит `directory.fields`
- `POST /directory/{id}/entry/list`
  - тело запроса поддерживает `offset`, `pageSize`, `fields`, `groupsOnly`,
    `entriesOnly`, `filterId`, `filters`
- `GET /directory/{id}/entry/{key}`
  - параметры запроса включают `fields`
- `POST /datatag/list`
  - тело запроса поддерживает `offset`, `pageSize`, `fields`
- `GET /datatag/{id}`
  - схема ответа содержит `dataTag.fields`

## Обязательные runtime-правила

Все HTTP-запросы к Planfix должны проходить через общий rate limiter:

- минимальная пауза между любыми двумя HTTP-запросами: `1.25` секунды;
- правило действует для GUI, read-only скриптов, малых разведочных выгрузок и
  долгих сканирований.

Долгие операции должны показывать прогресс:

- текущий этап;
- количество обработанных страниц, сущностей или полей;
- время последнего запроса;
- путь текущего output-файла.

## Вопросы для следующей проверки через API

Read-only разведочный скрипт должен ответить на эти вопросы до реализации
поиска:

- Какие endpoints пользовательских полей реально возвращают `formula`, если
  запросить это поле?
- Есть ли вычисляемые поля (`type == 24`) у задач, контактов, проектов,
  сотрудников, справочников, аналитик и основных полей в текущем аккаунте
  Planfix?
- Какой точный текст формулы возвращает Planfix?
- Как Planfix ссылается на другое поле внутри формулы?
- Какие текстовые поля справочников (`type == 2`) содержат формульные
  конструкции и ссылки `{{...}}`?
- Надежно ли доступны поля шаблонов задач через `/customfield/task/{id}` с id
  из `/task/templates`?
- Какие scoped ids принимает Planfix для `/customfield/contact/{id}`,
  `/customfield/project/{id}`, `/customfield/user/{id}`,
  `/customfield/directory/{id}` и `/customfield/datatag/{id}`?
