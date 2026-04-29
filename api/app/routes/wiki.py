import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import ActivityLog, Page, Revision, Workspace
from app.wikilinks import sync_links

router = APIRouter(prefix="/wiki", tags=["wiki"])


def _workspace_id(user: str) -> str:
    # Deterministic workspace per user for single-user setup
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"workspace:{user}"))


async def _ensure_workspace(session: AsyncSession, user: str) -> Workspace:
    ws_id = _workspace_id(user)
    result = await session.execute(
        select(Workspace).where(Workspace.id == ws_id)
    )
    ws = result.scalar_one_or_none()
    if not ws:
        ws = Workspace(id=ws_id, user_id=user)
        session.add(ws)
        await session.commit()
    return ws


class PageCreate(BaseModel):
    slug: str
    title: str
    body_md: str = ""
    summary: str = ""


class PageUpdate(BaseModel):
    title: str | None = None
    body_md: str | None = None
    summary: str | None = None


class PageOut(BaseModel):
    id: str
    slug: str
    title: str
    summary: str
    body_md: str
    updated_at: datetime

    model_config = {"from_attributes": True}


@router.get("/pages", response_model=list[PageOut])
async def list_pages(
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)
    result = await db.execute(
        select(Page)
            .where(Page.workspace_id == ws.id)
            .order_by(Page.updated_at.desc())
    )
    return result.scalars().all()


@router.post("/pages", response_model=PageOut, status_code=201)
async def create_page(
    body: PageCreate,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)
    existing = await db.execute(
        select(Page).where(Page.slug == body.slug, Page.workspace_id == ws.id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409, detail="Page with this slug already exists"
        )
    page = Page(workspace_id=ws.id, **body.model_dump())
    db.add(page)
    await db.flush()
    await sync_links(db, page)
    db.add(
        ActivityLog(
            workspace_id=ws.id,
            event_type="page_created",
            payload={"slug": page.slug, "title": page.title},
        )
    )
    await db.commit()
    await db.refresh(page)
    return page


@router.get("/pages/{slug:path}", response_model=PageOut)
async def get_page(
    slug: str,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)
    result = await db.execute(
        select(Page).where(Page.slug == slug, Page.workspace_id == ws.id)
    )
    page = result.scalar_one_or_none()
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    return page


@router.put("/pages/{slug:path}", response_model=PageOut)
async def update_page(
    slug: str,
    body: PageUpdate,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)
    result = await db.execute(
        select(Page).where(Page.slug == slug, Page.workspace_id == ws.id)
    )
    page = result.scalar_one_or_none()
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    # Save revision before updating
    db.add(Revision(page_id=page.id, body_md=page.body_md))
    if body.title is not None:
        page.title = body.title
    if body.body_md is not None:
        page.body_md = body.body_md
        await sync_links(db, page)
    if body.summary is not None:
        page.summary = body.summary
    page.updated_at = datetime.utcnow()
    db.add(
        ActivityLog(
            workspace_id=ws.id,
            event_type="page_updated",
            payload={"slug": page.slug},
        )
    )
    await db.commit()
    await db.refresh(page)
    return page


@router.delete("/pages/{slug:path}", status_code=204)
async def delete_page(
    slug: str,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)
    result = await db.execute(
        select(Page).where(Page.slug == slug, Page.workspace_id == ws.id)
    )
    page = result.scalar_one_or_none()
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    await db.execute(delete(Revision).where(Revision.page_id == page.id))
    await db.delete(page)
    await db.commit()
