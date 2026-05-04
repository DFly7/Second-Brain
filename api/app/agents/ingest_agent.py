import asyncio
import json
from pathlib import Path

import litellm
import structlog
from sqlalchemy import select

from app.agents.assistant_message import assistant_message_for_litellm
from app.agents.log_context import agent_run_context
from app.agents.prompt_render import render_system_prompt
from app.agents.tools import AgentTools
from app.agents import sub_agent
from app.config import settings
from app.database import AsyncSessionLocal
from app.models import ActivityLog, Source, SourcePage
from app.sse import broadcaster

_log = structlog.get_logger()

SMALL_DOC_THRESHOLD = 20
COST_CEILING_USD = 2.0

_PROMPTS = Path(__file__).parent / "prompts"
SYSTEM_PROMPT_SMALL = (_PROMPTS / "ingest_small.md").read_text()
SYSTEM_PROMPT_LARGE = (_PROMPTS / "ingest_large.md").read_text()

SPAWN_PAGE_READER_TOOL = {
    "type": "function",
    "function": {
        "name": "spawn_page_reader",
        "description": (
            "Spawn a sub-agent to read and summarise a page range concurrently. "
            "Call multiple times in the SAME response to process sections in parallel."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "page_start": {"type": "integer", "description": "First page (1-indexed)"},
                "page_end": {"type": "integer", "description": "Last page (inclusive)"},
                "focus_hint": {"type": "string", "description": "What to focus on"},
            },
            "required": ["page_start", "page_end"],
        },
    },
}


async def run(source_id: str, workspace_id: str, audience_user_id: str):
    with agent_run_context(
        "ingest_agent",
        source_id=source_id,
        workspace_id=workspace_id,
        audience_user_id=audience_user_id,
    ):
        _log.info("ingest_agent_start", source_id=source_id, workspace_id=workspace_id)
        async with AsyncSessionLocal() as session:
            src_result = await session.execute(select(Source).where(Source.id == source_id))
            source = src_result.scalar_one_or_none()
            if not source:
                _log.warning(
                    "ingest_agent_source_missing",
                    source_id=source_id,
                    workspace_id=workspace_id,
                )
                return

            pages_result = await session.execute(
                select(SourcePage)
                .where(SourcePage.source_id == source_id)
                .order_by(SourcePage.page_num)
            )
            pages = pages_result.scalars().all()
            page_count = len(pages)

            is_large = page_count > SMALL_DOC_THRESHOLD

            tools = AgentTools(
                session=session,
                workspace_id=workspace_id,
                broadcaster=broadcaster,
                source_id=source_id,
                audience_user_id=audience_user_id,
            )

            wiki_tool_names = ["list_pages", "search_pages", "read_page", "write_page", "create_page"]
            source_tool_names = ["list_source_pages", "read_source_page"]

            if is_large:
                tool_defs = tools.as_litellm_tools(allowed=wiki_tool_names + ["list_source_pages"])
                tool_defs.append(SPAWN_PAGE_READER_TOOL)
                system_prompt = render_system_prompt(SYSTEM_PROMPT_LARGE)
            else:
                tool_defs = tools.as_litellm_tools(allowed=wiki_tool_names + source_tool_names)
                system_prompt = render_system_prompt(SYSTEM_PROMPT_SMALL)

            messages = [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"Integrate the source document "
                        f"(source_id={source_id}, {page_count} pages) into the wiki."
                    ),
                },
            ]

            total_cost = 0.0
            pages_touched: list[str] = []

            for turn in range(30):
                _log.info("agent_llm_turn", turn=turn, max_turns=30)
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
                    _log.warning(
                        "ingest_agent_cost_ceiling_hit",
                        source_id=source_id,
                        cost_usd=round(total_cost, 4),
                    )
                    break

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
                    break

                spawn_calls = [tc for tc in msg.tool_calls if tc.function.name == "spawn_page_reader"]
                other_calls = [tc for tc in msg.tool_calls if tc.function.name != "spawn_page_reader"]

                if spawn_calls:
                    spawn_ranges = [
                        {
                            "page_start": json.loads(tc.function.arguments)["page_start"],
                            "page_end": json.loads(tc.function.arguments)["page_end"],
                        }
                        for tc in spawn_calls
                    ]
                    _log.info(
                        "ingest_spawn_parallel",
                        count=len(spawn_calls),
                        ranges=spawn_ranges,
                    )
                    tasks = [
                        sub_agent.run(
                            source_id=source_id,
                            workspace_id=workspace_id,
                            page_start=json.loads(tc.function.arguments)["page_start"],
                            page_end=json.loads(tc.function.arguments)["page_end"],
                            focus_hint=json.loads(tc.function.arguments).get("focus_hint", ""),
                        )
                        for tc in spawn_calls
                    ]
                    results = await asyncio.gather(*tasks)
                    for tc, result in zip(spawn_calls, results):
                        messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

                for tc in other_calls:
                    name = tc.function.name
                    args = json.loads(tc.function.arguments or "{}")
                    result_str = await tools.dispatch(name, args)
                    if name in ("write_page", "create_page") and "slug" in args:
                        pages_touched.append(args["slug"])
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": result_str})

            session.add(
                ActivityLog(
                    workspace_id=workspace_id,
                    event_type="source_ingested",
                    payload={
                        "source_id": source_id,
                        "pages_touched": pages_touched,
                        "cost_usd": round(total_cost, 4),
                        "page_count": page_count,
                    },
                )
            )
            await session.commit()
            _log.info(
                "ingest_agent_done",
                source_id=source_id,
                workspace_id=workspace_id,
                pages_touched=len(pages_touched),
                cost_usd=round(total_cost, 4),
            )
            await broadcaster.publish(
                {"event": "agent:done", "pages_touched": pages_touched, "source_id": source_id},
                audience_user_id=audience_user_id,
            )
