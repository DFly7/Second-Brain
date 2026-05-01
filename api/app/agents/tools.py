import base64
import re
from datetime import datetime
from pathlib import Path

from jinja2 import Template
import litellm
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import ActivityLog, Page, PageLink, Revision, SourcePage
from app.search import search_pages as _search
from app.sse import SSEBroadcaster
from app.storage import download_file
from app.wikilinks import sync_links

_PROMPTS = Path(__file__).parent / "prompts"
_VISION_CAPTION_TEMPLATE = Template((_PROMPTS / "vision_caption.md").read_text())
_VISION_DESCRIBE_PROMPT = (_PROMPTS / "vision_describe.md").read_text()

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*(/[a-z0-9][a-z0-9-]*)+$")
_FOLDER_RE = re.compile(r"^[a-z0-9][a-z0-9-]*(/[a-z0-9][a-z0-9-]*)*$")


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
                                "text": _VISION_CAPTION_TEMPLATE.render(context=markdown[:500]),
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
            markdown = pattern.sub(lambda m: m.group(1) + caption_block, markdown, count=1)
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
        await self.session.refresh(page)
        await self.update_index(slug, page.title, page.summary)
        return f"Page '{slug}' saved."

    async def create_page(
        self, slug: str, title: str, body_md: str, summary: str = ""
    ) -> str:
        return await self.write_page(slug, body_md, summary, title=title)

    async def update_index(self, slug: str, title: str, summary: str) -> None:
        """Patch meta/index with the entry for the given page. No-op for meta/index itself."""
        if slug == "meta/index":
            return

        folder = (slug.rsplit("/", 1)[0] + "/") if "/" in slug else "misc/"
        entry_line = f"- [[{slug}]] — {summary or title}"

        raw = await self.read_page("meta/index")
        if raw.startswith("[Page 'meta/index' not found]"):
            raw = "# Wiki Index\n\n"

        # Parse existing sections into dict[folder_header -> list[entry_line]]
        sections: dict[str, list[str]] = {}
        current_folder: str | None = None
        preamble: list[str] = []
        in_preamble = True

        for line in raw.split("\n"):
            m = re.match(r"^## (.+?)\s*\(\d+ pages?\)$", line)
            if m:
                in_preamble = False
                current_folder = m.group(1)
                if current_folder not in sections:
                    sections[current_folder] = []
            elif in_preamble:
                preamble.append(line)
            elif current_folder is not None and line.startswith("- [["):
                sections[current_folder].append(line)

        # Update or add entry for this slug
        if folder not in sections:
            sections[folder] = []
        sections[folder] = sorted(
            [e for e in sections[folder] if not e.startswith(f"- [[{slug}]]")]
            + [entry_line]
        )

        # Rebuild body — meta/ section always last
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        lines: list[str] = [f"# Wiki Index", "", f"_Last updated: {date_str}_", ""]
        for f in sorted(sections.keys(), key=lambda x: (x == "meta/", x)):
            lines.append(f"## {f} ({len(sections[f])} pages)")
            lines.extend(sections[f])
            lines.append("")

        await self.write_page(
            "meta/index",
            "\n".join(lines),
            summary="Wiki table of contents",
            title="Index",
        )

    async def _remove_from_index(self, slug: str) -> None:
        raw = await self.read_page("meta/index")
        if raw.startswith("[Page 'meta/index' not found]"):
            return

        sections: dict[str, list[str]] = {}
        current_folder: str | None = None
        in_preamble = True

        for line in raw.split("\n"):
            m = re.match(r"^## (.+?)\s*\(\d+ pages?\)$", line)
            if m:
                in_preamble = False
                current_folder = m.group(1)
                if current_folder not in sections:
                    sections[current_folder] = []
            elif not in_preamble and current_folder is not None and line.startswith("- [["):
                sections[current_folder].append(line)

        folder = (slug.rsplit("/", 1)[0] + "/") if "/" in slug else "misc/"
        if folder in sections:
            sections[folder] = [e for e in sections[folder] if not e.startswith(f"- [[{slug}]]")]

        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        lines: list[str] = ["# Wiki Index", "", f"_Last updated: {date_str}_", ""]
        for f in sorted(sections.keys(), key=lambda x: (x == "meta/", x)):
            if sections[f]:
                lines.append(f"## {f} ({len(sections[f])} pages)")
                lines.extend(sections[f])
                lines.append("")

        await self.write_page(
            "meta/index", "\n".join(lines), summary="Wiki table of contents", title="Index"
        )

    async def _do_move_page(self, old_slug: str, new_slug: str) -> None:
        result = await self.session.execute(
            select(Page).where(Page.slug == new_slug, Page.workspace_id == self.workspace_id)
        )
        if result.scalar_one_or_none() is not None:
            raise ValueError(f"Destination slug '{new_slug}' already exists.")

        result = await self.session.execute(
            select(Page).where(Page.slug == old_slug, Page.workspace_id == self.workspace_id)
        )
        old_page = result.scalar_one_or_none()
        if old_page is None:
            raise ValueError(f"Page '{old_slug}' not found.")

        await self.write_page(new_slug, old_page.body_md, old_page.summary, title=old_page.title)

        result = await self.session.execute(select(PageLink).where(PageLink.to_page_id == old_page.id))
        incoming_links = result.scalars().all()
        for link in incoming_links:
            result = await self.session.execute(select(Page).where(Page.id == link.from_page_id))
            linking_page = result.scalar_one_or_none()
            if linking_page:
                linking_page.body_md = linking_page.body_md.replace(
                    f"[[{old_slug}]]", f"[[{new_slug}]]"
                )
                self.session.add(linking_page)
                await sync_links(self.session, linking_page)

        await self.session.execute(
            delete(PageLink).where(
                (PageLink.from_page_id == old_page.id) | (PageLink.to_page_id == old_page.id)
            )
        )
        self.session.delete(old_page)
        await self._remove_from_index(old_slug)
        await self.session.commit()

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

        await _ensure_vision_captions(page, self.session)
        return page.markdown

    async def describe_image(self, s3_key: str) -> str:
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
                                "type": "image_url",
                                "image_url": {"url": f"data:{mime};base64,{b64}"},
                            },
                            {
                                "type": "text",
                                "text": _VISION_DESCRIBE_PROMPT,
                            },
                        ],
                    }
                ],
            )
            return resp.choices[0].message.content or ""
        except Exception as exc:
            return f"[describe_image error: {exc}]"

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
            {
                "type": "function",
                "function": {
                    "name": "describe_image",
                    "description": (
                        "Describe a specific image from the source document by its S3 key. "
                        "Use this when a page shows '(caption unavailable — image: `<key>`)' "
                        "to get a fresh vision description of that image."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "s3_key": {
                                "type": "string",
                                "description": "The S3 key of the image, as shown in the caption unavailable notice.",
                            }
                        },
                        "required": ["s3_key"],
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
        if name == "describe_image":
            return await self.describe_image(args["s3_key"])
        return f"Unknown tool: {name}"
