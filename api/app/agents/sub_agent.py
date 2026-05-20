import json
import uuid
from pathlib import Path

import litellm
import structlog

from app.agents.assistant_message import assistant_message_for_litellm
from app.agents.log_context import agent_run_context
from app.agents.prompt_render import render_system_prompt
from app.agents.tools import AgentTools
from app.config import settings
from app.database import AsyncSessionLocal

_PROMPTS = Path(__file__).parent / "prompts"
SYSTEM_PROMPT = (_PROMPTS / "sub_agent.md").read_text()

COST_CEILING_USD = 1.0

_log = structlog.get_logger()


async def run(
    source_id: str,
    workspace_id: str,
    page_start: int,
    page_end: int,
    focus_hint: str = "",
) -> str:
    with agent_run_context(
        "sub_agent",
        source_id=source_id,
        workspace_id=workspace_id,
        page_start=page_start,
        page_end=page_end,
    ):
        _log.info(
            "sub_agent_start",
            source_id=source_id,
            page_start=page_start,
            page_end=page_end,
        )
        async with AsyncSessionLocal() as session:
            tools = AgentTools(
                session=session,
                workspace_id=workspace_id,
                broadcaster=None,
                source_id=source_id,
            )
            tool_defs = tools.as_litellm_tools(allowed=["read_source_page"])

            messages = [
                {"role": "system", "content": render_system_prompt(SYSTEM_PROMPT)},
                {
                    "role": "user",
                    "content": (
                        f"Read pages {page_start} to {page_end} and summarise what you find."
                        + (f" Focus: {focus_hint}" if focus_hint else "")
                    ),
                },
            ]

            total_cost = 0.0
            trace_id = str(uuid.uuid4())
            for turn in range(50):
                _log.info("agent_llm_turn", turn=turn, max_turns=50)
                resp = await litellm.acompletion(
                    model=settings.litellm_model,
                    messages=messages,
                    tools=tool_defs,
                    tool_choice="auto",
                    metadata={
                        "trace_id": trace_id,
                        "trace_name": "sub_agent",
                        "session_id": source_id,
                        "tags": ["ingest", "sub-agent"],
                    },
                )
                try:
                    total_cost += litellm.completion_cost(resp) or 0.0
                except Exception:
                    pass
                if total_cost > COST_CEILING_USD:
                    _log.warning(
                        "sub_agent_cost_ceiling",
                        source_id=source_id,
                        cost_usd=round(total_cost, 4),
                    )
                    return "[Sub-agent reached cost ceiling]"

                msg = resp.choices[0].message
                tool_calls = getattr(msg, "tool_calls", None) or []
                tool_names = [tc.function.name for tc in tool_calls]
                _log.info(
                    "agent_llm_result",
                    turn=turn,
                    tool_calls=tool_names,
                    cumulative_cost_usd=round(total_cost, 4),
                )
                messages.append(assistant_message_for_litellm(msg))

                if not msg.tool_calls:
                    out = msg.content or ""
                    _log.info("sub_agent_done", source_id=source_id)
                    return out

                for tc in msg.tool_calls:
                    name = tc.function.name
                    args = json.loads(tc.function.arguments or "{}")
                    result = await tools.dispatch(name, args)
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

            _log.warning("sub_agent_incomplete", source_id=source_id)
            return "[Sub-agent did not complete]"
