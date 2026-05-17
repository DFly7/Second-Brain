# Agent Guide — Second Brain

This file is for Claude Code sub-agents. It covers how to verify work without Docker.

## Testing without Docker

All API tests mock the database session, Redis, and S3 — no real infrastructure is needed.

### One-time setup (Mac host)

```bash
cd api
pip3 install -r requirements.txt
# If asyncpg fails to build: brew install libpq first
```

### Running tests

```bash
# From repo root:
make test-local

# Or directly:
cd api && python3 -m pytest tests/ -v
```

All 25 tests should pass. If you see failures, check whether your changes broke something before assuming a pre-existing issue.

### Static analysis (fastest — no app startup)

```bash
# From repo root:
make lint        # ruff + mypy

# Or directly:
cd api && ruff check app/ tests/ && mypy app/
```

Install if missing: `pip install ruff mypy`.

## How the mocks work

`api/tests/conftest.py` applies three autouse fixtures to every test:

| Fixture | What it blocks |
|---|---|
| `_mock_broadcaster` | Redis — patches `broadcaster.connect/disconnect` so the FastAPI lifespan never dials out |
| `_mock_s3` | MinIO — blocks `upload_file`/`download_file`; raises loudly if a test accidentally triggers real storage |
| env vars | `VECTOR_SEARCH_ENABLED=false` so embedding API calls are never made |

Tests override the FastAPI `get_db` dependency to inject a mock `AsyncSession`, and override `get_current_user` to return a fixed email. No Postgres connection is ever attempted.

## Writing new tests

Follow the pattern in `api/tests/test_chat_routing.py`:

1. Override `get_db` with an async generator yielding a `MagicMock` session
2. Override `get_current_user` with an async function returning a fixed email string
3. Use `patch()` for any agents or external calls the route invokes
4. Always clean up overrides in a `finally` block (or use pytest fixtures)

```python
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from app.auth import get_current_user
from app.database import get_db
from app.main import app

def test_my_route():
    async def override_user():
        return "test@example.com"

    session = MagicMock()
    session.execute = AsyncMock(return_value=...)

    async def override_db():
        yield session

    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_db] = override_db

    try:
        client = TestClient(app)
        r = client.get("/my-route")
        assert r.status_code == 200
    finally:
        app.dependency_overrides.clear()
```

## Verification checklist before completing a task

1. `make lint` — zero ruff errors, zero mypy errors
2. `make test-local` — all tests pass
3. If you added a new route or agent: add a matching test in `api/tests/`
