import json
import re
from pathlib import Path

import litellm
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.assistant_message import assistant_message_for_litellm
from app.agents.tools import AgentTools
from app.config import settings
from app.sse import broadcaster


_PROMPTS = Path(__file__).parent / "prompts"
SYSTEM_PROMPT = (_PROMPTS / "query.md").read_text()

READ_ONLY_TOOLS = ["list_pages", "search_pages", "read_page"]


async def run(
    workspace_id: str,
    question: str,
    history: list[dict],
    session: AsyncSession,
) -> tuple[str, list[str]]:
    tools = AgentTools(
        session=session, workspace_id=workspace_id, broadcaster=broadcaster, context="chat"
    )
    tool_defs = tools.as_litellm_tools(allowed=READ_ONLY_TOOLS)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
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
            await broadcaster.publish({"event": "agent:done", "pages_touched": cited_pages})
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

    await broadcaster.publish({"event": "agent:done", "pages_touched": cited_pages})
    return "I wasn't able to find a good answer in your wiki.", cited_pages
