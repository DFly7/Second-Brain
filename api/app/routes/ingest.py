import base64
import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import AsyncSessionLocal, get_db
from app.models import Source, SourcePage, Workspace
from app.routes.wiki import _ensure_workspace
from app.sse import broadcaster
from app.storage import upload_file

router = APIRouter(prefix="/ingest", tags=["ingest"])

_log = logging.getLogger(__name__)

MARKER_TYPES = {"pdf", "docx", "doc", "pptx", "ppt", "xlsx", "xls", "png", "jpg", "jpeg", "webp"}
TEXT_TYPES = {"md", "markdown", "txt", "text"}
CHUNK_SIZE = 4000


async def _maybe_auto_health(
    background_tasks: BackgroundTasks,
    db: AsyncSession,
    ws: Workspace,
) -> None:
    count_result = await db.execute(
        select(func.count(Source.id)).where(Source.workspace_id == ws.id)
    )
    source_count = count_result.scalar() or 0
    if source_count > 0 and source_count % 10 == 0:
        from app.agents import health_agent

        background_tasks.add_task(health_agent.run, ws.id, ws.user_id)


class URLIngest(BaseModel):
    url: str


class TextIngest(BaseModel):
    text: str
    title: str = "Pasted note"


def _content_type(suffix: str) -> str:
    return {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
        "md": "text/markdown",
        "markdown": "text/markdown",
    }.get(suffix, "application/octet-stream")


def _chunk_text(text: str) -> list[str]:
    chunks = []
    for i in range(0, max(len(text), 1), CHUNK_SIZE):
        chunks.append(text[i : i + CHUNK_SIZE])
    return chunks


async def _run_pipeline(
    source_id: str, workspace_id: str, data: bytes, filename: str, audience_user_id: str
):
    from app.agents.ingest_agent import run as run_ingest
    from app.marker_client import make_client

    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    _log.info(
        "ingest pipeline start source_id=%s workspace_id=%s filename=%s suffix=%s bytes=%d",
        source_id,
        workspace_id,
        filename,
        suffix,
        len(data),
    )

    await broadcaster.publish(
        {"event": "agent:queued", "source_id": source_id, "filename": filename},
        audience_user_id=audience_user_id,
    )

    async with AsyncSessionLocal() as session:
        src_result = await session.execute(select(Source).where(Source.id == source_id))
        source = src_result.scalar_one_or_none()
        if not source:
            _log.warning("ingest pipeline aborted: source not found source_id=%s", source_id)
            return

        try:
            if suffix in TEXT_TYPES:
                await broadcaster.publish(
                    {"event": "agent:converting", "source_id": source_id, "filename": filename},
                    audience_user_id=audience_user_id,
                )
                _log.info(
                    "ingest skipping marker (plain text) source_id=%s suffix=%s",
                    source_id,
                    suffix,
                )
                text = data.decode("utf-8", errors="replace")
                chunks = _chunk_text(text)
                combined_md = text
                pages_data = [
                    {"page_num": i + 1, "markdown": chunk, "images": []}
                    for i, chunk in enumerate(chunks)
                ]
            else:
                await broadcaster.publish(
                    {"event": "agent:converting", "source_id": source_id, "filename": filename},
                    audience_user_id=audience_user_id,
                )
                _log.info("ingest calling marker source_id=%s filename=%s", source_id, filename)
                client = make_client()
                raw_pages = await client.convert(data, filename, source_id=source_id)
                _log.info(
                    "ingest marker done source_id=%s pages=%d",
                    source_id,
                    len(raw_pages),
                )
                pages_data = [
                    {
                        "page_num": p.page_num,
                        "markdown": p.markdown,
                        "images": [{"filename": img.filename, "b64": img.b64} for img in p.images],
                    }
                    for p in raw_pages
                ]
                combined_md = "\n\n".join(p["markdown"] for p in pages_data)

            # Upload combined markdown to S3
            md_key = f"{workspace_id}/{source_id}/converted.md"
            upload_file(md_key, combined_md.encode("utf-8"), "text/markdown")

            # Upload images and save SourcePage rows
            for p in pages_data:
                image_s3_keys = []
                for img in p["images"]:
                    ext = img["filename"].rsplit(".", 1)[-1] if "." in img["filename"] else "png"
                    img_key = f"{workspace_id}/{source_id}/p{p['page_num']}-{img['filename']}"
                    img_bytes = base64.b64decode(img["b64"])
                    image_content_type = "image/jpeg" if ext.lower() == "jpg" else f"image/{ext}"
                    upload_file(img_key, img_bytes, image_content_type)
                    image_s3_keys.append(img_key)

                session.add(
                    SourcePage(
                        source_id=source_id,
                        page_num=p["page_num"],
                        markdown=p["markdown"],
                        preview=p["markdown"][:200],
                        image_s3_keys=image_s3_keys,
                    )
                )

            source.markdown_s3_key = md_key
            source.status = "ingesting"
            await session.commit()
            _log.info(
                "ingest convert stage done source_id=%s pages_written=%d md_key=%s",
                source_id,
                len(pages_data),
                md_key,
            )

        except Exception:
            _log.exception("ingest pipeline failed source_id=%s filename=%s", source_id, filename)
            source.status = "error"
            await session.commit()
            await broadcaster.publish(
                {"event": "agent:error", "source_id": source_id},
                audience_user_id=audience_user_id,
            )
            return

    await broadcaster.publish(
        {"event": "agent:ingesting", "source_id": source_id, "filename": filename},
        audience_user_id=audience_user_id,
    )
    try:
        await run_ingest(source_id, workspace_id, audience_user_id)
    except Exception:
        _log.exception("ingest agent failed source_id=%s filename=%s", source_id, filename)
        async with AsyncSessionLocal() as session:
            src_result = await session.execute(select(Source).where(Source.id == source_id))
            source = src_result.scalar_one_or_none()
            if source:
                source.status = "error"
                await session.commit()
        await broadcaster.publish(
            {"event": "agent:error", "source_id": source_id},
            audience_user_id=audience_user_id,
        )
        return

    async with AsyncSessionLocal() as session:
        src_result = await session.execute(select(Source).where(Source.id == source_id))
        source = src_result.scalar_one_or_none()
        if source:
            source.status = "done"
            await session.commit()
    _log.info("ingest pipeline complete source_id=%s", source_id)


@router.post("/file")
async def ingest_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)
    suffix = file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else ""

    if suffix not in MARKER_TYPES and suffix not in TEXT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '.{suffix}'. Supported: PDF, DOCX, PPTX, XLSX, PNG, JPG, WEBP, MD, TXT.",
        )

    data = await file.read()
    s3_key = f"{ws.id}/{uuid.uuid4()}.{suffix}"
    upload_file(s3_key, data, _content_type(suffix))

    source = Source(
        workspace_id=ws.id,
        kind=suffix,
        s3_key=s3_key,
        status="converting",
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)

    background_tasks.add_task(
        _run_pipeline, source.id, ws.id, data, file.filename or f"file.{suffix}", user
    )
    _log.info(
        "ingest file accepted source_id=%s workspace_id=%s filename=%s bytes=%d queued=pipeline",
        source.id,
        ws.id,
        file.filename,
        len(data),
    )
    await _maybe_auto_health(background_tasks, db, ws)
    return {"source_id": source.id, "status": "converting"}


@router.post("/url")
async def ingest_url(
    body: URLIngest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    from app.extractors.url import extract_main_content

    ws = await _ensure_workspace(db, user)
    text = await extract_main_content(body.url)
    source = Source(workspace_id=ws.id, kind="url", s3_key=None, status="converting")
    db.add(source)
    await db.commit()
    await db.refresh(source)

    fake_data = text.encode("utf-8")
    background_tasks.add_task(_run_pipeline, source.id, ws.id, fake_data, "content.txt", user)
    await _maybe_auto_health(background_tasks, db, ws)
    return {"source_id": source.id, "status": "converting"}


@router.post("/text")
async def ingest_text(
    body: TextIngest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)
    source = Source(workspace_id=ws.id, kind="text", s3_key=None, status="converting")
    db.add(source)
    await db.commit()
    await db.refresh(source)

    fake_data = body.text.encode("utf-8")
    background_tasks.add_task(_run_pipeline, source.id, ws.id, fake_data, "note.txt", user)
    await _maybe_auto_health(background_tasks, db, ws)
    return {"source_id": source.id, "status": "converting"}
