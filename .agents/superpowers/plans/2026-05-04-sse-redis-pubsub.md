# SSE Redis Pub/Sub Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace in-memory `asyncio.Queue` SSE broadcaster with Redis Pub/Sub so gunicorn can run multiple workers on a single Docker host.

**Architecture:** Each connected SSE client opens a Redis PubSub subscription on channel `sse:{user_id}`. Any worker can publish an event to that channel; Redis fans it out to the worker holding the live connection. The `SSEBroadcaster` class in `api/app/sse.py` is the only application component that changes — all call sites (`broadcaster.publish(...)`) are unaffected except the SSE endpoint itself (which must `await` the now-async `subscribe` and `unsubscribe` calls).

**Tech Stack:** redis-py ≥ 4.0 (`redis[asyncio]`), Redis 7 Alpine, FastAPI lifespan context manager.

---

## Files touched

| Action | Path |
|--------|------|
| Modify | `docker-compose.yml` |
| Modify | `docker-compose.prod.yml` |
| Modify | `api/requirements.txt` |
| Modify | `api/requirements-prod.txt` |
| Rewrite | `api/app/sse.py` |
| Modify | `api/app/main.py` |
| Modify | `api/app/routes/chat.py` |
| Modify | `api/Dockerfile.prod` |
| Modify | `tests/conftest.py` |
| Create | `tests/test_sse.py` |

---

### Task 1: Add Redis service to compose files and install dependency

**Files:**
- Modify: `docker-compose.yml`
- Modify: `docker-compose.prod.yml`
- Modify: `api/requirements.txt`
- Modify: `api/requirements-prod.txt`

- [ ] **Step 1: Add redis service to `docker-compose.yml`**

Add after the `minio` service block (before the `api` service), and add `redis` to `api.depends_on`:

```yaml
  redis:
    image: redis:7-alpine
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5
```

Update the `api` service `depends_on` block:
```yaml
    depends_on:
      db:
        condition: service_healthy
      minio:
        condition: service_healthy
      redis:
        condition: service_healthy
```

Add to the `api` service `environment` block:
```yaml
      REDIS_URL: redis://redis:6379
```

- [ ] **Step 2: Add redis service to `docker-compose.prod.yml`**

Same redis service block as above. Add to `api.depends_on`:
```yaml
      redis:
        condition: service_healthy
```

Add to `api` service `environment` block:
```yaml
      REDIS_URL: redis://redis:6379
```

- [ ] **Step 3: Add redis-py to both requirements files**

In `api/requirements.txt`, add after the `httpx` line:
```
redis[asyncio]>=4.6.0
```

In `api/requirements-prod.txt`, add after the `httpx` line:
```
redis[asyncio]>=4.6.0
```

- [ ] **Step 4: Verify compose config parses**

```bash
docker compose config --quiet && echo "OK"
```
Expected: `OK` with no errors.

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml docker-compose.prod.yml api/requirements.txt api/requirements-prod.txt
git commit -m "feat: add Redis service to compose files and redis-py dependency"
```

---

### Task 2: Write failing tests for new SSEBroadcaster

**Files:**
- Modify: `tests/conftest.py`
- Create: `tests/test_sse.py`

- [ ] **Step 1: Add REDIS_URL to conftest.py**

In `tests/conftest.py`, add after the `VECTOR_SEARCH_ENABLED` line:
```python
os.environ.setdefault("REDIS_URL", "redis://redis:6379")
```

- [ ] **Step 2: Write `tests/test_sse.py`**

```python
import asyncio
import json
import pytest
import pytest_asyncio
from app.sse import SSEBroadcaster


@pytest_asyncio.fixture(loop_scope="function")
async def broadcaster():
    b = SSEBroadcaster()
    b.connect("redis://redis:6379")
    yield b
    await b.disconnect()


@pytest.mark.asyncio
async def test_publish_delivered_to_subscriber(broadcaster):
    pubsub = await broadcaster.subscribe("user-pub-1")
    await broadcaster.publish({"event": "agent:done"}, audience_user_id="user-pub-1")
    await asyncio.sleep(0.05)
    msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
    assert msg is not None
    assert json.loads(msg["data"]) == {"event": "agent:done"}
    await broadcaster.unsubscribe(pubsub)


@pytest.mark.asyncio
async def test_publish_not_delivered_to_wrong_user(broadcaster):
    pubsub = await broadcaster.subscribe("user-other")
    await broadcaster.publish({"event": "agent:done"}, audience_user_id="user-target")
    await asyncio.sleep(0.05)
    msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
    assert msg is None
    await broadcaster.unsubscribe(pubsub)


@pytest.mark.asyncio
async def test_stream_yields_data_chunk(broadcaster):
    pubsub = await broadcaster.subscribe("user-stream-1")
    await broadcaster.publish({"event": "agent:reading", "slug": "my-page"}, audience_user_id="user-stream-1")
    await asyncio.sleep(0.05)
    gen = broadcaster.stream(pubsub, keepalive_timeout=1.0)
    chunk = await gen.__anext__()
    assert chunk == 'data: {"event": "agent:reading", "slug": "my-page"}\n\n'
    await broadcaster.unsubscribe(pubsub)


@pytest.mark.asyncio
async def test_stream_sends_keepalive_when_idle(broadcaster):
    pubsub = await broadcaster.subscribe("user-keepalive")
    gen = broadcaster.stream(pubsub, keepalive_timeout=0.1)
    chunk = await gen.__anext__()
    assert chunk == ": keepalive\n\n"
    await broadcaster.unsubscribe(pubsub)


@pytest.mark.asyncio
async def test_publish_survives_redis_connection_error():
    from unittest.mock import AsyncMock, patch
    b = SSEBroadcaster()
    b.connect("redis://redis:6379")
    with patch.object(b, "_client") as mock_client:
        mock_redis = AsyncMock()
        mock_redis.publish.side_effect = ConnectionError("Redis down")
        mock_client.return_value = mock_redis
        # Must not raise — core pipeline callers must not crash on Redis blip
        await b.publish({"event": "agent:done"}, audience_user_id="user-x")
    await b.disconnect()


@pytest.mark.asyncio
async def test_multiple_subscribers_same_user_both_receive(broadcaster):
    pubsub_a = await broadcaster.subscribe("user-multi")
    pubsub_b = await broadcaster.subscribe("user-multi")
    await broadcaster.publish({"event": "health:done"}, audience_user_id="user-multi")
    await asyncio.sleep(0.05)
    msg_a = await pubsub_a.get_message(ignore_subscribe_messages=True, timeout=1.0)
    msg_b = await pubsub_b.get_message(ignore_subscribe_messages=True, timeout=1.0)
    assert msg_a is not None
    assert msg_b is not None
    await broadcaster.unsubscribe(pubsub_a)
    await broadcaster.unsubscribe(pubsub_b)
```

- [ ] **Step 3: Run tests to confirm they fail**

```bash
docker compose run --rm api pytest tests/test_sse.py -v
```
Expected: 6 failures — `SSEBroadcaster` has no `connect` method yet.

---

### Task 3: Rewrite `api/app/sse.py` with Redis Pub/Sub

**Files:**
- Rewrite: `api/app/sse.py`

- [ ] **Step 1: Replace the entire file**

```python
import json
import logging
from typing import AsyncIterator

import redis.asyncio as aioredis
from redis.asyncio.client import PubSub

log = logging.getLogger("app.sse")


class SSEBroadcaster:
    """Fan-out of SSE events via Redis Pub/Sub, scoped by authenticated user id (OIDC sub)."""

    def __init__(self):
        self._pool: aioredis.ConnectionPool | None = None

    def connect(self, redis_url: str) -> None:
        self._pool = aioredis.ConnectionPool.from_url(redis_url)

    async def disconnect(self) -> None:
        if self._pool:
            self._pool.disconnect()  # synchronous; safe to call from async context
            self._pool = None

    def _client(self) -> aioredis.Redis:
        return aioredis.Redis(connection_pool=self._pool)

    async def subscribe(self, user_id: str) -> PubSub:
        pubsub = self._client().pubsub()
        await pubsub.subscribe(f"sse:{user_id}")
        return pubsub

    async def unsubscribe(self, pubsub: PubSub) -> None:
        await pubsub.unsubscribe()
        await pubsub.aclose()

    async def publish(self, event: dict, *, audience_user_id: str) -> None:
        try:
            client = self._client()
            await client.publish(f"sse:{audience_user_id}", json.dumps(event))
        except Exception as exc:
            # Redis being unavailable must not abort ingest, chat, or health pipelines.
            # The user just won't see the real-time UI update for this event.
            log.warning("SSE publish failed (Redis unavailable?): %s", exc)

    async def stream(self, pubsub: PubSub, keepalive_timeout: float = 30.0) -> AsyncIterator[str]:
        while True:
            msg = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=keepalive_timeout
            )
            if msg is not None:
                yield f"data: {msg['data'].decode()}\n\n"
            else:
                yield ": keepalive\n\n"


broadcaster = SSEBroadcaster()
```

- [ ] **Step 2: Run the SSE tests to confirm they pass**

```bash
docker compose run --rm api pytest tests/test_sse.py -v
```
Expected: 6 tests pass.

- [ ] **Step 3: Run full test suite to confirm no regressions**

```bash
docker compose run --rm api pytest tests/ -v
```
Expected: all previously-passing tests still pass.

- [ ] **Step 4: Commit**

```bash
git add api/app/sse.py tests/test_sse.py tests/conftest.py
git commit -m "feat: rewrite SSEBroadcaster using Redis Pub/Sub"
```

---

### Task 4: Wire broadcaster lifecycle into FastAPI lifespan

**Files:**
- Modify: `api/app/main.py`

- [ ] **Step 1: Add lifespan to `api/app/main.py`**

Replace the top of `main.py` (imports + app creation) with:

```python
import logging
import os
import sys
from contextlib import asynccontextmanager

import litellm
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth import router as auth_router
from app.routes.activity import router as activity_router
from app.routes.chat import router as chat_router
from app.routes.health import router as health_router
from app.routes.ingest import router as ingest_router
from app.routes.wiki import router as wiki_router


def _configure_app_logging() -> None:
    log = logging.getLogger("app")
    if log.handlers:
        return
    log.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    )
    log.addHandler(handler)
    log.propagate = False


_configure_app_logging()
logging.getLogger("LiteLLM").setLevel(logging.WARNING)
logging.getLogger("litellm").setLevel(logging.WARNING)
litellm.suppress_debug_info = True


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.sse import broadcaster
    broadcaster.connect(os.environ.get("REDIS_URL", "redis://redis:6379"))
    yield
    await broadcaster.disconnect()


app = FastAPI(title="LLM Wiki", lifespan=lifespan)
```

The rest of the file (middleware, routers, `/health` endpoint) stays unchanged.

- [ ] **Step 2: Run full test suite**

```bash
docker compose run --rm api pytest tests/ -v
```
Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add api/app/main.py
git commit -m "feat: connect SSEBroadcaster to Redis on app startup via lifespan"
```

---

### Task 5: Update SSE endpoint in `chat.py` to use async subscribe/unsubscribe

**Files:**
- Modify: `api/app/routes/chat.py`

The `subscribe` and `unsubscribe` methods are now async and the handle is a `PubSub` object, not a `Queue`. The route must `await` both calls.

- [ ] **Step 1: Update the `sse_stream` endpoint**

Replace lines 125–140 (`@router.get("/sse")` block) with:

```python
@router.get("/sse")
async def sse_stream(user: str = Depends(get_current_user)):
    pubsub = await broadcaster.subscribe(user)

    async def event_gen():
        try:
            async for chunk in broadcaster.stream(pubsub):
                yield chunk
        finally:
            await broadcaster.unsubscribe(pubsub)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

- [ ] **Step 2: Run full test suite**

```bash
docker compose run --rm api pytest tests/ -v
```
Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add api/app/routes/chat.py
git commit -m "feat: update SSE endpoint to use async Redis PubSub subscribe/unsubscribe"
```

---

### Task 6: Enable multiple workers in production Dockerfile

**Files:**
- Modify: `api/Dockerfile.prod`

- [ ] **Step 1: Replace the hardcoded `-w 1` CMD**

Change the final `CMD` line from:
```dockerfile
CMD ["gunicorn", "app.main:app", "-w", "1", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000"]
```
to:
```dockerfile
CMD ["sh", "-c", "exec gunicorn app.main:app -w ${WEB_CONCURRENCY:-4} -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000"]
```

This defaults to 4 workers but lets you override via `WEB_CONCURRENCY` in the environment (e.g. set to `2` on a memory-constrained host).

- [ ] **Step 2: Smoke-test the prod build locally (optional but recommended)**

```bash
docker compose -f docker-compose.prod.yml build api
docker compose -f docker-compose.prod.yml run --rm api gunicorn --check-config app.main:app -k uvicorn.workers.UvicornWorker
```
Expected: exits 0 with no errors.

- [ ] **Step 3: Commit**

```bash
git add api/Dockerfile.prod
git commit -m "feat: use WEB_CONCURRENCY env var for gunicorn workers, default 4"
```

---

## Verification after all tasks

```bash
# Full test suite
docker compose run --rm api pytest tests/ -v

# Dev stack comes up cleanly with Redis
docker compose up --build

# Confirm 4 workers running in prod image
docker compose -f docker-compose.prod.yml up --build api
# In another terminal:
docker compose -f docker-compose.prod.yml exec api ps aux | grep gunicorn
# Expected: 1 master + 4 worker processes
```
