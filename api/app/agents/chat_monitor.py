import json

import litellm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.assistant_message import assistant_message_for_litellm
from app.agents.tools import AgentTools
from app.config import settings
from app.models import ActivityLog, ChatMessage
from app.sse import broadcaster

SYSTEM_PROMPT = """You are a background agent that reads chat transcripts and decides what to save to the user's wiki.

Review the conversation and identify anything worth retaining permanently:
- Decisions made ("I decided to...", "We agreed that...")
- Facts learned or confirmed
- Ideas worth developing
- Commitments or plans
- Insights or realisations

Do NOT ingest casual back-and-forth, clarifying questions, or content already well-covered in the wiki.

If you find something worth saving:
1. Use search_pages() to check if it already exists.
2. Use write_page() to add it to an existing page, or create a new one.

If nothing in the conversation is worth saving, do nothing."""


async def run(session_id: str, workspace_id: str, session: AsyncSession) -> None:
    result = await session.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
    )
    messages = result.scalars().all()
    if not messages:
        return

    transcript = "\n".join(f"{m.role.upper()}: {m.content}" for m in messages)

    tools_obj = AgentTools(session=session, workspace_id=workspace_id, broadcaster=broadcaster)
    tool_defs = tools_obj.as_litellm_tools()

    llm_messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Chat transcript to review:\n\n{transcript[:8000]}"},
    ]

    pages_saved = []

    for _ in range(10):
        resp = await litellm.acompletion(
            model=settings.litellm_model,
            messages=llm_messages,
            tools=tool_defs,
            tool_choice="auto",
        )
        msg = resp.choices[0].message
        llm_messages.append(assistant_message_for_litellm(msg))

        if not msg.tool_calls:
            break

        for tc in msg.tool_calls:
            name = tc.function.name
            args = json.loads(tc.function.arguments or "{}")
            result_str = await tools_obj.dispatch(name, args)
            if name in ("write_page", "create_page"):
                pages_saved.append(args.get("slug", ""))
            llm_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_str,
                }
            )

    if pages_saved:
        session.add(
            ActivityLog(
                workspace_id=workspace_id,
                event_type="chat_ingested",
                payload={"session_id": session_id, "pages_saved": pages_saved},
            )
        )
        await session.commit()
