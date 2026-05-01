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


async def run(
    workspace_id: str,
    question: str,
    history: list[dict],
    session: AsyncSession,
) -> tuple[str, list[str]]:
    tools = AgentTools(session=session, workspace_id=workspace_id, broadcaster=broadcaster)
    tool_defs = tools.as_litellm_tools(allowed=EDIT_TOOLS)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *history[-10:],
        {"role": "user", "content": question},
    ]

    touched_pages: list[str] = []

    for _ in range(20):
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
            touched_pages = re.findall(r"\[\[([^\]]+)\]\]", answer)
            await broadcaster.publish({"event": "agent:done", "pages_touched": touched_pages})
            return answer, touched_pages

        for tc in msg.tool_calls:
            name = tc.function.name
            args = json.loads(tc.function.arguments or "{}")
            result_str = await tools.dispatch(name, args)
            if name == "read_page":
                touched_pages.append(args.get("slug", ""))
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result_str})

    await broadcaster.publish({"event": "agent:done", "pages_touched": touched_pages})
    return "I wasn't able to complete the edit operation.", touched_pages
