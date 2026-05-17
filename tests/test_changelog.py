import pytest
from sqlalchemy import select

from app.agents.tools import AgentTools
from app.models import Page


@pytest.fixture
def tools(db_session, workspace_id):
    return AgentTools(session=db_session, workspace_id=workspace_id, broadcaster=None)


@pytest.mark.asyncio
async def test_append_changelog_creates_page_on_first_call(tools, db_session, workspace_id):
    await tools._append_changelog("created", "[[trips/paris]]")

    result = await db_session.execute(
        select(Page).where(
            Page.slug == "system/changelog", Page.workspace_id == workspace_id
        )
    )
    page = result.scalar_one_or_none()
    assert page is not None
    assert "| When | Action | Page |" in page.body_md
    assert "created" in page.body_md
    assert "trips/paris" in page.body_md


@pytest.mark.asyncio
async def test_append_changelog_appends_subsequent_calls(tools, db_session, workspace_id):
    await tools._append_changelog("created", "[[trips/paris]]")
    await tools._append_changelog("updated", "[[trips/paris]]")

    result = await db_session.execute(
        select(Page).where(
            Page.slug == "system/changelog", Page.workspace_id == workspace_id
        )
    )
    page = result.scalar_one_or_none()
    assert page.body_md.count("trips/paris") == 2
    assert "created" in page.body_md
    assert "updated" in page.body_md


@pytest.mark.asyncio
async def test_append_changelog_deleted_entry(tools, db_session, workspace_id):
    await tools._append_changelog("deleted", "notes/scratch")

    result = await db_session.execute(
        select(Page).where(
            Page.slug == "system/changelog", Page.workspace_id == workspace_id
        )
    )
    page = result.scalar_one_or_none()
    assert "deleted" in page.body_md
    assert "notes/scratch" in page.body_md


@pytest.mark.asyncio
async def test_append_changelog_moved_entry(tools, db_session, workspace_id):
    await tools._append_changelog("moved", "[[archive/old]] ← [[projects/old]]")

    result = await db_session.execute(
        select(Page).where(
            Page.slug == "system/changelog", Page.workspace_id == workspace_id
        )
    )
    page = result.scalar_one_or_none()
    assert "moved" in page.body_md
    assert "archive/old" in page.body_md
    assert "projects/old" in page.body_md


@pytest.mark.asyncio
async def test_write_page_logs_to_changelog(db_session, workspace_id):
    tools = AgentTools(session=db_session, workspace_id=workspace_id, broadcaster=None)
    await tools.write_page("trips/paris", "# Paris\n\nRoad trip notes.", summary="Paris trip")

    result = await db_session.execute(
        select(Page).where(
            Page.slug == "system/changelog", Page.workspace_id == workspace_id
        )
    )
    page = result.scalar_one_or_none()
    assert page is not None
    assert "trips/paris" in page.body_md


@pytest.mark.asyncio
async def test_write_page_excluded_slugs_not_logged(db_session, workspace_id):
    tools = AgentTools(session=db_session, workspace_id=workspace_id, broadcaster=None)
    await tools.write_page("system/memory", "# Memory\n\nSome facts.")

    result = await db_session.execute(
        select(Page).where(
            Page.slug == "system/changelog", Page.workspace_id == workspace_id
        )
    )
    # system/memory writes must not create a changelog entry
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_delete_page_logs_to_changelog(db_session, workspace_id):
    tools = AgentTools(session=db_session, workspace_id=workspace_id, broadcaster=None)
    await tools.write_page("notes/scratch", "# Scratch\n\nTemp.")
    await tools.delete_page("notes/scratch")

    result = await db_session.execute(
        select(Page).where(
            Page.slug == "system/changelog", Page.workspace_id == workspace_id
        )
    )
    page = result.scalar_one_or_none()
    assert page is not None
    assert "deleted" in page.body_md
    assert "notes/scratch" in page.body_md


@pytest.mark.asyncio
async def test_move_page_logs_single_moved_entry(db_session, workspace_id):
    tools = AgentTools(session=db_session, workspace_id=workspace_id, broadcaster=None)
    await tools.write_page("projects/old", "# Old\n\nContent.")
    # Reset changelog so we have a clean slate for the move
    result = await db_session.execute(
        select(Page).where(
            Page.slug == "system/changelog", Page.workspace_id == workspace_id
        )
    )
    changelog = result.scalar_one_or_none()
    if changelog:
        changelog.body_md = "# Wiki Changelog\n\n| When | Action | Page |\n| --- | --- | --- |"
        await db_session.commit()

    await tools.move_page("projects/old", "archive/old")

    result = await db_session.execute(
        select(Page).where(
            Page.slug == "system/changelog", Page.workspace_id == workspace_id
        )
    )
    page = result.scalar_one_or_none()
    assert page is not None
    assert "moved" in page.body_md
    assert "archive/old" in page.body_md
    assert "projects/old" in page.body_md
    # Should have exactly one "moved" entry, not a "created" entry from the internal write
    assert page.body_md.count("| moved |") == 1
    assert "| created |" not in page.body_md.split("# Wiki Changelog")[1]
