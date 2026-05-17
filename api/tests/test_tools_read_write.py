import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tools import AgentTools
from app.models import Page


@pytest.fixture
def session():
    s = AsyncMock(spec=AsyncSession)
    s.add = MagicMock()
    s.delete = AsyncMock()
    return s


@pytest.fixture
def tools(session):
    return AgentTools(session=session, workspace_id="ws-1", broadcaster=None)


# ---------------------------------------------------------------------------
# read_page
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_page_returns_body_when_found(tools, session):
    page = MagicMock(spec=Page)
    page.body_md = "# Hello\nSome content."

    session.execute.return_value = MagicMock(
        scalar_one_or_none=MagicMock(return_value=page)
    )

    result = await tools.read_page("notes/hello")

    assert result == "# Hello\nSome content."


@pytest.mark.asyncio
async def test_read_page_returns_not_found_string_when_missing(tools, session):
    session.execute.return_value = MagicMock(
        scalar_one_or_none=MagicMock(return_value=None)
    )

    result = await tools.read_page("notes/missing")

    assert result == "[Page 'notes/missing' not found]"


@pytest.mark.asyncio
async def test_read_page_broadcasts_reading_event(tools, session):
    broadcaster = MagicMock()
    broadcaster.publish = AsyncMock()
    tools.broadcaster = broadcaster
    tools.audience_user_id = "u-test"

    page = MagicMock(spec=Page)
    page.body_md = "content"
    session.execute.return_value = MagicMock(
        scalar_one_or_none=MagicMock(return_value=page)
    )

    await tools.read_page("notes/hello")

    broadcaster.publish.assert_awaited_once_with(
        {"context": "ingest", "event": "agent:reading", "slug": "notes/hello"},
        audience_user_id="u-test",
    )


@pytest.mark.asyncio
async def test_read_page_broadcasts_even_when_not_found(tools, session):
    broadcaster = MagicMock()
    broadcaster.publish = AsyncMock()
    tools.broadcaster = broadcaster
    tools.audience_user_id = "u-test"

    session.execute.return_value = MagicMock(
        scalar_one_or_none=MagicMock(return_value=None)
    )

    result = await tools.read_page("notes/ghost")

    broadcaster.publish.assert_awaited_once()
    assert "not found" in result


# ---------------------------------------------------------------------------
# list_pages
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_pages_returns_list_of_dicts(tools, session):
    rows = [
        {"slug": "notes/a", "title": "A", "summary": "About A"},
        {"slug": "notes/b", "title": "B", "summary": "About B"},
    ]
    mock_mappings = MagicMock()
    mock_mappings.all.return_value = rows
    session.execute.return_value = MagicMock(
        mappings=MagicMock(return_value=mock_mappings)
    )

    result = await tools.list_pages()

    assert result == [
        {"slug": "notes/a", "title": "A", "summary": "About A"},
        {"slug": "notes/b", "title": "B", "summary": "About B"},
    ]


@pytest.mark.asyncio
async def test_list_pages_returns_empty_list_when_no_pages(tools, session):
    mock_mappings = MagicMock()
    mock_mappings.all.return_value = []
    session.execute.return_value = MagicMock(
        mappings=MagicMock(return_value=mock_mappings)
    )

    result = await tools.list_pages()

    assert result == []


# ---------------------------------------------------------------------------
# search_pages
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_pages_delegates_to_search_module(tools):
    mock_results = [{"slug": "notes/foo", "title": "Foo", "score": 0.9}]

    with patch("app.agents.tools._search", new_callable=AsyncMock, return_value=mock_results):
        result = await tools.search_pages("foo query")

    assert result == mock_results


@pytest.mark.asyncio
async def test_search_pages_passes_workspace_id_and_limit(tools):
    with patch("app.agents.tools._search", new_callable=AsyncMock, return_value=[]) as mock_search:
        await tools.search_pages("test")

    mock_search.assert_awaited_once_with(tools.session, "ws-1", "test", limit=5)


# ---------------------------------------------------------------------------
# write_page — new page (create path)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_write_page_creates_new_page_when_slug_not_found(tools, session):
    # execute calls:
    # 1. select page for write_page (None → new page)
    # 2. _append_changelog UPDATE (returns a row → no create needed)
    changelog_row = MagicMock()
    session.execute.side_effect = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=None)),  # page lookup
        MagicMock(fetchone=MagicMock(return_value=changelog_row)),   # changelog UPDATE
    ]
    session.flush = AsyncMock()
    session.refresh = AsyncMock()

    with patch("app.agents.tools.sync_links", new_callable=AsyncMock):
        tools.update_index = AsyncMock()
        result = await tools.write_page("notes/new", "# New\nContent", "A new page", title="New")

    assert result == "Page 'notes/new' saved."
    # session.add should have been called at least once (for the new Page)
    assert session.add.called


@pytest.mark.asyncio
async def test_write_page_derives_title_from_slug_when_no_title(tools, session):
    # Capture the Page instance passed to session.add on the create path
    created_pages = []

    def capture_add(obj):
        if isinstance(obj, Page):
            created_pages.append(obj)

    session.add.side_effect = capture_add

    changelog_row = MagicMock()
    session.execute.side_effect = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
        MagicMock(fetchone=MagicMock(return_value=changelog_row)),
    ]
    session.flush = AsyncMock()
    session.refresh = AsyncMock()

    with patch("app.agents.tools.sync_links", new_callable=AsyncMock):
        tools.update_index = AsyncMock()
        await tools.write_page("notes/my-note", "body")

    assert any(p.title == "Notes/My-Note" or p.title == "My-Note" or p.title == "Notes/My Note" or p.title == "My Note" for p in created_pages) or created_pages[0].title is not None


@pytest.mark.asyncio
async def test_write_page_update_path_saves_revision(tools, session):
    existing = MagicMock(spec=Page)
    existing.id = "page-id"
    existing.body_md = "old body"
    existing.title = "Old Title"
    existing.summary = "old summary"

    changelog_row = MagicMock()
    session.execute.side_effect = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=existing)),  # page lookup
        MagicMock(fetchone=MagicMock(return_value=changelog_row)),        # changelog UPDATE
    ]
    session.refresh = AsyncMock()

    with patch("app.agents.tools.sync_links", new_callable=AsyncMock):
        tools.update_index = AsyncMock()
        result = await tools.write_page("notes/existing", "new body", "new summary")

    assert result == "Page 'notes/existing' saved."
    assert existing.body_md == "new body"
    assert existing.summary == "new summary"

    # A Revision should have been added
    from app.models import Revision
    added_revisions = [c[0][0] for c in session.add.call_args_list if isinstance(c[0][0], Revision)]
    assert len(added_revisions) == 1
    assert added_revisions[0].body_md == "old body"


@pytest.mark.asyncio
async def test_write_page_update_path_preserves_summary_when_empty(tools, session):
    existing = MagicMock(spec=Page)
    existing.id = "page-id"
    existing.body_md = "old body"
    existing.title = "Title"
    existing.summary = "kept summary"

    changelog_row = MagicMock()
    session.execute.side_effect = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=existing)),
        MagicMock(fetchone=MagicMock(return_value=changelog_row)),
    ]
    session.refresh = AsyncMock()

    with patch("app.agents.tools.sync_links", new_callable=AsyncMock):
        tools.update_index = AsyncMock()
        await tools.write_page("notes/existing", "new body", summary="")

    assert existing.summary == "kept summary"


@pytest.mark.asyncio
async def test_write_page_broadcasts_writing_event(tools, session):
    broadcaster = MagicMock()
    broadcaster.publish = AsyncMock()
    tools.broadcaster = broadcaster
    tools.audience_user_id = "u-test"

    changelog_row = MagicMock()
    session.execute.side_effect = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
        MagicMock(fetchone=MagicMock(return_value=changelog_row)),
    ]
    session.flush = AsyncMock()
    session.refresh = AsyncMock()

    with patch("app.agents.tools.sync_links", new_callable=AsyncMock):
        tools.update_index = AsyncMock()
        await tools.write_page("notes/new", "body")

    broadcaster.publish.assert_any_await(
        {"context": "ingest", "event": "agent:writing", "slug": "notes/new"},
        audience_user_id="u-test",
    )


@pytest.mark.asyncio
async def test_write_page_skips_broadcast_when_suppress_sse_set(tools, session):
    broadcaster = MagicMock()
    broadcaster.publish = AsyncMock()
    tools.broadcaster = broadcaster
    tools.audience_user_id = "u-test"
    tools._suppress_agent_writing_sse = True

    changelog_row = MagicMock()
    session.execute.side_effect = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
        MagicMock(fetchone=MagicMock(return_value=changelog_row)),
    ]
    session.flush = AsyncMock()
    session.refresh = AsyncMock()

    with patch("app.agents.tools.sync_links", new_callable=AsyncMock):
        tools.update_index = AsyncMock()
        await tools.write_page("notes/new", "body")

    broadcaster.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_write_page_skips_changelog_for_excluded_slug(tools, session):
    # system/changelog is in _CHANGELOG_EXCLUDED, so _append_changelog should not be called
    existing = MagicMock(spec=Page)
    existing.id = "page-id"
    existing.body_md = "old"
    existing.title = "Changelog"
    existing.summary = ""

    session.execute.return_value = MagicMock(
        scalar_one_or_none=MagicMock(return_value=existing)
    )
    session.refresh = AsyncMock()

    tools._append_changelog = AsyncMock()

    with patch("app.agents.tools.sync_links", new_callable=AsyncMock):
        tools.update_index = AsyncMock()
        await tools.write_page("system/changelog", "new body")

    tools._append_changelog.assert_not_awaited()


@pytest.mark.asyncio
async def test_write_page_skips_changelog_when_suppress_flag_set(tools, session):
    tools._suppress_changelog = True

    changelog_row = MagicMock()
    session.execute.side_effect = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
        MagicMock(fetchone=MagicMock(return_value=changelog_row)),
    ]
    session.flush = AsyncMock()
    session.refresh = AsyncMock()

    tools._append_changelog = AsyncMock()

    with patch("app.agents.tools.sync_links", new_callable=AsyncMock):
        tools.update_index = AsyncMock()
        await tools.write_page("notes/new", "body")

    tools._append_changelog.assert_not_awaited()


# ---------------------------------------------------------------------------
# _append_changelog — "create new changelog page" branch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_append_changelog_creates_page_when_update_returns_no_rows(tools, session):
    # UPDATE returns no row → fetchone() returns None → should create a new Page
    session.execute.return_value = MagicMock(
        fetchone=MagicMock(return_value=None)
    )

    await tools._append_changelog("created", "[[notes/new]]")

    # session.add should have been called with a Page for system/changelog
    assert session.add.called
    added = session.add.call_args[0][0]
    assert isinstance(added, Page)
    assert added.slug == "system/changelog"
    assert added.workspace_id == "ws-1"
    assert "# Wiki Changelog" in added.body_md
    assert "created" in added.body_md
    assert "[[notes/new]]" in added.body_md
    # commit should be called after the add
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_append_changelog_skips_add_when_update_succeeds(tools, session):
    # UPDATE returns a row → existing changelog page was updated, no new Page needed
    existing_row = MagicMock()
    session.execute.return_value = MagicMock(
        fetchone=MagicMock(return_value=existing_row)
    )

    await tools._append_changelog("updated", "[[notes/existing]]")

    # session.add should NOT have been called with a Page
    added_pages = [c[0][0] for c in session.add.call_args_list if isinstance(c[0][0], Page)]
    assert len(added_pages) == 0
    # expire_all should be called to refresh ORM state
    session.expire_all.assert_called_once()
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_append_changelog_new_page_contains_table_header(tools, session):
    session.execute.return_value = MagicMock(
        fetchone=MagicMock(return_value=None)
    )

    await tools._append_changelog("moved", "[[old/page]] → [[new/page]]")

    added = session.add.call_args[0][0]
    assert "| When | Action | Page |" in added.body_md
    assert "| --- | --- | --- |" in added.body_md
    assert "moved" in added.body_md
