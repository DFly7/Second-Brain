import asyncio
import uuid
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from app.database import get_db
from app.auth import get_current_user
from app.models import Source, Workspace
from app.storage import upload_file
from app.extractors.pdf import extract_pdf
from app.extractors.docx import extract_docx
from app.extractors.url import extract_main_content
from app.routes.wiki import _ensure_workspace

router = APIRouter(prefix="/ingest", tags=["ingest"])


class URLIngest(BaseModel):
    url: str


class TextIngest(BaseModel):
    text: str
    title: str = "Pasted note"


async def _run_ingest_agent(source_id: str, workspace_id: str):
    # Imported here to avoid circular imports
    from app.agents.ingest_agent import run as run_ingest
    await run_ingest(source_id, workspace_id)


@router.post("/file")
async def ingest_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user)
):
    ws = await _ensure_workspace(db, user)
    data = await file.read()
    suffix = file.filename.rsplit(".", 1)[-1].lower() if file.filename else ""
    if suffix == "pdf":
        kind = "pdf"
        text = extract_pdf(data)
        s3_key = f"{ws.id}/{uuid.uuid4()}.pdf"
        upload_file(s3_key, data, "application/pdf")
    elif suffix in ("docx", "doc"):
        kind = "docx"
        text = extract_docx(data)
        s3_key = f"{ws.id}/{uuid.uuid4()}.docx"
        upload_file(s3_key, data, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    else:
        raise HTTPException(status_code=400, detail="Unsupported file type. Upload PDF or DOCX.")
    source = Source(workspace_id=ws.id, kind=kind, s3_key=s3_key, extracted_text=text[:50000])
    db.add(source)
    await db.commit()
    await db.refresh(source)
    background_tasks.add_task(_run_ingest_agent, source.id, ws.id)
    return {"source_id": source.id, "status": "ingesting"}


@router.post("/url")
async def ingest_url(
    body: URLIngest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user)
):
    ws = await _ensure_workspace(db, user)
    text = await extract_main_content(body.url)
    source = Source(workspace_id=ws.id, kind="url", s3_key=None, extracted_text=text[:50000])
    db.add(source)
    await db.commit()
    await db.refresh(source)
    background_tasks.add_task(_run_ingest_agent, source.id, ws.id)
    return {"source_id": source.id, "status": "ingesting"}


@router.post("/text")
async def ingest_text(
    body: TextIngest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user)
):
    ws = await _ensure_workspace(db, user)
    source = Source(workspace_id=ws.id, kind="text", s3_key=None, extracted_text=body.text[:50000])
    db.add(source)
    await db.commit()
    await db.refresh(source)
    background_tasks.add_task(_run_ingest_agent, source.id, ws.id)
    return {"source_id": source.id, "status": "ingesting"}
