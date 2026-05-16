from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import Source, SourcePage
from app.routes.wiki import _ensure_workspace
from app.storage import download_file

router = APIRouter(prefix="/sources", tags=["sources"])

_CONTENT_TYPE: dict[str, str] = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "doc": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "ppt": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xls": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "md": "text/markdown",
    "markdown": "text/markdown",
    "txt": "text/plain",
    "text": "text/plain",
}


class SourceOut(BaseModel):
    id: str
    kind: str
    filename: str | None
    status: str
    has_file: bool
    has_markdown: bool
    created_at: datetime


@router.get("", response_model=list[SourceOut])
async def list_sources(
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)
    result = await db.execute(
        select(Source)
        .where(Source.workspace_id == ws.id)
        .order_by(Source.created_at.desc())
    )
    sources = result.scalars().all()
    return [
        SourceOut(
            id=s.id,
            kind=s.kind,
            filename=s.filename,
            status=s.status,
            has_file=s.s3_key is not None,
            has_markdown=s.markdown_s3_key is not None,
            created_at=s.created_at,
        )
        for s in sources
    ]


@router.get("/{source_id}/file")
async def get_source_file(
    source_id: str,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)
    result = await db.execute(
        select(Source).where(Source.id == source_id, Source.workspace_id == ws.id)
    )
    source = result.scalar_one_or_none()
    if source is None or source.s3_key is None:
        raise HTTPException(status_code=404, detail="File not found")
    data = download_file(source.s3_key)
    content_type = _CONTENT_TYPE.get(source.kind, "application/octet-stream")
    return Response(content=data, media_type=content_type)


@router.get("/{source_id}/images/{filename:path}")
async def get_source_image(
    source_id: str,
    filename: str,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)
    result = await db.execute(
        select(Source).where(Source.id == source_id, Source.workspace_id == ws.id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Source not found")

    pages_result = await db.execute(
        select(SourcePage).where(SourcePage.source_id == source_id)
    )
    pages = pages_result.scalars().all()

    img_key = None
    for page in pages:
        for key in (page.image_s3_keys or []):
            if key.endswith(f"-{filename}") or key.endswith(f"/{filename}"):
                img_key = key
                break
        if img_key:
            break

    if img_key is None:
        raise HTTPException(status_code=404, detail="Image not found")

    try:
        data = download_file(img_key)
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found in storage")

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "png"
    content_type = "image/jpeg" if ext == "jpg" else f"image/{ext}"
    return Response(content=data, media_type=content_type)


@router.get("/{source_id}/markdown")
async def get_source_markdown(
    source_id: str,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)
    result = await db.execute(
        select(Source).where(Source.id == source_id, Source.workspace_id == ws.id)
    )
    source = result.scalar_one_or_none()
    if source is None or source.markdown_s3_key is None:
        raise HTTPException(status_code=404, detail="Markdown not found")
    data = download_file(source.markdown_s3_key)
    return Response(content=data, media_type="text/markdown")
