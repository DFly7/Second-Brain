"""Route tests for /sources endpoints."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.database import get_db
from app.main import app

TEST_USER = "test@example.com"
WORKSPACE_ID = "ws-123"
SOURCE_ID = "src-abc"


@pytest.fixture
def sources_client():
    async def override_user():
        return TEST_USER

    app.dependency_overrides[get_current_user] = override_user
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


def _make_mock_ws():
    ws = MagicMock()
    ws.id = WORKSPACE_ID
    return ws


def _make_mock_source(
    *,
    source_id=SOURCE_ID,
    kind="pdf",
    filename="document.pdf",
    status="ready",
    s3_key="sources/doc.pdf",
    markdown_s3_key="sources/doc.md",
    created_at=None,
    title=None,
    description=None,
):
    s = MagicMock()
    s.id = source_id
    s.kind = kind
    s.filename = filename
    s.status = status
    s.s3_key = s3_key
    s.markdown_s3_key = markdown_s3_key
    s.created_at = created_at or datetime(2026, 5, 1, 10, 0, 0)
    s.title = title
    s.description = description
    return s


# ---------------------------------------------------------------------------
# GET /sources
# ---------------------------------------------------------------------------


def test_list_sources_returns_all_sources(sources_client):
    mock_ws = _make_mock_ws()
    src1 = _make_mock_source(source_id="src-1", created_at=datetime(2026, 5, 2, 0, 0, 0))
    src2 = _make_mock_source(source_id="src-2", created_at=datetime(2026, 5, 1, 0, 0, 0))

    db_result = MagicMock()
    db_result.scalars.return_value.all.return_value = [src1, src2]

    session = MagicMock()
    session.execute = AsyncMock(return_value=db_result)
    session.delete = AsyncMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch(
            "app.routes.sources._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            r = sources_client.get("/sources")
            assert r.status_code == 200
            data = r.json()
            assert len(data) == 2
            assert data[0]["id"] == "src-1"
            assert data[1]["id"] == "src-2"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_list_sources_has_file_and_has_markdown_flags(sources_client):
    mock_ws = _make_mock_ws()
    # Source with both s3_key and markdown_s3_key set
    src_full = _make_mock_source(source_id="src-full", s3_key="k", markdown_s3_key="mk")
    # Source with neither
    src_empty = _make_mock_source(source_id="src-empty", s3_key=None, markdown_s3_key=None)

    db_result = MagicMock()
    db_result.scalars.return_value.all.return_value = [src_full, src_empty]

    session = MagicMock()
    session.execute = AsyncMock(return_value=db_result)
    session.delete = AsyncMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch(
            "app.routes.sources._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            r = sources_client.get("/sources")
            assert r.status_code == 200
            data = r.json()
            full = next(d for d in data if d["id"] == "src-full")
            empty = next(d for d in data if d["id"] == "src-empty")
            assert full["has_file"] is True
            assert full["has_markdown"] is True
            assert empty["has_file"] is False
            assert empty["has_markdown"] is False
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_list_sources_returns_empty_list_when_none(sources_client):
    mock_ws = _make_mock_ws()

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
            "app.routes.sources._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            r = sources_client.get("/sources")
            assert r.status_code == 200
            assert r.json() == []
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_list_sources_includes_title_and_description(sources_client):
    mock_ws = _make_mock_ws()
    src = _make_mock_source(
        source_id="src-1",
        title="Lecture notes",
        description="Week 3 summary",
        created_at=datetime(2026, 5, 2, 0, 0, 0),
    )

    db_result = MagicMock()
    db_result.scalars.return_value.all.return_value = [src]

    session = MagicMock()
    session.execute = AsyncMock(return_value=db_result)
    session.delete = AsyncMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch(
            "app.routes.sources._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            r = sources_client.get("/sources")
            assert r.status_code == 200
            data = r.json()
            assert len(data) == 1
            assert data[0]["id"] == "src-1"
            assert data[0]["title"] == "Lecture notes"
            assert data[0]["description"] == "Week 3 summary"
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# PATCH /sources/{source_id}
# ---------------------------------------------------------------------------


def test_patch_source_updates_title_and_description(sources_client):
    mock_ws = _make_mock_ws()
    mock_source = _make_mock_source(title="Old T", description="Old D")

    source_result = MagicMock()
    source_result.scalar_one_or_none.return_value = mock_source

    session = MagicMock()
    session.execute = AsyncMock(return_value=source_result)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.delete = AsyncMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch(
            "app.routes.sources._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            r = sources_client.patch(
                f"/sources/{SOURCE_ID}",
                json={"title": "New T", "description": "New D"},
            )
            assert r.status_code == 200
            data = r.json()
            assert data["title"] == "New T"
            assert data["description"] == "New D"
            assert mock_source.title == "New T"
            assert mock_source.description == "New D"
            session.commit.assert_awaited_once()
            session.refresh.assert_awaited_once_with(mock_source)
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_patch_source_title_only_preserves_description(sources_client):
    mock_ws = _make_mock_ws()
    mock_source = _make_mock_source(title="Old", description="Keep me")

    source_result = MagicMock()
    source_result.scalar_one_or_none.return_value = mock_source

    session = MagicMock()
    session.execute = AsyncMock(return_value=source_result)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.delete = AsyncMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch(
            "app.routes.sources._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            r = sources_client.patch(
                f"/sources/{SOURCE_ID}",
                json={"title": "New"},
            )
            assert r.status_code == 200
            data = r.json()
            assert data["title"] == "New"
            assert data["description"] == "Keep me"
            assert mock_source.title == "New"
            assert mock_source.description == "Keep me"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_patch_source_returns_404_when_not_found(sources_client):
    mock_ws = _make_mock_ws()

    source_result = MagicMock()
    source_result.scalar_one_or_none.return_value = None

    session = MagicMock()
    session.execute = AsyncMock(return_value=source_result)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.delete = AsyncMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch(
            "app.routes.sources._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            r = sources_client.patch(
                f"/sources/{SOURCE_ID}",
                json={"title": "x"},
            )
            assert r.status_code == 404
            assert r.json()["detail"] == "Source not found"
            session.commit.assert_not_called()
            session.refresh.assert_not_called()
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# GET /sources/{source_id}/file
# ---------------------------------------------------------------------------


def test_get_source_file_returns_file_content(sources_client):
    mock_ws = _make_mock_ws()
    mock_source = _make_mock_source(kind="pdf", s3_key="sources/doc.pdf")

    source_result = MagicMock()
    source_result.scalar_one_or_none.return_value = mock_source

    session = MagicMock()
    session.execute = AsyncMock(return_value=source_result)
    session.delete = AsyncMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with (
            patch(
                "app.routes.sources._ensure_workspace",
                new_callable=AsyncMock,
                return_value=mock_ws,
            ),
            patch(
                "app.routes.sources.download_file",
                return_value=b"%PDF-content",
            ),
        ):
            r = sources_client.get(f"/sources/{SOURCE_ID}/file")
            assert r.status_code == 200
            assert r.content == b"%PDF-content"
            assert r.headers["content-type"] == "application/pdf"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_get_source_file_content_type_for_png(sources_client):
    mock_ws = _make_mock_ws()
    mock_source = _make_mock_source(kind="png", s3_key="sources/img.png")

    source_result = MagicMock()
    source_result.scalar_one_or_none.return_value = mock_source

    session = MagicMock()
    session.execute = AsyncMock(return_value=source_result)
    session.delete = AsyncMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with (
            patch(
                "app.routes.sources._ensure_workspace",
                new_callable=AsyncMock,
                return_value=mock_ws,
            ),
            patch(
                "app.routes.sources.download_file",
                return_value=b"\x89PNG",
            ),
        ):
            r = sources_client.get(f"/sources/{SOURCE_ID}/file")
            assert r.status_code == 200
            assert "image/png" in r.headers["content-type"]
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_get_source_file_unknown_kind_uses_octet_stream(sources_client):
    mock_ws = _make_mock_ws()
    mock_source = _make_mock_source(kind="xyz", s3_key="sources/data.xyz")

    source_result = MagicMock()
    source_result.scalar_one_or_none.return_value = mock_source

    session = MagicMock()
    session.execute = AsyncMock(return_value=source_result)
    session.delete = AsyncMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with (
            patch(
                "app.routes.sources._ensure_workspace",
                new_callable=AsyncMock,
                return_value=mock_ws,
            ),
            patch(
                "app.routes.sources.download_file",
                return_value=b"binary",
            ),
        ):
            r = sources_client.get(f"/sources/{SOURCE_ID}/file")
            assert r.status_code == 200
            assert "application/octet-stream" in r.headers["content-type"]
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_get_source_file_returns_404_when_source_not_found(sources_client):
    mock_ws = _make_mock_ws()

    source_result = MagicMock()
    source_result.scalar_one_or_none.return_value = None

    session = MagicMock()
    session.execute = AsyncMock(return_value=source_result)
    session.delete = AsyncMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch(
            "app.routes.sources._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            r = sources_client.get(f"/sources/{SOURCE_ID}/file")
            assert r.status_code == 404
            assert r.json()["detail"] == "File not found"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_get_source_file_returns_404_when_no_s3_key(sources_client):
    mock_ws = _make_mock_ws()
    mock_source = _make_mock_source(s3_key=None)

    source_result = MagicMock()
    source_result.scalar_one_or_none.return_value = mock_source

    session = MagicMock()
    session.execute = AsyncMock(return_value=source_result)
    session.delete = AsyncMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch(
            "app.routes.sources._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            r = sources_client.get(f"/sources/{SOURCE_ID}/file")
            assert r.status_code == 404
            assert r.json()["detail"] == "File not found"
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# GET /sources/{source_id}/images/{filename}
# ---------------------------------------------------------------------------


def test_get_source_image_returns_image_content(sources_client):
    mock_ws = _make_mock_ws()
    mock_source = _make_mock_source()

    mock_page = MagicMock()
    mock_page.image_s3_keys = ["sources/src-abc/page1-photo.png"]

    source_result = MagicMock()
    source_result.scalar_one_or_none.return_value = mock_source

    pages_result = MagicMock()
    pages_result.scalars.return_value.all.return_value = [mock_page]

    session = MagicMock()
    session.execute = AsyncMock(side_effect=[source_result, pages_result])
    session.delete = AsyncMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with (
            patch(
                "app.routes.sources._ensure_workspace",
                new_callable=AsyncMock,
                return_value=mock_ws,
            ),
            patch(
                "app.routes.sources.download_file",
                return_value=b"\x89PNG",
            ),
        ):
            r = sources_client.get(f"/sources/{SOURCE_ID}/images/photo.png")
            assert r.status_code == 200
            assert r.content == b"\x89PNG"
            assert "image/png" in r.headers["content-type"]
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_get_source_image_jpg_uses_jpeg_content_type(sources_client):
    mock_ws = _make_mock_ws()
    mock_source = _make_mock_source()

    mock_page = MagicMock()
    mock_page.image_s3_keys = ["sources/src-abc/page1-shot.jpg"]

    source_result = MagicMock()
    source_result.scalar_one_or_none.return_value = mock_source

    pages_result = MagicMock()
    pages_result.scalars.return_value.all.return_value = [mock_page]

    session = MagicMock()
    session.execute = AsyncMock(side_effect=[source_result, pages_result])
    session.delete = AsyncMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with (
            patch(
                "app.routes.sources._ensure_workspace",
                new_callable=AsyncMock,
                return_value=mock_ws,
            ),
            patch(
                "app.routes.sources.download_file",
                return_value=b"\xff\xd8",
            ),
        ):
            r = sources_client.get(f"/sources/{SOURCE_ID}/images/shot.jpg")
            assert r.status_code == 200
            assert "image/jpeg" in r.headers["content-type"]
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_get_source_image_returns_404_when_source_not_found(sources_client):
    mock_ws = _make_mock_ws()

    source_result = MagicMock()
    source_result.scalar_one_or_none.return_value = None

    session = MagicMock()
    session.execute = AsyncMock(return_value=source_result)
    session.delete = AsyncMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch(
            "app.routes.sources._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            r = sources_client.get(f"/sources/{SOURCE_ID}/images/photo.png")
            assert r.status_code == 404
            assert r.json()["detail"] == "Source not found"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_get_source_image_returns_404_when_image_key_not_in_pages(sources_client):
    mock_ws = _make_mock_ws()
    mock_source = _make_mock_source()

    mock_page = MagicMock()
    mock_page.image_s3_keys = ["sources/src-abc/page1-other.png"]

    source_result = MagicMock()
    source_result.scalar_one_or_none.return_value = mock_source

    pages_result = MagicMock()
    pages_result.scalars.return_value.all.return_value = [mock_page]

    session = MagicMock()
    session.execute = AsyncMock(side_effect=[source_result, pages_result])
    session.delete = AsyncMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch(
            "app.routes.sources._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            r = sources_client.get(f"/sources/{SOURCE_ID}/images/missing.png")
            assert r.status_code == 404
            assert r.json()["detail"] == "Image not found"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_get_source_image_returns_404_when_no_pages(sources_client):
    mock_ws = _make_mock_ws()
    mock_source = _make_mock_source()

    source_result = MagicMock()
    source_result.scalar_one_or_none.return_value = mock_source

    pages_result = MagicMock()
    pages_result.scalars.return_value.all.return_value = []

    session = MagicMock()
    session.execute = AsyncMock(side_effect=[source_result, pages_result])
    session.delete = AsyncMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch(
            "app.routes.sources._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            r = sources_client.get(f"/sources/{SOURCE_ID}/images/photo.png")
            assert r.status_code == 404
            assert r.json()["detail"] == "Image not found"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_get_source_image_returns_404_when_download_raises(sources_client):
    mock_ws = _make_mock_ws()
    mock_source = _make_mock_source()

    mock_page = MagicMock()
    mock_page.image_s3_keys = ["sources/src-abc/page1-photo.png"]

    source_result = MagicMock()
    source_result.scalar_one_or_none.return_value = mock_source

    pages_result = MagicMock()
    pages_result.scalars.return_value.all.return_value = [mock_page]

    session = MagicMock()
    session.execute = AsyncMock(side_effect=[source_result, pages_result])
    session.delete = AsyncMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with (
            patch(
                "app.routes.sources._ensure_workspace",
                new_callable=AsyncMock,
                return_value=mock_ws,
            ),
            patch(
                "app.routes.sources.download_file",
                side_effect=Exception("S3 error"),
            ),
        ):
            r = sources_client.get(f"/sources/{SOURCE_ID}/images/photo.png")
            assert r.status_code == 404
            assert r.json()["detail"] == "Image not found in storage"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_get_source_image_page_with_null_image_keys_skipped(sources_client):
    """Pages with image_s3_keys=None should not cause an error."""
    mock_ws = _make_mock_ws()
    mock_source = _make_mock_source()

    page_no_keys = MagicMock()
    page_no_keys.image_s3_keys = None

    page_with_keys = MagicMock()
    page_with_keys.image_s3_keys = ["sources/src-abc/page2-photo.png"]

    source_result = MagicMock()
    source_result.scalar_one_or_none.return_value = mock_source

    pages_result = MagicMock()
    pages_result.scalars.return_value.all.return_value = [page_no_keys, page_with_keys]

    session = MagicMock()
    session.execute = AsyncMock(side_effect=[source_result, pages_result])
    session.delete = AsyncMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with (
            patch(
                "app.routes.sources._ensure_workspace",
                new_callable=AsyncMock,
                return_value=mock_ws,
            ),
            patch(
                "app.routes.sources.download_file",
                return_value=b"\x89PNG",
            ),
        ):
            r = sources_client.get(f"/sources/{SOURCE_ID}/images/photo.png")
            assert r.status_code == 200
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# GET /sources/{source_id}/markdown
# ---------------------------------------------------------------------------


def test_get_source_markdown_returns_markdown_content(sources_client):
    mock_ws = _make_mock_ws()
    mock_source = _make_mock_source(markdown_s3_key="sources/doc.md")

    source_result = MagicMock()
    source_result.scalar_one_or_none.return_value = mock_source

    session = MagicMock()
    session.execute = AsyncMock(return_value=source_result)
    session.delete = AsyncMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with (
            patch(
                "app.routes.sources._ensure_workspace",
                new_callable=AsyncMock,
                return_value=mock_ws,
            ),
            patch(
                "app.routes.sources.download_file",
                return_value=b"# Heading\nContent here",
            ),
        ):
            r = sources_client.get(f"/sources/{SOURCE_ID}/markdown")
            assert r.status_code == 200
            assert r.content == b"# Heading\nContent here"
            assert "text/markdown" in r.headers["content-type"]
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_get_source_markdown_returns_404_when_source_not_found(sources_client):
    mock_ws = _make_mock_ws()

    source_result = MagicMock()
    source_result.scalar_one_or_none.return_value = None

    session = MagicMock()
    session.execute = AsyncMock(return_value=source_result)
    session.delete = AsyncMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch(
            "app.routes.sources._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            r = sources_client.get(f"/sources/{SOURCE_ID}/markdown")
            assert r.status_code == 404
            assert r.json()["detail"] == "Markdown not found"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_get_source_markdown_returns_404_when_no_markdown_s3_key(sources_client):
    mock_ws = _make_mock_ws()
    mock_source = _make_mock_source(markdown_s3_key=None)

    source_result = MagicMock()
    source_result.scalar_one_or_none.return_value = mock_source

    session = MagicMock()
    session.execute = AsyncMock(return_value=source_result)
    session.delete = AsyncMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch(
            "app.routes.sources._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            r = sources_client.get(f"/sources/{SOURCE_ID}/markdown")
            assert r.status_code == 404
            assert r.json()["detail"] == "Markdown not found"
    finally:
        app.dependency_overrides.pop(get_db, None)
