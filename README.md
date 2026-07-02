# approval-service

A backend service for approving/rejecting/cancelling content before publication.
Content itself (publications, scenarios, edits, users, workspaces) lives in other
services; this service only stores approval requests that reference them by
opaque id.

Stack: **Python 3.12 + FastAPI + SQLAlchemy + Alembic**. SQLite for local/dev,
PostgreSQL for docker-compose (works with either via `DATABASE_URL`).

## Run with Docker (recommended)

```bash
docker compose up --build
```

This starts Postgres, runs Alembic migrations, and serves the API on
`http://localhost:8000`. Health check: `curl http://localhost:8000/health`.

## Run locally without Docker

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # defaults to sqlite:///./approval_service.db
export $(cat .env | xargs)

alembic upgrade head
uvicorn app.main:app --reload
```

## Run tests

```bash
pip install -r requirements.txt
pytest -v
```

Tests spin up an isolated SQLite file per test (via `Base.metadata.create_all`,
not Alembic, for speed) and never touch a shared database.

## Auth (local stub)

There's no real identity provider here. Every request must carry three headers
that a real gateway/auth service would normally inject after validating a token:

| Header            | Meaning                                              |
|--------------------|-------------------------------------------------------|
| `X-User-Id`        | opaque external user id, e.g. `usr_1`                 |
| `X-Workspace-Id`   | opaque external workspace id, e.g. `ws_1`              |
| `X-Scopes`         | comma-separated list of granted scopes                |

Scopes:

| Scope              | Required for                          |
|---------------------|----------------------------------------|
| `approval:read`     | `GET` list / get                       |
| `approval:create`   | `POST .../approval-requests`           |
| `approval:decide`   | `POST .../approve`, `POST .../reject`  |
| `approval:cancel`   | `POST .../cancel`                      |

The `workspace_id` in the URL **must** match `X-Workspace-Id`; a mismatch is
rejected with `403` rather than silently scoping to the header's workspace,
so a client can never accidentally (or intentionally) read/write a workspace
its token wasn't issued for.

Example:

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

## Idempotency

Every state-changing endpoint (`create`, `approve`, `reject`, `cancel`) requires
an `Idempotency-Key` header. Repeating the same request with the same key
replays the original response instead of creating a duplicate approval
request or applying a decision twice. Reusing a key with a different request
body returns `409`. See `DESIGN.md` for details.

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

Interactive docs (Swagger UI) once running: `http://localhost:8000/docs`.

See `DESIGN.md` for the data model, service boundaries, and known trade-offs.
