import json
import re
from pathlib import Path

import litellm
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.assistant_message import assistant_message_for_litellm
from app.agents.log_context import agent_run_context
from app.agents.prompt_render import render_system_prompt
from app.agents.tools import AgentTools
from app.config import settings
from app.sse import broadcaster


_PROMPTS = Path(__file__).parent / "prompts"
SYSTEM_PROMPT = (_PROMPTS / "edit.md").read_text()

EDIT_TOOLS = [
    "list_pages",
    "search_pages",
    "read_page",
    "write_page",
    "create_page",
    "move_page",
    "move_folder",
    "delete_page",
]


_log = structlog.get_logger()


async def run(
    workspace_id: str,
    question: str,
    history: list[dict],
    session: AsyncSession,
    audience_user_id: str,
    session_id: str = "",
) -> tuple[str, list[str]]:
    with agent_run_context(
        "edit_agent",
        workspace_id=workspace_id,
        audience_user_id=audience_user_id,
    ):
        _log.info("edit_agent_start", workspace_id=workspace_id)
        tools = AgentTools(
            session=session,
            workspace_id=workspace_id,
            broadcaster=broadcaster,
            context="chat",
            audience_user_id=audience_user_id,
        )
        tool_defs = tools.as_litellm_tools(allowed=EDIT_TOOLS)

        messages = [
            {"role": "system", "content": render_system_prompt(SYSTEM_PROMPT)},
            *history[-10:],
            {"role": "user", "content": question},
        ]

        touched_pages: list[str] = []

        for turn in range(20):
            _log.info("agent_llm_turn", turn=turn, max_turns=20)
            resp = await litellm.acompletion(
                model=settings.litellm_model,
                messages=messages,
                tools=tool_defs,
                tool_choice="auto",
                metadata={
                    "trace_name": "edit_agent",
                    "session_id": session_id or workspace_id,
                    "tags": ["chat", "edit"],
                },
            )
            turn_cost = 0.0
            try:
                turn_cost = litellm.completion_cost(resp) or 0.0
            except Exception:
                pass
            msg = resp.choices[0].message
            tool_calls = getattr(msg, "tool_calls", None) or []
            tool_names = [tc.function.name for tc in tool_calls]
            _log.info(
                "agent_llm_result",
                turn=turn,
                tool_calls=tool_names,
                turn_cost_usd=round(turn_cost, 4),
            )
            messages.append(assistant_message_for_litellm(msg))

            if not msg.tool_calls:
                answer = msg.content or ""
                touched_pages = re.findall(r"\[\[([^\]]+)\]\]", answer)
                _log.info("edit_agent_done", touched_pages=len(touched_pages))
                await broadcaster.publish(
                    {"event": "agent:done", "context": "chat", "pages_touched": touched_pages},
                    audience_user_id=audience_user_id,
                )
                return answer, touched_pages

            for tc in msg.tool_calls:
                name = tc.function.name
                args = json.loads(tc.function.arguments or "{}")
                result_str = await tools.dispatch(name, args)
                if name == "read_page":
                    touched_pages.append(args.get("slug", ""))
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result_str})

        _log.warning("edit_agent_no_result", workspace_id=workspace_id)
        await broadcaster.publish(
            {"event": "agent:done", "context": "chat", "pages_touched": touched_pages},
            audience_user_id=audience_user_id,
        )
        return "I wasn't able to complete the edit operation.", touched_pages
