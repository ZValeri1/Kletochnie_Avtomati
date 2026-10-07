# Gamma Irradiation Web Model

Локальный исследовательский прототип модели металлической решётки под гамма-облучением Co-60. Сервер, интерфейс и тесты находятся в одном проекте. Текущая физическая реализация пересматривается по документам в `docs/`.

> Это исследовательский прототип для изучения сценариев. Модель не является откалиброванным предсказателем свойств материала и не заменяет физический расчёт или эксперимент.

## Возможности

- 2D- и 3D-отображение состояния симуляции.
- Отдельные серверные модули для модели, управления, API и данных.
- Версионированные DTO, HTTP API и WebSocket.
- Несколько независимых симуляций, сохранение проектов и исследовательские серии.

Новые физические правила, интерфейсные функции и критерии приёмки описаны в `docs/new_docs/IMPLEMENTATION_PLAN.md` и сопутствующих ТЗ. Перечисление текущих возможностей не означает, что эти критерии уже выполнены.

## Архитектура

```text
React / store / RenderFrame
            │ HTTP / WebSocket DTO
            ▼
FastAPI API adapters
            │
            ▼
SimulationManager ── SimulationScheduler
            │                    │
            ▼                    ▼
Atomic Model             Data & Research
Topology · State         Projects · Export
Events · Metrics         Experiments · Statistics
```

Python-бэкенд является источником истины. Каждая симуляция имеет отдельные состояние, RNG, историю и очередь команд. Команды одной симуляции выполняются последовательно, разные симуляции — параллельно в пределах лимита scheduler. Renderer получает готовый `RenderFrame` и не содержит физической логики.

## Требования

- Python 3.11+.
- Node.js 20+ и pnpm.
- Playwright-браузеры для end-to-end тестов.

Зависимости Python перечислены в [`requirements.txt`](requirements.txt), интерфейса — в [`package.json`](package.json).

## Установка

```powershell
cd D:\gamma-irradiation-web
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
pnpm install --frozen-lockfile
pnpm build
```

## Запуск

```powershell
cd D:\gamma-irradiation-web
.\.venv\Scripts\Activate.ps1
uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Откройте <http://127.0.0.1:8000>.

Для Windows можно запустить [`scripts/start.bat`](scripts/start.bat). Скрипт раздаёт собранный интерфейс из корневого `dist/` и запускает API на `127.0.0.1:8000`. Для доступа с другого устройства потребуется отдельно настроить адрес прослушивания, брандмауэр и внешний туннель.

## Работа в интерфейсе

1. Выберите размерность и параметры, доступные в текущей панели.
2. Создайте симуляцию и используйте команды шага, запуска и паузы.
3. При необходимости сохраните проект или экспортируйте результат.

Непрерывный запуск выполняется без промежуточной отрисовки: интерфейс получает
последнее рассчитанное состояние при паузе или остановке. Вероятности переходов
настраиваются по типу позиции, контуру и положению относительно металла.

Правила модели и план их обновления находятся в документации `docs/`.

## API

| Метод | Маршрут | Назначение |
|---|---|---|
| `GET` | `/health` | Проверка сервера |
| `POST` | `/api/simulations` | Создать симуляцию |
| `GET` | `/api/simulations` | Список активных симуляций |
| `GET` | `/api/simulations/{id}/snapshot` | Получить snapshot |
| `PATCH` | `/api/simulations/{id}/configuration` | Изменить конфигурацию до старта |
| `POST` | `/api/simulations/{id}/edit` | Единая команда add/remove/move/boundary |
| `POST` | `/api/simulations/{id}/start` | Завершить подготовку без физического акта |
| `POST` | `/api/simulations/{id}/step` | Один акт с `expected_revision` |
| `POST` | `/api/simulations/{id}/run` | Непрерывный запуск |
| `POST` | `/api/simulations/{id}/pause` | Пауза |
| `POST` | `/api/simulations/{id}/stop` | Остановка |
| `POST` | `/api/simulations/{id}/reset` | Новая траектория из исходной конфигурации |
| `POST` | `/api/simulations/{id}/undo` | Отмена |
| `POST` | `/api/simulations/{id}/redo` | Повтор |
| `POST` | `/api/simulations/{id}/error/retry` | Повторить восстановимую команду |
| `POST` | `/api/simulations/{id}/error/acknowledge` | Подтвердить ошибку и вернуться на паузу |
| `POST` | `/api/simulations/{id}/diagnostics/probabilities` | Диагностика вероятностей на паузе |
| `GET` | `/api/simulations/{id}/events` | Фильтруемый журнал событий |
| `GET` | `/api/simulations/{id}/metrics` | Полный или диапазонный ряд метрик |
| `GET` | `/api/simulations/{id}/slices?axis=z` | Атлас Z-срезов |
| `GET` | `/api/simulations/{id}/journal.json` | Явная загрузка журнала JSON |
| `POST` | `/api/experiments` | Серия и агрегация |
| `GET` | `/api/projects` | Список сохранённых проектов |
| `POST` | `/api/projects/{id}/save` | Атомарное сохранение проекта |
| `POST` | `/api/projects/{id}/load` | Загрузка проекта |
| `DELETE` | `/api/projects/{id}?confirm=true` | Подтверждённое удаление проекта |
| `WebSocket` | `/ws/simulations/{id}` | События одной симуляции |

OpenAPI-документация доступна по адресу <http://127.0.0.1:8000/docs>.

Новая симуляция создаётся в статусе `PREPARATION`. В запросе создания можно задать `initialization_mode`: `ordered`, `random_defective`, `explicit_defective` или `symmetric_defective`. Для явного и симметричного режимов используются независимые целые `n_v`, `n_i`, `n_as`. Для случайного режима шесть параметров задаются в `random_parameters`, например `{"vacancies":{"mu":2,"sigma":1},"interstitials":{"mu":1,"sigma":0.5},"adatoms":{"mu":0.5,"sigma":0.2}}`. Все правки принимают `expected_revision`; первый `start`, `step` или `run` блокирует конфигурацию и границу. Ручной перенос не увеличивает номер физического акта.

### Пример создания модели

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/api/simulations `
  -ContentType 'application/json' `
  -Body '{"dimensions":[20,20],"seed_init":42,"seed_sim":43,"profile":"fe_co60_physical"}'
```

### Пример шага

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/api/simulations/SIMULATION_ID/step `
  -ContentType 'application/json' `
  -Body '{"expected_revision":0}'
```

## Сохранение проектов

Проекты сохраняются в `runtime/projects/` и не попадают в Git. Запись выполняется через временный каталог и атомарную замену; RNG и checkpoint-история входят в проект. Пользовательский экспорт журнала отделён от проекта: он формируется только по явному `GET .../journal.json`, не принимает серверный путь и не создаёт файл в `runtime/`.

## Разработка

```text
backend/                         # домен, управление, данные, DTO и API
src/                             # React-приложение и renderer-адаптеры
tests/unit/                      # изолированные component tests
tests/property/                  # генерируемые доменные инварианты
tests/integration/               # API, WebSocket, storage, research
tests/contract/                  # общие версионированные DTO fixtures
tests/e2e/                       # короткие браузерные сценарии
tests/long/                      # длительные проверки, только вручную
docs/                            # архитектурная и тестовая спецификации
runtime/                         # локальные проекты и экспорты
scripts/                         # точки запуска
legacy/                          # сохранённый архив прежних материалов
```

Команды проверки собраны в [`tests/README.md`](tests/README.md). Для разработки интерфейса используйте `pnpm dev`; API запускается отдельно.

## Тестирование

Используйте команды и порядок запуска из [`tests/README.md`](tests/README.md).

## Ограничения текущей версии

- Модель качественная и не откалибрована под конкретный материал.
- По умолчанию сервер слушает только `127.0.0.1`.
- Активные сессии хранятся в памяти процесса; долговременное состояние нужно сохранять как проект.

## Вклад в проект

Перед отправкой изменений запускайте тесты, проверку TypeScript и production-сборку. Для новых событий добавляйте тесты на геометрию, нормировку вероятностей, сохранение числа атомов и метрики.

## Лицензия

Файл лицензии в репозитории не указан. До добавления `LICENSE` права на код не определены для свободного использования.
