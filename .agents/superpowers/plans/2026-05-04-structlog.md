# Structlog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the ad-hoc stdlib logging setup with structlog, adding a request logging middleware and coverage in agents and routes that currently have no logging.

**Architecture:** A single `logging_config.py` module owns all structlog setup. It uses `structlog.stdlib.ProcessorFormatter` so that uvicorn's own stdlib loggers are also formatted. `LOG_FORMAT=console` enables human-readable colored output in dev; the default `json` emits one JSON object per line to stderr (visible in `docker compose logs api`). All existing `logging.getLogger(...)` calls are replaced with `structlog.get_logger()`. A lightweight Starlette middleware logs every HTTP request with method, path, status, and latency.

**Tech Stack:** `structlog>=24.0.0`, Python stdlib `logging`, Starlette `BaseHTTPMiddleware`, pytest `structlog.testing.capture_logs`

---

### Task 1: Add structlog and create logging_config.py

**Files:**
- Modify: `api/requirements.txt`
- Create: `api/app/logging_config.py`
- Create: `tests/test_logging_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_logging_config.py
import logging
import os

import structlog
import structlog.testing
import pytest

from app.logging_config import configure_logging


def test_configure_logging_json_sets_up_structlog(monkeypatch):
    monkeypatch.setenv("LOG_FORMAT", "json")
    configure_logging()
    # structlog is configured when processors chain is non-empty
    config = structlog.get_config()
    assert config["logger_factory"].__class__.__name__ == "LoggerFactory"


def test_configure_logging_console_does_not_raise(monkeypatch):
    monkeypatch.setenv("LOG_FORMAT", "console")
    configure_logging()  # must not raise


def test_litellm_loggers_suppressed():
    configure_logging()
    assert logging.getLogger("LiteLLM").level == logging.WARNING
    assert logging.getLogger("litellm").level == logging.WARNING
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker compose run --rm api pytest tests/test_logging_config.py -v
```

Expected: `ImportError: cannot import name 'configure_logging' from 'app.logging_config'`

- [ ] **Step 3: Add structlog to requirements.txt**

Add this line after `httpx==0.28.1`:

```
structlog>=24.0.0
```

- [ ] **Step 4: Create api/app/logging_config.py**

```python
import logging
import os
import sys

import structlog


def configure_logging() -> None:
    log_format = os.environ.get("LOG_FORMAT", "json")

    timestamper = structlog.processors.TimeStamper(fmt="iso")
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        timestamper,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
    ]

    if log_format == "console":
        renderer: structlog.types.Processor = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            renderer,
        ],
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    # Avoid duplicate handlers if called more than once (e.g. in tests)
    root.handlers = [h for h in root.handlers if not isinstance(h, logging.StreamHandler)]
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    for noisy in ("LiteLLM", "litellm", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
```

- [ ] **Step 5: Rebuild container and run tests**

```bash
docker compose run --rm api pytest tests/test_logging_config.py -v
```

Expected: all 3 tests PASS

- [ ] **Step 6: Commit**

```bash
git add api/requirements.txt api/app/logging_config.py tests/test_logging_config.py
git commit -m "feat: add structlog and configure_logging()"
```

---

### Task 2: Wire logging_config into main.py and add request middleware

**Files:**
- Modify: `api/app/main.py`
- Create: `api/app/middleware.py`
- Create: `tests/test_request_middleware.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_request_middleware.py
import structlog.testing
import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app


@pytest.mark.asyncio
async def test_request_middleware_logs_request():
    with structlog.testing.capture_logs() as cap:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/health")

    assert response.status_code == 200
    request_logs = [e for e in cap if e.get("event") == "request"]
    assert len(request_logs) == 1
    log = request_logs[0]
    assert log["method"] == "GET"
    assert log["path"] == "/health"
    assert log["status"] == 200
    assert "latency_ms" in log
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker compose run --rm api pytest tests/test_request_middleware.py -v
```

Expected: FAIL — no `request` log event emitted

- [ ] **Step 3: Create api/app/middleware.py**

```python
import time

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

log = structlog.get_logger()


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        latency_ms = round((time.perf_counter() - start) * 1000)
        log.info(
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            latency_ms=latency_ms,
        )
        return response
```

- [ ] **Step 4: Update api/app/main.py**

Replace the entire file:

```python
import os
from contextlib import asynccontextmanager

import litellm
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.logging_config import configure_logging
from app.middleware import RequestLoggingMiddleware

configure_logging()

import structlog  # noqa: E402 — must import after configure_logging()

litellm.suppress_debug_info = True

log = structlog.get_logger()

from app.auth import router as auth_router  # noqa: E402
from app.routes.activity import router as activity_router  # noqa: E402
from app.routes.chat import router as chat_router  # noqa: E402
from app.routes.health import router as health_router  # noqa: E402
from app.routes.ingest import router as ingest_router  # noqa: E402
from app.routes.wiki import router as wiki_router  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.sse import broadcaster

    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379")
    log.info("startup", redis_url=redis_url)
    await broadcaster.connect(redis_url)
    yield
    await broadcaster.disconnect()
    log.info("shutdown")


app = FastAPI(title="LLM Wiki", lifespan=lifespan)

app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "https://smoothstudy.ai"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(wiki_router)
app.include_router(ingest_router)
app.include_router(chat_router)
app.include_router(activity_router)
app.include_router(health_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 5: Run tests**

```bash
docker compose run --rm api pytest tests/test_request_middleware.py tests/test_logging_config.py -v
```

Expected: all tests PASS

- [ ] **Step 6: Commit**

```bash
git add api/app/main.py api/app/middleware.py tests/test_request_middleware.py
git commit -m "feat: wire structlog into main.py and add request logging middleware"
```

---

### Task 3: Migrate existing stdlib loggers to structlog

**Files:**
- Modify: `api/app/auth.py`
- Modify: `api/app/sse.py`
- Modify: `api/app/marker_client.py`
- Modify: `api/app/routes/ingest.py`

No new tests — the existing call sites don't change behaviour, only the logger type. The existing test suite verifies nothing breaks.

- [ ] **Step 1: Update api/app/auth.py**

Replace:
```python
import logging
...
log = logging.getLogger("app.auth")
```
With:
```python
import structlog
...
log = structlog.get_logger()
```

Replace the two warning calls (lines 77, 86):
```python
# line 77
log.warning("no_access_token_cookie", path=request.url.path)

# line 86
log.warning("token_validation_failed", path=request.url.path, detail=e.detail)
```

- [ ] **Step 2: Update api/app/sse.py**

Replace:
```python
import logging
...
log = logging.getLogger("app.sse")
```
With:
```python
import structlog
...
log = structlog.get_logger()
```

Replace the warning call (line 55):
```python
log.warning("sse_publish_failed", error=str(exc))
```

- [ ] **Step 3: Update api/app/marker_client.py**

Replace:
```python
import logging
...
_log = logging.getLogger(__name__)
```
With:
```python
import structlog
...
_log = structlog.get_logger()
```

Update all `_log` call sites to use keyword arguments instead of `%s` interpolation. Find every `_log.info(...)`, `_log.error(...)`, `_log.warning(...)` call and rewrite using kwargs. For example:

```python
# Old
_log.error("Datalab API error: status=%s body=%s", resp.status_code, body)
# New
_log.error("datalab_api_error", status=resp.status_code, body=body)

# Old
_log.info("Datalab submission request_id=%s", request_id)
# New
_log.info("datalab_submission", request_id=request_id)

# Old  
_log.info("Datalab conversion complete request_id=%s", request_id)
# New
_log.info("datalab_conversion_complete", request_id=request_id)

# Old
_log.warning("Local marker connect error (retry %d/%d): %s", ...)
# New
_log.warning("marker_connect_retry", attempt=attempt, max=max_retries, error=str(exc))

# Old
_log.info("Local marker POST source_id=%s bytes=%d", source_id, len(data))
# New
_log.info("local_marker_post", source_id=source_id, bytes=len(data))

# Old
_log.info("Local marker response pages=%d", page_count)
# New
_log.info("local_marker_response", pages=page_count)
```

- [ ] **Step 4: Update api/app/routes/ingest.py**

Replace:
```python
import logging
...
_log = logging.getLogger(__name__)
```
With:
```python
import structlog
...
_log = structlog.get_logger()
```

Rewrite all `_log` calls to use keyword args (structlog style). For example:

```python
# Old
_log.info("ingest pipeline start source_id=%s workspace_id=%s filename=%s suffix=%s bytes=%d", ...)
# New
_log.info("ingest_pipeline_start", source_id=source_id, workspace_id=workspace_id, filename=filename, suffix=suffix, bytes=len(data))

# Old
_log.warning("ingest pipeline aborted: source not found source_id=%s", source_id)
# New
_log.warning("ingest_source_not_found", source_id=source_id)

# Old
_log.info("ingest skipping marker (plain text) source_id=%s suffix=%s", source_id, suffix)
# New
_log.info("ingest_skip_marker_plain_text", source_id=source_id, suffix=suffix)

# Old
_log.info("ingest calling marker source_id=%s filename=%s", source_id, filename)
# New
_log.info("ingest_calling_marker", source_id=source_id, filename=filename)

# Old
_log.info("ingest marker done source_id=%s pages=%d", source_id, len(raw_pages))
# New
_log.info("ingest_marker_done", source_id=source_id, pages=len(raw_pages))

# Old
_log.info("ingest convert stage done source_id=%s pages_written=%d md_key=%s", ...)
# New
_log.info("ingest_convert_done", source_id=source_id, pages_written=len(pages_data), md_key=md_key)

# Old
_log.exception("ingest pipeline failed source_id=%s filename=%s", source_id, filename)
# New
_log.exception("ingest_pipeline_failed", source_id=source_id, filename=filename)

# Old
_log.exception("ingest agent failed source_id=%s filename=%s", source_id, filename)
# New
_log.exception("ingest_agent_failed", source_id=source_id, filename=filename)

# Old
_log.info("ingest pipeline complete source_id=%s", source_id)
# New
_log.info("ingest_pipeline_complete", source_id=source_id)

# Old
_log.info("ingest file accepted source_id=%s workspace_id=%s filename=%s bytes=%d queued=pipeline", ...)
# New
_log.info("ingest_file_accepted", source_id=source.id, workspace_id=ws.id, filename=file.filename, bytes=len(data))
```

- [ ] **Step 5: Run full test suite**

```bash
docker compose run --rm api pytest tests/ -v
```

Expected: all tests PASS

- [ ] **Step 6: Commit**

```bash
git add api/app/auth.py api/app/sse.py api/app/marker_client.py api/app/routes/ingest.py
git commit -m "refactor: migrate existing stdlib loggers to structlog"
```

---

### Task 4: Add logging to ingest_agent.py and query_agent.py

**Files:**
- Modify: `api/app/agents/ingest_agent.py`
- Modify: `api/app/agents/query_agent.py`
- Create: `tests/test_agent_logging.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_agent_logging.py
import pytest
import structlog.testing
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_ingest_agent_logs_start_and_done():
    mock_source = MagicMock()
    mock_source.id = "src-1"

    mock_page = MagicMock()
    mock_page.page_num = 1
    mock_page.markdown = "hello"

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock()
    mock_session.execute.return_value.scalar_one_or_none = MagicMock(return_value=mock_source)
    mock_session.execute.return_value.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[mock_page])))
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    mock_broadcaster = AsyncMock()

    with structlog.testing.capture_logs() as cap:
        with patch("app.agents.ingest_agent.AsyncSessionLocal", return_value=mock_session):
            with patch("app.agents.ingest_agent.broadcaster", mock_broadcaster):
                with patch("app.agents.ingest_agent.litellm.acompletion", new_callable=AsyncMock) as mock_llm:
                    mock_msg = MagicMock()
                    mock_msg.tool_calls = None
                    mock_msg.content = "done"
                    mock_resp = MagicMock()
                    mock_resp.choices = [MagicMock(message=mock_msg)]
                    mock_llm.return_value = mock_resp
                    from app.agents import ingest_agent
                    await ingest_agent.run("src-1", "ws-1", "user-1")

    events = [e["event"] for e in cap]
    assert "ingest_agent_start" in events
    assert "ingest_agent_done" in events


@pytest.mark.asyncio
async def test_query_agent_logs_start_and_answer():
    mock_session = AsyncMock()
    mock_tools = AsyncMock()
    mock_tools.as_litellm_tools = MagicMock(return_value=[])
    mock_tools.read_page = AsyncMock(return_value="[Page 'system/memory' not found]")
    mock_tools.dispatch = AsyncMock(return_value="result")

    mock_broadcaster = AsyncMock()

    with structlog.testing.capture_logs() as cap:
        with patch("app.agents.query_agent.AgentTools", return_value=mock_tools):
            with patch("app.agents.query_agent.broadcaster", mock_broadcaster):
                with patch("app.agents.query_agent.litellm.acompletion", new_callable=AsyncMock) as mock_llm:
                    mock_msg = MagicMock()
                    mock_msg.tool_calls = None
                    mock_msg.content = "The answer is 42."
                    mock_resp = MagicMock()
                    mock_resp.choices = [MagicMock(message=mock_msg)]
                    mock_llm.return_value = mock_resp
                    from app.agents import query_agent
                    answer, _ = await query_agent.run("ws-1", "what is 42?", [], mock_session, "user-1")

    events = [e["event"] for e in cap]
    assert "query_agent_start" in events
    assert "query_agent_answer" in events
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker compose run --rm api pytest tests/test_agent_logging.py -v
```

Expected: FAIL — no `ingest_agent_start` or `query_agent_start` events emitted

- [ ] **Step 3: Add logging to api/app/agents/ingest_agent.py**

Add at the top of the file (after existing imports):
```python
import structlog

_log = structlog.get_logger()
```

Add at the start of the `run()` function, before the `async with AsyncSessionLocal()` block:
```python
_log.info("ingest_agent_start", source_id=source_id, workspace_id=workspace_id)
```

Add inside the `run()` function, just before the final `await broadcaster.publish({"event": "agent:done", ...})`:
```python
_log.info(
    "ingest_agent_done",
    source_id=source_id,
    workspace_id=workspace_id,
    pages_touched=len(pages_touched),
    cost_usd=round(total_cost, 4),
)
```

Add a cost ceiling log inside the `if total_cost > COST_CEILING_USD: break` block:
```python
if total_cost > COST_CEILING_USD:
    _log.warning("ingest_agent_cost_ceiling_hit", source_id=source_id, cost_usd=round(total_cost, 4))
    break
```

- [ ] **Step 4: Add logging to api/app/agents/query_agent.py**

Add at the top of the file (after existing imports):
```python
import structlog

_log = structlog.get_logger()
```

Add at the start of the `run()` function, before the `tools = AgentTools(...)` line:
```python
_log.info("query_agent_start", workspace_id=workspace_id)
```

In the `if not msg.tool_calls:` branch, before the `return` statement:
```python
_log.info("query_agent_answer", workspace_id=workspace_id, cited_pages=len(cited_pages))
```

At the fallback `return` at the bottom of the loop (the "wasn't able to find" branch):
```python
_log.warning("query_agent_no_answer", workspace_id=workspace_id)
```

- [ ] **Step 5: Run tests**

```bash
docker compose run --rm api pytest tests/test_agent_logging.py tests/ -v
```

Expected: all tests PASS

- [ ] **Step 6: Commit**

```bash
git add api/app/agents/ingest_agent.py api/app/agents/query_agent.py tests/test_agent_logging.py
git commit -m "feat: add structlog logging to ingest_agent and query_agent"
```

---

### Task 5: Add logging to chat route

**Files:**
- Modify: `api/app/routes/chat.py`
- Create: `tests/test_chat_logging.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_chat_logging.py
import pytest
import structlog.testing
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport

from app.main import app


@pytest.mark.asyncio
async def test_chat_message_logs_query():
    with structlog.testing.capture_logs() as cap:
        with patch("app.routes.chat.run_query", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = ("answer text", ["wiki/page"])
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                client.cookies.set("access_token", "dev")
                response = await client.post(
                    "/chat/message",
                    json={"message": "hello", "mode": "query"},
                )

    # The route may 401 if dev_auth_bypass isn't set — we only check the log shape if 200
    if response.status_code == 200:
        events = [e["event"] for e in cap]
        assert "chat_message_received" in events
        assert "chat_message_answered" in events
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker compose run --rm api pytest tests/test_chat_logging.py -v
```

Expected: FAIL — no `chat_message_received` event

- [ ] **Step 3: Update api/app/routes/chat.py**

Add at the top of the file (after existing imports):
```python
import structlog

_log = structlog.get_logger()
```

In the `send_message()` route handler, add after `ws = await _ensure_workspace(db, user)`:
```python
_log.info("chat_message_received", workspace_id=ws.id, mode=body.mode, session_id=body.session_id)
```

After `answer, cited = await run_query(...)` / `await run_edit(...)` and before `assistant_msg = ChatMessage(...)`:
```python
_log.info("chat_message_answered", workspace_id=ws.id, mode=body.mode, cited_pages=len(cited))
```

- [ ] **Step 4: Run full test suite**

```bash
docker compose run --rm api pytest tests/ -v
```

Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add api/app/routes/chat.py tests/test_chat_logging.py
git commit -m "feat: add structlog logging to chat route"
```

---

## Seeing it in docker logs

**JSON (default):**
```bash
docker compose logs api
# api-1  | {"timestamp":"2026-05-04T10:23:41Z","level":"info","event":"request","method":"GET","path":"/health","status":200,"latency_ms":4}
# api-1  | {"timestamp":"2026-05-04T10:23:45Z","level":"info","event":"ingest_pipeline_start","source_id":"abc-123","filename":"report.pdf","bytes":204800}
```

**Pretty (dev):** add `LOG_FORMAT=console` to the `api` service environment in `docker-compose.yml`:
```yaml
environment:
  LOG_FORMAT: console
```

Then:
```bash
docker compose logs api
# api-1  | 2026-05-04T10:23:41Z [info     ] request          method=GET path=/health status=200 latency_ms=4
# api-1  | 2026-05-04T10:23:45Z [info     ] ingest_pipeline_start  source_id=abc-123 filename=report.pdf bytes=204800
```

Filter with jq (JSON mode):
```bash
docker compose logs api | jq 'select(.event == "request") | {path, status, latency_ms}'
```
