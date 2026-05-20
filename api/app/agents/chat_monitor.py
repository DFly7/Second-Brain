import json
import uuid
from datetime import date as _date
from pathlib import Path

import litellm
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.assistant_message import assistant_message_for_litellm
from app.agents.log_context import agent_run_context
from app.agents.prompt_render import render_system_prompt
from app.agents.tools import AgentTools
from app.config import settings
from app.models import ActivityLog, ChatMessage, ChatSession
from app.sse import broadcaster

_PROMPTS = Path(__file__).parent / "prompts"
SYSTEM_PROMPT = (_PROMPTS / "chat_monitor.md").read_text()

MONITOR_THRESHOLD = 4

_log = structlog.get_logger()


async def run(
    session_id: str, workspace_id: str, session: AsyncSession, audience_user_id: str
) -> None:
    with agent_run_context(
        "chat_monitor",
        session_id=session_id,
        workspace_id=workspace_id,
        audience_user_id=audience_user_id,
    ):
        session_result = await session.execute(
            select(ChatSession).where(ChatSession.id == session_id)
        )
        chat_session = session_result.scalar_one_or_none()
        if not chat_session:
            _log.info("chat_monitor_skip", reason="session_not_found", session_id=session_id)
            return

        all_result = await session.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at)
        )
        all_messages = all_result.scalars().all()
        if not all_messages:
            _log.info("chat_monitor_skip", reason="no_messages", session_id=session_id)
            return

        if chat_session.last_monitored_message_id:
            cursor_ids = [m.id for m in all_messages]
            try:
                cursor_idx = cursor_ids.index(chat_session.last_monitored_message_id)
                messages = all_messages[cursor_idx + 1 :]
            except ValueError:
                messages = all_messages
        else:
            messages = all_messages

        if len(messages) < MONITOR_THRESHOLD:
            _log.info(
                "chat_monitor_skip",
                reason="below_threshold",
                session_id=session_id,
                message_count=len(messages),
            )
            return

        _log.info(
            "chat_monitor_start",
            session_id=session_id,
            workspace_id=workspace_id,
            messages_to_review=len(messages),
        )

        transcript = "\n".join(f"{m.role.upper()}: {m.content}" for m in messages)

        tools_obj = AgentTools(
            session=session,
            workspace_id=workspace_id,
            broadcaster=broadcaster,
            audience_user_id=audience_user_id,
        )
        tool_defs = tools_obj.as_litellm_tools()

        today = _date.today().isoformat()
        llm_messages = [
            {"role": "system", "content": render_system_prompt(SYSTEM_PROMPT)},
            {
                "role": "user",
                "content": (
                    f"Session ID: {session_id}\n"
                    f"Date: {today}\n\n"
                    f"New messages to review:\n\n{transcript[:8000]}"
                ),
            },
        ]

        pages_saved = []
        trace_id = str(uuid.uuid4())

        for turn in range(10):
            _log.info("agent_llm_turn", turn=turn, max_turns=10)
            resp = await litellm.acompletion(
                model=settings.litellm_model,
                messages=llm_messages,
                tools=tool_defs,
                tool_choice="auto",
                metadata={
                    "trace_id": trace_id,
                    "trace_name": "chat_monitor",
                    "session_id": session_id,
                    "tags": ["chat", "monitor"],
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
        _log.info(
            "chat_monitor_done",
            session_id=session_id,
            pages_saved=len(pages_saved),
        )
