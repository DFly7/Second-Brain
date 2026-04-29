import json
from datetime import datetime

import litellm

from app.agents.assistant_message import assistant_message_for_litellm
from app.agents.tools import AgentTools
from app.config import settings
from app.database import AsyncSessionLocal
from app.sse import broadcaster

COST_CEILING_USD = 2.0

SYSTEM_PROMPT = """You are a wiki health agent. Your job is to fix and report issues in the wiki.

Run these steps in order:

1. Call list_pages() to get all pages.
2. Call read_page("meta/index") to load the current index.
3. Regenerate meta/index from scratch using write_page("meta/index", ...) with all pages grouped
   by folder (slug prefix). Format:
     ## people/ (N pages)
     - [[people/alice]] — one-line summary
4. For each page (sample up to 20 if large wiki):
   a. Call read_page(slug) to read its content.
   b. Find [[wikilinks]] that reference slugs not in the page list — these are broken links.
   c. If you can identify the correct target page, fix the link with write_page().
   d. Find plain-text mentions of other page titles/slugs not wrapped in [[]] — add wikilinks.
5. Identify orphan pages: pages that appear in list_pages() but are not linked from any other page.
   Do NOT delete them — just note them.
6. Write meta/health-report with two sections:
   ## Fixed
   - list every patch made (what was broken, what you changed)
   ## Needs attention
   - orphan pages with suggested actions
   - broken links you could not resolve
   - any contradictions or gaps you noticed

Be thorough but do not invent facts. Only fix what you are confident about."""


async def run(workspace_id: str) -> None:
    async with AsyncSessionLocal() as session:
        tools = AgentTools(
            session=session,
            workspace_id=workspace_id,
            broadcaster=broadcaster,
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
            total_cost += litellm.completion_cost(resp) or 0.0
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

        await broadcaster.publish({"event": "health:done"})
