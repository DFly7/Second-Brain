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
| [`api/requirements.txt`](api/requirements.txt) | Local/dev API deps (mounted dev container) |
| [`api/requirements-prod.txt`](api/requirements-prod.txt) | **Production-only** deps for [`api/Dockerfile.prod`](api/Dockerfile.prod) / `docker-compose.prod.yml` |
| `ios/SecondBrainApp/` | Tuist iOS app; Debug vs Release xcconfigs set `BACKEND_URL`; `make ios-run` / `make ios-device` wrap [`scripts/ios-sim.sh`](scripts/ios-sim.sh) / [`scripts/ios-device.sh`](scripts/ios-device.sh) |

## Local vs production (Docker Compose)

- **Dev:** root `docker-compose.yml` → API built from `./api`; installs [`api/requirements.txt`](api/requirements.txt); frontend is Vite in dev mode.
- **Prod:** [`docker-compose.prod.yml`](docker-compose.prod.yml) → API built via [`api/Dockerfile.prod`](api/Dockerfile.prod), which runs **`pip install -r requirements-prod.txt`** (not `requirements.txt`). Gunicorn workers boot the FastAPI app.
- **When you add a runtime import:** mirror the package in **both** `requirements.txt` and `requirements-prod.txt` (keep versions aligned unless you have a reason not to). Test-only packages (pytest, etc.) stay in dev requirements only. Skipping prod causes `ModuleNotFoundError` on the server while local still runs.
- **Frontend prod:** [`frontend/Dockerfile.prod`](frontend/Dockerfile.prod) — production build behind nginx.

## Development

```bash
# Start stack
docker compose up --build

# Migrations run on API container start (api/docker-entrypoint.sh). Manual run without starting the app:
docker compose run --rm api alembic upgrade head

# Tests (safe — wiki_test only)
docker compose run --rm api pytest tests/ -v

# iOS Simulator: Tuist generate + build + install + launch (Debug xcconfig by default)
make ios-run

# Same against production API URL (Release xcconfig → https://smoothstudy.ai/api)
make ios-run ARGS="--release"

# Physical iPhone (default Release / prod API; Developer Mode required). Signing: DEVELOPMENT_TEAM in ios Config-*.xcconfig (`IOS_DEVICE_TEAM=…` only to override)

make ios-device
make ios-device ARGS="--debug"   # Debug xcconfig + local BACKEND_URL
make ios-devices                 # list paired devices (devicectl)
```

**Skip migrations on start (debug only):** set `SKIP_DB_MIGRATE=1` on the `api` service environment. See `CLAUDE.md` → Database migrations.

**iOS Debug vs Release:** Simulator default is Debug; use `make ios-run ARGS="--release"` for prod API URL. **Physical device** defaults to **Release** via `make ios-device` (prod API); use `make ios-device ARGS="--debug"` for `Config-Debug.xcconfig` / local API. Full notes: `CLAUDE.md` → iOS app (Simulator & physical device).

**Changing Apple Team ID:** edit `DEVELOPMENT_TEAM` in `ios/SecondBrainApp/Config-Debug.xcconfig` and `Config-Release.xcconfig`, then `make ios-gen`.

## Pi deployment

Two stacks on `darragh@pi-server.local`, started in order:

1. **Auth** (`~/auth-compose/auth-config/`) — Authentik + its Cloudflare tunnel
2. **App** (`~/second-brain/Second-Brain/`) — this repo via `docker-compose.prod.yml`

Env files live only on the Mac and must be scp'd before first deploy — see `CLAUDE.md` for the exact commands. The app stack needs Authentik healthy before starting or the JWKS endpoint won't be reachable on boot.

## Conventions

- Generate migrations with `alembic revision --autogenerate -m "description"`, then review before applying
- SSE endpoints stream agent status — prefer extending existing SSE patterns over new polling routes
- `VECTOR_SEARCH_ENABLED=false` disables embedding API calls; useful during development/testing to avoid LLM costs
