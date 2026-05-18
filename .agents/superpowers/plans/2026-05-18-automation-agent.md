# Automation Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a dedicated Automations page where an LLM agent controls a real Chromium browser to carry out user goals, with a live noVNC view, SSE-fed action log, run history, and Playwright screen recordings saved to MinIO.

**Architecture:** A new `browser-agent` Docker container runs Playwright + Chromium in a virtual Xvfb display, streams live via noVNC on port 6080, and exposes a small FastAPI tool server on port 8001. The existing API container hosts a new `AutomationAgent` (same litellm tool-loop pattern as `query_agent.py`) that calls browser tools via HTTP to `browser-agent:8001`. The React frontend adds an `/automations` route with an embedded noVNC iframe for the live view, plus a run history panel.

**Tech Stack:** Playwright (Python async), Xvfb + x11vnc + websockify/noVNC, httpx, FastAPI, SQLAlchemy async, litellm, React 18 + TypeScript, react-router-dom.

---

## File Map

### New files
```
browser-agent/
  Dockerfile
  requirements.txt
  start.sh
  main.py

api/app/agents/automation_agent.py
api/app/agents/prompts/automation.md
api/app/routes/automations.py
api/alembic/versions/<rev>_add_automation_tables.py
api/tests/test_automation_routes.py

frontend/src/components/AutomationsPage.tsx
```

### Modified files
```
api/app/models.py            — add AutomationRun, AutomationAction
api/app/config.py            — add browser_agent_url, novnc_url
api/app/main.py              — register automations router
api/requirements.txt         — no change needed (httpx already present)
frontend/src/App.tsx         — add /automations route
frontend/src/components/TopBar.tsx  — add Automations nav link
frontend/src/api/client.ts   — add automation API functions
docker-compose.yml           — add browser-agent service
docker-compose.prod.yml      — add browser-agent service
```

---

## Task 1: browser-agent container scaffold

**Files:**
- Create: `browser-agent/Dockerfile`
- Create: `browser-agent/requirements.txt`
- Create: `browser-agent/start.sh`
- Create: `browser-agent/main.py`

- [ ] **Step 1: Create `browser-agent/requirements.txt`**

```
fastapi==0.115.0
uvicorn[standard]==0.30.0
playwright==1.49.0
boto3==1.35.0
pydantic==2.9.2
```

- [ ] **Step 2: Create `browser-agent/Dockerfile`**

```dockerfile
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV DISPLAY=:99
# ARM64 (Raspberry Pi): Playwright has no ARM64 Chromium binaries.
# Set this so playwright install doesn't try to download x86_64 binaries.
# On ARM64, chromium-browser is installed via apt below and passed via executable_path in main.py.
# On x86_64 (local dev / CI), leave this unset and let playwright install its own Chromium.
# To deploy on Pi: build with --build-arg ARCH=arm64
ARG ARCH=x86_64
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=${ARCH:+0}

RUN apt-get update && apt-get install -y \
    python3 python3-pip \
    xvfb x11vnc \
    git curl wget \
    && if [ "$ARCH" = "arm64" ]; then apt-get install -y chromium-browser; fi \
    && rm -rf /var/lib/apt/lists/*

# Install websockify + noVNC
RUN pip3 install websockify && \
    git clone --depth=1 https://github.com/novnc/noVNC.git /opt/novnc

WORKDIR /app
COPY requirements.txt .
RUN pip3 install -r requirements.txt && \
    if [ "$ARCH" != "arm64" ]; then playwright install chromium && playwright install-deps chromium; fi

COPY . .
RUN chmod +x start.sh

EXPOSE 6080 8001

CMD ["./start.sh"]
```

> **Pi note:** Build with `docker compose build --build-arg ARCH=arm64 browser-agent` on the Pi. This skips Playwright's x86_64 binary download and installs the system ARM64 `chromium-browser` package instead. Also add `CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium-browser` to the Pi's `.env` so `main.py` passes the correct path to Playwright at runtime.

- [ ] **Step 3: Create `browser-agent/start.sh`**

```bash
#!/bin/bash
set -e

# Start virtual display
Xvfb :99 -screen 0 1280x800x24 &
sleep 1

# Start VNC server (no password, local only)
x11vnc -display :99 -forever -nopw -listen localhost -port 5900 &
sleep 1

# Start noVNC WebSocket proxy
websockify --web=/opt/novnc 0.0.0.0:6080 localhost:5900 &
sleep 1

# Start FastAPI tool server
exec uvicorn main:app --host 0.0.0.0 --port 8001
```

- [ ] **Step 4: Create `browser-agent/main.py` with just `/health`**

```python
from fastapi import FastAPI

app = FastAPI(title="Browser Agent")


@app.get("/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 5: Add `browser-agent` service to `docker-compose.yml`**

Add after the `redis` service block:

```yaml
  browser-agent:
    build: browser-agent/
    shm_size: '2gb'
    environment:
      - DISPLAY=:99
      - MINIO_ENDPOINT=http://minio:9000
      - MINIO_ACCESS_KEY=minioadmin
      - MINIO_SECRET_KEY=minioadmin
      - S3_BUCKET=wiki
    ports:
      - "6080:6080"
      - "8001:8001"
    depends_on:
      - minio
    restart: unless-stopped
```

> **Why `shm_size: '2gb'`:** Docker containers default to 64MB of `/dev/shm`. Chromium uses shared memory heavily for rendering — without this, it crashes with SIGBUS or renders blank white pages on modern asset-heavy sites.

- [ ] **Step 6: Build and verify**

```bash
docker compose build browser-agent
docker compose up -d browser-agent
sleep 5
curl http://localhost:8001/health
```

Expected:
```json
{"status": "ok"}
```

Also open `http://localhost:6080/vnc.html?autoconnect=1&view_only=1` in your browser — you should see a black Xvfb display (empty, no browser yet).

- [ ] **Step 7: Commit**

```bash
git add browser-agent/ docker-compose.yml
git commit -m "feat(browser-agent): add container scaffold with noVNC + health endpoint"
```

---

## Task 2: browser-agent session API

**Files:**
- Modify: `browser-agent/main.py` (full implementation)

- [ ] **Step 1: Replace `browser-agent/main.py` with the full session API**

```python
import base64
import os
import tempfile
import uuid
from contextlib import asynccontextmanager

import boto3
from botocore.exceptions import ClientError
from fastapi import FastAPI, HTTPException
from playwright.async_api import async_playwright
from pydantic import BaseModel

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "http://minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
S3_BUCKET = os.getenv("S3_BUCKET", "wiki")

_playwright = None
_sessions: dict[str, dict] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _playwright
    _playwright = await async_playwright().start()
    yield
    for s in list(_sessions.values()):
        try:
            await s["browser"].close()
        except Exception:
            pass
    await _playwright.stop()


app = FastAPI(title="Browser Agent", lifespan=lifespan)


def _s3_client():
    return boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        region_name="us-east-1",
    )


def _ensure_bucket():
    s3 = _s3_client()
    try:
        s3.head_bucket(Bucket=S3_BUCKET)
    except ClientError:
        s3.create_bucket(Bucket=S3_BUCKET)


def _get_session(session_id: str) -> dict:
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return _sessions[session_id]


@app.get("/health")
async def health():
    return {"status": "ok"}


_CHROMIUM_PATH = os.getenv("CHROMIUM_EXECUTABLE_PATH")  # set on ARM64/Pi via env


@app.post("/session/new")
async def session_new():
    session_id = str(uuid.uuid4())
    video_dir = tempfile.mkdtemp()
    launch_kwargs = {"headless": False}
    if _CHROMIUM_PATH:
        launch_kwargs["executable_path"] = _CHROMIUM_PATH
    browser = await _playwright.chromium.launch(**launch_kwargs)
    context = await browser.new_context(
        record_video_dir=video_dir,
        viewport={"width": 1280, "height": 800},
    )
    page = await context.new_page()
    _sessions[session_id] = {
        "browser": browser,
        "context": context,
        "page": page,
        "video_dir": video_dir,
    }
    return {"session_id": session_id}


class NavigateRequest(BaseModel):
    url: str


@app.post("/session/{session_id}/navigate")
async def session_navigate(session_id: str, body: NavigateRequest):
    s = _get_session(session_id)
    await s["page"].goto(body.url, wait_until="domcontentloaded")
    title = await s["page"].title()
    return {"title": title, "url": s["page"].url}


class ClickRequest(BaseModel):
    selector: str | None = None
    x: float | None = None
    y: float | None = None


@app.post("/session/{session_id}/click")
async def session_click(session_id: str, body: ClickRequest):
    s = _get_session(session_id)
    if body.selector:
        await s["page"].click(body.selector)
    elif body.x is not None and body.y is not None:
        await s["page"].mouse.click(body.x, body.y)
    else:
        raise HTTPException(status_code=400, detail="Provide selector or x,y coordinates")
    return {"ok": True}


class TypeRequest(BaseModel):
    text: str


@app.post("/session/{session_id}/type")
async def session_type(session_id: str, body: TypeRequest):
    s = _get_session(session_id)
    await s["page"].keyboard.type(body.text)
    return {"ok": True}


class ScrollRequest(BaseModel):
    direction: str = "down"
    amount: int = 300


@app.post("/session/{session_id}/scroll")
async def session_scroll(session_id: str, body: ScrollRequest):
    s = _get_session(session_id)
    delta = body.amount if body.direction == "down" else -body.amount
    await s["page"].mouse.wheel(0, delta)
    return {"ok": True}


@app.post("/session/{session_id}/extract")
async def session_extract(session_id: str):
    s = _get_session(session_id)
    text = await s["page"].inner_text("body")
    return {"text": text[:20000]}


@app.post("/session/{session_id}/screenshot")
async def session_screenshot(session_id: str):
    s = _get_session(session_id)
    png = await s["page"].screenshot(full_page=False)
    return {"image_b64": base64.b64encode(png).decode()}


@app.post("/session/{session_id}/close")
async def session_close(session_id: str):
    s = _get_session(session_id)
    page = s["page"]
    context = s["context"]
    browser = s["browser"]

    await page.close()
    video_path = await page.video.path()
    await context.close()
    await browser.close()

    recording_url = None
    try:
        _ensure_bucket()
        key = f"automation-recordings/{session_id}.webm"
        with open(video_path, "rb") as f:
            _s3_client().put_object(
                Bucket=S3_BUCKET,
                Key=key,
                Body=f.read(),
                ContentType="video/webm",
            )
        recording_url = key
    except Exception:
        pass

    del _sessions[session_id]
    return {"recording_url": recording_url}
```

- [ ] **Step 2: Rebuild and smoke-test the session API**

```bash
docker compose build browser-agent && docker compose up -d browser-agent
sleep 5
# Create a session
SESSION=$(curl -s -X POST http://localhost:8001/session/new | python3 -c "import sys,json; print(json.load(sys.stdin)['session_id'])")
echo "Session: $SESSION"
# Navigate
curl -s -X POST http://localhost:8001/session/$SESSION/navigate \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'
# You should see the browser in noVNC at http://localhost:6080
# Close
curl -s -X POST http://localhost:8001/session/$SESSION/close
```

- [ ] **Step 3: Commit**

```bash
git add browser-agent/main.py
git commit -m "feat(browser-agent): implement full Playwright session API with video recording"
```

---

## Task 3: DB models + Alembic migration

**Files:**
- Modify: `api/app/models.py`
- Create: `api/alembic/versions/<rev>_add_automation_tables.py` (via autogenerate)

- [ ] **Step 1: Add `AutomationRun` and `AutomationAction` to `api/app/models.py`**

Add after the `Source` class:

```python
class AutomationRun(Base):
    __tablename__ = "automation_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    goal: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="pending")  # pending/running/completed/failed/stopped
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    recording_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    actions: Mapped[list["AutomationAction"]] = relationship(back_populates="run")


class AutomationAction(Base):
    __tablename__ = "automation_actions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("automation_runs.id"))
    type: Mapped[str] = mapped_column(String)  # navigate/click/type/scroll/read/wiki_write/screenshot
    detail: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    run: Mapped["AutomationRun"] = relationship(back_populates="actions")
```

- [ ] **Step 2: Generate Alembic migration**

```bash
docker compose run --rm api alembic revision --autogenerate -m "add_automation_tables"
```

Expected output: `Generating /app/alembic/versions/<hash>_add_automation_tables.py`

- [ ] **Step 3: Verify the migration contains the right tables**

Open the generated file. It should contain:

```python
def upgrade() -> None:
    op.create_table('automation_runs', ...)
    op.create_table('automation_actions', ...)
```

If it looks wrong (empty upgrade), ensure the `api` container imports models.py via alembic's `env.py`. Check `api/alembic/env.py` — it should have `from app.models import Base` and `target_metadata = Base.metadata`.

- [ ] **Step 4: Run migration**

```bash
docker compose run --rm api alembic upgrade head
```

Expected: no errors, ends with `Running upgrade ... -> <hash>, add_automation_tables`

- [ ] **Step 5: Commit**

```bash
git add api/app/models.py api/alembic/versions/
git commit -m "feat(automation): add AutomationRun and AutomationAction models + migration"
```

---

## Task 4: Config additions

**Files:**
- Modify: `api/app/config.py`
- Modify: `docker-compose.yml` (api service environment)

- [ ] **Step 1: Add new settings to `api/app/config.py`**

Add after `openai_api_key`:

```python
    browser_agent_url: str = "http://browser-agent:8001"
    novnc_url: str = "http://localhost:6080/vnc.html"
```

- [ ] **Step 2: Add env vars to `api` service in `docker-compose.yml`**

In the `api` service `environment:` block, add:

```yaml
      BROWSER_AGENT_URL: http://browser-agent:8001
      NOVNC_URL: http://localhost:6080/vnc.html
```

- [ ] **Step 3: Verify settings load**

```bash
docker compose run --rm api python3 -c "from app.config import settings; print(settings.browser_agent_url, settings.novnc_url)"
```

Expected:
```
http://browser-agent:8001 http://localhost:6080/vnc.html
```

- [ ] **Step 4: Commit**

```bash
git add api/app/config.py docker-compose.yml
git commit -m "feat(automation): add browser_agent_url and novnc_url config settings"
```

---

## Task 5: AutomationAgent

**Files:**
- Create: `api/app/agents/prompts/automation.md`
- Create: `api/app/agents/automation_agent.py`

- [ ] **Step 1: Create `api/app/agents/prompts/automation.md`**

```markdown
You are an automation agent that controls a real web browser to complete goals on behalf of the user.

You have browser tools to navigate, click, type, scroll, and read page content. You also have wiki tools to save findings to the user's knowledge base.

## Guidelines

- Start by navigating to a relevant page for the goal.
- Use `browser_read` to extract page content before deciding what to click or type.
- Use `browser_screenshot` sparingly — only when you need to confirm the current visual state.
- When you find information worth saving, use `write_page` or `create_page` to save it to the wiki.
- Keep wiki page slugs lowercase with hyphens, e.g. `research/topic-name`.
- If a page requires login and you can't proceed, stop and report what you found so far.
- When the goal is complete, say so clearly and summarise what was done.
```

- [ ] **Step 2: Create `api/app/agents/automation_agent.py`**

```python
import json
from datetime import datetime
from pathlib import Path

import httpx
import litellm
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.assistant_message import assistant_message_for_litellm
from app.agents.log_context import agent_run_context
from app.agents.prompt_render import render_system_prompt
from app.agents.tools import AgentTools
from app.config import settings
from app.models import AutomationAction, AutomationRun
from app.sse import broadcaster

_PROMPTS = Path(__file__).parent / "prompts"
SYSTEM_PROMPT = (_PROMPTS / "automation.md").read_text()

WIKI_TOOLS = [
    "list_pages",
    "search_pages",
    "read_page",
    "write_page",
    "create_page",
    "append_to_page",
]

BROWSER_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "browser_navigate",
            "description": "Navigate the browser to a URL.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string", "description": "Full URL to navigate to"}},
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_click",
            "description": "Click an element on the page by CSS selector.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector of element to click"}
                },
                "required": ["selector"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_type",
            "description": "Type text using the keyboard into the currently focused element.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string", "description": "Text to type"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_scroll",
            "description": "Scroll the page up or down.",
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {"type": "string", "enum": ["up", "down"]},
                    "amount": {"type": "integer", "description": "Pixels to scroll (default 300)"},
                },
                "required": ["direction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_read",
            "description": "Extract all visible text from the current page for reading its content.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_screenshot",
            "description": "Take a screenshot of the current browser state to confirm what is visible.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

_log = structlog.get_logger()


async def run(
    run_id: str,
    workspace_id: str,
    goal: str,
    session: AsyncSession,
    audience_user_id: str,
) -> None:
    with agent_run_context(
        "automation_agent",
        workspace_id=workspace_id,
        audience_user_id=audience_user_id,
        run_id=run_id,
    ):
        _log.info("automation_agent_start", run_id=run_id)

        wiki_tools = AgentTools(
            session=session,
            workspace_id=workspace_id,
            broadcaster=broadcaster,
            context="automation",
            audience_user_id=audience_user_id,
        )
        tool_defs = BROWSER_TOOLS + wiki_tools.as_litellm_tools(allowed=WIKI_TOOLS)

        messages = [
            {"role": "system", "content": render_system_prompt(SYSTEM_PROMPT, model=settings.litellm_model)},
            {"role": "user", "content": f"Goal: {goal}"},
        ]

        final_status = "completed"
        browser_session_id: str | None = None

        async with httpx.AsyncClient(base_url=settings.browser_agent_url, timeout=60.0) as http:
            try:
                resp = await http.post("/session/new")
                resp.raise_for_status()
                browser_session_id = resp.json()["session_id"]
                _log.info("browser_session_created", session_id=browser_session_id)

                for turn in range(30):
                    # Check stop flag between turns.
                    # Use expire_all() + scalar query to bypass SQLAlchemy's identity map cache —
                    # without this, the session returns the stale in-memory object loaded on turn 1
                    # and never sees the status update written by the stop HTTP endpoint.
                    await session.expire_all()
                    status_result = await session.execute(
                        select(AutomationRun.status).where(AutomationRun.id == run_id)
                    )
                    current_status = status_result.scalar_one_or_none()
                    if current_status == "stopped":
                        _log.info("automation_stopped_by_user", run_id=run_id)
                        final_status = "stopped"
                        break

                    resp = await litellm.acompletion(
                        model=settings.litellm_model,
                        messages=messages,
                        tools=tool_defs,
                        tool_choice="auto",
                    )
                    msg = resp.choices[0].message
                    tool_calls = getattr(msg, "tool_calls", None) or []
                    messages.append(assistant_message_for_litellm(msg))

                    if not tool_calls:
                        _log.info("automation_agent_finished", run_id=run_id, turn=turn)
                        break

                    tool_results = []
                    for tc in tool_calls:
                        name = tc.function.name
                        args = json.loads(tc.function.arguments or "{}")
                        result_str = await _dispatch(
                            name, args, browser_session_id, http,
                            wiki_tools, run_id, session, audience_user_id,
                        )
                        tool_results.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result_str,
                        })
                    messages.extend(tool_results)

            except Exception as exc:
                _log.error("automation_agent_error", run_id=run_id, error=str(exc))
                final_status = "failed"

            finally:
                recording_url = None
                if browser_session_id:
                    try:
                        close_resp = await http.post(f"/session/{browser_session_id}/close")
                        recording_url = close_resp.json().get("recording_url")
                    except Exception:
                        pass

                result = await session.execute(
                    select(AutomationRun).where(AutomationRun.id == run_id)
                )
                run_obj = result.scalar_one_or_none()
                if run_obj:
                    if run_obj.status == "running":
                        run_obj.status = final_status
                    run_obj.completed_at = datetime.utcnow()
                    if recording_url:
                        run_obj.recording_url = recording_url
                await session.commit()

                await broadcaster.publish(
                    {
                        "event": "automation:status",
                        "run_id": run_id,
                        "status": run_obj.status if run_obj else final_status,
                    },
                    audience_user_id=audience_user_id,
                )


async def _dispatch(
    name: str,
    args: dict,
    session_id: str,
    http: httpx.AsyncClient,
    wiki_tools: AgentTools,
    run_id: str,
    db: AsyncSession,
    audience_user_id: str,
) -> str:
    if name == "browser_navigate":
        resp = await http.post(f"/session/{session_id}/navigate", json={"url": args["url"]})
        resp.raise_for_status()
        detail = f"Navigated to {args['url']}"
        await _record(db, run_id, "navigate", detail)
        await broadcaster.publish(
            {"event": "automation:action", "run_id": run_id, "type": "navigate", "detail": detail},
            audience_user_id=audience_user_id,
        )
        return resp.json().get("title", "ok")

    if name == "browser_click":
        resp = await http.post(f"/session/{session_id}/click", json={"selector": args["selector"]})
        resp.raise_for_status()
        detail = f"Clicked '{args['selector']}'"
        await _record(db, run_id, "click", detail)
        await broadcaster.publish(
            {"event": "automation:action", "run_id": run_id, "type": "click", "detail": detail},
            audience_user_id=audience_user_id,
        )
        return "clicked"

    if name == "browser_type":
        resp = await http.post(f"/session/{session_id}/type", json={"text": args["text"]})
        resp.raise_for_status()
        preview = args["text"][:40] + ("…" if len(args["text"]) > 40 else "")
        detail = f"Typed \"{preview}\""
        await _record(db, run_id, "type", detail)
        await broadcaster.publish(
            {"event": "automation:action", "run_id": run_id, "type": "type", "detail": detail},
            audience_user_id=audience_user_id,
        )
        return "typed"

    if name == "browser_scroll":
        direction = args.get("direction", "down")
        amount = int(args.get("amount", 300))
        resp = await http.post(f"/session/{session_id}/scroll", json={"direction": direction, "amount": amount})
        resp.raise_for_status()
        detail = f"Scrolled {direction}"
        await _record(db, run_id, "scroll", detail)
        await broadcaster.publish(
            {"event": "automation:action", "run_id": run_id, "type": "scroll", "detail": detail},
            audience_user_id=audience_user_id,
        )
        return "scrolled"

    if name == "browser_read":
        resp = await http.post(f"/session/{session_id}/extract")
        resp.raise_for_status()
        text = resp.json().get("text", "")
        detail = f"Read page content ({len(text)} chars)"
        await _record(db, run_id, "read", detail)
        await broadcaster.publish(
            {"event": "automation:action", "run_id": run_id, "type": "read", "detail": detail},
            audience_user_id=audience_user_id,
        )
        return text

    if name == "browser_screenshot":
        resp = await http.post(f"/session/{session_id}/screenshot")
        resp.raise_for_status()
        image_b64 = resp.json().get("image_b64", "")
        detail = "Took screenshot"
        await _record(db, run_id, "screenshot", detail)
        await broadcaster.publish(
            {"event": "automation:screenshot", "run_id": run_id, "image_b64": image_b64},
            audience_user_id=audience_user_id,
        )
        return "screenshot taken"

    # Wiki tools
    result_str = await wiki_tools.dispatch(name, args)
    if name in ("write_page", "create_page", "append_to_page"):
        slug = args.get("slug", "")
        detail = f"Wrote wiki page: {slug}"
        await _record(db, run_id, "wiki_write", detail)
        await broadcaster.publish(
            {"event": "automation:action", "run_id": run_id, "type": "wiki_write", "detail": detail},
            audience_user_id=audience_user_id,
        )
    return result_str


async def _record(db: AsyncSession, run_id: str, type_: str, detail: str) -> None:
    db.add(AutomationAction(run_id=run_id, type=type_, detail=detail))
    await db.commit()
```

- [ ] **Step 3: Verify the file imports cleanly**

```bash
docker compose run --rm api python3 -c "from app.agents.automation_agent import run; print('ok')"
```

Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add api/app/agents/automation_agent.py api/app/agents/prompts/automation.md
git commit -m "feat(automation): add AutomationAgent with browser + wiki tools"
```

---

## Task 6: Automation routes

**Files:**
- Create: `api/app/routes/automations.py`
- Modify: `api/app/main.py`

- [ ] **Step 1: Create `api/app/routes/automations.py`**

```python
from datetime import datetime

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import settings
from app.database import AsyncSessionLocal, get_db
from app.models import AutomationAction, AutomationRun
from app.routes.wiki import _ensure_workspace

router = APIRouter(prefix="/automations", tags=["automations"])
_log = structlog.get_logger()


class RunRequest(BaseModel):
    goal: str


async def _run_automation(run_id: str, workspace_id: str, user: str, goal: str) -> None:
    async with AsyncSessionLocal() as session:
        from app.agents.automation_agent import run
        await run(run_id, workspace_id, goal, session, user)


@router.post("/run", status_code=202)
async def start_run(
    body: RunRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)

    # Enforce single-run-at-a-time. The browser-agent container uses a single
    # Xvfb display (:99) and a single VNC stream — concurrent runs would render
    # on top of each other and corrupt both sessions.
    existing = await db.execute(
        select(AutomationRun).where(
            AutomationRun.workspace_id == ws.id,
            AutomationRun.status == "running",
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="An automation is already in progress.")

    run_obj = AutomationRun(workspace_id=ws.id, goal=body.goal, status="running")
    db.add(run_obj)
    await db.flush()
    run_id = run_obj.id
    await db.commit()

    background_tasks.add_task(_run_automation, run_id, ws.id, user, body.goal)
    _log.info("automation_run_started", run_id=run_id, workspace_id=ws.id)
    return {"run_id": run_id, "status": "running"}


@router.post("/runs/{run_id}/stop", status_code=200)
async def stop_run(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)
    result = await db.execute(
        select(AutomationRun).where(
            AutomationRun.id == run_id,
            AutomationRun.workspace_id == ws.id,
        )
    )
    run_obj = result.scalar_one_or_none()
    if not run_obj:
        raise HTTPException(status_code=404, detail="Run not found")
    if run_obj.status == "running":
        run_obj.status = "stopped"
        run_obj.completed_at = datetime.utcnow()
        await db.commit()
    return {"run_id": run_id, "status": run_obj.status}


@router.get("/runs")
async def list_runs(
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)
    result = await db.execute(
        select(AutomationRun)
        .where(AutomationRun.workspace_id == ws.id)
        .order_by(AutomationRun.created_at.desc())
        .limit(50)
    )
    runs = result.scalars().all()
    return [_serialise_run(r) for r in runs]


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)
    result = await db.execute(
        select(AutomationRun).where(
            AutomationRun.id == run_id,
            AutomationRun.workspace_id == ws.id,
        )
    )
    run_obj = result.scalar_one_or_none()
    if not run_obj:
        raise HTTPException(status_code=404, detail="Run not found")

    actions_result = await db.execute(
        select(AutomationAction)
        .where(AutomationAction.run_id == run_id)
        .order_by(AutomationAction.timestamp.asc())
    )
    actions = actions_result.scalars().all()

    data = _serialise_run(run_obj)
    data["actions"] = [
        {
            "id": a.id,
            "type": a.type,
            "detail": a.detail,
            "timestamp": a.timestamp.isoformat(),
        }
        for a in actions
    ]
    return data


@router.get("/novnc-url")
async def novnc_url(user: str = Depends(get_current_user)):
    base = settings.novnc_url.rstrip("/")
    return {"url": f"{base}?autoconnect=1&view_only=1&resize=scale"}


@router.get("/runs/{run_id}/recording")
async def get_recording(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)
    result = await db.execute(
        select(AutomationRun).where(
            AutomationRun.id == run_id,
            AutomationRun.workspace_id == ws.id,
        )
    )
    run_obj = result.scalar_one_or_none()
    if not run_obj or not run_obj.recording_url:
        raise HTTPException(status_code=404, detail="Recording not found")

    from fastapi.responses import StreamingResponse
    from app.storage import download_file
    data = download_file(run_obj.recording_url)
    return StreamingResponse(
        iter([data]),
        media_type="video/webm",
        headers={"Content-Disposition": f"inline; filename={run_id}.webm"},
    )


def _serialise_run(r: AutomationRun) -> dict:
    return {
        "id": r.id,
        "goal": r.goal,
        "status": r.status,
        "created_at": r.created_at.isoformat(),
        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        "recording_url": r.recording_url,
    }
```

- [ ] **Step 2: Register the router in `api/app/main.py`**

Add the import alongside the other route imports:

```python
from app.routes.automations import router as automations_router  # noqa: E402
```

Add the include after the existing `app.include_router(sources_router)` line:

```python
app.include_router(automations_router)
```

- [ ] **Step 3: Verify the routes mount correctly**

```bash
docker compose run --rm api python3 -c "
from app.main import app
routes = [r.path for r in app.routes]
automation_routes = [r for r in routes if 'automation' in r]
print(automation_routes)
"
```

Expected:
```
['/automations/run', '/automations/runs/{run_id}/stop', '/automations/runs', '/automations/runs/{run_id}', '/automations/novnc-url']
```

- [ ] **Step 4: Commit**

```bash
git add api/app/routes/automations.py api/app/main.py
git commit -m "feat(automation): add automation routes and register in main"
```

---

## Task 7: Route tests

**Files:**
- Create: `api/tests/test_automation_routes.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for /automations routes."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.database import get_db
from app.main import app

USER = "test@example.com"


@pytest.fixture
def client():
    async def override_user():
        return USER

    app.dependency_overrides[get_current_user] = override_user
    yield TestClient(app)
    app.dependency_overrides.clear()


def _make_ws(id="ws-1"):
    ws = MagicMock()
    ws.id = id
    return ws


def _make_run(
    id="run-1",
    goal="research something",
    status="completed",
    recording_url=None,
    created_at=None,
    completed_at=None,
):
    from datetime import datetime
    run = MagicMock()
    run.id = id
    run.goal = goal
    run.status = status
    run.recording_url = recording_url
    run.created_at = created_at or datetime(2026, 5, 18, 12, 0, 0)
    run.completed_at = completed_at
    return run


# ---------------------------------------------------------------------------
# POST /automations/run
# ---------------------------------------------------------------------------


def test_start_run_returns_202(client):
    mock_ws = _make_ws()
    mock_run = _make_run(status="running")
    mock_run.id = "run-abc"

    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock())
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch(
            "app.routes.automations._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ), patch(
            "app.routes.automations._run_automation",
            new_callable=AsyncMock,
        ) as mock_run_task:
            # Simulate flush setting the run id
            def fake_add(obj):
                obj.id = "run-abc"
            session.add.side_effect = fake_add

            r = client.post("/automations/run", json={"goal": "research note-taking apps"})
            assert r.status_code == 202
            data = r.json()
            assert "run_id" in data
            assert data["status"] == "running"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_start_run_requires_goal(client):
    r = client.post("/automations/run", json={})
    assert r.status_code == 422


def test_start_run_409_when_already_running(client):
    mock_ws = _make_ws()
    existing_run = _make_run(id="run-existing", status="running")

    existing_result = MagicMock()
    existing_result.scalar_one_or_none.return_value = existing_run

    session = MagicMock()
    session.execute = AsyncMock(return_value=existing_result)

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch(
            "app.routes.automations._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            r = client.post("/automations/run", json={"goal": "do something"})
            assert r.status_code == 409
            assert "already in progress" in r.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# GET /automations/runs
# ---------------------------------------------------------------------------


def test_list_runs_returns_newest_first(client):
    from datetime import datetime
    mock_ws = _make_ws()

    r1 = _make_run(id="run-old", created_at=datetime(2026, 5, 1))
    r2 = _make_run(id="run-new", created_at=datetime(2026, 5, 18))

    db_result = MagicMock()
    db_result.scalars.return_value.all.return_value = [r2, r1]

    session = MagicMock()
    session.execute = AsyncMock(return_value=db_result)

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch(
            "app.routes.automations._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            r = client.get("/automations/runs")
            assert r.status_code == 200
            data = r.json()
            assert data[0]["id"] == "run-new"
            assert data[1]["id"] == "run-old"
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# POST /automations/runs/{run_id}/stop
# ---------------------------------------------------------------------------


def test_stop_run_sets_status_stopped(client):
    mock_ws = _make_ws()
    run_obj = _make_run(id="run-1", status="running")

    db_result = MagicMock()
    db_result.scalar_one_or_none.return_value = run_obj

    session = MagicMock()
    session.execute = AsyncMock(return_value=db_result)
    session.commit = AsyncMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch(
            "app.routes.automations._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            r = client.post("/automations/runs/run-1/stop")
            assert r.status_code == 200
            assert r.json()["status"] == "stopped"
            assert run_obj.status == "stopped"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_stop_run_404_when_not_found(client):
    mock_ws = _make_ws()
    db_result = MagicMock()
    db_result.scalar_one_or_none.return_value = None

    session = MagicMock()
    session.execute = AsyncMock(return_value=db_result)

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch(
            "app.routes.automations._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            r = client.post("/automations/runs/no-such-run/stop")
            assert r.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# GET /automations/novnc-url
# ---------------------------------------------------------------------------


def test_novnc_url_returns_configured_url(client):
    with patch("app.routes.automations.settings") as mock_settings:
        mock_settings.novnc_url = "http://localhost:6080/vnc.html"
        r = client.get("/automations/novnc-url")
        assert r.status_code == 200
        url = r.json()["url"]
        assert "autoconnect=1" in url
        assert "view_only=1" in url
        assert "resize=scale" in url
```

- [ ] **Step 2: Run the tests and verify they pass**

```bash
cd api && python3 -m pytest tests/test_automation_routes.py -v
```

Expected: all 6 tests pass.

- [ ] **Step 3: Commit**

```bash
git add api/tests/test_automation_routes.py
git commit -m "test(automation): add route tests for start/stop/list/novnc-url"
```

---

## Task 8: Docker Compose — production config

**Files:**
- Modify: `docker-compose.prod.yml`

- [ ] **Step 1: Add `browser-agent` service to `docker-compose.prod.yml`**

Read `docker-compose.prod.yml` to find the right insertion point, then add after `redis`:

```yaml
  browser-agent:
    build: browser-agent/
    shm_size: '2gb'
    environment:
      - DISPLAY=:99
    env_file: .env
    ports:
      - "6080:6080"
    depends_on:
      - minio
    restart: unless-stopped
```

Note: `env_file: .env` picks up `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `S3_BUCKET` from the production env file. `shm_size: '2gb'` is required — see Task 1 note.

- [ ] **Step 2: Add `BROWSER_AGENT_URL` and `NOVNC_URL` to the `api` service in `docker-compose.prod.yml`**

In the `api` service environment block, add:

```yaml
      BROWSER_AGENT_URL: http://browser-agent:8001
      NOVNC_URL: http://smoothstudy.ai:6080/vnc.html
```

Note: `smoothstudy.ai:6080` must be reachable from the user's browser. If Cloudflare proxies port 6080, use the appropriate URL. For a direct Pi deployment, this is the Pi's public hostname on port 6080.

- [ ] **Step 3: Commit**

```bash
git add docker-compose.prod.yml
git commit -m "feat(automation): add browser-agent to production docker-compose"
```

---

## Task 9: Frontend — API client + routing + nav

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/TopBar.tsx`

- [ ] **Step 1: Add automation API functions to `frontend/src/api/client.ts`**

Read `client.ts` to find the end of the file, then append:

```typescript
// --- Automations ---

export type AutomationStatus = 'pending' | 'running' | 'completed' | 'failed' | 'stopped'

export interface AutomationRun {
  id: string
  goal: string
  status: AutomationStatus
  created_at: string
  completed_at: string | null
  recording_url: string | null
}

export interface AutomationAction {
  id: string
  type: string
  detail: string
  timestamp: string
}

export interface AutomationRunDetail extends AutomationRun {
  actions: AutomationAction[]
}

export async function startAutomationRun(goal: string): Promise<{ run_id: string; status: string }> {
  return apiFetch('/automations/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ goal }),
  })
}

export async function stopAutomationRun(runId: string): Promise<void> {
  await apiFetch(`/automations/runs/${runId}/stop`, { method: 'POST' })
}

export async function getAutomationRuns(): Promise<AutomationRun[]> {
  return apiFetch('/automations/runs')
}

export async function getAutomationRun(runId: string): Promise<AutomationRunDetail> {
  return apiFetch(`/automations/runs/${runId}`)
}

export async function getNovncUrl(): Promise<string> {
  const data: { url: string } = await apiFetch('/automations/novnc-url')
  return data.url
}
```

Note: `apiFetch` is the authenticated fetch wrapper already defined in `client.ts`. Search the file for its name — it may be called `apiFetch`, `apiRequest`, or similar. Use whatever the existing wrapper is named.

- [ ] **Step 2: Add `/automations` route to `frontend/src/App.tsx`**

Add the import at the top with the other component imports:

```typescript
import AutomationsPage from './components/AutomationsPage'
```

In the `Routes` block (inside the `authState === 'authenticated'` branch), add before the catch-all `*` route:

```tsx
<Route path="/automations" element={<AutomationsPage />} />
```

- [ ] **Step 3: Add Automations nav link to `frontend/src/components/TopBar.tsx`**

Add the `useMatch` hook for `/automations` alongside the existing ones:

```typescript
const onAutomations = useMatch({ path: '/automations', end: true })
```

Add the nav link after the `Files` link:

```tsx
<Link
  to="/automations"
  style={{
    padding: '4px 12px',
    borderRadius: 6,
    fontSize: 13,
    textDecoration: 'none',
    border: `1px solid ${onAutomations ? '#58a6ff' : '#30363d'}`,
    color: onAutomations ? '#58a6ff' : '#8b949e',
    background: onAutomations ? '#1f3a5f' : 'transparent',
  }}
>
  Automations
</Link>
```

- [ ] **Step 4: Start dev server and verify nav renders**

```bash
cd frontend && npm run dev
```

Open `http://localhost:5173`. The top bar should show Wiki | Files | Automations. Clicking Automations should navigate to `/automations` (you'll get an error since the component doesn't exist yet — that's fine).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/App.tsx frontend/src/components/TopBar.tsx
git commit -m "feat(automation): add API client functions, /automations route, and nav link"
```

---

## Task 10: AutomationsPage component

**Files:**
- Create: `frontend/src/components/AutomationsPage.tsx`

- [ ] **Step 1: Create `frontend/src/components/AutomationsPage.tsx`**

```tsx
import React, { useEffect, useRef, useState } from 'react'
import {
  type AutomationAction,
  type AutomationRun,
  getAutomationRun,
  getAutomationRuns,
  getNovncUrl,
  startAutomationRun,
  stopAutomationRun,
} from '../api/client'
import { useSse } from '../hooks/useSse'

type PageState = 'idle' | 'running'

export default function AutomationsPage() {
  const [pageState, setPageState] = useState<PageState>('idle')
  const [runs, setRuns] = useState<AutomationRun[]>([])
  const [activeRunId, setActiveRunId] = useState<string | null>(null)
  const [actions, setActions] = useState<AutomationAction[]>([])
  const [currentUrl, setCurrentUrl] = useState('')
  const [novncUrl, setNovncUrl] = useState<string | null>(null)
  const [goal, setGoal] = useState('')
  const [startError, setStartError] = useState<string | null>(null)
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null)
  const actionsEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    getAutomationRuns().then(setRuns).catch(() => {})
    getNovncUrl().then(setNovncUrl).catch(() => {})
  }, [])

  useEffect(() => {
    actionsEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [actions])

  useSse((data: unknown) => {
    const ev = data as Record<string, unknown>
    if (ev.event === 'automation:action') {
      const action = {
        id: String(Date.now()),
        type: String(ev.type ?? ''),
        detail: String(ev.detail ?? ''),
        timestamp: new Date().toISOString(),
      }
      setActions(prev => [...prev, action])
      if (ev.type === 'navigate') setCurrentUrl(String(ev.detail ?? '').replace('Navigated to ', ''))
    }
    if (ev.event === 'automation:status') {
      const status = String(ev.status ?? '')
      if (status !== 'running') {
        setPageState('idle')
        setActiveRunId(null)
        getAutomationRuns().then(setRuns).catch(() => {})
      }
    }
  })

  async function handleStart() {
    if (!goal.trim()) return
    setStartError(null)
    try {
      const { run_id } = await startAutomationRun(goal.trim())
      setActiveRunId(run_id)
      setActions([])
      setCurrentUrl('')
      setPageState('running')
      setGoal('')
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      setStartError(msg.includes('409') ? 'An automation is already in progress.' : 'Failed to start.')
    }
  }

  async function handleStop() {
    if (!activeRunId) return
    await stopAutomationRun(activeRunId)
    setPageState('idle')
    setActiveRunId(null)
    getAutomationRuns().then(setRuns).catch(() => {})
  }

  function formatDuration(run: AutomationRun): string {
    if (!run.completed_at) return ''
    const ms = new Date(run.completed_at).getTime() - new Date(run.created_at).getTime()
    const s = Math.round(ms / 1000)
    if (s < 60) return `${s}s`
    return `${Math.floor(s / 60)}m ${s % 60}s`
  }

  function statusDot(status: string): string {
    if (status === 'completed') return '#3fb950'
    if (status === 'failed') return '#f85149'
    if (status === 'running') return '#58a6ff'
    return '#d29922'
  }

  const ACTION_ICON: Record<string, string> = {
    navigate: '🧭',
    click: '🖱',
    type: '⌨️',
    scroll: '↕️',
    read: '📖',
    screenshot: '📸',
    wiki_write: '✍️',
  }

  if (pageState === 'running') {
    return (
      <div style={{ display: 'flex', height: '100%', overflow: 'hidden', background: '#0d1117' }}>
        {/* Left panel */}
        <div style={{
          width: 300,
          background: '#161b22',
          borderRight: '1px solid #30363d',
          display: 'flex',
          flexDirection: 'column',
          flexShrink: 0,
        }}>
          <div style={{ padding: '12px 16px', borderBottom: '1px solid #30363d', fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.8px', color: '#8b949e' }}>
            Goal
          </div>
          <div style={{ flex: 1, padding: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div style={{ fontSize: 13, color: '#e6edf3', lineHeight: 1.5, background: '#21262d', border: '1px solid #30363d', borderRadius: 8, padding: '10px 12px' }}>
              {goal || 'Running…'}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, background: '#388bfd18', border: '1px solid #388bfd40', borderRadius: 20, padding: '4px 12px', width: 'fit-content' }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#58a6ff', display: 'inline-block', animation: 'pulse 1.5s ease-in-out infinite' }} />
              <span style={{ fontSize: 11, color: '#58a6ff' }}>Running — {actions.length} actions</span>
            </div>
          </div>
          <div style={{ padding: 12, borderTop: '1px solid #30363d' }}>
            <button
              type="button"
              onClick={handleStop}
              style={{ width: '100%', padding: 8, background: '#f8514918', border: '1px solid #f8514940', borderRadius: 7, color: '#f85149', fontSize: 12, fontWeight: 600, cursor: 'pointer' }}
            >
              ⏹ Stop Agent
            </button>
          </div>
        </div>

        {/* Center: browser */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', background: '#0d1117', minWidth: 0 }}>
          <div style={{ background: '#161b22', borderBottom: '1px solid #30363d', padding: '8px 12px', display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0 }}>
            <div style={{ display: 'flex', gap: 4 }}>
              <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#f85149', display: 'inline-block' }} />
              <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#ffbd2e', display: 'inline-block' }} />
              <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#3fb950', display: 'inline-block' }} />
            </div>
            <div style={{ flex: 1, background: '#0d1117', border: '1px solid #30363d', borderRadius: 6, padding: '4px 12px', fontSize: 12, color: '#8b949e', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {currentUrl || 'Starting browser…'}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 5, background: '#3fb95012', border: '1px solid #3fb95030', padding: '3px 8px', borderRadius: 20, fontSize: 11, color: '#3fb950', flexShrink: 0 }}>
              <span style={{ width: 5, height: 5, borderRadius: '50%', background: '#3fb950', display: 'inline-block', animation: 'pulse 1.5s ease-in-out infinite' }} />
              LIVE
            </div>
          </div>
          <div style={{ flex: 1, overflow: 'hidden', background: '#000' }}>
            {novncUrl ? (
              <iframe
                src={novncUrl}
                style={{ width: '100%', height: '100%', border: 'none', display: 'block' }}
                title="Live browser"
              />
            ) : (
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#8b949e', fontSize: 13 }}>
                Connecting to browser…
              </div>
            )}
          </div>
        </div>

        {/* Right panel: activity */}
        <div style={{
          width: 260,
          background: '#161b22',
          borderLeft: '1px solid #30363d',
          display: 'flex',
          flexDirection: 'column',
          flexShrink: 0,
        }}>
          <div style={{ padding: '12px 16px', borderBottom: '1px solid #30363d', fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.8px', color: '#8b949e' }}>
            Activity
          </div>
          <div style={{ flex: 1, overflowY: 'auto', padding: 10, display: 'flex', flexDirection: 'column', gap: 6 }}>
            {actions.length === 0 && (
              <div style={{ color: '#8b949e', fontSize: 12, fontStyle: 'italic', textAlign: 'center', marginTop: 20 }}>
                Waiting for agent…
              </div>
            )}
            {actions.map((action, i) => (
              <div key={action.id} style={{
                display: 'flex',
                gap: 8,
                padding: '7px 10px',
                background: i === actions.length - 1 ? '#388bfd10' : '#21262d',
                border: `1px solid ${i === actions.length - 1 ? '#388bfd40' : '#30363d'}`,
                borderRadius: 7,
                fontSize: 12,
              }}>
                <span>{ACTION_ICON[action.type] ?? '•'}</span>
                <span style={{ color: action.type === 'wiki_write' ? '#3fb950' : '#c9d1d9', flex: 1, lineHeight: 1.4 }}>
                  {action.detail}
                </span>
              </div>
            ))}
            <div ref={actionsEndRef} />
          </div>
        </div>

        <style>{`@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }`}</style>
      </div>
    )
  }

  // Idle: history view
  return (
    <div style={{ flex: 1, overflowY: 'auto', background: '#0d1117', padding: 24 }}>
      <div style={{ maxWidth: 720, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 12 }}>
        <h2 style={{ fontSize: 18, fontWeight: 700, color: '#e6edf3', margin: '0 0 8px' }}>Automations</h2>

        {/* New run */}
        <div style={{ background: '#161b22', border: '1px solid #30363d', borderRadius: 10, padding: 16, display: 'flex', flexDirection: 'column', gap: 10 }}>
          <textarea
            value={goal}
            onChange={e => setGoal(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleStart() }}
            placeholder="Give the agent a goal, e.g. 'Research the top 5 note-taking apps and save a comparison to tools/note-apps'"
            rows={3}
            style={{
              width: '100%',
              background: '#0d1117',
              border: '1px solid #30363d',
              borderRadius: 8,
              padding: '10px 12px',
              color: '#e6edf3',
              fontSize: 13,
              resize: 'none',
              outline: 'none',
              fontFamily: 'inherit',
              lineHeight: 1.5,
              boxSizing: 'border-box',
            }}
          />
          <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: 12 }}>
            {startError && (
              <span style={{ fontSize: 12, color: '#f85149' }}>{startError}</span>
            )}
            <button
              type="button"
              onClick={handleStart}
              disabled={!goal.trim()}
              style={{
                padding: '8px 20px',
                background: goal.trim() ? '#238636' : '#21262d',
                border: `1px solid ${goal.trim() ? '#2ea043' : '#30363d'}`,
                borderRadius: 7,
                color: goal.trim() ? '#ffffff' : '#8b949e',
                fontSize: 13,
                fontWeight: 600,
                cursor: goal.trim() ? 'pointer' : 'default',
              }}
            >
              Run
            </button>
          </div>
        </div>

        {/* Run history */}
        {runs.map(run => (
          <div key={run.id} style={{ background: '#161b22', border: '1px solid #30363d', borderRadius: 10, overflow: 'hidden' }}>
            <div style={{ padding: '12px 16px', display: 'flex', alignItems: 'center', gap: 12 }}>
              <span style={{ width: 8, height: 8, borderRadius: '50%', background: statusDot(run.status), display: 'inline-block', flexShrink: 0 }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, color: '#e6edf3', fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {run.goal}
                </div>
                <div style={{ fontSize: 11, color: '#8b949e', marginTop: 2 }}>
                  {run.status.charAt(0).toUpperCase() + run.status.slice(1)}
                  {run.completed_at && ` · ${formatDuration(run)}`}
                </div>
              </div>
              <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
                {run.recording_url && (
                  <button
                    type="button"
                    onClick={() => window.open(`/api/automations/runs/${run.id}/recording`, '_blank')}
                    style={smallBtn}
                  >
                    ▶ Watch
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => setExpandedRunId(expandedRunId === run.id ? null : run.id)}
                  style={smallBtn}
                >
                  Actions {expandedRunId === run.id ? '▴' : '▾'}
                </button>
              </div>
            </div>
            {expandedRunId === run.id && (
              <ExpandedActions runId={run.id} />
            )}
          </div>
        ))}

        {runs.length === 0 && (
          <div style={{ textAlign: 'center', color: '#8b949e', fontSize: 13, marginTop: 32 }}>
            No automation runs yet. Write a goal above to get started.
          </div>
        )}
      </div>
    </div>
  )
}

function ExpandedActions({ runId }: { runId: string }) {
  const [actions, setActions] = useState<AutomationAction[]>([])

  useEffect(() => {
    getAutomationRun(runId).then(data => setActions(data.actions)).catch(() => {})
  }, [runId])

  const ACTION_ICON: Record<string, string> = {
    navigate: '🧭', click: '🖱', type: '⌨️', scroll: '↕️',
    read: '📖', screenshot: '📸', wiki_write: '✍️',
  }

  return (
    <div style={{ borderTop: '1px solid #30363d', background: '#0d1117', padding: '10px 16px', display: 'flex', flexDirection: 'column', gap: 5 }}>
      <div style={{ fontSize: 10, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.6px', color: '#8b949e', marginBottom: 4 }}>
        Action Log
      </div>
      {actions.slice(0, 20).map(a => (
        <div key={a.id} style={{ display: 'flex', gap: 10, fontSize: 12 }}>
          <span style={{ color: '#8b949e', width: 42, flexShrink: 0 }}>
            {new Date(a.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </span>
          <span>{ACTION_ICON[a.type] ?? '•'}</span>
          <span style={{ color: a.type === 'wiki_write' ? '#3fb950' : '#8b949e' }}>{a.detail}</span>
        </div>
      ))}
      {actions.length > 20 && (
        <div style={{ fontSize: 11, color: '#8b949e', fontStyle: 'italic' }}>+ {actions.length - 20} more actions</div>
      )}
      {actions.length === 0 && (
        <div style={{ fontSize: 12, color: '#8b949e', fontStyle: 'italic' }}>Loading…</div>
      )}
    </div>
  )
}

const smallBtn: React.CSSProperties = {
  padding: '4px 10px',
  background: '#21262d',
  border: '1px solid #30363d',
  borderRadius: 6,
  color: '#8b949e',
  fontSize: 11,
  cursor: 'pointer',
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && npm run build 2>&1 | tail -20
```

Expected: no TypeScript errors. If there are type errors, fix them before proceeding.

- [ ] **Step 3: Test the idle state visually**

```bash
cd frontend && npm run dev
```

Navigate to `http://localhost:5173/automations`. You should see the Automations page with the goal input and empty run history. The layout should match the approved mockup.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/AutomationsPage.tsx
git commit -m "feat(automation): add AutomationsPage with idle/running states and noVNC iframe"
```

---

## Task 11: End-to-end smoke test

- [ ] **Step 1: Start all services**

```bash
docker compose up --build -d
```

Wait for all services to be healthy:
```bash
docker compose ps
```

- [ ] **Step 2: Verify browser-agent is running**

```bash
curl http://localhost:8001/health
```

Expected: `{"status":"ok"}`

Open `http://localhost:6080/vnc.html?autoconnect=1&view_only=1` — you should see the Xvfb display.

- [ ] **Step 3: Start a test automation run via the UI**

1. Open `http://localhost:5173/automations`
2. Type: `Go to example.com and save the page title and description to the wiki under research/example-com`
3. Click Run
4. The page should switch to running state
5. The noVNC iframe should show Chromium opening and navigating to example.com
6. The right panel should fill with action entries

- [ ] **Step 4: Verify the wiki page was created**

After the run completes, navigate to `http://localhost:5173/wiki` and look for `research/example-com`.

- [ ] **Step 5: Verify run history and recording**

On the Automations page (idle state), the completed run should appear in history. If it has a "Watch" button, the recording was saved to MinIO successfully.

- [ ] **Step 6: Final commit**

```bash
git add .
git commit -m "feat(automation): complete automation agent — browser control, live noVNC, recordings, run history"
```

---

## Notes

**`apiFetch` wrapper name:** Search `frontend/src/api/client.ts` for the authenticated fetch helper before adding the automation functions. Match the exact function name used by existing API calls in the same file.

**Pi deployment:** After deploying, update `NOVNC_URL` in the Pi's `.env` to use the Pi's public hostname on port 6080. Port 6080 must be reachable from your browser — either expose it directly in the Cloudflare tunnel config or open it on the Pi's firewall.

**Playwright headless=False:** The browser-agent container uses `headless=False` so Chromium renders to the Xvfb display and is visible in noVNC. If you set `headless=True`, the VNC stream will show nothing and video recording may not work as expected.
