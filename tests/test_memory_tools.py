import pytest
from unittest.mock import AsyncMock, MagicMock
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
async def test_append_to_existing_page(tools):
    tools.read_page = AsyncMock(return_value="# Existing\n\nOld content.")
    tools.write_page = AsyncMock(return_value="Page 'system/history' saved.")

    result = await tools.append_to_page("system/history", "## New Entry\nSome text.")

    tools.write_page.assert_called_once()
    written_body = tools.write_page.call_args[0][1]
    assert "Old content." in written_body
    assert "## New Entry" in written_body
    assert written_body.index("Old content.") < written_body.index("## New Entry")


@pytest.mark.asyncio
async def test_append_to_missing_page_creates_it(tools):
    tools.read_page = AsyncMock(return_value="[Page 'system/history' not found]")
    tools.write_page = AsyncMock(return_value="Page 'system/history' saved.")

    await tools.append_to_page("system/history", "## First Entry\nContent.")

    written_body = tools.write_page.call_args[0][1]
    assert written_body == "## First Entry\nContent."


@pytest.mark.asyncio
async def test_patch_page_replaces_unique_match(tools):
    tools.read_page = AsyncMock(
        return_value="## 2026-05-01 · abc\nOld summary.\n\n## 2026-05-02 · def\nOther."
    )
    tools.write_page = AsyncMock(return_value="Page 'system/history' saved.")

    result = await tools.patch_page("system/history", "Old summary.", "New summary.")

    written_body = tools.write_page.call_args[0][1]
    assert "New summary." in written_body
    assert "Old summary." not in written_body


@pytest.mark.asyncio
async def test_patch_page_fails_on_not_found(tools):
    tools.read_page = AsyncMock(return_value="Some content without the target.")
    tools.write_page = AsyncMock()

    result = await tools.patch_page("system/history", "missing text", "replacement")

    assert result == "patch failed: old_text not found in 'system/history'"
    tools.write_page.assert_not_called()


@pytest.mark.asyncio
async def test_patch_page_fails_on_multiple_matches(tools):
    tools.read_page = AsyncMock(return_value="duplicate\nduplicate\n")
    tools.write_page = AsyncMock()

    result = await tools.patch_page("system/history", "duplicate", "replacement")

    assert result == "patch failed: old_text matches 2 locations in 'system/history', be more specific"
    tools.write_page.assert_not_called()


@pytest.mark.asyncio
async def test_patch_page_fails_on_missing_page(tools):
    tools.read_page = AsyncMock(return_value="[Page 'system/history' not found]")
    tools.write_page = AsyncMock()

    result = await tools.patch_page("system/history", "anything", "replacement")

    assert result == "patch failed: page 'system/history' not found"
    tools.write_page.assert_not_called()
