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

# Migrations without starting the API (optional — see “Database migrations” below)
docker compose run --rm api alembic upgrade head

# Run tests (safe — targets wiki_test only)
docker compose run --rm api pytest tests/ -v
```

## iOS Simulator (Makefile / Tuist)

From the repo root, `make ios-run` runs Tuist generate, builds **Debug**, picks an iPhone simulator, installs, and launches `SecondBrainApp`. Debug reads [`ios/SecondBrainApp/Config-Debug.xcconfig`](ios/SecondBrainApp/Config-Debug.xcconfig) (`BACKEND_URL` is `http://YOUR_MACHINE_IP:8000` until you substitute your Mac’s LAN IP for local API testing).

To build **Release** on the simulator (uses [`Config-Release.xcconfig`](ios/SecondBrainApp/Config-Release.xcconfig): prod API base `https://smoothstudy.ai/api`, matching production):

```bash
make ios-run ARGS="--release"
```

Flags are forwarded to [`scripts/ios-sim.sh`](scripts/ios-sim.sh); combine as needed, e.g. `make ios-run ARGS="--release --logs"` or `ARGS="--udid <UDID>"`. Open the workspace with `make ios-open`.

## Database migrations

The API image runs **`alembic upgrade head` on every container start** via `api/docker-entrypoint.sh` (before uvicorn or Gunicorn). If the database is already at the latest revision, this is effectively a no-op.

To **disable migrations** for a given start (debug only — e.g. investigating a bad revision), set on the `api` service:

```yaml
environment:
  SKIP_DB_MIGRATE: "1"
```

(Or add the same under `environment` in `docker-compose.yml` / `docker-compose.prod.yml` next to your other API vars.)

You can still run migrations manually without booting the app: `docker compose run --rm api alembic upgrade head`.

## Local vs production (Docker Compose)

**Two stacks:**

| | Local (`docker-compose.yml`) | Production (`docker-compose.prod.yml`) |
|--|-------------------------------|----------------------------------------|
| **API image** | `api/Dockerfile` (volume-mount `./api`; hot reload via uvicorn `--reload`) | `api/Dockerfile.prod` (Gunicorn + `uvicorn.workers.UvicornWorker`) |
| **Python deps** | [`api/requirements.txt`](api/requirements.txt) | [`api/requirements-prod.txt`](api/requirements-prod.txt) only |
| **Frontend** | Vite dev server on port 5173 | `frontend/Dockerfile.prod`: `npm run build` → nginx on 80 |

**Critical:** Prod installs dependencies **only** from `requirements-prod.txt`. Anything the app imports at runtime must appear there **as well as** in `requirements.txt` (unless the package is test-only — e.g. pytest). Adding a dependency only to `requirements.txt` will break production with `ModuleNotFoundError` even when local `docker compose up` works. Rebuild prod API after edits: `docker compose -f docker-compose.prod.yml build --no-cache api` (or `up --build`) so cached layers reinstall.

## Auth configuration pitfalls

**`DEV_AUTH_BYPASS` must be `false` in production.** With `DEV_AUTH_BYPASS=true`, the backend short-circuits all JWT validation and only accepts the literal string `"dev"` as a valid token. A real Authentik JWT will be rejected with 401 on every request, causing an infinite redirect loop between the app and Authentik. The frontend `.env` does not set `VITE_DEV_AUTH_BYPASS`, so the frontend always runs the real PKCE flow — if the backend is in bypass mode, auth will never work.

Check `.env` before debugging any auth loop: `grep DEV_AUTH_BYPASS .env`

## Pi deployment

Two stacks live on the Pi — auth first, app second:

- Auth stack: `darragh@pi-server.local:/home/darragh/auth-compose/auth-config/` (Authentik + Cloudflare tunnel)
- App stack: `darragh@pi-server.local:/home/darragh/second-brain/Second-Brain/` (this repo, prod compose)

**Copying env files from Mac before first deploy (or after secret rotation):**

```bash
scp /Users/darraghflynn/Documents/Second-Brain/.env darragh@pi-server.local:/home/darragh/second-brain/Second-Brain/.env
scp /Users/darraghflynn/Documents/Second-Brain/frontend/.env darragh@pi-server.local:/home/darragh/second-brain/Second-Brain/frontend/.env
scp /Users/darraghflynn/Documents/auth-config/.env darragh@pi-server.local:/home/darragh/auth-compose/auth-config/.env
```

**Starting both stacks (order matters):**

```bash
# 1. Auth stack first
cd ~/auth-compose/auth-config && docker compose up -d

# 2. App stack (wait ~30s for Authentik to be healthy)
cd ~/second-brain/Second-Brain
docker compose -f docker-compose.prod.yml up --build -d

# Migrations run when the API container starts. Optional manual run if needed:
# docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head
```

Verify `https://auth.smoothstudy.ai` is responding before testing `https://smoothstudy.ai`.

## Key conventions

- Migrations live in `api/alembic/versions/` — always generate via `alembic revision --autogenerate`
- API routes are in `api/app/routes/`
- Background agents are in `api/app/agents/`
- SSE is used for live status from ingest and chat agents
- `VECTOR_SEARCH_ENABLED` (default `true`) gates embedding calls; safe to set `false` locally to avoid LLM API usage during development
