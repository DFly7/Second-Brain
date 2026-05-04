import json
import re
from pathlib import Path

import litellm
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.assistant_message import assistant_message_for_litellm
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

    messages = [
        {"role": "system", "content": system_prompt},
        *history[-10:],  # last 10 messages for context
        {"role": "user", "content": question},
    ]

    cited_pages: list[str] = []

    for _ in range(10):
        resp = await litellm.acompletion(
            model=settings.litellm_model,
            messages=messages,
            tools=tool_defs,
            tool_choice="auto",
        )
        msg = resp.choices[0].message
        messages.append(assistant_message_for_litellm(msg))

        if not msg.tool_calls:
            answer = msg.content or ""
            cited_pages = re.findall(r"\[\[([^\]]+)\]\]", answer)
            _log.info("query_agent_answer", workspace_id=workspace_id, cited_pages=len(cited_pages))
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
