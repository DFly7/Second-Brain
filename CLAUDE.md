# Second Brain — Claude Code Guide

## Project overview

Single-user LLM wiki app. FastAPI + async SQLAlchemy backend, React 18 + Vite frontend, Postgres 16 + pgvector, MinIO for file storage. See `README.md` for full feature list.

## Running tests

**CRITICAL — tests use a separate `wiki_test` database, NOT the production `wiki` database.**

`tests/conftest.py` has an `autouse` fixture (`clean_db`) that runs `drop_all` + `create_all` before every test. This completely destroys and recreates all tables. If tests ever pointed at `wiki`, all production data would be wiped.

- Tests must always connect to `postgresql+asyncpg://wiki:wiki@db:5432/wiki_test`
- `conftest.py` unconditionally sets `DATABASE_URL` to `wiki_test` — do NOT change this to `setdefault`, as the container environment already has `DATABASE_URL` pointing at the production DB
- A `assert "test" in DATABASE_URL` guard in `conftest.py` will blow up loudly if anything is misconfigured
- The `wiki_test` database is created automatically on fresh volumes via `postgres-init/01-create-test-db.sql`
- For an existing running container: `docker compose exec db psql -U wiki -c "CREATE DATABASE wiki_test;"`

Run tests inside the compose network:

```bash
docker compose run --rm api pytest tests/ -v
```

## Development commands

```bash
# Start everything
docker compose up --build

# Run migrations (first time or after adding a revision)
docker compose run --rm api alembic upgrade head

# Run tests (safe — targets wiki_test only)
docker compose run --rm api pytest tests/ -v
```

## Key conventions

- Migrations live in `api/alembic/versions/` — always generate via `alembic revision --autogenerate`
- API routes are in `api/app/routes/`
- Background agents are in `api/app/agents/`
- SSE is used for live status from ingest and chat agents
- `VECTOR_SEARCH_ENABLED` (default `true`) gates embedding calls; safe to set `false` locally to avoid LLM API usage during development
