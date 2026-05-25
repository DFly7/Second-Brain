"""Tests for /browser-chat routes."""
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.database import get_db
from app.main import app

USER = "test@example.com"


@pytest.fixture
def client():
    async def override_user():
        return USER

    app.dependency_overrides[get_current_user] = override_user
    yield TestClient(app)
    app.dependency_overrides.clear()


def _make_ws(id="ws-1"):
    ws = MagicMock()
    ws.id = id
    return ws


def _make_session(
    id="sess-1",
    status="active",
    browser_session_id="bsess-1",
    created_at=None,
    completed_at=None,
    last_activity_at=None,
):
    s = MagicMock()
    s.id = id
    s.status = status
    s.browser_session_id = browser_session_id
    s.created_at = created_at or datetime(2026, 5, 18, 12, 0, 0)
    s.completed_at = completed_at
    s.last_activity_at = last_activity_at or datetime(2026, 5, 18, 12, 0, 0)
    s.user_interrupted = False
    return s


# ---------------------------------------------------------------------------
# POST /browser-chat/sessions — connect
# ---------------------------------------------------------------------------


def test_connect_creates_session(client):
    mock_ws = _make_ws()
    no_existing = MagicMock()
    no_existing.scalar_one_or_none.return_value = None

    session = MagicMock()
    session.execute = AsyncMock(return_value=no_existing)
    session.commit = AsyncMock()
    session.add = MagicMock()
    session.refresh = AsyncMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch("app.routes.browser_chat._ensure_workspace", new_callable=AsyncMock, return_value=mock_ws), \
             patch("httpx.AsyncClient") as mock_http_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {"session_id": "bsess-abc"}
            mock_http.post = AsyncMock(return_value=mock_resp)
            mock_http_cls.return_value = mock_http

            def fake_add(obj):
                obj.id = "sess-abc"
            session.add.side_effect = fake_add

            r = client.post("/browser-chat/sessions")
            assert r.status_code == 201
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_connect_409_when_active_session_exists(client):
    mock_ws = _make_ws()
    existing = MagicMock()
    existing.scalar_one_or_none.return_value = _make_session()

    session = MagicMock()
    session.execute = AsyncMock(return_value=existing)

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch("app.routes.browser_chat._ensure_workspace", new_callable=AsyncMock, return_value=mock_ws):
            r = client.post("/browser-chat/sessions")
            assert r.status_code == 409
            assert "already active" in r.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_connect_with_prior_session_id_copies_messages(client):
    mock_ws = _make_ws()
    no_existing = MagicMock()
    no_existing.scalar_one_or_none.return_value = None

    # Prior messages returned by the second execute call
    prior_msg_1 = MagicMock()
    prior_msg_1.role = "user"
    prior_msg_1.content = "go to google"

    prior_msg_2 = MagicMock()
    prior_msg_2.role = "assistant"
    prior_msg_2.content = "Navigated to google.com"

    prior_msgs_result = MagicMock()
    prior_msgs_result.scalars.return_value.all.return_value = [prior_msg_1, prior_msg_2]

    # execute returns no-existing on first call (active check), prior msgs on second call
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[no_existing, prior_msgs_result])
    session.commit = AsyncMock()
    session.add = MagicMock()
    session.refresh = AsyncMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch("app.routes.browser_chat._ensure_workspace", new_callable=AsyncMock, return_value=mock_ws), \
             patch("httpx.AsyncClient") as mock_http_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {"session_id": "bsess-abc"}
            mock_http.post = AsyncMock(return_value=mock_resp)
            mock_http_cls.return_value = mock_http

            def fake_add(obj):
                if hasattr(obj, "browser_session_id"):
                    obj.id = "sess-new"

            session.add.side_effect = fake_add

            r = client.post("/browser-chat/sessions", json={"prior_session_id": "sess-old"})
            assert r.status_code == 201
            assert session.add.call_count == 3
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# POST /browser-chat/sessions/{id}/message
# ---------------------------------------------------------------------------


def test_send_message_returns_202(client):
    mock_ws = _make_ws()
    mock_sess = _make_session()

    sess_result = MagicMock()
    sess_result.scalar_one_or_none.return_value = mock_sess

    session = MagicMock()
    session.execute = AsyncMock(return_value=sess_result)
    session.commit = AsyncMock()
    session.add = MagicMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch("app.routes.browser_chat._ensure_workspace", new_callable=AsyncMock, return_value=mock_ws), \
             patch("app.routes.browser_chat._run_turn_task", new_callable=AsyncMock):
            r = client.post("/browser-chat/sessions/sess-1/message", json={"content": "go to google"})
            assert r.status_code == 202
            assert r.json()["status"] == "accepted"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_send_message_404_when_session_not_found(client):
    mock_ws = _make_ws()
    sess_result = MagicMock()
    sess_result.scalar_one_or_none.return_value = None

    session = MagicMock()
    session.execute = AsyncMock(return_value=sess_result)

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch("app.routes.browser_chat._ensure_workspace", new_callable=AsyncMock, return_value=mock_ws):
            r = client.post("/browser-chat/sessions/no-such/message", json={"content": "go to google"})
            assert r.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_send_message_422_when_empty_content(client):
    mock_ws = _make_ws()
    mock_sess = _make_session()
    sess_result = MagicMock()
    sess_result.scalar_one_or_none.return_value = mock_sess

    session = MagicMock()
    session.execute = AsyncMock(return_value=sess_result)
    session.commit = AsyncMock()
    session.add = MagicMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch("app.routes.browser_chat._ensure_workspace", new_callable=AsyncMock, return_value=mock_ws):
            r = client.post("/browser-chat/sessions/sess-1/message", json={"content": "   "})
            assert r.status_code == 422
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# POST /browser-chat/sessions/{id}/interrupt
# ---------------------------------------------------------------------------


def test_interrupt_sets_flag(client):
    mock_ws = _make_ws()
    mock_sess = _make_session()
    sess_result = MagicMock()
    sess_result.scalar_one_or_none.return_value = mock_sess

    session = MagicMock()
    session.execute = AsyncMock(return_value=sess_result)
    session.commit = AsyncMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch("app.routes.browser_chat._ensure_workspace", new_callable=AsyncMock, return_value=mock_ws):
            r = client.post("/browser-chat/sessions/sess-1/interrupt")
            assert r.status_code == 200
            assert mock_sess.user_interrupted is True
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# POST /browser-chat/sessions/{id}/disconnect
# ---------------------------------------------------------------------------


def test_disconnect_marks_completed(client):
    mock_ws = _make_ws()
    mock_sess = _make_session()
    sess_result = MagicMock()
    sess_result.scalar_one_or_none.return_value = mock_sess

    session = MagicMock()
    session.execute = AsyncMock(return_value=sess_result)
    session.commit = AsyncMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch("app.routes.browser_chat._ensure_workspace", new_callable=AsyncMock, return_value=mock_ws), \
             patch("httpx.AsyncClient") as mock_http_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.post = AsyncMock(return_value=MagicMock())
            mock_http_cls.return_value = mock_http

            r = client.post("/browser-chat/sessions/sess-1/disconnect")
            assert r.status_code == 200
            assert mock_sess.status == "completed"
            assert mock_sess.completed_at is not None
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# POST /browser-chat/sessions/{id}/recover
# ---------------------------------------------------------------------------


def test_recover_calls_browser_agent(client):
    mock_ws = _make_ws()
    mock_sess = _make_session()
    sess_result = MagicMock()
    sess_result.scalar_one_or_none.return_value = mock_sess

    session = MagicMock()
    session.execute = AsyncMock(return_value=sess_result)
    session.commit = AsyncMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch("app.routes.browser_chat._ensure_workspace", new_callable=AsyncMock, return_value=mock_ws), \
             patch("httpx.AsyncClient") as mock_http_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_http.post = AsyncMock(return_value=mock_resp)
            mock_http_cls.return_value = mock_http

            r = client.post("/browser-chat/sessions/sess-1/recover")
            assert r.status_code == 200
            assert r.json() == {"ok": True}
            mock_http.post.assert_called_once_with("/session/bsess-1/recover")
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_recover_404_for_unknown_session(client):
    mock_ws = _make_ws()
    sess_result = MagicMock()
    sess_result.scalar_one_or_none.return_value = None

    session = MagicMock()
    session.execute = AsyncMock(return_value=sess_result)

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch("app.routes.browser_chat._ensure_workspace", new_callable=AsyncMock, return_value=mock_ws):
            r = client.post("/browser-chat/sessions/no-such/recover")
            assert r.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# GET /browser-chat/sessions
# ---------------------------------------------------------------------------


def test_list_sessions_returns_newest_first(client):
    mock_ws = _make_ws()
    s1 = _make_session(id="old", created_at=datetime(2026, 5, 1))
    s2 = _make_session(id="new", created_at=datetime(2026, 5, 18))

    db_result = MagicMock()
    db_result.scalars.return_value.all.return_value = [s2, s1]

    session = MagicMock()
    session.execute = AsyncMock(return_value=db_result)

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch("app.routes.browser_chat._ensure_workspace", new_callable=AsyncMock, return_value=mock_ws):
            r = client.get("/browser-chat/sessions")
            assert r.status_code == 200
            data = r.json()
            assert data[0]["id"] == "new"
            assert data[1]["id"] == "old"
    finally:
        app.dependency_overrides.pop(get_db, None)
