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
            "name": "browser_get_page_state",
            "description": (
                "Get the current page URL, title, and a structured list of all visible interactive elements "
                "(buttons, links, inputs, selects) with their CSS selectors and text. "
                "Call this after navigating or whenever you need to know what you can click."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_click",
            "description": "Click an element on the page. Provide either a CSS selector or the visible text of the element.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector of element to click"},
                    "text": {"type": "string", "description": "Visible text of the element to click (alternative to selector)"},
                },
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
            "name": "browser_press_key",
            "description": "Press a keyboard key. Use for Enter (submit forms), Tab (move focus), Escape (close modals), arrow keys, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Playwright key name: Enter, Tab, Escape, ArrowDown, ArrowUp, ArrowLeft, ArrowRight, Backspace, Delete, Space, etc.",
                    }
                },
                "required": ["key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_focus",
            "description": "Focus a specific input element by CSS selector before typing into it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector of element to focus"}
                },
                "required": ["selector"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_hover",
            "description": "Hover over an element to reveal dropdown menus or tooltips.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector of element to hover over"}
                },
                "required": ["selector"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_select_option",
            "description": "Select an option from a <select> dropdown element.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector of the <select> element"},
                    "value": {"type": "string", "description": "The option value or label text to select"},
                },
                "required": ["selector", "value"],
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
            "name": "browser_wait_for",
            "description": "Wait for an element or text to appear on the page. Use after clicks or navigation on dynamic/SPA pages.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector to wait for"},
                    "text": {"type": "string", "description": "Text string to wait for in the page body (alternative to selector)"},
                    "timeout": {"type": "integer", "description": "Max wait in milliseconds (default 10000)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_read",
            "description": "Extract all visible text from the current page.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_execute_js",
            "description": "Execute a JavaScript expression in the page and return the result. Use as an escape hatch for interactions not possible with other tools.",
            "parameters": {
                "type": "object",
                "properties": {
                    "script": {"type": "string", "description": "JavaScript expression to evaluate (must return a serialisable value)"}
                },
                "required": ["script"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_screenshot",
            "description": "Take a screenshot and see the current browser view as an image. Use when you need to confirm visual state or are stuck.",
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

                max_turns = 50
                for turn in range(max_turns):
                    # Bypass SQLAlchemy identity map to catch stop signals from other requests.
                    session.expire_all()
                    status_result = await session.execute(
                        select(AutomationRun.status).where(AutomationRun.id == run_id)
                    )
                    current_status = status_result.scalar_one_or_none()
                    if current_status in ("stopped", "stopping"):
                        _log.info("automation_stopped_by_user", run_id=run_id)
                        final_status = "stopped"
                        break

                    turns_left = max_turns - turn
                    turn_messages = messages.copy()
                    if turns_left <= 10:
                        turn_messages[0] = {
                            **turn_messages[0],
                            "content": turn_messages[0]["content"] + f"\n\n⚠️ You have {turns_left} turns remaining. If you cannot complete the goal, summarise what you found and save any useful information to the wiki now.",
                        }

                    resp = await litellm.acompletion(
                        model=settings.litellm_model,
                        messages=turn_messages,
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
                        try:
                            result = await _dispatch(
                                name, args, browser_session_id, http,
                                wiki_tools, run_id, session, audience_user_id,
                            )
                        except Exception as tool_exc:
                            result = f"Error: {tool_exc}"
                        tool_results.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result,
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

                db_result = await session.execute(
                    select(AutomationRun).where(AutomationRun.id == run_id)
                )
                run_obj = db_result.scalar_one_or_none()
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
) -> str | list:
    _log.info("automation_tool_call", tool=name, run_id=run_id, args=args)
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

    if name == "browser_get_page_state":
        resp = await http.post(f"/session/{session_id}/get_page_state")
        resp.raise_for_status()
        data = resp.json()
        detail = f"Page state: {data.get('title', '')} ({data.get('url', '')})"
        await _record(db, run_id, "get_page_state", detail)
        await broadcaster.publish(
            {"event": "automation:action", "run_id": run_id, "type": "get_page_state", "detail": detail},
            audience_user_id=audience_user_id,
        )
        return json.dumps(data)

    if name == "browser_click":
        payload: dict = {}
        if args.get("selector"):
            payload["selector"] = args["selector"]
            detail = f"Clicked '{args['selector']}'"
        elif args.get("text"):
            payload["text"] = args["text"]
            detail = f"Clicked text '{args['text']}'"
        else:
            return "Error: provide selector or text"
        resp = await http.post(f"/session/{session_id}/click", json=payload)
        resp.raise_for_status()
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

    if name == "browser_press_key":
        key = args["key"]
        resp = await http.post(f"/session/{session_id}/press_key", json={"key": key})
        resp.raise_for_status()
        detail = f"Pressed key: {key}"
        await _record(db, run_id, "press_key", detail)
        await broadcaster.publish(
            {"event": "automation:action", "run_id": run_id, "type": "press_key", "detail": detail},
            audience_user_id=audience_user_id,
        )
        return "key pressed"

    if name == "browser_focus":
        selector = args["selector"]
        resp = await http.post(f"/session/{session_id}/focus", json={"selector": selector})
        resp.raise_for_status()
        detail = f"Focused '{selector}'"
        await _record(db, run_id, "focus", detail)
        await broadcaster.publish(
            {"event": "automation:action", "run_id": run_id, "type": "focus", "detail": detail},
            audience_user_id=audience_user_id,
        )
        return "focused"

    if name == "browser_hover":
        selector = args["selector"]
        resp = await http.post(f"/session/{session_id}/hover", json={"selector": selector})
        resp.raise_for_status()
        detail = f"Hovered over '{selector}'"
        await _record(db, run_id, "hover", detail)
        await broadcaster.publish(
            {"event": "automation:action", "run_id": run_id, "type": "hover", "detail": detail},
            audience_user_id=audience_user_id,
        )
        return "hovered"

    if name == "browser_select_option":
        selector = args["selector"]
        value = args["value"]
        resp = await http.post(f"/session/{session_id}/select_option", json={"selector": selector, "value": value})
        resp.raise_for_status()
        detail = f"Selected '{value}' in '{selector}'"
        await _record(db, run_id, "select_option", detail)
        await broadcaster.publish(
            {"event": "automation:action", "run_id": run_id, "type": "select_option", "detail": detail},
            audience_user_id=audience_user_id,
        )
        return f"selected: {resp.json().get('selected')}"

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

    if name == "browser_wait_for":
        payload: dict = {}
        if args.get("selector"):
            payload["selector"] = args["selector"]
            detail = f"Waited for '{args['selector']}'"
        elif args.get("text"):
            payload["text"] = args["text"]
            detail = f"Waited for text '{args['text']}'"
        else:
            return "Error: provide selector or text"
        if args.get("timeout"):
            payload["timeout"] = int(args["timeout"])
        resp = await http.post(f"/session/{session_id}/wait_for", json=payload)
        resp.raise_for_status()
        data = resp.json()
        await _record(db, run_id, "wait_for", detail)
        await broadcaster.publish(
            {"event": "automation:action", "run_id": run_id, "type": "wait_for", "detail": detail},
            audience_user_id=audience_user_id,
        )
        if not data.get("found"):
            return data.get("error", "element not found")
        return "found"

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

    if name == "browser_execute_js":
        script = args["script"]
        resp = await http.post(f"/session/{session_id}/execute_js", json={"script": script})
        resp.raise_for_status()
        js_result = resp.json().get("result")
        detail = f"Executed JS: {script[:60]}{'…' if len(script) > 60 else ''}"
        await _record(db, run_id, "execute_js", detail)
        await broadcaster.publish(
            {"event": "automation:action", "run_id": run_id, "type": "execute_js", "detail": detail},
            audience_user_id=audience_user_id,
        )
        return json.dumps(js_result)

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
        # Return image content block so the LLM can actually see the screenshot.
        return [
            {"type": "text", "text": "Here is the current browser screenshot:"},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
        ]

    # Wiki tools
    wiki_result = await wiki_tools.dispatch(name, args)
    if name in ("write_page", "create_page", "append_to_page"):
        slug = args.get("slug", "")
        detail = f"Wrote wiki page: {slug}"
        await _record(db, run_id, "wiki_write", detail)
        await broadcaster.publish(
            {"event": "automation:action", "run_id": run_id, "type": "wiki_write", "detail": detail},
            audience_user_id=audience_user_id,
        )
    return wiki_result


async def _record(db: AsyncSession, run_id: str, type_: str, detail: str) -> None:
    db.add(AutomationAction(run_id=run_id, type=type_, detail=detail))
    await db.commit()
