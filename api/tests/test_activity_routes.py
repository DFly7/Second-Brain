"""Route tests for GET /activity/."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.database import get_db
from app.main import app

TEST_USER = "test@example.com"
WS_ID = "ws-activity-1"


@pytest.fixture
def activity_client():
    async def override_user():
        return TEST_USER

    app.dependency_overrides[get_current_user] = override_user
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


def _make_log(
    log_id: str,
    event_type: str,
    payload: dict,
    created_at: datetime | None = None,
) -> MagicMock:
    log = MagicMock()
    log.id = log_id
    log.event_type = event_type
    log.payload = payload
    log.created_at = created_at or datetime(2026, 5, 17, 10, 0, 0)
    return log


# ---------------------------------------------------------------------------
# GET /activity/
# ---------------------------------------------------------------------------


def test_get_activity_returns_logs_in_order(activity_client):
    mock_ws = MagicMock()
    mock_ws.id = WS_ID

    log1 = _make_log("log-1", "ingest.complete", {"source_id": "src-1"}, datetime(2026, 5, 17, 9, 0, 0))
    log2 = _make_log("log-2", "wiki.page_created", {"slug": "home"}, datetime(2026, 5, 17, 10, 0, 0))

    # Route returns logs ordered by created_at desc — newest first.
    db_result = MagicMock()
    db_result.scalars.return_value.all.return_value = [log2, log1]

    session = MagicMock()
    session.execute = AsyncMock(return_value=db_result)
    session.delete = AsyncMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch(
            "app.routes.activity._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            r = activity_client.get("/activity/")
            assert r.status_code == 200
            data = r.json()
            assert len(data) == 2
            assert data[0]["id"] == "log-2"
            assert data[0]["event_type"] == "wiki.page_created"
            assert data[0]["payload"] == {"slug": "home"}
            assert data[1]["id"] == "log-1"
            assert data[1]["event_type"] == "ingest.complete"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_get_activity_returns_empty_list_when_no_logs(activity_client):
    mock_ws = MagicMock()
    mock_ws.id = WS_ID

    db_result = MagicMock()
    db_result.scalars.return_value.all.return_value = []

    session = MagicMock()
    session.execute = AsyncMock(return_value=db_result)
    session.delete = AsyncMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch(
            "app.routes.activity._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            r = activity_client.get("/activity/")
            assert r.status_code == 200
            assert r.json() == []
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_get_activity_response_shape(activity_client):
    """Each entry must include id, event_type, payload, and created_at."""
    mock_ws = MagicMock()
    mock_ws.id = WS_ID

    ts = datetime(2026, 5, 17, 12, 30, 0)
    log = _make_log("log-3", "chat.query", {"query": "What is X?"}, ts)

    db_result = MagicMock()
    db_result.scalars.return_value.all.return_value = [log]

    session = MagicMock()
    session.execute = AsyncMock(return_value=db_result)
    session.delete = AsyncMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch(
            "app.routes.activity._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            r = activity_client.get("/activity/")
            assert r.status_code == 200
            entry = r.json()[0]
            assert "id" in entry
            assert "event_type" in entry
            assert "payload" in entry
            assert "created_at" in entry
            assert entry["payload"] == {"query": "What is X?"}
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_get_activity_respects_limit_param(activity_client):
    """The `limit` query param is forwarded to the DB query; route should not error."""
    mock_ws = MagicMock()
    mock_ws.id = WS_ID

    db_result = MagicMock()
    db_result.scalars.return_value.all.return_value = []

    session = MagicMock()
    session.execute = AsyncMock(return_value=db_result)
    session.delete = AsyncMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch(
            "app.routes.activity._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            r = activity_client.get("/activity/?limit=10")
            assert r.status_code == 200
    finally:
        app.dependency_overrides.pop(get_db, None)
