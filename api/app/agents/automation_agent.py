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
                    if current_status in ("stopped", "stopping"):
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
                    if run_obj.status in ("running", "stopping"):
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
