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
SYSTEM_PROMPT = (_PROMPTS / "query.md").read_text()

READ_ONLY_TOOLS = ["list_pages", "search_pages", "read_page", "grep_page"]

_log = structlog.get_logger()


async def run(
    workspace_id: str,
    question: str,
    history: list[dict],
    session: AsyncSession,
    audience_user_id: str,
) -> tuple[str, list[str]]:
    with agent_run_context(
        "query_agent",
        workspace_id=workspace_id,
        audience_user_id=audience_user_id,
    ):
        _log.info("query_agent_start", workspace_id=workspace_id)
        tools = AgentTools(
            session=session,
            workspace_id=workspace_id,
            broadcaster=broadcaster,
            context="chat",
            audience_user_id=audience_user_id,
        )
        tool_defs = tools.as_litellm_tools(allowed=READ_ONLY_TOOLS)

        user_memory = await tools.read_page("system/memory")
        if user_memory.startswith("[Page 'system/memory' not found]"):
            system_prompt = SYSTEM_PROMPT
        else:
            system_prompt = f"<user_context>\n{user_memory}\n</user_context>\n\n{SYSTEM_PROMPT}"

        system_prompt = render_system_prompt(
            system_prompt, model=settings.litellm_model
        )

        messages = [
            {"role": "system", "content": system_prompt},
            *history[-10:],  # last 10 messages for context
            {"role": "user", "content": question},
        ]

        cited_pages: list[str] = []

        for turn in range(10):
            _log.info("agent_llm_turn", turn=turn, max_turns=10)
            resp = await litellm.acompletion(
                model=settings.litellm_model,
                messages=messages,
                tools=tool_defs,
                tool_choice="auto",
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
                cited_pages = re.findall(r"\[\[([^\]]+)\]\]", answer)
                _log.info(
                    "query_agent_answer",
                    workspace_id=workspace_id,
                    cited_pages=len(cited_pages),
                )
                await broadcaster.publish(
                    {"event": "agent:done", "context": "chat", "pages_touched": cited_pages},
                    audience_user_id=audience_user_id,
                )
                return answer, cited_pages

            for tc in msg.tool_calls:
                name = tc.function.name
                args = json.loads(tc.function.arguments or "{}")
                result_str = await tools.dispatch(name, args)
                if name == "read_page":
                    cited_pages.append(args.get("slug", ""))
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result_str,
                    }
                )

        _log.warning("query_agent_no_answer", workspace_id=workspace_id)
        await broadcaster.publish(
            {"event": "agent:done", "context": "chat", "pages_touched": cited_pages},
            audience_user_id=audience_user_id,
        )
        return "I wasn't able to find a good answer in your wiki.", cited_pages
