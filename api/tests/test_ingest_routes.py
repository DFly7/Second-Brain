"""Route tests for /ingest endpoints (file, url, text).

SSE streaming inside _run_pipeline is exercised manually; background pipeline
execution is not tested here — only that the route accepts the request,
creates a Source record, and schedules the background task.
"""

import asyncio
import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.database import get_db
from app.main import app
from app.routes.ingest import _generate_metadata

TEST_USER = "test@example.com"
WS_ID = "ws-ingest-1"
SOURCE_ID = "src-1"


@pytest.fixture
def ingest_client():
    async def override_user():
        return TEST_USER

    app.dependency_overrides[get_current_user] = override_user
    client = TestClient(app, raise_server_exceptions=False)
    yield client
    app.dependency_overrides.clear()


def _make_session(source_id: str = SOURCE_ID, ws_id: str = WS_ID):
    """Return a minimal AsyncSession mock wired for ingest route usage."""
    mock_source = MagicMock()
    mock_source.id = source_id
    mock_source.status = "converting"

    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock(side_effect=lambda obj: setattr(obj, "id", source_id) or None)
    session.execute = AsyncMock()
    session.delete = AsyncMock()
    return session


def _make_workspace(ws_id: str = WS_ID):
    mock_ws = MagicMock()
    mock_ws.id = ws_id
    mock_ws.user_id = TEST_USER
    return mock_ws


# ---------------------------------------------------------------------------
# POST /ingest/file
# ---------------------------------------------------------------------------


def test_ingest_file_accepted(ingest_client):
    session = _make_session()
    mock_ws = _make_workspace()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    # _maybe_auto_health executes a count query; source_count = 0 so health agent
    # is not triggered.
    count_result = MagicMock()
    count_result.scalar.return_value = 0
    session.execute = AsyncMock(return_value=count_result)

    try:
        with (
            patch(
                "app.routes.ingest._ensure_workspace",
                new_callable=AsyncMock,
                return_value=mock_ws,
            ),
            patch(
                "app.routes.ingest.upload_file",
                return_value=None,
            ),
            patch(
                "app.routes.ingest._run_pipeline",
                new_callable=AsyncMock,
            ) as mock_pipeline,
        ):
            file_data = io.BytesIO(b"%PDF-1.4 fake content")
            r = ingest_client.post(
                "/ingest/file",
                files={"file": ("document.pdf", file_data, "application/pdf")},
            )
            assert r.status_code == 200
            body = r.json()
            assert body["status"] == "converting"
            assert "source_id" in body
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_ingest_file_unsupported_type_returns_400(ingest_client):
    session = _make_session()
    mock_ws = _make_workspace()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch(
            "app.routes.ingest._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            file_data = io.BytesIO(b"some data")
            r = ingest_client.post(
                "/ingest/file",
                files={"file": ("archive.zip", file_data, "application/zip")},
            )
            assert r.status_code == 400
            assert "Unsupported file type" in r.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_ingest_file_txt_accepted(ingest_client):
    """Plain-text (.txt) files go through the TEXT_TYPES path."""
    session = _make_session()
    mock_ws = _make_workspace()

    count_result = MagicMock()
    count_result.scalar.return_value = 0
    session.execute = AsyncMock(return_value=count_result)

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with (
            patch(
                "app.routes.ingest._ensure_workspace",
                new_callable=AsyncMock,
                return_value=mock_ws,
            ),
            patch("app.routes.ingest.upload_file", return_value=None),
            patch("app.routes.ingest._run_pipeline", new_callable=AsyncMock),
        ):
            file_data = io.BytesIO(b"Hello world")
            r = ingest_client.post(
                "/ingest/file",
                files={"file": ("note.txt", file_data, "text/plain")},
            )
            assert r.status_code == 200
            assert r.json()["status"] == "converting"
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# POST /ingest/url
# ---------------------------------------------------------------------------


def test_ingest_url_accepted(ingest_client):
    session = _make_session()
    mock_ws = _make_workspace()

    count_result = MagicMock()
    count_result.scalar.return_value = 0
    session.execute = AsyncMock(return_value=count_result)

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with (
            patch(
                "app.routes.ingest._ensure_workspace",
                new_callable=AsyncMock,
                return_value=mock_ws,
            ),
            patch(
                "app.extractors.url.extract_main_content",
                new_callable=AsyncMock,
                return_value="Extracted page content",
            ),
            patch("app.routes.ingest._run_pipeline", new_callable=AsyncMock) as mock_pipeline,
        ):
            r = ingest_client.post(
                "/ingest/url",
                json={"url": "https://example.com/article"},
            )
            assert r.status_code == 200
            body = r.json()
            assert body["status"] == "converting"
            assert "source_id" in body
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# POST /ingest/text
# ---------------------------------------------------------------------------


def test_ingest_text_accepted(ingest_client):
    session = _make_session()
    mock_ws = _make_workspace()

    count_result = MagicMock()
    count_result.scalar.return_value = 0
    session.execute = AsyncMock(return_value=count_result)

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with (
            patch(
                "app.routes.ingest._ensure_workspace",
                new_callable=AsyncMock,
                return_value=mock_ws,
            ),
            patch("app.routes.ingest._run_pipeline", new_callable=AsyncMock) as mock_pipeline,
        ):
            r = ingest_client.post(
                "/ingest/text",
                json={"text": "My note content", "title": "Meeting notes"},
            )
            assert r.status_code == 200
            body = r.json()
            assert body["status"] == "converting"
            assert "source_id" in body
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_ingest_text_default_title(ingest_client):
    """Omitting `title` should still succeed (defaults to 'Pasted note')."""
    session = _make_session()
    mock_ws = _make_workspace()

    count_result = MagicMock()
    count_result.scalar.return_value = 0
    session.execute = AsyncMock(return_value=count_result)

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with (
            patch(
                "app.routes.ingest._ensure_workspace",
                new_callable=AsyncMock,
                return_value=mock_ws,
            ),
            patch("app.routes.ingest._run_pipeline", new_callable=AsyncMock),
        ):
            r = ingest_client.post(
                "/ingest/text",
                json={"text": "Just a note"},
            )
            assert r.status_code == 200
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Auto-health agent trigger (every 10th source)
# ---------------------------------------------------------------------------


def test_ingest_file_triggers_health_agent_on_tenth_source(ingest_client):
    """When source_count % 10 == 0 and > 0, health_agent.run should be scheduled."""
    session = _make_session()
    mock_ws = _make_workspace()

    count_result = MagicMock()
    count_result.scalar.return_value = 10  # triggers health agent
    session.execute = AsyncMock(return_value=count_result)

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with (
            patch(
                "app.routes.ingest._ensure_workspace",
                new_callable=AsyncMock,
                return_value=mock_ws,
            ),
            patch("app.routes.ingest.upload_file", return_value=None),
            patch("app.routes.ingest._run_pipeline", new_callable=AsyncMock),
            patch("app.agents.health_agent.run", new_callable=AsyncMock) as mock_health,
        ):
            file_data = io.BytesIO(b"%PDF-1.4 fake content")
            r = ingest_client.post(
                "/ingest/file",
                files={"file": ("doc.pdf", file_data, "application/pdf")},
            )
            assert r.status_code == 200
            # BackgroundTasks schedules health_agent.run — not awaited directly,
            # but TestClient runs background tasks synchronously so the mock is called.
            mock_health.assert_awaited_once()
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# _generate_metadata unit tests
# ---------------------------------------------------------------------------


def _make_litellm_resp(content: str):
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def test_generate_metadata_normal_path_returns_title_and_description():
    long_md = "A" * 200  # >= 100 chars triggers normal path
    resp = _make_litellm_resp('{"title": "My Doc", "description": "A great document."}')

    with patch("app.routes.ingest.litellm.acompletion", new_callable=AsyncMock, return_value=resp):
        title, desc = asyncio.get_event_loop().run_until_complete(
            _generate_metadata(kind="pdf", filename="report.pdf", combined_md=long_md, raw_data=b"")
        )

    assert title == "My Doc"
    assert desc == "A great document."


def test_generate_metadata_image_path_sends_image_content():
    """Sparse markdown + image kind → sends image_url content block."""
    short_md = "   "  # < 100 chars
    resp = _make_litellm_resp('{"title": "Beach photo", "description": "A sunny day."}')
    captured: list = []

    async def fake_acompletion(**kwargs):
        captured.append(kwargs["messages"])
        return resp

    with patch("app.routes.ingest.litellm.acompletion", side_effect=fake_acompletion):
        title, desc = asyncio.get_event_loop().run_until_complete(
            _generate_metadata(kind="png", filename="IMG_001.png", combined_md=short_md, raw_data=b"\x89PNG")
        )

    assert title == "Beach photo"
    user_content = captured[0][1]["content"]
    assert any(block.get("type") == "image_url" for block in user_content)


def test_generate_metadata_sparse_non_image_sends_text_only():
    """Sparse markdown + non-image kind → text-only content."""
    short_md = "  "
    resp = _make_litellm_resp('{"title": "PDF doc", "description": "No text extracted."}')
    captured: list = []

    async def fake_acompletion(**kwargs):
        captured.append(kwargs["messages"])
        return resp

    with patch("app.routes.ingest.litellm.acompletion", side_effect=fake_acompletion):
        title, _ = asyncio.get_event_loop().run_until_complete(
            _generate_metadata(kind="pdf", filename="scan.pdf", combined_md=short_md, raw_data=b"%PDF")
        )

    assert title == "PDF doc"
    user_content = captured[0][1]["content"]
    assert isinstance(user_content, list)
    assert all(block.get("type") == "text" for block in user_content)


def test_generate_metadata_returns_none_on_llm_exception():
    with patch(
        "app.routes.ingest.litellm.acompletion",
        new_callable=AsyncMock,
        side_effect=Exception("LLM error"),
    ):
        title, desc = asyncio.get_event_loop().run_until_complete(
            _generate_metadata(kind="pdf", filename="doc.pdf", combined_md="x" * 200, raw_data=b"")
        )

    assert title is None
    assert desc is None


def test_generate_metadata_returns_none_on_bad_json():
    resp = _make_litellm_resp("not json at all")

    with patch("app.routes.ingest.litellm.acompletion", new_callable=AsyncMock, return_value=resp):
        title, desc = asyncio.get_event_loop().run_until_complete(
            _generate_metadata(kind="pdf", filename="doc.pdf", combined_md="x" * 200, raw_data=b"")
        )

    assert title is None
    assert desc is None


# SSE endpoint (_run_pipeline publishes broadcaster events) — tested manually.
