import base64
import re
from datetime import datetime

import litellm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import ActivityLog, Page, Revision, SourcePage
from app.search import search_pages as _search
from app.sse import SSEBroadcaster
from app.storage import download_file
from app.wikilinks import sync_links


async def _ensure_vision_captions(page: SourcePage, session: AsyncSession) -> None:
    if page.vision_processed:
        return
    if not page.image_s3_keys or not settings.vision_model:
        return

    markdown = page.markdown

    for s3_key in page.image_s3_keys:
        basename = s3_key.rsplit("/", 1)[-1]
        original_filename = re.sub(r"^p\d+-", "", basename)

        try:
            img_bytes = download_file(s3_key)
            b64 = base64.b64encode(img_bytes).decode()
            ext = s3_key.rsplit(".", 1)[-1].lower()
            mime = {
                "png": "image/png",
                "jpg": "image/jpeg",
                "jpeg": "image/jpeg",
                "webp": "image/webp",
            }.get(ext, "image/png")
            resp = await litellm.acompletion(
                model=settings.vision_model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": f"Describe this image in the context of the surrounding document text:\n\n{markdown[:500]}",
                            },
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:{mime};base64,{b64}"},
                            },
                        ],
                    }
                ],
            )
            caption = resp.choices[0].message.content or ""
            caption_block = f"\n> **[AI-generated caption — {settings.vision_model}]** {caption}"
        except Exception:
            caption_block = (
                f"\n> **[AI-generated caption — {settings.vision_model}]**"
                f" *(caption unavailable — image: `{s3_key}`)*"
            )

        pattern = re.compile(
            r"(!\[.*?\]\([^)]*" + re.escape(original_filename) + r"[^)]*\))"
        )
        if pattern.search(markdown):
            markdown = pattern.sub(r"\1" + caption_block, markdown, count=1)
        else:
            markdown += caption_block

    page.markdown = markdown
    page.vision_processed = True
    session.add(page)
    await session.commit()


class AgentTools:
    def __init__(
        self,
        session: AsyncSession,
        workspace_id: str,
        broadcaster: SSEBroadcaster | None,
        source_id: str | None = None,
    ):
        self.session = session
        self.workspace_id = workspace_id
        self.broadcaster = broadcaster
        self.source_id = source_id

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

    async def list_source_pages(self) -> list[dict]:
        result = await self.session.execute(
            select(SourcePage)
            .where(SourcePage.source_id == self.source_id)
            .order_by(SourcePage.page_num)
        )
        pages = result.scalars().all()
        return [
            {
                "page_num": p.page_num,
                "has_images": bool(p.image_s3_keys),
                "preview": p.preview,
            }
            for p in pages
        ]

    async def read_source_page(self, page_num: int) -> str:
        result = await self.session.execute(
            select(SourcePage).where(
                SourcePage.source_id == self.source_id,
                SourcePage.page_num == page_num,
            )
        )
        page = result.scalar_one_or_none()
        if not page:
            return f"[Page {page_num} not found]"

        markdown = page.markdown

        if page.image_s3_keys and settings.vision_model:
            descriptions = []
            for s3_key in page.image_s3_keys:
                img_bytes = download_file(s3_key)
                b64 = base64.b64encode(img_bytes).decode()
                ext = s3_key.rsplit(".", 1)[-1].lower()
                mime = {
                    "png": "image/png",
                    "jpg": "image/jpeg",
                    "jpeg": "image/jpeg",
                    "webp": "image/webp",
                }.get(ext, "image/png")
                resp = await litellm.acompletion(
                    model=settings.vision_model,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": f"Describe this image in the context of the surrounding document text:\n\n{markdown[:500]}",
                                },
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:{mime};base64,{b64}"},
                                },
                            ],
                        }
                    ],
                )
                descriptions.append(resp.choices[0].message.content or "")
            for i, desc in enumerate(descriptions):
                markdown += f"\n\n> [Figure {i + 1}] {desc}"

        return markdown

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
            {
                "type": "function",
                "function": {
                    "name": "list_source_pages",
                    "description": "List all pages of the source document with a short preview and whether each has images. Call this first to understand document structure.",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "read_source_page",
                    "description": "Read the full markdown of a source document page. Pages with images include vision-model descriptions of figures inline.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "page_num": {
                                "type": "integer",
                                "description": "1-indexed page number",
                            }
                        },
                        "required": ["page_num"],
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
        if name == "list_source_pages":
            pages = await self.list_source_pages()
            return str(pages)
        if name == "read_source_page":
            return await self.read_source_page(args["page_num"])
        return f"Unknown tool: {name}"
