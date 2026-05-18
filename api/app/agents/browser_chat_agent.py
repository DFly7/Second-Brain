import json
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
                    try:
                        result_str = await _dispatch(
                            name, args, browser_session_id, http,
                            wiki_tools, chat_session_id, audience_user_id,
                        )
                    except Exception as tool_exc:
                        result_str = f"Error: {tool_exc}"
                    tool_results.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result_str,
                    })
                messages.extend(tool_results)
            else:
                last_assistant = next(
                    (m.get("content") for m in reversed(messages) if isinstance(m, dict) and m.get("role") == "assistant"),
                    None,
                )
                if not last_assistant and messages:
                    last_msg = messages[-1]
                    last_assistant = last_msg.get("content") if isinstance(last_msg, dict) else getattr(last_msg, "content", None)
                reply_text = "I've reached my turn limit for this message. Here's where I got to: " + (last_assistant or "see browser.")

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
            label = args["selector"]
        elif args.get("text"):
            payload["text"] = args["text"]
            label = args["text"]
        else:
            return "Error: provide selector or text"
        resp = await http.post(f"/session/{browser_session_id}/click", json=payload)
        resp.raise_for_status()
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
        payload: dict = {}
        if args.get("selector"):
            payload["selector"] = args["selector"]
            label = args["selector"]
        elif args.get("text"):
            payload["text"] = args["text"]
            label = args["text"]
        else:
            return "Error: provide selector or text"
        if args.get("timeout"):
            payload["timeout"] = int(args["timeout"])
        resp = await http.post(f"/session/{browser_session_id}/wait_for", json=payload)
        resp.raise_for_status()
        data = resp.json()
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
