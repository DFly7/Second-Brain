from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.routes.wiki import _ensure_workspace

router = APIRouter(prefix="/health", tags=["health"])


@router.post("/run", status_code=202)
async def run_health_check(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    from app.agents import health_agent

    ws = await _ensure_workspace(db, user)
    background_tasks.add_task(health_agent.run, ws.id, user)
    return {"status": "health check started"}
