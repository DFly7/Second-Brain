"""Tests for /wiki routes (list, create, get, update, delete pages)."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.database import get_db
from app.main import app

USER = "test@example.com"


@pytest.fixture
def wiki_client():
    async def override_user():
        return USER

    app.dependency_overrides[get_current_user] = override_user
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


def _make_page(
    id="page-1",
    slug="people/alice",
    title="Alice",
    summary="A person",
    body_md="# Alice",
    updated_at=None,
):
    page = MagicMock()
    page.id = id
    page.slug = slug
    page.title = title
    page.summary = summary
    page.body_md = body_md
    page.updated_at = updated_at or datetime(2026, 1, 1, 12, 0, 0)
    return page


def _make_ws(id="ws-1"):
    ws = MagicMock()
    ws.id = id
    return ws


# ---------------------------------------------------------------------------
# GET /wiki/pages
# ---------------------------------------------------------------------------


def test_list_pages_returns_all_pages(wiki_client):
    mock_ws = _make_ws()
    p1 = _make_page(id="p1", slug="people/alice", updated_at=datetime(2026, 2, 1))
    p2 = _make_page(id="p2", slug="notes/foo", updated_at=datetime(2026, 1, 1))

    db_result = MagicMock()
    db_result.scalars.return_value.all.return_value = [p1, p2]

    session = MagicMock()
    session.execute = AsyncMock(return_value=db_result)

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    try:
        with patch(
            "app.routes.wiki._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            r = wiki_client.get("/wiki/pages")
            assert r.status_code == 200
            data = r.json()
            assert len(data) == 2
            assert data[0]["slug"] == "people/alice"
            assert data[1]["slug"] == "notes/foo"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_list_pages_returns_empty_list(wiki_client):
    mock_ws = _make_ws()

    db_result = MagicMock()
    db_result.scalars.return_value.all.return_value = []

    session = MagicMock()
    session.execute = AsyncMock(return_value=db_result)

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    try:
        with patch(
            "app.routes.wiki._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            r = wiki_client.get("/wiki/pages")
            assert r.status_code == 200
            assert r.json() == []
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# POST /wiki/pages
# ---------------------------------------------------------------------------


def test_create_page_success(wiki_client):
    mock_ws = _make_ws()
    new_page = _make_page(slug="people/bob", title="Bob", body_md="# Bob", summary="")

    # execute calls: 1) check existing (returns None), no further executes
    no_existing = MagicMock()
    no_existing.scalar_one_or_none.return_value = None

    session = MagicMock()
    session.execute = AsyncMock(return_value=no_existing)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()

    # After refresh the page object should be returned as-is
    async def fake_refresh(obj):
        obj.id = new_page.id
        obj.slug = new_page.slug
        obj.title = new_page.title
        obj.summary = new_page.summary
        obj.body_md = new_page.body_md
        obj.updated_at = new_page.updated_at

    session.refresh.side_effect = fake_refresh

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    try:
        with (
            patch(
                "app.routes.wiki._ensure_workspace",
                new_callable=AsyncMock,
                return_value=mock_ws,
            ),
            patch("app.routes.wiki.sync_links", new_callable=AsyncMock),
        ):
            r = wiki_client.post(
                "/wiki/pages",
                json={"slug": "people/bob", "title": "Bob", "body_md": "# Bob"},
            )
            assert r.status_code == 201
            data = r.json()
            assert data["slug"] == "people/bob"
            assert data["title"] == "Bob"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_create_page_conflict_returns_409(wiki_client):
    mock_ws = _make_ws()
    existing_page = _make_page(slug="people/alice")

    existing_result = MagicMock()
    existing_result.scalar_one_or_none.return_value = existing_page

    session = MagicMock()
    session.execute = AsyncMock(return_value=existing_result)

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    try:
        with patch(
            "app.routes.wiki._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            r = wiki_client.post(
                "/wiki/pages",
                json={"slug": "people/alice", "title": "Alice"},
            )
            assert r.status_code == 409
            assert "already exists" in r.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_create_page_missing_required_fields_returns_422(wiki_client):
    async def override_db():
        yield MagicMock()

    app.dependency_overrides[get_db] = override_db
    try:
        # slug and title are required
        r = wiki_client.post("/wiki/pages", json={"body_md": "no slug or title"})
        assert r.status_code == 422
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# GET /wiki/pages/{slug}
# ---------------------------------------------------------------------------


def test_get_page_success(wiki_client):
    mock_ws = _make_ws()
    page = _make_page(slug="people/alice", title="Alice")

    page_result = MagicMock()
    page_result.scalar_one_or_none.return_value = page

    session = MagicMock()
    session.execute = AsyncMock(return_value=page_result)

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    try:
        with patch(
            "app.routes.wiki._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            r = wiki_client.get("/wiki/pages/people/alice")
            assert r.status_code == 200
            data = r.json()
            assert data["slug"] == "people/alice"
            assert data["title"] == "Alice"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_get_page_not_found_returns_404(wiki_client):
    mock_ws = _make_ws()

    not_found = MagicMock()
    not_found.scalar_one_or_none.return_value = None

    session = MagicMock()
    session.execute = AsyncMock(return_value=not_found)

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    try:
        with patch(
            "app.routes.wiki._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            r = wiki_client.get("/wiki/pages/does/not/exist")
            assert r.status_code == 404
            assert r.json()["detail"] == "Page not found"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_get_page_nested_slug_path(wiki_client):
    """Slug path parameter captures slashes via {slug:path}."""
    mock_ws = _make_ws()
    page = _make_page(slug="projects/2026/alpha", title="Alpha")

    page_result = MagicMock()
    page_result.scalar_one_or_none.return_value = page

    session = MagicMock()
    session.execute = AsyncMock(return_value=page_result)

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    try:
        with patch(
            "app.routes.wiki._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            r = wiki_client.get("/wiki/pages/projects/2026/alpha")
            assert r.status_code == 200
            assert r.json()["slug"] == "projects/2026/alpha"
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# PUT /wiki/pages/{slug}
# ---------------------------------------------------------------------------


def test_update_page_success(wiki_client):
    mock_ws = _make_ws()
    page = _make_page(slug="people/alice", title="Alice", body_md="old body")

    page_result = MagicMock()
    page_result.scalar_one_or_none.return_value = page

    session = MagicMock()
    session.execute = AsyncMock(return_value=page_result)
    session.commit = AsyncMock()
    session.add = MagicMock()

    async def fake_refresh(obj):
        # simulate the DB reflecting the update
        obj.title = "Alice Updated"
        obj.body_md = "new body"

    session.refresh = AsyncMock(side_effect=fake_refresh)

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    try:
        with (
            patch(
                "app.routes.wiki._ensure_workspace",
                new_callable=AsyncMock,
                return_value=mock_ws,
            ),
            patch("app.routes.wiki.sync_links", new_callable=AsyncMock),
        ):
            r = wiki_client.put(
                "/wiki/pages/people/alice",
                json={"title": "Alice Updated", "body_md": "new body"},
            )
            assert r.status_code == 200
            data = r.json()
            assert data["title"] == "Alice Updated"
            assert data["body_md"] == "new body"
            # Revision should have been added
            session.add.assert_called()
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_update_page_not_found_returns_404(wiki_client):
    mock_ws = _make_ws()

    not_found = MagicMock()
    not_found.scalar_one_or_none.return_value = None

    session = MagicMock()
    session.execute = AsyncMock(return_value=not_found)

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    try:
        with patch(
            "app.routes.wiki._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            r = wiki_client.put(
                "/wiki/pages/missing/page",
                json={"title": "Should Fail"},
            )
            assert r.status_code == 404
            assert r.json()["detail"] == "Page not found"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_update_page_partial_update_only_summary(wiki_client):
    """PUT with only summary — title and body_md unchanged, sync_links NOT called."""
    mock_ws = _make_ws()
    page = _make_page(slug="notes/foo", title="Foo", body_md="original body")

    page_result = MagicMock()
    page_result.scalar_one_or_none.return_value = page

    session = MagicMock()
    session.execute = AsyncMock(return_value=page_result)
    session.commit = AsyncMock()
    session.add = MagicMock()
    session.refresh = AsyncMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    try:
        with (
            patch(
                "app.routes.wiki._ensure_workspace",
                new_callable=AsyncMock,
                return_value=mock_ws,
            ),
            patch("app.routes.wiki.sync_links", new_callable=AsyncMock) as mock_sync,
        ):
            r = wiki_client.put(
                "/wiki/pages/notes/foo",
                json={"summary": "updated summary"},
            )
            assert r.status_code == 200
            # sync_links should not have been called — body_md not changed
            mock_sync.assert_not_called()
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_update_page_body_triggers_sync_links(wiki_client):
    """PUT with body_md — sync_links must be called."""
    mock_ws = _make_ws()
    page = _make_page(slug="notes/bar", title="Bar", body_md="old")

    page_result = MagicMock()
    page_result.scalar_one_or_none.return_value = page

    session = MagicMock()
    session.execute = AsyncMock(return_value=page_result)
    session.commit = AsyncMock()
    session.add = MagicMock()
    session.refresh = AsyncMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    try:
        with (
            patch(
                "app.routes.wiki._ensure_workspace",
                new_callable=AsyncMock,
                return_value=mock_ws,
            ),
            patch("app.routes.wiki.sync_links", new_callable=AsyncMock) as mock_sync,
        ):
            r = wiki_client.put(
                "/wiki/pages/notes/bar",
                json={"body_md": "[[new link]]"},
            )
            assert r.status_code == 200
            mock_sync.assert_awaited_once()
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# DELETE /wiki/pages/{slug}
# ---------------------------------------------------------------------------


def test_delete_page_success(wiki_client):
    mock_ws = _make_ws()
    page = _make_page(slug="people/alice", id="page-abc")

    page_result = MagicMock()
    page_result.scalar_one_or_none.return_value = page

    # Two execute calls: 1) select page, 2) delete revisions
    delete_result = MagicMock()

    session = MagicMock()
    session.execute = AsyncMock(side_effect=[page_result, delete_result])
    session.delete = AsyncMock()
    session.commit = AsyncMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    try:
        with patch(
            "app.routes.wiki._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            r = wiki_client.delete("/wiki/pages/people/alice")
            assert r.status_code == 204
            session.delete.assert_awaited_once_with(page)
            session.commit.assert_awaited_once()
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_delete_page_not_found_returns_404(wiki_client):
    mock_ws = _make_ws()

    not_found = MagicMock()
    not_found.scalar_one_or_none.return_value = None

    session = MagicMock()
    session.execute = AsyncMock(return_value=not_found)
    session.delete = AsyncMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    try:
        with patch(
            "app.routes.wiki._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            r = wiki_client.delete("/wiki/pages/ghost/page")
            assert r.status_code == 404
            assert r.json()["detail"] == "Page not found"
            session.delete.assert_not_awaited()
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_delete_page_nested_slug(wiki_client):
    mock_ws = _make_ws()
    page = _make_page(slug="a/b/c", id="page-xyz")

    page_result = MagicMock()
    page_result.scalar_one_or_none.return_value = page

    delete_result = MagicMock()

    session = MagicMock()
    session.execute = AsyncMock(side_effect=[page_result, delete_result])
    session.delete = AsyncMock()
    session.commit = AsyncMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    try:
        with patch(
            "app.routes.wiki._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            r = wiki_client.delete("/wiki/pages/a/b/c")
            assert r.status_code == 204
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# PageOut schema
# ---------------------------------------------------------------------------


def test_list_pages_response_shape(wiki_client):
    """Each item in the list should have all PageOut fields."""
    mock_ws = _make_ws()
    page = _make_page(
        id="p-1",
        slug="notes/test",
        title="Test",
        summary="A summary",
        body_md="## Hello",
        updated_at=datetime(2026, 3, 15, 9, 0, 0),
    )

    db_result = MagicMock()
    db_result.scalars.return_value.all.return_value = [page]

    session = MagicMock()
    session.execute = AsyncMock(return_value=db_result)

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    try:
        with patch(
            "app.routes.wiki._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            r = wiki_client.get("/wiki/pages")
            assert r.status_code == 200
            item = r.json()[0]
            assert item["id"] == "p-1"
            assert item["slug"] == "notes/test"
            assert item["title"] == "Test"
            assert item["summary"] == "A summary"
            assert item["body_md"] == "## Hello"
            assert "updated_at" in item
    finally:
        app.dependency_overrides.pop(get_db, None)
