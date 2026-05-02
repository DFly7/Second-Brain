import json
from pathlib import Path

import litellm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.assistant_message import assistant_message_for_litellm
from app.agents.tools import AgentTools
from app.config import settings
from app.models import ActivityLog, ChatMessage, ChatSession
from app.sse import broadcaster

_PROMPTS = Path(__file__).parent / "prompts"
SYSTEM_PROMPT = (_PROMPTS / "chat_monitor.md").read_text()

MONITOR_THRESHOLD = 4


async def run(session_id: str, workspace_id: str, session: AsyncSession) -> None:
    # Load session for cursor
    session_result = await session.execute(
        select(ChatSession).where(ChatSession.id == session_id)
    )
    chat_session = session_result.scalar_one_or_none()
    if not chat_session:
        return

    # Fetch all messages then slice from cursor
    all_result = await session.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
    )
    all_messages = all_result.scalars().all()
    if not all_messages:
        return

    if chat_session.last_monitored_message_id:
        cursor_ids = [m.id for m in all_messages]
        try:
            cursor_idx = cursor_ids.index(chat_session.last_monitored_message_id)
            messages = all_messages[cursor_idx + 1:]
        except ValueError:
            messages = all_messages
    else:
        messages = all_messages

    if len(messages) < MONITOR_THRESHOLD:
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

    chat_session.last_monitored_message_id = messages[-1].id
    session.add(chat_session)
    if pages_saved:
        session.add(
            ActivityLog(
                workspace_id=workspace_id,
                event_type="chat_ingested",
                payload={"session_id": session_id, "pages_saved": pages_saved},
            )
        )
    await session.commit()
