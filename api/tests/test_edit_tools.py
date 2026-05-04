import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tools import AgentTools


@pytest.fixture
def session():
    s = AsyncMock(spec=AsyncSession)
    s.add = MagicMock()
    s.delete = MagicMock()
    return s


@pytest.fixture
def tools(session):
    return AgentTools(session=session, workspace_id="ws-1", broadcaster=None)


@pytest.mark.asyncio
async def test_remove_from_index_removes_entry(tools):
    index_body = (
        "# Wiki Index\n\n_Last updated: 2026-01-01_\n\n"
        "## people/ (2 pages)\n"
        "- [[people/alice]] — Alice\n"
        "- [[people/bob]] — Bob\n"
    )
    tools.read_page = AsyncMock(return_value=index_body)
    tools.write_page = AsyncMock(return_value="saved")

    await tools._remove_from_index("people/alice")

    written_body = tools.write_page.call_args[0][1]
    assert "people/alice" not in written_body
    assert "people/bob" in written_body


@pytest.mark.asyncio
async def test_remove_from_index_no_op_when_missing(tools):
    tools.read_page = AsyncMock(return_value="[Page 'meta/index' not found]")
    tools.write_page = AsyncMock()

    await tools._remove_from_index("people/alice")

    tools.write_page.assert_not_called()


@pytest.mark.asyncio
async def test_do_move_page_copies_and_deletes(tools, session):
    from app.models import Page

    old_page = MagicMock(spec=Page)
    old_page.id = "old-id"
    old_page.title = "Alice"
    old_page.body_md = "Content here."
    old_page.summary = "About Alice"

    # execute calls in order:
    # 1. check new_slug exists → None
    # 2. get old_page by old_slug → old_page
    # 3. query incoming PageLinks → empty list
    session.execute.side_effect = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=old_page)),
        MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        MagicMock(),  # delete PageLinks statement
    ]

    tools.write_page = AsyncMock(return_value="saved")
    tools._remove_from_index = AsyncMock()

    await tools._do_move_page("people/alice", "people/alice-jones")

    tools.write_page.assert_called_once_with(
        "people/alice-jones", old_page.body_md, old_page.summary, title=old_page.title
    )
    tools._remove_from_index.assert_called_once_with("people/alice")
    session.delete.assert_called_once_with(old_page)
    session.commit.assert_called()


@pytest.mark.asyncio
async def test_do_move_page_raises_on_collision(tools, session):
    from app.models import Page

    existing = MagicMock(spec=Page)
    session.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=existing))

    with pytest.raises(ValueError, match="already exists"):
        await tools._do_move_page("people/alice", "people/bob")


@pytest.mark.asyncio
async def test_do_move_page_rewrites_backlinks(tools, session):
    from app.models import Page, PageLink

    old_page = MagicMock(spec=Page)
    old_page.id = "old-id"
    old_page.title = "Alice"
    old_page.body_md = "Old content."
    old_page.summary = ""

    linking_page = MagicMock(spec=Page)
    linking_page.id = "linker-id"
    linking_page.slug = "projects/alpha"
    linking_page.body_md = "See [[people/alice]] for details."
    linking_page.workspace_id = "ws-1"

    link = MagicMock(spec=PageLink)
    link.from_page_id = "linker-id"

    session.execute.side_effect = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=None)),  # new_slug check
        MagicMock(scalar_one_or_none=MagicMock(return_value=old_page)),  # get old page
        MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[link])))
        ),  # incoming links
        MagicMock(scalar_one_or_none=MagicMock(return_value=linking_page)),  # get linking page
        MagicMock(),  # delete PageLinks
    ]

    tools.write_page = AsyncMock(return_value="saved")
    tools._remove_from_index = AsyncMock()

    with patch("app.agents.tools.sync_links", new_callable=AsyncMock):
        await tools._do_move_page("people/alice", "people/alice-jones")

    assert "[[people/alice-jones]]" in linking_page.body_md
    assert "[[people/alice]]" not in linking_page.body_md


@pytest.mark.asyncio
async def test_move_page_invalid_slug_returns_error(tools):
    broadcaster = MagicMock()
    broadcaster.publish = AsyncMock()
    tools.broadcaster = broadcaster

    out = await tools.dispatch(
        "move_page",
        {"old_slug": "people/alice", "new_slug": "Bad/Slug"},
    )

    assert "invalid" in out.lower() or "Invalid" in out
    broadcaster.publish.assert_not_called()


@pytest.mark.asyncio
async def test_move_page_collision_returns_error(tools, session):
    from app.models import Page

    existing = MagicMock(spec=Page)
    session.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=existing))

    out = await tools.dispatch(
        "move_page",
        {"old_slug": "people/alice", "new_slug": "people/bob"},
    )

    assert "already exists" in out


@pytest.mark.asyncio
async def test_move_page_broadcasts_and_returns_success(tools):
    broadcaster = MagicMock()
    broadcaster.publish = AsyncMock()
    tools.broadcaster = broadcaster
    tools.audience_user_id = "u-test"
    tools._do_move_page = AsyncMock()

    out = await tools.dispatch(
        "move_page",
        {"old_slug": "people/alice", "new_slug": "people/alice-jones"},
    )

    tools._do_move_page.assert_awaited_once_with("people/alice", "people/alice-jones")
    broadcaster.publish.assert_awaited_once_with(
        {"event": "agent:moving", "from": "people/alice", "to": "people/alice-jones"},
        audience_user_id="u-test",
    )
    assert "moved" in out.lower()


@pytest.mark.asyncio
async def test_do_delete_page_removes_and_rewrites_backlinks(tools, session):
    from app.models import Page, PageLink

    page = MagicMock(spec=Page)
    page.id = "del-id"
    page.title = "Alice"
    page.slug = "people/alice"

    linking_page = MagicMock(spec=Page)
    linking_page.id = "linker-id"
    linking_page.slug = "projects/alpha"
    linking_page.body_md = "See [[people/alice]] for details."
    linking_page.workspace_id = "ws-1"

    link = MagicMock(spec=PageLink)
    link.from_page_id = "linker-id"

    session.execute.side_effect = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=page)),
        MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[link])))
        ),
        MagicMock(scalar_one_or_none=MagicMock(return_value=linking_page)),
        MagicMock(),  # delete PageLinks
    ]

    session.flush = AsyncMock()

    with patch("app.agents.tools.sync_links", new_callable=AsyncMock):
        title = await tools._do_delete_page("people/alice")

    assert title == "Alice"
    assert "[[people/alice]] *(page deleted)*" in linking_page.body_md
    assert linking_page.body_md.count("[[people/alice]]") == 1
    session.delete.assert_called_once_with(page)
    session.commit.assert_called()


@pytest.mark.asyncio
async def test_delete_page_not_found_returns_error(tools, session):
    session.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))

    out = await tools.dispatch("delete_page", {"slug": "people/nobody"})

    assert "not found" in out.lower()


@pytest.mark.asyncio
async def test_delete_page_broadcasts_and_appends_log(tools):
    broadcaster = MagicMock()
    broadcaster.publish = AsyncMock()
    tools.broadcaster = broadcaster
    tools.audience_user_id = "u-test"
    tools._do_delete_page = AsyncMock(return_value="Gone Title")
    tools._remove_from_index = AsyncMock()
    tools._append_deleted_log = AsyncMock()

    out = await tools.dispatch("delete_page", {"slug": "people/alice"})

    tools._do_delete_page.assert_awaited_once_with("people/alice")
    tools._remove_from_index.assert_awaited_once_with("people/alice")
    tools._append_deleted_log.assert_awaited_once_with("people/alice", "Gone Title")
    broadcaster.publish.assert_awaited_once_with(
        {"event": "agent:deleting", "slug": "people/alice"},
        audience_user_id="u-test",
    )
    assert "deleted" in out.lower()


@pytest.mark.asyncio
async def test_move_folder_invalid_prefix_returns_error(tools):
    result = await tools.move_folder("PROJECTS/2025", "archive/2025")
    assert "invalid" in result.lower()


@pytest.mark.asyncio
async def test_move_folder_empty_source_returns_error(tools, session):
    session.execute.return_value = MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    )
    result = await tools.move_folder("projects/2025", "archive/2025")
    assert "no pages" in result.lower()


@pytest.mark.asyncio
async def test_move_folder_collision_returns_error(tools, session):
    from app.models import Page

    src = MagicMock(spec=Page)
    src.slug = "projects/2025/alpha"
    conflict = MagicMock(spec=Page)
    conflict.slug = "archive/2025/alpha"

    session.execute.side_effect = [
        MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[src])))),
        MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[conflict])))),
    ]
    result = await tools.move_folder("projects/2025", "archive/2025")
    assert "conflict" in result.lower() or "already" in result.lower()


@pytest.mark.asyncio
async def test_move_folder_moves_all_and_broadcasts(tools, session):
    from app.models import Page

    page_a = MagicMock(spec=Page)
    page_a.slug = "projects/2025/alpha"
    page_b = MagicMock(spec=Page)
    page_b.slug = "projects/2025/beta"

    session.execute.side_effect = [
        MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[page_a, page_b])))),
        MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),  # no collisions
    ]

    tools._do_move_page = AsyncMock()
    broadcaster = AsyncMock()
    tools.broadcaster = broadcaster
    tools.audience_user_id = "u-test"

    result = await tools.move_folder("projects/2025", "archive/2025")

    assert tools._do_move_page.call_count == 2
    tools._do_move_page.assert_any_call("projects/2025/alpha", "archive/2025/alpha")
    tools._do_move_page.assert_any_call("projects/2025/beta", "archive/2025/beta")
    broadcaster.publish.assert_awaited_once_with(
        {
            "event": "agent:moved_folder",
            "from": "projects/2025",
            "to": "archive/2025",
            "count": 2,
        },
        audience_user_id="u-test",
    )
    assert "2 pages" in result


@pytest.mark.asyncio
async def test_move_folder_suppresses_writing_sse_while_moving(tools, session):
    from app.models import Page

    page_a = MagicMock(spec=Page)
    page_a.slug = "projects/2025/alpha"

    session.execute.side_effect = [
        MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[page_a])))),
        MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
    ]

    seen: list[bool] = []

    async def tracking_do_move(old, new):
        seen.append(tools._suppress_agent_writing_sse)

    tools._do_move_page = tracking_do_move

    await tools.move_folder("projects/2025", "archive/2025")

    assert seen == [True]
    assert tools._suppress_agent_writing_sse is False
