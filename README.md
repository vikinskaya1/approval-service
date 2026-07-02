# approval-service

Backend-сервис для согласования контента (approve/reject/cancel) перед публикацией.
Сам контент (публикации, сценарии, правки, пользователи, workspace'ы) живёт в других
сервисах; этот сервис хранит только заявки на согласование, которые ссылаются на них
по внешним (opaque) идентификаторам.

Стек: **Python 3.12 + FastAPI + SQLAlchemy + Alembic**. SQLite — для локального
запуска/разработки, PostgreSQL — для docker-compose (работает с обеими БД через
`DATABASE_URL`).

## Запуск через Docker (рекомендуется)

```bash
docker compose up --build
```

Поднимется Postgres, применятся миграции Alembic, и API будет доступен на
`http://localhost:8000`. Проверка: `curl http://localhost:8000/health`.

## Запуск локально без Docker

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # по умолчанию используется sqlite:///./approval_service.db
export $(cat .env | xargs)

alembic upgrade head
uvicorn app.main:app --reload
```

## Запуск тестов

```bash
pip install -r requirements.txt
pytest -v
```

Каждый тест поднимает изолированный файл SQLite (через `Base.metadata.create_all`,
а не через Alembic — для скорости) и никогда не трогает общую/боевую базу данных.

## Авторизация (локальная заглушка)

Реального провайдера идентификации здесь нет. Каждый запрос должен содержать три
заголовка, которые в реальной системе обычно проставляет шлюз/сервис авторизации
после проверки токена:

| Заголовок          | Значение                                              |
|---------------------|--------------------------------------------------------|
| `X-User-Id`        | внешний (opaque) идентификатор пользователя, напр. `usr_1` |
| `X-Workspace-Id`   | внешний (opaque) идентификатор workspace, напр. `ws_1`     |
| `X-Scopes`         | список прав через запятую                              |

Права доступа (scopes):

| Scope               | Требуется для                          |
|----------------------|------------------------------------------|
| `approval:read`     | `GET` списка / одной заявки              |
| `approval:create`   | `POST .../approval-requests`             |
| `approval:decide`   | `POST .../approve`, `POST .../reject`    |
| `approval:cancel`   | `POST .../cancel`                        |

`workspace_id` в URL **обязан** совпадать с `X-Workspace-Id`; при несовпадении
запрос отклоняется с кодом `403`, а не молча обрабатывается в контексте workspace
из заголовка. Это гарантирует, что клиент никогда не сможет (случайно или намеренно)
прочитать/изменить данные workspace, для которого его токен не выдавался.

Пример:

```bash
curl -X POST http://localhost:8000/api/v1/workspaces/ws_1/approval-requests \
  -H "Content-Type: application/json" \
  -H "X-User-Id: usr_1" \
  -H "X-Workspace-Id: ws_1" \
  -H "X-Scopes: approval:read,approval:create,approval:decide,approval:cancel" \
  -H "Idempotency-Key: 4f6c9b1e-2222-4a3e-9b3a-111111111111" \
  -d '{
    "sourceType": "publication",
    "sourceId": "pub_123",
    "title": "Instagram reel draft",
    "description": "Needs final approval",
    "reviewerUserIds": ["usr_1", "usr_2"]
  }'
```

## Идемпотентность

Каждый изменяющий состояние эндпоинт (`create`, `approve`, `reject`, `cancel`)
требует заголовок `Idempotency-Key`. Повторный запрос с тем же ключом возвращает
исходный ответ вместо того, чтобы создать дубликат заявки или применить решение
повторно. Повторное использование ключа с другим телом запроса возвращает `409`.
Подробности — в `DESIGN.md`.

## API

```
GET  /health
GET  /ready

POST /api/v1/workspaces/{workspace_id}/approval-requests
GET  /api/v1/workspaces/{workspace_id}/approval-requests
GET  /api/v1/workspaces/{workspace_id}/approval-requests/{request_id}
POST /api/v1/workspaces/{workspace_id}/approval-requests/{request_id}/approve
POST /api/v1/workspaces/{workspace_id}/approval-requests/{request_id}/reject
POST /api/v1/workspaces/{workspace_id}/approval-requests/{request_id}/cancel
```

Интерактивная документация (Swagger UI) при запущенном сервисе:
`http://localhost:8000/docs`.

Модель данных, границы сервиса и известные компромиссы — см. `DESIGN.md`.
