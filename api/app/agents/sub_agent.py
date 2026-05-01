import json
from pathlib import Path

import litellm

from app.agents.assistant_message import assistant_message_for_litellm
from app.agents.tools import AgentTools
from app.config import settings
from app.database import AsyncSessionLocal

_PROMPTS = Path(__file__).parent / "prompts"
SYSTEM_PROMPT = (_PROMPTS / "sub_agent.md").read_text()

COST_CEILING_USD = 1.0


async def run(
    source_id: str,
    workspace_id: str,
    page_start: int,
    page_end: int,
    focus_hint: str = "",
) -> str:
    async with AsyncSessionLocal() as session:
        tools = AgentTools(
            session=session,
            workspace_id=workspace_id,
            broadcaster=None,
            source_id=source_id,
        )
        tool_defs = tools.as_litellm_tools(allowed=["read_source_page"])

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Read pages {page_start} to {page_end} and summarise what you find."
                    + (f" Focus: {focus_hint}" if focus_hint else "")
                ),
            },
        ]

        total_cost = 0.0
        for _ in range(50):
            resp = await litellm.acompletion(
                model=settings.litellm_model,
                messages=messages,
                tools=tool_defs,
                tool_choice="auto",
            )
            total_cost += litellm.completion_cost(resp) or 0.0
            if total_cost > COST_CEILING_USD:
                return "[Sub-agent reached cost ceiling]"

            msg = resp.choices[0].message
            messages.append(assistant_message_for_litellm(msg))

            if not msg.tool_calls:
                return msg.content or ""

            for tc in msg.tool_calls:
                name = tc.function.name
                args = json.loads(tc.function.arguments or "{}")
                result = await tools.dispatch(name, args)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

    return "[Sub-agent did not complete]"
