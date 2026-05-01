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
