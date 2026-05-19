from datetime import datetime

import httpx
import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import settings
from app.database import AsyncSessionLocal, get_db
from app.models import BrowserChatMessage, BrowserChatSession
from app.routes.wiki import _ensure_workspace
from app.sse import broadcaster

router = APIRouter(prefix="/browser-chat", tags=["browser-chat"])
_log = structlog.get_logger()


class MessageRequest(BaseModel):
    content: str
    max_turns: int = 20


# ---------------------------------------------------------------------------
# POST /browser-chat/sessions — Connect
# ---------------------------------------------------------------------------

@router.post("/sessions", status_code=201)
async def connect(
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)

    # One active session at a time (single Xvfb display).
    existing = await db.execute(
        select(BrowserChatSession).where(
            BrowserChatSession.workspace_id == ws.id,
            BrowserChatSession.status == "active",
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="A browser chat session is already active.")

    async with httpx.AsyncClient(base_url=settings.browser_agent_url, timeout=30.0) as http:
        try:
            resp = await http.post("/session/new")
            resp.raise_for_status()
            browser_session_id = resp.json()["session_id"]
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Failed to start browser session: {exc}")

    sess = BrowserChatSession(
        workspace_id=ws.id,
        browser_session_id=browser_session_id,
        status="active",
        last_activity_at=datetime.utcnow(),
    )
    db.add(sess)
    await db.commit()
    await db.refresh(sess)
    _log.info("browser_chat_connected", session_id=sess.id, browser_session_id=browser_session_id)
    return {"session_id": sess.id}


# ---------------------------------------------------------------------------
# POST /browser-chat/sessions/{id}/message — Send message (202)
# ---------------------------------------------------------------------------

async def _run_turn_task(
    chat_session_id: str,
    workspace_id: str,
    browser_session_id: str,
    user_content: str,
    audience_user_id: str,
    max_turns: int = 20,
) -> None:
    async with AsyncSessionLocal() as db:
        # Load full history (already includes the new user message).
        result = await db.execute(
            select(BrowserChatMessage)
            .where(BrowserChatMessage.session_id == chat_session_id)
            .order_by(BrowserChatMessage.created_at.asc())
        )
        messages = result.scalars().all()
        history = [{"role": m.role, "content": m.content} for m in messages]

        await broadcaster.publish(
            {"event": "browser_chat:status", "session_id": chat_session_id, "status": "thinking"},
            audience_user_id=audience_user_id,
        )

        from app.agents.browser_chat_agent import run_turn
        try:
            reply = await run_turn(
                chat_session_id=chat_session_id,
                workspace_id=workspace_id,
                browser_session_id=browser_session_id,
                conversation_history=history,
                audience_user_id=audience_user_id,
                db_session=db,
                max_turns=max_turns,
            )
        except Exception as exc:
            _log.error("browser_chat_turn_error", session_id=chat_session_id, error=str(exc))
            reply = "Sorry, something went wrong. The browser session is still open — try again."

        # Persist assistant reply.
        db.add(BrowserChatMessage(session_id=chat_session_id, role="assistant", content=reply))

        # Update last_activity_at.
        sess_result = await db.execute(
            select(BrowserChatSession).where(BrowserChatSession.id == chat_session_id)
        )
        sess = sess_result.scalar_one_or_none()
        if sess:
            sess.last_activity_at = datetime.utcnow()
        await db.commit()

        await broadcaster.publish(
            {"event": "browser_chat:reply", "session_id": chat_session_id, "content": reply},
            audience_user_id=audience_user_id,
        )
        await broadcaster.publish(
            {"event": "browser_chat:status", "session_id": chat_session_id, "status": "idle"},
            audience_user_id=audience_user_id,
        )


@router.post("/sessions/{session_id}/message", status_code=202)
async def send_message(
    session_id: str,
    body: MessageRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)
    result = await db.execute(
        select(BrowserChatSession).where(
            BrowserChatSession.id == session_id,
            BrowserChatSession.workspace_id == ws.id,
        )
    )
    sess = result.scalar_one_or_none()
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    if sess.status != "active":
        raise HTTPException(status_code=409, detail="Session is not active")
    if not body.content.strip():
        raise HTTPException(status_code=422, detail="Message content cannot be empty")

    # Persist user message.
    db.add(BrowserChatMessage(session_id=session_id, role="user", content=body.content.strip()))
    sess.last_activity_at = datetime.utcnow()
    await db.commit()

    background_tasks.add_task(
        _run_turn_task,
        session_id,
        ws.id,
        sess.browser_session_id,
        body.content.strip(),
        user,
        body.max_turns,
    )
    return {"status": "accepted"}


# ---------------------------------------------------------------------------
# POST /browser-chat/sessions/{id}/interrupt
# ---------------------------------------------------------------------------

@router.post("/sessions/{session_id}/interrupt", status_code=200)
async def interrupt(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)
    result = await db.execute(
        select(BrowserChatSession).where(
            BrowserChatSession.id == session_id,
            BrowserChatSession.workspace_id == ws.id,
        )
    )
    sess = result.scalar_one_or_none()
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    sess.user_interrupted = True
    await db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# POST /browser-chat/sessions/{id}/disconnect
# ---------------------------------------------------------------------------

@router.post("/sessions/{session_id}/disconnect", status_code=200)
async def disconnect(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)
    result = await db.execute(
        select(BrowserChatSession).where(
            BrowserChatSession.id == session_id,
            BrowserChatSession.workspace_id == ws.id,
        )
    )
    sess = result.scalar_one_or_none()
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")

    if sess.browser_session_id:
        async with httpx.AsyncClient(base_url=settings.browser_agent_url, timeout=10.0) as http:
            try:
                await http.post(f"/session/{sess.browser_session_id}/close")
            except Exception:
                pass

    sess.status = "completed"
    sess.completed_at = datetime.utcnow()
    await db.commit()
    _log.info("browser_chat_disconnected", session_id=session_id)
    return {"ok": True}


# ---------------------------------------------------------------------------
# POST /browser-chat/sessions/{id}/recover
# ---------------------------------------------------------------------------

@router.post("/sessions/{session_id}/recover", status_code=200)
async def recover(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)
    result = await db.execute(
        select(BrowserChatSession).where(
            BrowserChatSession.id == session_id,
            BrowserChatSession.workspace_id == ws.id,
        )
    )
    sess = result.scalar_one_or_none()
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")

    async with httpx.AsyncClient(base_url=settings.browser_agent_url, timeout=30.0) as http:
        try:
            resp = await http.post(f"/session/{sess.browser_session_id}/recover")
            resp.raise_for_status()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Failed to recover browser session: {exc}")

    sess.last_activity_at = datetime.utcnow()
    await db.commit()
    _log.info("browser_chat_recovered", session_id=session_id)
    return {"ok": True}


# ---------------------------------------------------------------------------
# GET /browser-chat/sessions — List sessions
# ---------------------------------------------------------------------------

@router.get("/sessions")
async def list_sessions(
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)
    result = await db.execute(
        select(BrowserChatSession)
        .where(BrowserChatSession.workspace_id == ws.id)
        .order_by(BrowserChatSession.created_at.desc())
        .limit(50)
    )
    sessions = result.scalars().all()
    return [_serialise_session(s) for s in sessions]


# ---------------------------------------------------------------------------
# GET /browser-chat/sessions/{id} — Get session + messages
# ---------------------------------------------------------------------------

@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)
    result = await db.execute(
        select(BrowserChatSession).where(
            BrowserChatSession.id == session_id,
            BrowserChatSession.workspace_id == ws.id,
        )
    )
    sess = result.scalar_one_or_none()
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")

    msgs_result = await db.execute(
        select(BrowserChatMessage)
        .where(BrowserChatMessage.session_id == session_id)
        .order_by(BrowserChatMessage.created_at.asc())
    )
    msgs = msgs_result.scalars().all()
    data = _serialise_session(sess)
    data["messages"] = [
        {"id": m.id, "role": m.role, "content": m.content, "created_at": m.created_at.isoformat()}
        for m in msgs
    ]
    return data


def _serialise_session(s: BrowserChatSession) -> dict:
    return {
        "id": s.id,
        "status": s.status,
        "created_at": s.created_at.isoformat(),
        "completed_at": s.completed_at.isoformat() if s.completed_at else None,
    }
