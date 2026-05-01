# Second Brain — Agent Guide

## Project overview

Single-user LLM wiki app. FastAPI + async SQLAlchemy backend, React 18 + Vite frontend, Postgres 16 + pgvector, MinIO for file storage. See `README.md` for full feature list and `docs/architecture.md` for system diagrams.

## CRITICAL — test database isolation

**Never run pytest against the `wiki` database.** The `tests/conftest.py` `clean_db` fixture (`autouse=True`) runs `drop_all` + `create_all` before every single test, wiping all tables. Running this against the production `wiki` database destroys all user data.

Tests are wired to a dedicated `wiki_test` database:

- `conftest.py` line 10 forces `DATABASE_URL=postgresql+asyncpg://wiki:wiki@db:5432/wiki_test`
- Do not change this URL — never point tests at `wiki`
- `wiki_test` is created on fresh volumes via `postgres-init/01-create-test-db.sql`
- If `wiki_test` does not exist yet: `docker compose exec db psql -U wiki -c "CREATE DATABASE wiki_test;"`

Always run tests inside the compose network:

```bash
docker compose run --rm api pytest tests/ -v
```

## Repo layout

| Path | Role |
|------|------|
| `api/app/routes/` | FastAPI route handlers |
| `api/app/agents/` | Background ingest, chat, monitor agents |
| `api/app/models.py` | SQLAlchemy models |
| `api/alembic/versions/` | DB migrations |
| `frontend/src/` | React + TypeScript UI |
| `tests/` | Pytest suite (mounted into API container) |
| `postgres-init/` | SQL scripts run on fresh Postgres volume |

## Development

```bash
# Start stack
docker compose up --build

# Migrations
docker compose run --rm api alembic upgrade head

# Tests (safe — wiki_test only)
docker compose run --rm api pytest tests/ -v
```

## Conventions

- Generate migrations with `alembic revision --autogenerate -m "description"`, then review before applying
- SSE endpoints stream agent status — prefer extending existing SSE patterns over new polling routes
- `VECTOR_SEARCH_ENABLED=false` disables embedding API calls; useful during development/testing to avoid LLM costs
