import json

import litellm
from sqlalchemy import select

from app.agents.tools import AgentTools
from app.config import settings
from app.database import AsyncSessionLocal
from app.models import ActivityLog, Source
from app.sse import broadcaster

SYSTEM_PROMPT = """You are an agent that maintains a personal knowledge wiki.
You have been given a new source document. Your job is to integrate its knowledge into the wiki.

Process:
1. Call list_pages() to see what exists.
2. Call search_pages() to find pages related to the source content.
3. Read the most relevant pages with read_page().
4. Decide: does this content belong in an existing page, or does it need a new page?
   - Update an existing page if the source adds to, refines, or contradicts something already there.
   - Create a new page if the topic has no home yet, or if the content is substantial enough to stand alone.
   - Prefer updating over creating — a wiki with 50 developed pages beats 200 stubs.
5. Write changes using write_page(). You may update multiple pages.
6. When done, stop calling tools.

Write in clear markdown. Use [[wikilinks]] to link related pages. Keep summaries to one sentence."""

COST_CEILING_USD = 2.0


async def run(source_id: str, workspace_id: str):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Source).where(Source.id == source_id))
        source = result.scalar_one_or_none()
        if not source:
            return

        tools = AgentTools(
            session=session, workspace_id=workspace_id, broadcaster=broadcaster
        )
        tool_defs = tools.as_litellm_tools()

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"New source to integrate:\n\n{source.extracted_text[:12000]}",
            },
        ]

        total_cost = 0.0
        pages_touched: list[str] = []

        for _ in range(20):  # max iterations
            resp = await litellm.acompletion(
                model=settings.litellm_model,
                messages=messages,
                tools=tool_defs,
                tool_choice="auto",
            )
            # litellm 1.52.0 returns cost via completion_cost(ModelResponse)
            total_cost += litellm.completion_cost(resp) or 0.0
            if total_cost > COST_CEILING_USD:
                break

            msg = resp.choices[0].message
            messages.append(msg.model_dump(exclude_none=True))

            if not msg.tool_calls:
                break

            for tc in msg.tool_calls:
                name = tc.function.name
                args = json.loads(tc.function.arguments)
                result_str = await tools.dispatch(name, args)
                if name in ("write_page", "create_page") and "slug" in args:
                    pages_touched.append(args["slug"])
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result_str,
                    }
                )

        session.add(
            ActivityLog(
                workspace_id=workspace_id,
                event_type="source_ingested",
                payload={
                    "source_id": source_id,
                    "pages_touched": pages_touched,
                    "cost_usd": round(total_cost, 4),
                },
            )
        )
        await session.commit()
        await broadcaster.publish(
            {"event": "agent:done", "pages_touched": pages_touched}
        )
