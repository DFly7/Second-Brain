import json
from datetime import datetime
from pathlib import Path

import litellm

from app.agents.assistant_message import assistant_message_for_litellm
from app.agents.tools import AgentTools
from app.config import settings
from app.database import AsyncSessionLocal
from app.sse import broadcaster

COST_CEILING_USD = 2.0

_PROMPTS = Path(__file__).parent / "prompts"
SYSTEM_PROMPT = (_PROMPTS / "health.md").read_text()


async def run(workspace_id: str, audience_user_id: str) -> None:
    async with AsyncSessionLocal() as session:
        tools = AgentTools(
            session=session,
            workspace_id=workspace_id,
            broadcaster=broadcaster,
            audience_user_id=audience_user_id,
        )

        tool_names = ["list_pages", "search_pages", "read_page", "write_page", "create_page"]
        tool_defs = tools.as_litellm_tools(allowed=tool_names)

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Run a full health check on the wiki. Fix what you can, "
                    "then write meta/health-report."
                ),
            },
        ]

        total_cost = 0.0
        last_assistant_content = ""

        for _ in range(40):
            resp = await litellm.acompletion(
                model=settings.litellm_model,
                messages=messages,
                tools=tool_defs,
                tool_choice="auto",
            )
            try:
                total_cost += litellm.completion_cost(resp) or 0.0
            except Exception:
                pass
            if total_cost > COST_CEILING_USD:
                await tools.write_page(
                    "meta/health-report",
                    (
                        f"# Health Report\n\n_Run: {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} "
                        "| STOPPED: cost ceiling reached_\n\nPartial results above.\n"
                    ),
                    summary="Health check results",
                    title="Health Report",
                )
                break

            msg = resp.choices[0].message
            last_assistant_content = getattr(msg, "content", None) or ""
            messages.append(assistant_message_for_litellm(msg))

            if not msg.tool_calls:
                break

            for tc in msg.tool_calls:
                name = tc.function.name
                args = json.loads(tc.function.arguments or "{}")
                result_str = await tools.dispatch(name, args)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result_str})

        report = await tools.read_page("meta/health-report")
        if report.startswith("[Page 'meta/health-report' not found]"):
            body = (
                f"# Health Report\n\n{last_assistant_content.strip() or '_No detailed changes._'}\n"
            )
            await tools.write_page(
                "meta/health-report",
                body,
                summary="Health check results",
                title="Health Report",
            )

        await broadcaster.publish({"event": "health:done"}, audience_user_id=audience_user_id)
