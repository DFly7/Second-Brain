import json
import re

import litellm
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.assistant_message import assistant_message_for_litellm
from app.agents.tools import AgentTools
from app.config import settings
from app.sse import broadcaster


SYSTEM_PROMPT = """You are a knowledgeable assistant with access to the user's personal wiki.
When answering questions:
1. Call read_page("meta/index") first to see the full wiki structure and find relevant pages.
2. Use search_pages() to narrow down if needed.
3. Use read_page() to read up to 5 of the most relevant pages in full.
4. Answer based on what you find. Cite pages using their full slug: [[people/alice-jones]].
5. If the wiki doesn't contain the answer, say so clearly.
You may only read pages — do not write or create anything."""

READ_ONLY_TOOLS = ["list_pages", "search_pages", "read_page"]


async def run(
    workspace_id: str,
    question: str,
    history: list[dict],
    session: AsyncSession,
) -> tuple[str, list[str]]:
    tools = AgentTools(session=session, workspace_id=workspace_id, broadcaster=broadcaster)
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
