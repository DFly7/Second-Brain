from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import ActivityLog
from app.routes.wiki import _ensure_workspace

router = APIRouter(prefix="/activity", tags=["activity"])


@router.get("/")
async def get_activity(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)
    result = await db.execute(
        select(ActivityLog)
        .where(ActivityLog.workspace_id == ws.id)
        .order_by(ActivityLog.created_at.desc())
        .limit(limit)
    )
    logs = result.scalars().all()
    return [
        {
            "id": log.id,
            "event_type": log.event_type,
            "payload": log.payload,
            "created_at": log.created_at,
        }
        for log in logs
    ]
