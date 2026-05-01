import re

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Page, PageLink

WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


def extract_slugs(body_md: str) -> list[str]:
    return WIKILINK_RE.findall(body_md)


async def sync_links(session: AsyncSession, page: Page) -> None:
    slugs = list(dict.fromkeys(extract_slugs(page.body_md)))
    await session.execute(
        delete(PageLink).where(PageLink.from_page_id == page.id)
    )
    for slug in slugs:
        result = await session.execute(
            select(Page).where(
                Page.slug == slug, Page.workspace_id == page.workspace_id
            )
        )
        target = result.scalar_one_or_none()
        if target:
            session.add(PageLink(from_page_id=page.id, to_page_id=target.id))
