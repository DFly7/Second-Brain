from datetime import datetime

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import settings
from app.database import AsyncSessionLocal, get_db
from app.models import AutomationAction, AutomationRun
from app.routes.wiki import _ensure_workspace

router = APIRouter(prefix="/automations", tags=["automations"])
_log = structlog.get_logger()


class RunRequest(BaseModel):
    goal: str


async def _run_automation(run_id: str, workspace_id: str, user: str, goal: str) -> None:
    async with AsyncSessionLocal() as session:
        from app.agents.automation_agent import run
        await run(run_id, workspace_id, goal, session, user)


@router.post("/run", status_code=202)
async def start_run(
    body: RunRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)

    # Enforce single-run-at-a-time. The browser-agent container uses a single
    # Xvfb display (:99) and a single VNC stream — concurrent runs would render
    # on top of each other and corrupt both sessions.
    existing = await db.execute(
        select(AutomationRun).where(
            AutomationRun.workspace_id == ws.id,
            AutomationRun.status == "running",
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="An automation is already in progress.")

    run_obj = AutomationRun(workspace_id=ws.id, goal=body.goal, status="running")
    db.add(run_obj)
    await db.flush()
    run_id = run_obj.id
    await db.commit()

    background_tasks.add_task(_run_automation, run_id, ws.id, user, body.goal)
    _log.info("automation_run_started", run_id=run_id, workspace_id=ws.id)
    return {"run_id": run_id, "status": "running"}


@router.post("/runs/{run_id}/stop", status_code=200)
async def stop_run(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)
    result = await db.execute(
        select(AutomationRun).where(
            AutomationRun.id == run_id,
            AutomationRun.workspace_id == ws.id,
        )
    )
    run_obj = result.scalar_one_or_none()
    if not run_obj:
        raise HTTPException(status_code=404, detail="Run not found")
    if run_obj.status == "running":
        run_obj.status = "stopped"
        run_obj.completed_at = datetime.utcnow()
        await db.commit()
    return {"run_id": run_id, "status": run_obj.status}


@router.get("/runs")
async def list_runs(
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)
    result = await db.execute(
        select(AutomationRun)
        .where(AutomationRun.workspace_id == ws.id)
        .order_by(AutomationRun.created_at.desc())
        .limit(50)
    )
    runs = result.scalars().all()
    return [_serialise_run(r) for r in runs]


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)
    result = await db.execute(
        select(AutomationRun).where(
            AutomationRun.id == run_id,
            AutomationRun.workspace_id == ws.id,
        )
    )
    run_obj = result.scalar_one_or_none()
    if not run_obj:
        raise HTTPException(status_code=404, detail="Run not found")

    actions_result = await db.execute(
        select(AutomationAction)
        .where(AutomationAction.run_id == run_id)
        .order_by(AutomationAction.timestamp.asc())
    )
    actions = actions_result.scalars().all()

    data = _serialise_run(run_obj)
    data["actions"] = [
        {
            "id": a.id,
            "type": a.type,
            "detail": a.detail,
            "timestamp": a.timestamp.isoformat(),
        }
        for a in actions
    ]
    return data


@router.get("/novnc-url")
async def novnc_url(user: str = Depends(get_current_user)):
    base = settings.novnc_url.rstrip("/")
    return {"url": f"{base}?autoconnect=1&view_only=1&resize=scale"}


@router.get("/runs/{run_id}/recording")
async def get_recording(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)
    result = await db.execute(
        select(AutomationRun).where(
            AutomationRun.id == run_id,
            AutomationRun.workspace_id == ws.id,
        )
    )
    run_obj = result.scalar_one_or_none()
    if not run_obj or not run_obj.recording_url:
        raise HTTPException(status_code=404, detail="Recording not found")

    from fastapi.responses import StreamingResponse
    from app.storage import download_file
    data = download_file(run_obj.recording_url)
    return StreamingResponse(
        iter([data]),
        media_type="video/webm",
        headers={"Content-Disposition": f"inline; filename={run_id}.webm"},
    )


def _serialise_run(r: AutomationRun) -> dict:
    return {
        "id": r.id,
        "goal": r.goal,
        "status": r.status,
        "created_at": r.created_at.isoformat(),
        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        "recording_url": r.recording_url,
    }
