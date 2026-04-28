import json

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response
from fastapi.responses import StreamingResponse
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.query_agent import run as run_query
from app.auth import ALGORITHM, get_current_user
from app.config import settings
from app.database import AsyncSessionLocal, get_db
from app.models import ActivityLog, ChatMessage, ChatSession
from app.routes.wiki import _ensure_workspace
from app.sse import broadcaster

router = APIRouter(prefix="/chat", tags=["chat"])


class MessageRequest(BaseModel):
    message: str
    session_id: str | None = None


@router.post("/message")
async def send_message(
    body: MessageRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)

    session_obj: ChatSession | None = None
    if body.session_id:
        result = await db.execute(
            select(ChatSession).where(
                ChatSession.id == body.session_id, ChatSession.workspace_id == ws.id
            )
        )
        session_obj = result.scalar_one_or_none()

    if not session_obj:
        session_obj = ChatSession(workspace_id=ws.id)
        db.add(session_obj)
        await db.flush()

    user_msg = ChatMessage(session_id=session_obj.id, role="user", content=body.message)
    db.add(user_msg)
    await db.commit()

    history_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_obj.id)
        .order_by(ChatMessage.created_at)
    )
    history = [{"role": m.role, "content": m.content} for m in history_result.scalars()]

    answer, cited = await run_query(ws.id, body.message, history[:-1], db)

    assistant_msg = ChatMessage(
        session_id=session_obj.id, role="assistant", content=answer
    )
    db.add(assistant_msg)
    db.add(
        ActivityLog(
            workspace_id=ws.id,
            event_type="chat_message",
            payload={"session_id": session_obj.id, "cited_pages": cited},
        )
    )
    await db.commit()

    background_tasks.add_task(_run_chat_monitor, session_obj.id, ws.id)

    return {"session_id": session_obj.id, "answer": answer, "cited_pages": cited}


@router.get("/sessions/{session_id}/messages")
async def get_messages(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)
    session_result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id, ChatSession.workspace_id == ws.id
        )
    )
    session_obj = session_result.scalar_one_or_none()
    if not session_obj:
        return []

    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
    )
    return [
        {"role": m.role, "content": m.content, "id": m.id} for m in result.scalars()
    ]


@router.get("/sse")
async def sse_stream(token: str = Query(...)):
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        if payload.get("sub") is None:
            return Response(status_code=401)
    except JWTError:
        return Response(status_code=401)

    q = broadcaster.subscribe()

    async def event_gen():
        try:
            async for chunk in broadcaster.stream(q):
                yield chunk
        finally:
            broadcaster.unsubscribe(q)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _run_chat_monitor(session_id: str, workspace_id: str):
    from app.agents.chat_monitor import run as run_monitor

    async with AsyncSessionLocal() as session:
        await run_monitor(session_id, workspace_id, session)
