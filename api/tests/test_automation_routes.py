"""Tests for /automations routes."""
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


def _make_run(
    id="run-1",
    goal="research something",
    status="completed",
    recording_url=None,
    created_at=None,
    completed_at=None,
):
    from datetime import datetime
    run = MagicMock()
    run.id = id
    run.goal = goal
    run.status = status
    run.recording_url = recording_url
    run.created_at = created_at or datetime(2026, 5, 18, 12, 0, 0)
    run.completed_at = completed_at
    return run


# ---------------------------------------------------------------------------
# POST /automations/run
# ---------------------------------------------------------------------------


def test_start_run_returns_202(client):
    mock_ws = _make_ws()
    mock_run = _make_run(status="running")
    mock_run.id = "run-abc"

    no_existing = MagicMock()
    no_existing.scalar_one_or_none.return_value = None

    session = MagicMock()
    session.execute = AsyncMock(return_value=no_existing)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch(
            "app.routes.automations._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ), patch(
            "app.routes.automations._run_automation",
            new_callable=AsyncMock,
        ), patch(
            "app.routes.automations._reclaim_stale_runs",
            new_callable=AsyncMock,
            return_value=0,
        ):
            # Simulate flush setting the run id
            def fake_add(obj):
                obj.id = "run-abc"
            session.add.side_effect = fake_add

            r = client.post("/automations/run", json={"goal": "research note-taking apps"})
            assert r.status_code == 202
            data = r.json()
            assert "run_id" in data
            assert data["status"] == "running"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_start_run_requires_goal(client):
    r = client.post("/automations/run", json={})
    assert r.status_code == 422


def test_start_run_409_when_already_running(client):
    mock_ws = _make_ws()
    existing_run = _make_run(id="run-existing", status="running")

    existing_result = MagicMock()
    existing_result.scalar_one_or_none.return_value = existing_run

    session = MagicMock()
    session.execute = AsyncMock(return_value=existing_result)

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch(
            "app.routes.automations._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ), patch(
            "app.routes.automations._reclaim_stale_runs",
            new_callable=AsyncMock,
            return_value=0,
        ):
            r = client.post("/automations/run", json={"goal": "do something"})
            assert r.status_code == 409
            assert "already in progress" in r.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# GET /automations/runs
# ---------------------------------------------------------------------------


def test_list_runs_returns_newest_first(client):
    from datetime import datetime
    mock_ws = _make_ws()

    r1 = _make_run(id="run-old", created_at=datetime(2026, 5, 1))
    r2 = _make_run(id="run-new", created_at=datetime(2026, 5, 18))

    db_result = MagicMock()
    db_result.scalars.return_value.all.return_value = [r2, r1]

    session = MagicMock()
    session.execute = AsyncMock(return_value=db_result)

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch(
            "app.routes.automations._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ), patch(
            "app.routes.automations._reclaim_stale_runs",
            new_callable=AsyncMock,
            return_value=0,
        ):
            r = client.get("/automations/runs")
            assert r.status_code == 200
            data = r.json()
            assert data[0]["id"] == "run-new"
            assert data[1]["id"] == "run-old"
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# POST /automations/runs/{run_id}/stop
# ---------------------------------------------------------------------------


def test_stop_run_sets_status_stopping(client):
    mock_ws = _make_ws()
    run_obj = _make_run(id="run-1", status="running")

    db_result = MagicMock()
    db_result.scalar_one_or_none.return_value = run_obj

    session = MagicMock()
    session.execute = AsyncMock(return_value=db_result)
    session.commit = AsyncMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch(
            "app.routes.automations._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            r = client.post("/automations/runs/run-1/stop")
            assert r.status_code == 200
            assert r.json()["status"] == "stopping"
            assert run_obj.status == "stopping"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_start_run_409_when_stopping(client):
    mock_ws = _make_ws()
    existing_run = _make_run(id="run-existing", status="stopping")

    existing_result = MagicMock()
    existing_result.scalar_one_or_none.return_value = existing_run

    session = MagicMock()
    session.execute = AsyncMock(return_value=existing_result)

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch(
            "app.routes.automations._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ), patch(
            "app.routes.automations._reclaim_stale_runs",
            new_callable=AsyncMock,
            return_value=0,
        ):
            r = client.post("/automations/run", json={"goal": "do something"})
            assert r.status_code == 409
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_stop_run_404_when_not_found(client):
    mock_ws = _make_ws()
    db_result = MagicMock()
    db_result.scalar_one_or_none.return_value = None

    session = MagicMock()
    session.execute = AsyncMock(return_value=db_result)

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch(
            "app.routes.automations._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            r = client.post("/automations/runs/no-such-run/stop")
            assert r.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# GET /automations/novnc-url
# ---------------------------------------------------------------------------


def test_novnc_url_returns_configured_url(client):
    with patch("app.routes.automations.settings") as mock_settings:
        mock_settings.novnc_url = "/vnc/vnc.html"
        r = client.get("/automations/novnc-url")
        assert r.status_code == 200
        url = r.json()["url"]
        assert url.startswith("/vnc/vnc.html")
        assert "autoconnect=1" in url
        assert "view_only=1" in url
        assert "resize=scale" in url
