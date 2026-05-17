# Second Brain — Claude Code Guide

## Project overview

Single-user LLM wiki app. FastAPI + async SQLAlchemy backend, React 18 + Vite frontend, Postgres 16 + pgvector, MinIO for file storage. See `README.md` for full feature list.

## Running tests

Tests mock the database session, Redis, and S3 — **no Docker required for the test suite**.

### Local (preferred for agents and fast iteration)

One-time setup:
```bash
cd api && pip3 install -r requirements.txt
# If asyncpg fails to build: brew install libpq first
```

Then:
```bash
make test-local        # pytest without Docker (~10s)
make lint              # ruff + mypy static analysis (~5s)
```

See `AGENT.md` for the full agent verification guide and test-writing patterns.

### Docker (integration / CI)

```bash
make test-docker       # docker compose run --rm api pytest tests/ -v
```

**CRITICAL — tests use a separate `wiki_test` database, NOT the production `wiki` database.**

- `conftest.py` unconditionally sets `DATABASE_URL` to `wiki_test` — do NOT change this to `setdefault`, as the container environment already has `DATABASE_URL` pointing at the production DB
- A `assert “test” in DATABASE_URL` guard in `conftest.py` will blow up loudly if anything is misconfigured
- The `wiki_test` database is created automatically on fresh volumes via `postgres-init/01-create-test-db.sql`
- For an existing running container: `docker compose exec db psql -U wiki -c “CREATE DATABASE wiki_test;”`

### How the mocks work

`conftest.py` applies three autouse fixtures to every test:
- `_mock_broadcaster` — patches Redis connect/disconnect so the FastAPI lifespan never dials out
- `_mock_s3` — blocks upload/download; raises loudly if a test hits real storage
- `VECTOR_SEARCH_ENABLED=false` — prevents any embedding API calls

Tests override FastAPI's `get_db` and `get_current_user` dependencies. No real Postgres connection is ever attempted.

## Development commands

```bash
# Start everything
docker compose up --build

# Migrations without starting the API (optional — see “Database migrations” below)
docker compose run --rm api alembic upgrade head

# Run tests — no Docker needed
make test-local

# Static analysis only
make lint
```

## iOS app (Makefile / Tuist)

### Simulator

From the repo root, `make ios-run` runs Tuist generate, builds **Debug**, picks an iPhone simulator, installs, and launches `SecondBrainApp`. Debug reads [`ios/SecondBrainApp/Config-Debug.xcconfig`](ios/SecondBrainApp/Config-Debug.xcconfig) (`BACKEND_URL` is `http://YOUR_MACHINE_IP:8000` until you substitute your Mac’s LAN IP for local API testing).

To build **Release** on the simulator (uses [`Config-Release.xcconfig`](ios/SecondBrainApp/Config-Release.xcconfig): prod API base `https://smoothstudy.ai/api`, matching production):

```bash
make ios-run ARGS="--release"
```

Flags are forwarded to [`scripts/ios-sim.sh`](scripts/ios-sim.sh); combine as needed, e.g. `make ios-run ARGS="--release --logs"` or `ARGS="--udid <SIMULATOR_UDID>"`. Open the workspace with `make ios-open`.

### Physical iPhone

`make ios-device` runs Tuist generate, builds **`Release` / `iphoneos`** by default (uses [`Config-Release.xcconfig`](ios/SecondBrainApp/Config-Release.xcconfig) — prod API base `https://smoothstudy.ai/api`). It installs with **`devicectl`** and launches on a **paired physical iPhone** (USB or local-network Core Device). **Developer Mode** is required on the phone. **Signing** uses `CODE_SIGN_STYLE` + `DEVELOPMENT_TEAM` from [`Config-Debug.xcconfig`](ios/SecondBrainApp/Config-Debug.xcconfig) / [`Config-Release.xcconfig`](ios/SecondBrainApp/Config-Release.xcconfig), wired via [`Project.swift`](ios/SecondBrainApp/Project.swift). For **Debug** / local `BACKEND_URL` on device, use `make ios-device ARGS="--debug"`. Override team only when needed (another Apple account / CI):

```bash
make ios-device ARGS="--debug"
IOS_DEVICE_TEAM=OTHER_ID make ios-device
```

See [`scripts/ios-device.sh`](scripts/ios-device.sh) for flags (`--logs`, `--regen`, etc.). Xcode 15+ with Core Device support is expected (`devicectl`).

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
