from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActivityLog, Page, Revision
from app.search import search_pages as _search
from app.sse import SSEBroadcaster
from app.wikilinks import sync_links


class AgentTools:
    def __init__(
        self, session: AsyncSession, workspace_id: str, broadcaster: SSEBroadcaster | None
    ):
        self.session = session
        self.workspace_id = workspace_id
        self.broadcaster = broadcaster

    async def _broadcast(self, event: dict):
        if self.broadcaster:
            await self.broadcaster.publish(event)

    async def list_pages(self) -> list[dict]:
        result = await self.session.execute(
            select(Page.slug, Page.title, Page.summary)
            .where(Page.workspace_id == self.workspace_id)
            .order_by(Page.updated_at.desc())
        )
        rows = result.mappings().all()
        return [
            {"slug": row["slug"], "title": row["title"], "summary": row["summary"]}
            for row in rows
        ]

    async def search_pages(self, query: str) -> list[dict]:
        return await _search(self.session, self.workspace_id, query, limit=5)

    async def read_page(self, slug: str) -> str:
        await self._broadcast({"event": "agent:reading", "slug": slug})
        result = await self.session.execute(
            select(Page).where(Page.slug == slug, Page.workspace_id == self.workspace_id)
        )
        page = result.scalar_one_or_none()
        return page.body_md if page else f"[Page '{slug}' not found]"

    async def write_page(
        self, slug: str, body_md: str, summary: str = "", title: str | None = None
    ) -> str:
        await self._broadcast({"event": "agent:writing", "slug": slug})
        result = await self.session.execute(
            select(Page).where(Page.slug == slug, Page.workspace_id == self.workspace_id)
        )
        page = result.scalar_one_or_none()
        if page:
            self.session.add(Revision(page_id=page.id, body_md=page.body_md))
            page.body_md = body_md
            if title:
                page.title = title
            page.summary = summary or page.summary
            page.updated_at = datetime.utcnow()
            await sync_links(self.session, page)
            self.session.add(
                ActivityLog(
                    workspace_id=self.workspace_id,
                    event_type="page_updated",
                    payload={"slug": slug},
                )
            )
        else:
            page = Page(
                workspace_id=self.workspace_id,
                slug=slug,
                title=title or slug.replace("-", " ").title(),
                body_md=body_md,
                summary=summary,
            )
            self.session.add(page)
            await self.session.flush()
            await sync_links(self.session, page)
            self.session.add(
                ActivityLog(
                    workspace_id=self.workspace_id,
                    event_type="page_created",
                    payload={"slug": slug},
                )
            )
        await self.session.commit()
        return f"Page '{slug}' saved."

    async def create_page(
        self, slug: str, title: str, body_md: str, summary: str = ""
    ) -> str:
        return await self.write_page(slug, body_md, summary, title=title)

    def as_litellm_tools(self, allowed: list[str] | None = None) -> list[dict]:
        all_tools = [
            {
                "type": "function",
                "function": {
                    "name": "list_pages",
                    "description": "List all pages in the wiki with their slugs, titles, and summaries.",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "search_pages",
                    "description": "Search wiki pages by query using hybrid full-text + semantic search.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search query",
                            }
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "read_page",
                    "description": "Read the full markdown content of a wiki page by slug.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "slug": {"type": "string", "description": "Page slug"}
                        },
                        "required": ["slug"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "write_page",
                    "description": "Create or update a wiki page. Creates if slug doesn't exist, updates if it does.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "slug": {"type": "string"},
                            "body_md": {"type": "string", "description": "Full markdown content"},
                            "summary": {
                                "type": "string",
                                "description": "One-sentence summary",
                            },
                        },
                        "required": ["slug", "body_md"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "create_page",
                    "description": "Create a new wiki page.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "slug": {"type": "string"},
                            "title": {"type": "string"},
                            "body_md": {"type": "string"},
                            "summary": {"type": "string"},
                        },
                        "required": ["slug", "title", "body_md"],
                    },
                },
            },
        ]
        if allowed:
            return [t for t in all_tools if t["function"]["name"] in allowed]
        return all_tools

    async def dispatch(self, name: str, args: dict) -> str:
        if name == "list_pages":
            pages = await self.list_pages()
            return str(pages)
        if name == "search_pages":
            results = await self.search_pages(args["query"])
            return str(results)
        if name == "read_page":
            return await self.read_page(args["slug"])
        if name == "write_page":
            return await self.write_page(
                args["slug"], args["body_md"], args.get("summary", "")
            )
        if name == "create_page":
            return await self.create_page(
                args["slug"],
                args["title"],
                args["body_md"],
                args.get("summary", ""),
            )
        return f"Unknown tool: {name}"
