# Browser Chat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a `/browser-chat` page where the user connects to a persistent browser session and has a real-time chat with an agent that controls the browser, with conversation history saved and a session reaper for abandoned connections.

**Architecture:** New DB models (`BrowserChatSession`, `BrowserChatMessage`) + routes under `/browser-chat/` + a `BrowserChatAgent` that runs one tool loop per user message (202+background-task pattern), reusing the existing `browser-agent` container and SSE broadcaster. A periodic reaper task closes sessions idle >20 minutes. The frontend (`BrowserChatPage.tsx`) shows a left chat panel and a right noVNC iframe; a `window.blur` listener while the agent is running fires a `POST /interrupt` to notify the agent of user iframe interaction.

**Tech Stack:** Python async, FastAPI BackgroundTasks, SQLAlchemy async, LiteLLM tool loop, httpx, React 18 + TypeScript, existing `useSse` hook, react-router-dom.

---

## File Map

### New files
```
api/app/agents/prompts/browser_chat.md          — agent system prompt
api/app/agents/browser_chat_agent.py            — BrowserChatAgent run_turn()
api/app/routes/browser_chat.py                  — all /browser-chat/* routes
api/alembic/versions/<rev>_add_browser_chat_tables.py  — migration (generated)
api/tests/test_browser_chat_routes.py           — route unit tests
frontend/src/components/BrowserChatPage.tsx     — full page component
```

### Modified files
```
api/app/models.py              — add BrowserChatSession, BrowserChatMessage
api/app/main.py                — register browser_chat router + reaper task
frontend/src/App.tsx           — add /browser-chat route
frontend/src/components/TopBar.tsx  — add Browser Chat nav link
frontend/src/api/client.ts     — add browser chat API types + functions
```

---

## Task 1: DB models

**Files:**
- Modify: `api/app/models.py`

- [ ] **Step 1: Add `BrowserChatSession` and `BrowserChatMessage` to `api/app/models.py`**

Add after the `AutomationAction` class:

```python
class BrowserChatSession(Base):
    __tablename__ = "browser_chat_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    status: Mapped[str] = mapped_column(String, default="active")  # active / completed
    browser_session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    user_interrupted: Mapped[bool] = mapped_column(default=False)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    messages: Mapped[list["BrowserChatMessage"]] = relationship(back_populates="session")


class BrowserChatMessage(Base):
    __tablename__ = "browser_chat_messages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("browser_chat_sessions.id"))
    role: Mapped[str] = mapped_column(String)  # user / assistant
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    session: Mapped["BrowserChatSession"] = relationship(back_populates="messages")
```

- [ ] **Step 2: Verify the models import cleanly**

```bash
cd api && python3 -c "from app.models import BrowserChatSession, BrowserChatMessage; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Generate Alembic migration**

```bash
docker compose run --rm api alembic revision --autogenerate -m "add_browser_chat_tables"
```

Open the generated file in `api/alembic/versions/`. Confirm `upgrade()` creates `browser_chat_sessions` and `browser_chat_messages` tables.

- [ ] **Step 4: Run migration**

```bash
docker compose run --rm api alembic upgrade head
```

Expected: ends with `Running upgrade ... -> <hash>, add_browser_chat_tables`

- [ ] **Step 5: Commit**

```bash
git add api/app/models.py api/alembic/versions/
git commit -m "feat(browser-chat): add BrowserChatSession and BrowserChatMessage models + migration"
```

---

## Task 2: Agent prompt + BrowserChatAgent

**Files:**
- Create: `api/app/agents/prompts/browser_chat.md`
- Create: `api/app/agents/browser_chat_agent.py`

- [ ] **Step 1: Create `api/app/agents/prompts/browser_chat.md`**

```markdown
You are a browser assistant. The user will give you tasks to carry out in a real web browser. You have full control of the browser — navigate, click, type, read, screenshot.

You also have wiki tools to save useful findings to the user's knowledge base.

## Workflow

1. Read the user's message and decide what to do.
2. Call `browser_get_page_state` after navigating to see what interactive elements are available.
3. Execute the task using browser tools.
4. When done, reply in chat with a concise summary of what you did.

## Tool reference

| Tool | When to use |
|------|-------------|
| `browser_navigate(url)` | Go to a URL |
| `browser_get_page_state()` | Get URL, title, and interactive elements with selectors |
| `browser_click(selector?, text?)` | Click by CSS selector or visible text |
| `browser_type(text)` | Type into the focused element |
| `browser_press_key(key)` | Press Enter, Tab, Escape, arrow keys, etc. |
| `browser_focus(selector)` | Focus a specific input before typing |
| `browser_hover(selector)` | Hover to reveal dropdowns or tooltips |
| `browser_select_option(selector, value)` | Select from a `<select>` dropdown |
| `browser_scroll(direction, amount?)` | Scroll up or down |
| `browser_wait_for(selector?, text?, timeout?)` | Wait for element or text to appear |
| `browser_read()` | Extract all visible text from the page |
| `browser_execute_js(script)` | Run JavaScript — escape hatch |
| `browser_screenshot()` | Take a screenshot to see the current browser view |

## Guidelines

- After each navigation, call `browser_get_page_state` before deciding what to click.
- Use `browser_click(text="Sign in")` when you know the button label — it's more reliable than guessing a selector.
- After form submissions, call `browser_wait_for` before continuing.
- If you get stuck, take a `browser_screenshot` to see what is on screen.
- Keep wiki page slugs lowercase with hyphens, e.g. `research/topic-name`.
- If the system tells you the user has interacted with the browser, call `browser_screenshot` to see the updated state before continuing.
- Reply concisely — the user can see the browser, so focus on what you did and what you found.
```

- [ ] **Step 2: Create `api/app/agents/browser_chat_agent.py`**

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
from app.agents.automation_agent import BROWSER_TOOLS, WIKI_TOOLS
from app.agents.log_context import agent_run_context
from app.agents.prompt_render import render_system_prompt
from app.agents.tools import AgentTools
from app.config import settings
from app.models import BrowserChatSession
from app.sse import broadcaster

_PROMPTS = Path(__file__).parent / "prompts"
SYSTEM_PROMPT = (_PROMPTS / "browser_chat.md").read_text()

_log = structlog.get_logger()

MAX_TURNS = 20


async def run_turn(
    chat_session_id: str,
    workspace_id: str,
    browser_session_id: str,
    conversation_history: list[dict],
    audience_user_id: str,
    db_session: AsyncSession,
) -> str:
    """
    Run one agent turn for the latest user message.

    `conversation_history` is the full list of {role, content} dicts including
    the new user message already appended. Returns the assistant reply text.
    """
    with agent_run_context(
        "browser_chat_agent",
        workspace_id=workspace_id,
        audience_user_id=audience_user_id,
        chat_session_id=chat_session_id,
    ):
        _log.info("browser_chat_turn_start", session_id=chat_session_id)

        wiki_tools = AgentTools(
            session=db_session,
            workspace_id=workspace_id,
            broadcaster=broadcaster,
            context="browser_chat",
            audience_user_id=audience_user_id,
        )
        tool_defs = BROWSER_TOOLS + wiki_tools.as_litellm_tools(allowed=WIKI_TOOLS)

        system_msg = {
            "role": "system",
            "content": render_system_prompt(SYSTEM_PROMPT, model=settings.litellm_model),
        }
        messages = [system_msg] + conversation_history

        reply_text = "Done."

        async with httpx.AsyncClient(base_url=settings.browser_agent_url, timeout=60.0) as http:
            for turn in range(MAX_TURNS):
                # Check interrupt flag between turns.
                db_session.expire_all()
                result = await db_session.execute(
                    select(BrowserChatSession).where(BrowserChatSession.id == chat_session_id)
                )
                sess = result.scalar_one_or_none()
                if sess and sess.user_interrupted:
                    messages.append({
                        "role": "user",
                        "content": "[System: the user interacted with the browser while you were working — browser state may have changed. Call browser_screenshot to see the updated state if needed.]",
                    })
                    sess.user_interrupted = False
                    await db_session.commit()

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
                    reply_text = getattr(msg, "content", None) or "Done."
                    _log.info("browser_chat_turn_done", session_id=chat_session_id, turn=turn)
                    break

                tool_results = []
                for tc in tool_calls:
                    name = tc.function.name
                    args = json.loads(tc.function.arguments or "{}")
                    result_str = await _dispatch(
                        name, args, browser_session_id, http,
                        wiki_tools, chat_session_id, audience_user_id,
                    )
                    tool_results.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result_str if isinstance(result_str, str) else json.dumps(result_str),
                    })
                messages.extend(tool_results)
            else:
                reply_text = "I've reached my turn limit for this message. Here's where I got to: " + (getattr(messages[-1], "content", None) or "see browser.")

        return reply_text


async def _dispatch(
    name: str,
    args: dict,
    browser_session_id: str,
    http: httpx.AsyncClient,
    wiki_tools: AgentTools,
    chat_session_id: str,
    audience_user_id: str,
) -> str | list:
    async def _action(type_: str, detail: str) -> None:
        await broadcaster.publish(
            {
                "event": "browser_chat:action",
                "session_id": chat_session_id,
                "type": type_,
                "detail": detail,
            },
            audience_user_id=audience_user_id,
        )

    if name == "browser_navigate":
        resp = await http.post(f"/session/{browser_session_id}/navigate", json={"url": args["url"]})
        resp.raise_for_status()
        await _action("navigate", f"Navigated to {args['url']}")
        return resp.json().get("title", "ok")

    if name == "browser_get_page_state":
        resp = await http.post(f"/session/{browser_session_id}/get_page_state")
        resp.raise_for_status()
        data = resp.json()
        await _action("page_state", f"Got page state: {data.get('title', '')}")
        return json.dumps(data)

    if name == "browser_click":
        payload: dict = {}
        if args.get("selector"):
            payload["selector"] = args["selector"]
        if args.get("text"):
            payload["text"] = args["text"]
        resp = await http.post(f"/session/{browser_session_id}/click", json=payload)
        resp.raise_for_status()
        label = args.get("text") or args.get("selector", "element")
        await _action("click", f"Clicked '{label}'")
        return "clicked"

    if name == "browser_type":
        resp = await http.post(f"/session/{browser_session_id}/type", json={"text": args["text"]})
        resp.raise_for_status()
        preview = args["text"][:40] + ("…" if len(args["text"]) > 40 else "")
        await _action("type", f'Typed "{preview}"')
        return "typed"

    if name == "browser_press_key":
        resp = await http.post(f"/session/{browser_session_id}/press_key", json={"key": args["key"]})
        resp.raise_for_status()
        await _action("key", f"Pressed {args['key']}")
        return "key pressed"

    if name == "browser_focus":
        resp = await http.post(f"/session/{browser_session_id}/focus", json={"selector": args["selector"]})
        resp.raise_for_status()
        await _action("focus", f"Focused '{args['selector']}'")
        return "focused"

    if name == "browser_hover":
        resp = await http.post(f"/session/{browser_session_id}/hover", json={"selector": args["selector"]})
        resp.raise_for_status()
        await _action("hover", f"Hovered over '{args['selector']}'")
        return "hovered"

    if name == "browser_select_option":
        resp = await http.post(f"/session/{browser_session_id}/select_option", json={"selector": args["selector"], "value": args["value"]})
        resp.raise_for_status()
        await _action("select", f"Selected '{args['value']}' in '{args['selector']}'")
        return f"selected: {resp.json().get('selected')}"

    if name == "browser_scroll":
        direction = args.get("direction", "down")
        amount = int(args.get("amount", 300))
        resp = await http.post(f"/session/{browser_session_id}/scroll", json={"direction": direction, "amount": amount})
        resp.raise_for_status()
        await _action("scroll", f"Scrolled {direction}")
        return "scrolled"

    if name == "browser_wait_for":
        payload = {}
        if args.get("selector"):
            payload["selector"] = args["selector"]
        if args.get("text"):
            payload["text"] = args["text"]
        if args.get("timeout"):
            payload["timeout"] = int(args["timeout"])
        resp = await http.post(f"/session/{browser_session_id}/wait_for", json=payload)
        resp.raise_for_status()
        data = resp.json()
        label = args.get("selector") or args.get("text", "element")
        await _action("wait_for", f"Waited for '{label}'")
        if not data.get("found"):
            return data.get("error", "element not found")
        return "found"

    if name == "browser_read":
        resp = await http.post(f"/session/{browser_session_id}/extract")
        resp.raise_for_status()
        text = resp.json().get("text", "")
        await _action("read", f"Read page content ({len(text)} chars)")
        return text

    if name == "browser_execute_js":
        resp = await http.post(f"/session/{browser_session_id}/execute_js", json={"script": args["script"]})
        resp.raise_for_status()
        js_result = resp.json().get("result")
        preview = args["script"][:60] + ("…" if len(args["script"]) > 60 else "")
        await _action("execute_js", f"Executed JS: {preview}")
        return json.dumps(js_result)

    if name == "browser_screenshot":
        resp = await http.post(f"/session/{browser_session_id}/screenshot")
        resp.raise_for_status()
        image_b64 = resp.json().get("image_b64", "")
        await _action("screenshot", "Took screenshot")
        return [
            {"type": "text", "text": "Current browser screenshot:"},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
        ]

    # Wiki tools
    wiki_result = await wiki_tools.dispatch(name, args)
    if name in ("write_page", "create_page", "append_to_page"):
        await _action("wiki_write", f"Wrote wiki page: {args.get('slug', '')}")
    return wiki_result
```

- [ ] **Step 3: Verify the agent imports cleanly**

```bash
cd api && python3 -c "from app.agents.browser_chat_agent import run_turn; print('ok')"
```

Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add api/app/agents/browser_chat_agent.py api/app/agents/prompts/browser_chat.md
git commit -m "feat(browser-chat): add BrowserChatAgent with full browser + wiki tool dispatch"
```

---

## Task 3: Routes + register + reaper

**Files:**
- Create: `api/app/routes/browser_chat.py`
- Modify: `api/app/main.py`

- [ ] **Step 1: Create `api/app/routes/browser_chat.py`**

```python
from datetime import datetime, timedelta

import httpx
import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import settings
from app.database import AsyncSessionLocal, get_db
from app.models import BrowserChatMessage, BrowserChatSession
from app.routes.wiki import _ensure_workspace
from app.sse import broadcaster

router = APIRouter(prefix="/browser-chat", tags=["browser-chat"])
_log = structlog.get_logger()

_IDLE_TIMEOUT_MINUTES = 20


class MessageRequest(BaseModel):
    content: str


# ---------------------------------------------------------------------------
# POST /browser-chat/sessions — Connect
# ---------------------------------------------------------------------------

@router.post("/sessions", status_code=201)
async def connect(
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)

    # One active session at a time (single Xvfb display).
    existing = await db.execute(
        select(BrowserChatSession).where(
            BrowserChatSession.workspace_id == ws.id,
            BrowserChatSession.status == "active",
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="A browser chat session is already active.")

    async with httpx.AsyncClient(base_url=settings.browser_agent_url, timeout=30.0) as http:
        try:
            resp = await http.post("/session/new")
            resp.raise_for_status()
            browser_session_id = resp.json()["session_id"]
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Failed to start browser session: {exc}")

    sess = BrowserChatSession(
        workspace_id=ws.id,
        browser_session_id=browser_session_id,
        status="active",
        last_activity_at=datetime.utcnow(),
    )
    db.add(sess)
    await db.commit()
    await db.refresh(sess)
    _log.info("browser_chat_connected", session_id=sess.id, browser_session_id=browser_session_id)
    return {"session_id": sess.id}


# ---------------------------------------------------------------------------
# POST /browser-chat/sessions/{id}/message — Send message (202)
# ---------------------------------------------------------------------------

async def _run_turn_task(
    chat_session_id: str,
    workspace_id: str,
    browser_session_id: str,
    user_content: str,
    audience_user_id: str,
) -> None:
    async with AsyncSessionLocal() as db:
        # Load full history (already includes the new user message).
        result = await db.execute(
            select(BrowserChatMessage)
            .where(BrowserChatMessage.session_id == chat_session_id)
            .order_by(BrowserChatMessage.created_at.asc())
        )
        messages = result.scalars().all()
        history = [{"role": m.role, "content": m.content} for m in messages]

        await broadcaster.publish(
            {"event": "browser_chat:status", "session_id": chat_session_id, "status": "thinking"},
            audience_user_id=audience_user_id,
        )

        from app.agents.browser_chat_agent import run_turn
        try:
            reply = await run_turn(
                chat_session_id=chat_session_id,
                workspace_id=workspace_id,
                browser_session_id=browser_session_id,
                conversation_history=history,
                audience_user_id=audience_user_id,
                db_session=db,
            )
        except Exception as exc:
            _log.error("browser_chat_turn_error", session_id=chat_session_id, error=str(exc))
            reply = "Sorry, something went wrong. The browser session is still open — try again."

        # Persist assistant reply.
        db.add(BrowserChatMessage(session_id=chat_session_id, role="assistant", content=reply))

        # Update last_activity_at.
        sess_result = await db.execute(
            select(BrowserChatSession).where(BrowserChatSession.id == chat_session_id)
        )
        sess = sess_result.scalar_one_or_none()
        if sess:
            sess.last_activity_at = datetime.utcnow()
        await db.commit()

        await broadcaster.publish(
            {"event": "browser_chat:reply", "session_id": chat_session_id, "content": reply},
            audience_user_id=audience_user_id,
        )
        await broadcaster.publish(
            {"event": "browser_chat:status", "session_id": chat_session_id, "status": "idle"},
            audience_user_id=audience_user_id,
        )


@router.post("/sessions/{session_id}/message", status_code=202)
async def send_message(
    session_id: str,
    body: MessageRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)
    result = await db.execute(
        select(BrowserChatSession).where(
            BrowserChatSession.id == session_id,
            BrowserChatSession.workspace_id == ws.id,
        )
    )
    sess = result.scalar_one_or_none()
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    if sess.status != "active":
        raise HTTPException(status_code=409, detail="Session is not active")
    if not body.content.strip():
        raise HTTPException(status_code=422, detail="Message content cannot be empty")

    # Persist user message.
    db.add(BrowserChatMessage(session_id=session_id, role="user", content=body.content.strip()))
    sess.last_activity_at = datetime.utcnow()
    await db.commit()

    background_tasks.add_task(
        _run_turn_task,
        session_id,
        ws.id,
        sess.browser_session_id,
        body.content.strip(),
        user,
    )
    return {"status": "accepted"}


# ---------------------------------------------------------------------------
# POST /browser-chat/sessions/{id}/interrupt
# ---------------------------------------------------------------------------

@router.post("/sessions/{session_id}/interrupt", status_code=200)
async def interrupt(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)
    result = await db.execute(
        select(BrowserChatSession).where(
            BrowserChatSession.id == session_id,
            BrowserChatSession.workspace_id == ws.id,
        )
    )
    sess = result.scalar_one_or_none()
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    sess.user_interrupted = True
    await db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# POST /browser-chat/sessions/{id}/disconnect
# ---------------------------------------------------------------------------

@router.post("/sessions/{session_id}/disconnect", status_code=200)
async def disconnect(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)
    result = await db.execute(
        select(BrowserChatSession).where(
            BrowserChatSession.id == session_id,
            BrowserChatSession.workspace_id == ws.id,
        )
    )
    sess = result.scalar_one_or_none()
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")

    if sess.browser_session_id:
        async with httpx.AsyncClient(base_url=settings.browser_agent_url, timeout=10.0) as http:
            try:
                await http.post(f"/session/{sess.browser_session_id}/close")
            except Exception:
                pass

    sess.status = "completed"
    sess.completed_at = datetime.utcnow()
    await db.commit()
    _log.info("browser_chat_disconnected", session_id=session_id)
    return {"ok": True}


# ---------------------------------------------------------------------------
# GET /browser-chat/sessions — List sessions
# ---------------------------------------------------------------------------

@router.get("/sessions")
async def list_sessions(
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)
    result = await db.execute(
        select(BrowserChatSession)
        .where(BrowserChatSession.workspace_id == ws.id)
        .order_by(BrowserChatSession.created_at.desc())
        .limit(50)
    )
    sessions = result.scalars().all()
    return [_serialise_session(s) for s in sessions]


# ---------------------------------------------------------------------------
# GET /browser-chat/sessions/{id} — Get session + messages
# ---------------------------------------------------------------------------

@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)
    result = await db.execute(
        select(BrowserChatSession).where(
            BrowserChatSession.id == session_id,
            BrowserChatSession.workspace_id == ws.id,
        )
    )
    sess = result.scalar_one_or_none()
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")

    msgs_result = await db.execute(
        select(BrowserChatMessage)
        .where(BrowserChatMessage.session_id == session_id)
        .order_by(BrowserChatMessage.created_at.asc())
    )
    msgs = msgs_result.scalars().all()
    data = _serialise_session(sess)
    data["messages"] = [
        {"id": m.id, "role": m.role, "content": m.content, "created_at": m.created_at.isoformat()}
        for m in msgs
    ]
    return data


def _serialise_session(s: BrowserChatSession) -> dict:
    return {
        "id": s.id,
        "status": s.status,
        "created_at": s.created_at.isoformat(),
        "completed_at": s.completed_at.isoformat() if s.completed_at else None,
    }
```

- [ ] **Step 2: Register router + reaper in `api/app/main.py`**

Add the import alongside the other route imports (after the existing `from app.routes.automations` line):

```python
from app.routes.browser_chat import router as browser_chat_router  # noqa: E402
```

Add the include after `app.include_router(automations_router)`:

```python
app.include_router(browser_chat_router)
```

Add the reaper coroutine and wire it into the lifespan. Add this function before the `lifespan` definition:

```python
async def _browser_chat_reaper() -> None:
    import asyncio
    from datetime import timedelta
    import httpx
    from app.database import AsyncSessionLocal
    from app.models import BrowserChatSession
    from sqlalchemy import select

    while True:
        await asyncio.sleep(300)  # every 5 minutes
        try:
            async with AsyncSessionLocal() as db:
                cutoff = datetime.utcnow() - timedelta(minutes=20)
                result = await db.execute(
                    select(BrowserChatSession).where(
                        BrowserChatSession.status == "active",
                        BrowserChatSession.last_activity_at < cutoff,
                    )
                )
                stale = result.scalars().all()
                for sess in stale:
                    if sess.browser_session_id:
                        from app.config import settings as _s
                        async with httpx.AsyncClient(base_url=_s.browser_agent_url, timeout=10.0) as http:
                            try:
                                await http.post(f"/session/{sess.browser_session_id}/close")
                            except Exception:
                                pass
                    sess.status = "completed"
                    sess.completed_at = datetime.utcnow()
                    log.warning("browser_chat_session_reaped", session_id=sess.id)
                if stale:
                    await db.commit()
        except Exception as exc:
            log.error("browser_chat_reaper_error", error=str(exc))
```

Also add `from datetime import datetime` at the top of `main.py` if not already present. Then update the lifespan to start and stop the reaper:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    from app.sse import broadcaster

    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379")
    from app.config import settings
    log.info("startup", redis_url=_sanitize_redis_url_for_log(redis_url))
    if settings.dev_auth_bypass:
        log.warning("dev_auth_bypass_enabled", hint="all JWT validation is disabled — set DEV_AUTH_BYPASS=false in production")
    await broadcaster.connect(redis_url)
    reaper_task = asyncio.create_task(_browser_chat_reaper())
    yield
    reaper_task.cancel()
    await broadcaster.disconnect()
    log.info("shutdown")
```

- [ ] **Step 3: Verify routes mount**

```bash
docker compose run --rm api python3 -c "
from app.main import app
routes = [r.path for r in app.routes if 'browser' in r.path]
print(routes)
"
```

Expected:
```
['/browser-chat/sessions', '/browser-chat/sessions/{session_id}/message', '/browser-chat/sessions/{session_id}/interrupt', '/browser-chat/sessions/{session_id}/disconnect', '/browser-chat/sessions', '/browser-chat/sessions/{session_id}']
```

- [ ] **Step 4: Commit**

```bash
git add api/app/routes/browser_chat.py api/app/main.py
git commit -m "feat(browser-chat): add routes, register router, and add session reaper"
```

---

## Task 4: Route tests

**Files:**
- Create: `api/tests/test_browser_chat_routes.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for /browser-chat routes."""
from datetime import datetime
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


def _make_session(
    id="sess-1",
    status="active",
    browser_session_id="bsess-1",
    created_at=None,
    completed_at=None,
    last_activity_at=None,
):
    s = MagicMock()
    s.id = id
    s.status = status
    s.browser_session_id = browser_session_id
    s.created_at = created_at or datetime(2026, 5, 18, 12, 0, 0)
    s.completed_at = completed_at
    s.last_activity_at = last_activity_at or datetime(2026, 5, 18, 12, 0, 0)
    s.user_interrupted = False
    return s


# ---------------------------------------------------------------------------
# POST /browser-chat/sessions — connect
# ---------------------------------------------------------------------------


def test_connect_creates_session(client):
    mock_ws = _make_ws()
    no_existing = MagicMock()
    no_existing.scalar_one_or_none.return_value = None

    session = MagicMock()
    session.execute = AsyncMock(return_value=no_existing)
    session.commit = AsyncMock()
    session.add = MagicMock()
    session.refresh = AsyncMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch("app.routes.browser_chat._ensure_workspace", new_callable=AsyncMock, return_value=mock_ws), \
             patch("httpx.AsyncClient") as mock_http_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {"session_id": "bsess-abc"}
            mock_http.post = AsyncMock(return_value=mock_resp)
            mock_http_cls.return_value = mock_http

            def fake_add(obj):
                obj.id = "sess-abc"
            session.add.side_effect = fake_add

            r = client.post("/browser-chat/sessions")
            assert r.status_code == 201
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_connect_409_when_active_session_exists(client):
    mock_ws = _make_ws()
    existing = MagicMock()
    existing.scalar_one_or_none.return_value = _make_session()

    session = MagicMock()
    session.execute = AsyncMock(return_value=existing)

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch("app.routes.browser_chat._ensure_workspace", new_callable=AsyncMock, return_value=mock_ws):
            r = client.post("/browser-chat/sessions")
            assert r.status_code == 409
            assert "already active" in r.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# POST /browser-chat/sessions/{id}/message
# ---------------------------------------------------------------------------


def test_send_message_returns_202(client):
    mock_ws = _make_ws()
    mock_sess = _make_session()

    sess_result = MagicMock()
    sess_result.scalar_one_or_none.return_value = mock_sess

    session = MagicMock()
    session.execute = AsyncMock(return_value=sess_result)
    session.commit = AsyncMock()
    session.add = MagicMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch("app.routes.browser_chat._ensure_workspace", new_callable=AsyncMock, return_value=mock_ws), \
             patch("app.routes.browser_chat._run_turn_task", new_callable=AsyncMock):
            r = client.post("/browser-chat/sessions/sess-1/message", json={"content": "go to google"})
            assert r.status_code == 202
            assert r.json()["status"] == "accepted"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_send_message_404_when_session_not_found(client):
    mock_ws = _make_ws()
    sess_result = MagicMock()
    sess_result.scalar_one_or_none.return_value = None

    session = MagicMock()
    session.execute = AsyncMock(return_value=sess_result)

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch("app.routes.browser_chat._ensure_workspace", new_callable=AsyncMock, return_value=mock_ws):
            r = client.post("/browser-chat/sessions/no-such/message", json={"content": "go to google"})
            assert r.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_send_message_422_when_empty_content(client):
    mock_ws = _make_ws()
    mock_sess = _make_session()
    sess_result = MagicMock()
    sess_result.scalar_one_or_none.return_value = mock_sess

    session = MagicMock()
    session.execute = AsyncMock(return_value=sess_result)
    session.commit = AsyncMock()
    session.add = MagicMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch("app.routes.browser_chat._ensure_workspace", new_callable=AsyncMock, return_value=mock_ws):
            r = client.post("/browser-chat/sessions/sess-1/message", json={"content": "   "})
            assert r.status_code == 422
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# POST /browser-chat/sessions/{id}/interrupt
# ---------------------------------------------------------------------------


def test_interrupt_sets_flag(client):
    mock_ws = _make_ws()
    mock_sess = _make_session()
    sess_result = MagicMock()
    sess_result.scalar_one_or_none.return_value = mock_sess

    session = MagicMock()
    session.execute = AsyncMock(return_value=sess_result)
    session.commit = AsyncMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch("app.routes.browser_chat._ensure_workspace", new_callable=AsyncMock, return_value=mock_ws):
            r = client.post("/browser-chat/sessions/sess-1/interrupt")
            assert r.status_code == 200
            assert mock_sess.user_interrupted is True
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# POST /browser-chat/sessions/{id}/disconnect
# ---------------------------------------------------------------------------


def test_disconnect_marks_completed(client):
    mock_ws = _make_ws()
    mock_sess = _make_session()
    sess_result = MagicMock()
    sess_result.scalar_one_or_none.return_value = mock_sess

    session = MagicMock()
    session.execute = AsyncMock(return_value=sess_result)
    session.commit = AsyncMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch("app.routes.browser_chat._ensure_workspace", new_callable=AsyncMock, return_value=mock_ws), \
             patch("httpx.AsyncClient") as mock_http_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.post = AsyncMock(return_value=MagicMock())
            mock_http_cls.return_value = mock_http

            r = client.post("/browser-chat/sessions/sess-1/disconnect")
            assert r.status_code == 200
            assert mock_sess.status == "completed"
            assert mock_sess.completed_at is not None
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# GET /browser-chat/sessions
# ---------------------------------------------------------------------------


def test_list_sessions_returns_newest_first(client):
    mock_ws = _make_ws()
    s1 = _make_session(id="old", created_at=datetime(2026, 5, 1))
    s2 = _make_session(id="new", created_at=datetime(2026, 5, 18))

    db_result = MagicMock()
    db_result.scalars.return_value.all.return_value = [s2, s1]

    session = MagicMock()
    session.execute = AsyncMock(return_value=db_result)

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch("app.routes.browser_chat._ensure_workspace", new_callable=AsyncMock, return_value=mock_ws):
            r = client.get("/browser-chat/sessions")
            assert r.status_code == 200
            data = r.json()
            assert data[0]["id"] == "new"
            assert data[1]["id"] == "old"
    finally:
        app.dependency_overrides.pop(get_db, None)
```

- [ ] **Step 2: Run the tests**

```bash
cd api && python3 -m pytest tests/test_browser_chat_routes.py -v
```

Expected: all 8 tests pass.

- [ ] **Step 3: Run full test suite to confirm no regressions**

```bash
cd api && python3 -m pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add api/tests/test_browser_chat_routes.py
git commit -m "test(browser-chat): add route tests for connect/message/interrupt/disconnect/list"
```

---

## Task 5: Frontend API client

**Files:**
- Modify: `frontend/src/api/client.ts`

- [ ] **Step 1: Append browser chat types and API functions to `frontend/src/api/client.ts`**

Add at the end of the file:

```typescript
// --- Browser Chat ---

export interface BrowserChatSession {
  id: string
  status: 'active' | 'completed'
  created_at: string
  completed_at: string | null
}

export interface BrowserChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  created_at: string
}

export interface BrowserChatSessionDetail extends BrowserChatSession {
  messages: BrowserChatMessage[]
}

export async function connectBrowserChat(): Promise<{ session_id: string }> {
  const r = await fetchWithAuth(`${BASE}/browser-chat/sessions`, { method: 'POST' })
  if (!r.ok) throw new Error(`connectBrowserChat failed: ${r.status}`)
  return r.json()
}

export async function sendBrowserChatMessage(sessionId: string, content: string): Promise<void> {
  const r = await fetchWithAuth(`${BASE}/browser-chat/sessions/${sessionId}/message`, {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify({ content }),
  })
  if (!r.ok) throw new Error(`sendBrowserChatMessage failed: ${r.status}`)
}

export async function interruptBrowserChat(sessionId: string): Promise<void> {
  const r = await fetchWithAuth(`${BASE}/browser-chat/sessions/${sessionId}/interrupt`, { method: 'POST' })
  if (!r.ok) throw new Error(`interruptBrowserChat failed: ${r.status}`)
}

export async function disconnectBrowserChat(sessionId: string): Promise<void> {
  const r = await fetchWithAuth(`${BASE}/browser-chat/sessions/${sessionId}/disconnect`, { method: 'POST' })
  if (!r.ok) throw new Error(`disconnectBrowserChat failed: ${r.status}`)
}

export async function listBrowserChatSessions(): Promise<BrowserChatSession[]> {
  const r = await fetchWithAuth(`${BASE}/browser-chat/sessions`)
  if (!r.ok) throw new Error(`listBrowserChatSessions failed: ${r.status}`)
  return r.json()
}

export async function getBrowserChatSession(sessionId: string): Promise<BrowserChatSessionDetail> {
  const r = await fetchWithAuth(`${BASE}/browser-chat/sessions/${sessionId}`)
  if (!r.ok) throw new Error(`getBrowserChatSession failed: ${r.status}`)
  return r.json()
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && npm run build 2>&1 | tail -10
```

Expected: no TypeScript errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/client.ts
git commit -m "feat(browser-chat): add API client types and functions"
```

---

## Task 6: BrowserChatPage component

**Files:**
- Create: `frontend/src/components/BrowserChatPage.tsx`

- [ ] **Step 1: Create `frontend/src/components/BrowserChatPage.tsx`**

```tsx
import React, { useCallback, useEffect, useRef, useState } from 'react'
import {
  type BrowserChatMessage,
  type BrowserChatSession,
  connectBrowserChat,
  disconnectBrowserChat,
  getBrowserChatSession,
  interruptBrowserChat,
  listBrowserChatSessions,
  sendBrowserChatMessage,
} from '../api/client'
import { getNovncUrl } from '../api/client'
import { useSse } from '../hooks/useSse'

type ConnectionState = 'disconnected' | 'connecting' | 'connected'

export default function BrowserChatPage() {
  const [connectionState, setConnectionState] = useState<ConnectionState>('disconnected')
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null)
  const [messages, setMessages] = useState<BrowserChatMessage[]>([])
  const [agentRunning, setAgentRunning] = useState(false)
  const [novncUrl, setNovncUrl] = useState<string | null>(null)
  const [pastSessions, setPastSessions] = useState<BrowserChatSession[]>([])
  const [expandedSessionId, setExpandedSessionId] = useState<string | null>(null)
  const [expandedMessages, setExpandedMessages] = useState<BrowserChatMessage[]>([])
  const [input, setInput] = useState('')
  const [connectError, setConnectError] = useState<string | null>(null)
  const [currentUrl, setCurrentUrl] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    getNovncUrl().then(setNovncUrl).catch(() => {})
    listBrowserChatSessions().then(setPastSessions).catch(() => {})
  }, [])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Blur listener: fires when user clicks into the noVNC iframe while agent is running.
  const handleWindowBlur = useCallback(() => {
    if (activeSessionId && agentRunning) {
      interruptBrowserChat(activeSessionId).catch(() => {})
    }
  }, [activeSessionId, agentRunning])

  useEffect(() => {
    if (agentRunning) {
      window.addEventListener('blur', handleWindowBlur)
      return () => window.removeEventListener('blur', handleWindowBlur)
    }
  }, [agentRunning, handleWindowBlur])

  useSse((data: unknown) => {
    const ev = data as Record<string, unknown>
    if (ev.session_id !== activeSessionId) return

    if (ev.event === 'browser_chat:action') {
      if (ev.type === 'navigate') {
        setCurrentUrl(String(ev.detail ?? '').replace('Navigated to ', ''))
      }
    }
    if (ev.event === 'browser_chat:reply') {
      const msg: BrowserChatMessage = {
        id: String(Date.now()),
        role: 'assistant',
        content: String(ev.content ?? ''),
        created_at: new Date().toISOString(),
      }
      setMessages(prev => [...prev, msg])
      setAgentRunning(false)
      inputRef.current?.focus()
    }
    if (ev.event === 'browser_chat:status') {
      setAgentRunning(ev.status === 'thinking')
    }
  })

  async function handleConnect() {
    setConnectError(null)
    setConnectionState('connecting')
    try {
      const { session_id } = await connectBrowserChat()
      setActiveSessionId(session_id)
      setMessages([])
      setCurrentUrl('')
      setConnectionState('connected')
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      setConnectError(msg.includes('409') ? 'A browser session is already active.' : 'Failed to connect.')
      setConnectionState('disconnected')
    }
  }

  async function handleDisconnect() {
    if (!activeSessionId) return
    try {
      await disconnectBrowserChat(activeSessionId)
    } catch { /* best-effort */ }
    setConnectionState('disconnected')
    setActiveSessionId(null)
    setMessages([])
    setAgentRunning(false)
    listBrowserChatSessions().then(setPastSessions).catch(() => {})
  }

  async function handleSend() {
    if (!input.trim() || !activeSessionId || agentRunning) return
    const content = input.trim()
    setInput('')
    const userMsg: BrowserChatMessage = {
      id: String(Date.now()),
      role: 'user',
      content,
      created_at: new Date().toISOString(),
    }
    setMessages(prev => [...prev, userMsg])
    setAgentRunning(true)
    try {
      await sendBrowserChatMessage(activeSessionId, content)
    } catch (err: unknown) {
      setAgentRunning(false)
      setMessages(prev => [...prev, {
        id: String(Date.now() + 1),
        role: 'assistant',
        content: 'Failed to send message. Please try again.',
        created_at: new Date().toISOString(),
      }])
    }
  }

  async function toggleExpandSession(sessionId: string) {
    if (expandedSessionId === sessionId) {
      setExpandedSessionId(null)
      setExpandedMessages([])
      return
    }
    setExpandedSessionId(sessionId)
    try {
      const detail = await getBrowserChatSession(sessionId)
      setExpandedMessages(detail.messages)
    } catch { setExpandedMessages([]) }
  }

  if (connectionState === 'connected') {
    return (
      <div style={{ display: 'flex', height: '100%', overflow: 'hidden', background: '#0d1117' }}>
        {/* Left: chat */}
        <div style={{
          width: 320,
          flexShrink: 0,
          background: '#161b22',
          borderRight: '1px solid #30363d',
          display: 'flex',
          flexDirection: 'column',
        }}>
          <div style={{ padding: '10px 14px', borderBottom: '1px solid #30363d', fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.8px', color: '#8b949e' }}>
            Chat
          </div>
          <div style={{ flex: 1, overflowY: 'auto', padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 8 }}>
            {messages.length === 0 && (
              <div style={{ color: '#8b949e', fontSize: 12, fontStyle: 'italic', textAlign: 'center', marginTop: 24 }}>
                Type a message to get started.
              </div>
            )}
            {messages.map(msg => (
              <div key={msg.id} style={{
                alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start',
                maxWidth: '90%',
                background: msg.role === 'user' ? '#1f3a5f' : '#21262d',
                border: `1px solid ${msg.role === 'user' ? '#388bfd40' : '#30363d'}`,
                borderRadius: msg.role === 'user' ? '12px 12px 2px 12px' : '12px 12px 12px 2px',
                padding: '8px 12px',
                fontSize: 13,
                color: '#e6edf3',
                lineHeight: 1.5,
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
              }}>
                {msg.content}
              </div>
            ))}
            {agentRunning && (
              <div style={{ alignSelf: 'flex-start', background: '#21262d', border: '1px solid #30363d', borderRadius: '12px 12px 12px 2px', padding: '8px 12px', fontSize: 13, color: '#8b949e' }}>
                <span style={{ animation: 'pulse 1.5s ease-in-out infinite', display: 'inline-block' }}>thinking…</span>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
          <div style={{ padding: '10px 12px', borderTop: '1px solid #30363d', display: 'flex', flexDirection: 'column', gap: 8 }}>
            <textarea
              ref={inputRef}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSend() }}
              disabled={agentRunning}
              placeholder={agentRunning ? 'Agent is working…' : 'Tell the agent what to do… (⌘↵ to send)'}
              rows={3}
              style={{
                width: '100%',
                background: '#0d1117',
                border: `1px solid ${agentRunning ? '#30363d' : '#388bfd40'}`,
                borderRadius: 8,
                padding: '8px 10px',
                color: agentRunning ? '#8b949e' : '#e6edf3',
                fontSize: 13,
                resize: 'none',
                outline: 'none',
                fontFamily: 'inherit',
                lineHeight: 1.5,
                boxSizing: 'border-box',
              }}
            />
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <button
                type="button"
                onClick={handleDisconnect}
                style={{ padding: '5px 10px', background: 'transparent', border: '1px solid #f8514940', borderRadius: 6, color: '#f85149', fontSize: 11, cursor: 'pointer' }}
              >
                Disconnect
              </button>
              <button
                type="button"
                onClick={handleSend}
                disabled={!input.trim() || agentRunning}
                style={{
                  padding: '6px 14px',
                  background: input.trim() && !agentRunning ? '#238636' : '#21262d',
                  border: `1px solid ${input.trim() && !agentRunning ? '#2ea043' : '#30363d'}`,
                  borderRadius: 6,
                  color: input.trim() && !agentRunning ? '#ffffff' : '#8b949e',
                  fontSize: 12,
                  fontWeight: 600,
                  cursor: input.trim() && !agentRunning ? 'pointer' : 'default',
                }}
              >
                Send
              </button>
            </div>
          </div>
        </div>

        {/* Right: browser */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          <div style={{ background: '#161b22', borderBottom: '1px solid #30363d', padding: '8px 12px', display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0 }}>
            <div style={{ display: 'flex', gap: 4 }}>
              <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#f85149', display: 'inline-block' }} />
              <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#ffbd2e', display: 'inline-block' }} />
              <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#3fb950', display: 'inline-block' }} />
            </div>
            <div style={{ flex: 1, background: '#0d1117', border: '1px solid #30363d', borderRadius: 6, padding: '4px 12px', fontSize: 12, color: '#8b949e', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {currentUrl || 'Browser ready'}
            </div>
            {agentRunning && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 5, background: '#388bfd12', border: '1px solid #388bfd40', padding: '3px 8px', borderRadius: 20, fontSize: 11, color: '#58a6ff', flexShrink: 0 }}>
                <span style={{ width: 5, height: 5, borderRadius: '50%', background: '#58a6ff', display: 'inline-block', animation: 'pulse 1.5s ease-in-out infinite' }} />
                Working
              </div>
            )}
          </div>
          <div style={{ flex: 1, background: '#000', overflow: 'hidden' }}>
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

        <style>{`@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }`}</style>
      </div>
    )
  }

  // Disconnected / idle state
  return (
    <div style={{ flex: 1, overflowY: 'auto', background: '#0d1117', padding: 24 }}>
      <div style={{ maxWidth: 680, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 16 }}>
        <h2 style={{ fontSize: 18, fontWeight: 700, color: '#e6edf3', margin: 0 }}>Browser Chat</h2>

        <div style={{ background: '#161b22', border: '1px solid #30363d', borderRadius: 10, padding: 24, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12 }}>
          <div style={{ fontSize: 13, color: '#8b949e', textAlign: 'center', lineHeight: 1.6 }}>
            Connect to a live browser and chat with an agent that controls it in real time.
          </div>
          {connectError && (
            <div style={{ fontSize: 12, color: '#f85149' }}>{connectError}</div>
          )}
          <button
            type="button"
            onClick={handleConnect}
            disabled={connectionState === 'connecting'}
            style={{
              padding: '10px 28px',
              background: connectionState === 'connecting' ? '#21262d' : '#238636',
              border: `1px solid ${connectionState === 'connecting' ? '#30363d' : '#2ea043'}`,
              borderRadius: 8,
              color: connectionState === 'connecting' ? '#8b949e' : '#ffffff',
              fontSize: 14,
              fontWeight: 600,
              cursor: connectionState === 'connecting' ? 'default' : 'pointer',
            }}
          >
            {connectionState === 'connecting' ? 'Connecting…' : 'Connect'}
          </button>
        </div>

        {pastSessions.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.8px', color: '#8b949e' }}>Past Sessions</div>
            {pastSessions.map(s => (
              <div key={s.id} style={{ background: '#161b22', border: '1px solid #30363d', borderRadius: 10, overflow: 'hidden' }}>
                <div style={{ padding: '10px 14px', display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{ width: 7, height: 7, borderRadius: '50%', background: s.status === 'active' ? '#58a6ff' : '#8b949e', display: 'inline-block', flexShrink: 0 }} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 12, color: '#e6edf3' }}>
                      {new Date(s.created_at).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })}
                    </div>
                    <div style={{ fontSize: 11, color: '#8b949e' }}>
                      {s.status === 'active' ? 'Active' : 'Completed'}
                      {s.completed_at && ` · ${Math.round((new Date(s.completed_at).getTime() - new Date(s.created_at).getTime()) / 60000)}m`}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => toggleExpandSession(s.id)}
                    style={smallBtn}
                  >
                    Messages {expandedSessionId === s.id ? '▴' : '▾'}
                  </button>
                </div>
                {expandedSessionId === s.id && (
                  <div style={{ borderTop: '1px solid #30363d', background: '#0d1117', padding: '10px 14px', display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {expandedMessages.length === 0 && (
                      <div style={{ fontSize: 12, color: '#8b949e', fontStyle: 'italic' }}>No messages.</div>
                    )}
                    {expandedMessages.map(m => (
                      <div key={m.id} style={{
                        alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start',
                        maxWidth: '90%',
                        background: m.role === 'user' ? '#1f3a5f' : '#21262d',
                        border: `1px solid ${m.role === 'user' ? '#388bfd40' : '#30363d'}`,
                        borderRadius: 8,
                        padding: '6px 10px',
                        fontSize: 12,
                        color: '#c9d1d9',
                        lineHeight: 1.5,
                        whiteSpace: 'pre-wrap',
                        wordBreak: 'break-word',
                      }}>
                        {m.content}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
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
  flexShrink: 0,
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && npm run build 2>&1 | tail -10
```

Expected: no TypeScript errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/BrowserChatPage.tsx
git commit -m "feat(browser-chat): add BrowserChatPage component"
```

---

## Task 7: Wire routing + TopBar nav

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/TopBar.tsx`

- [ ] **Step 1: Add import and route in `frontend/src/App.tsx`**

Add the import alongside the other component imports at the top:

```typescript
import BrowserChatPage from './components/BrowserChatPage'
```

In the `Routes` block (inside the `authState === 'authenticated'` branch), add before the `*` catch-all:

```tsx
<Route path="/browser-chat" element={<BrowserChatPage />} />
```

- [ ] **Step 2: Add nav link in `frontend/src/components/TopBar.tsx`**

Add the `useMatch` after the existing `onAutomations` line:

```typescript
const onBrowserChat = useMatch({ path: '/browser-chat', end: true })
```

Add the nav link after the Automations `<Link>`:

```tsx
<Link
  to="/browser-chat"
  style={{
    padding: '4px 12px',
    borderRadius: 6,
    fontSize: 13,
    textDecoration: 'none',
    border: `1px solid ${onBrowserChat ? '#58a6ff' : '#30363d'}`,
    color: onBrowserChat ? '#58a6ff' : '#8b949e',
    background: onBrowserChat ? '#1f3a5f' : 'transparent',
  }}
>
  Browser
</Link>
```

- [ ] **Step 3: Start dev server and verify**

```bash
cd frontend && npm run dev
```

Open `http://localhost:5173`. The top bar should show Wiki | Files | Automations | Browser. Clicking **Browser** should navigate to `/browser-chat` and show the Connect screen.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.tsx frontend/src/components/TopBar.tsx
git commit -m "feat(browser-chat): add /browser-chat route and TopBar nav link"
```

---

## Task 8: End-to-end smoke test

- [ ] **Step 1: Start all services**

```bash
docker compose up --build -d
docker compose ps
```

Wait until all containers are healthy.

- [ ] **Step 2: Verify browser-agent is healthy**

```bash
curl http://localhost:8001/health
```

Expected: `{"status":"ok"}`

- [ ] **Step 3: Connect and send a message**

1. Open `http://localhost:5173/browser-chat`
2. Click **Connect** — button should change to "Connecting…" then the page should switch to the connected layout with the noVNC iframe.
3. Type: `Go to example.com and tell me the page title.`
4. Press ⌘↵ (or click Send).
5. The agent bubble should appear with "thinking…", then a reply.
6. The noVNC iframe should show Chromium navigating to example.com.

- [ ] **Step 4: Test the interrupt flow**

While the agent is working on a longer task (e.g. "search google for python tutorials"), click inside the noVNC iframe. The agent should acknowledge the interruption in its next reply.

- [ ] **Step 5: Disconnect**

Click **Disconnect**. The page returns to the idle state and the completed session appears in Past Sessions.

- [ ] **Step 6: Run full test suite**

```bash
make test-local
```

Expected: all tests pass.

- [ ] **Step 7: Final commit**

```bash
git add .
git commit -m "feat(browser-chat): complete browser chat — persistent sessions, interrupt flow, reaper, history"
```
