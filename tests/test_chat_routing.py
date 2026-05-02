"""Routing tests for /chat/message (mode query vs edit)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.database import get_db
from app.main import app


@pytest.fixture
def chat_api_client():
    async def override_user():
        return "test@example.com"

    app.dependency_overrides[get_current_user] = override_user
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


def test_list_sessions_returns_sessions_newest_first(chat_api_client):
    from datetime import datetime
    from unittest.mock import AsyncMock, MagicMock, patch

    mock_ws = MagicMock()
    mock_ws.id = "ws-1"

    s1 = MagicMock()
    s1.id = "sess-old"
    s1.created_at = datetime(2026, 5, 1, 10, 0, 0)
    s2 = MagicMock()
    s2.id = "sess-new"
    s2.created_at = datetime(2026, 5, 2, 12, 0, 0)

    db_result = MagicMock()
    db_result.scalars.return_value.all.return_value = [s2, s1]

    session = MagicMock()
    session.execute = AsyncMock(return_value=db_result)

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch(
            "app.routes.chat._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            r = chat_api_client.get("/chat/sessions")
            assert r.status_code == 200
            data = r.json()
            assert len(data) == 2
            assert data[0]["id"] == "sess-new"
            assert data[1]["id"] == "sess-old"
            assert "created_at" in data[0]
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_list_sessions_returns_empty_when_none(chat_api_client):
    from unittest.mock import AsyncMock, MagicMock, patch

    mock_ws = MagicMock()
    mock_ws.id = "ws-1"

    db_result = MagicMock()
    db_result.scalars.return_value.all.return_value = []

    session = MagicMock()
    session.execute = AsyncMock(return_value=db_result)

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch(
            "app.routes.chat._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            r = chat_api_client.get("/chat/sessions")
            assert r.status_code == 200
            assert r.json() == []
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_post_message_mode_edit_uses_edit_agent(chat_api_client):
    session = MagicMock()
    mock_msg = MagicMock()
    mock_msg.role = "user"
    mock_msg.content = "hi"

    hist_result = MagicMock()
    hist_result.scalars.return_value.all.return_value = [mock_msg]
    session.execute = AsyncMock(return_value=hist_result)
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    mock_ws = MagicMock()
    mock_ws.id = "ws-1"
    mock_session_obj = MagicMock()
    mock_session_obj.id = "sess-1"

    try:
        with (
            patch(
                "app.routes.chat._ensure_workspace",
                new_callable=AsyncMock,
                return_value=mock_ws,
            ),
            patch("app.routes.chat.ChatSession", return_value=mock_session_obj),
            patch("app.routes.chat.run_query", new_callable=AsyncMock) as mock_query,
            patch(
                "app.agents.edit_agent.run",
                new_callable=AsyncMock,
                return_value=("edited-answer", []),
            ) as mock_edit,
            patch("app.routes.chat._run_chat_monitor", new_callable=AsyncMock),
        ):
            r = chat_api_client.post(
                "/chat/message",
                json={"message": "hi", "mode": "edit"},
            )
            assert r.status_code == 200
            body = r.json()
            assert body["answer"] == "edited-answer"
            mock_edit.assert_awaited_once()
            mock_query.assert_not_called()
            assert mock_edit.call_args[0][0] == "ws-1"
            assert mock_edit.call_args[0][1] == "hi"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_post_message_mode_query_uses_query_agent(chat_api_client):
    session = MagicMock()
    mock_msg = MagicMock()
    mock_msg.role = "user"
    mock_msg.content = "hi"

    hist_result = MagicMock()
    hist_result.scalars.return_value.all.return_value = [mock_msg]
    session.execute = AsyncMock(return_value=hist_result)
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    mock_ws = MagicMock()
    mock_ws.id = "ws-1"
    mock_session_obj = MagicMock()
    mock_session_obj.id = "sess-1"

    try:
        with (
            patch(
                "app.routes.chat._ensure_workspace",
                new_callable=AsyncMock,
                return_value=mock_ws,
            ),
            patch("app.routes.chat.ChatSession", return_value=mock_session_obj),
            patch(
                "app.routes.chat.run_query",
                new_callable=AsyncMock,
                return_value=("query-answer", []),
            ) as mock_query,
            patch("app.agents.edit_agent.run", new_callable=AsyncMock) as mock_edit,
            patch("app.routes.chat._run_chat_monitor", new_callable=AsyncMock),
        ):
            r = chat_api_client.post(
                "/chat/message",
                json={"message": "hi", "mode": "query"},
            )
            assert r.status_code == 200
            body = r.json()
            assert body["answer"] == "query-answer"
            mock_query.assert_awaited_once()
            mock_edit.assert_not_called()
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_post_message_default_mode_is_query(chat_api_client):
    session = MagicMock()
    mock_msg = MagicMock()
    mock_msg.role = "user"
    mock_msg.content = "hi"

    hist_result = MagicMock()
    hist_result.scalars.return_value.all.return_value = [mock_msg]
    session.execute = AsyncMock(return_value=hist_result)
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    mock_ws = MagicMock()
    mock_ws.id = "ws-1"
    mock_session_obj = MagicMock()
    mock_session_obj.id = "sess-1"

    try:
        with (
            patch(
                "app.routes.chat._ensure_workspace",
                new_callable=AsyncMock,
                return_value=mock_ws,
            ),
            patch("app.routes.chat.ChatSession", return_value=mock_session_obj),
            patch(
                "app.routes.chat.run_query",
                new_callable=AsyncMock,
                return_value=("query-answer", []),
            ) as mock_query,
            patch("app.agents.edit_agent.run", new_callable=AsyncMock) as mock_edit,
            patch("app.routes.chat._run_chat_monitor", new_callable=AsyncMock),
        ):
            r = chat_api_client.post("/chat/message", json={"message": "hi"})
            assert r.status_code == 200
            mock_query.assert_awaited_once()
            mock_edit.assert_not_called()
    finally:
        app.dependency_overrides.pop(get_db, None)
