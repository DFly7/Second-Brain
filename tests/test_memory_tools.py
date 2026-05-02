import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tools import AgentTools

pytestmark = pytest.mark.no_database


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
