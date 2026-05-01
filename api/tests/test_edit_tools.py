import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tools import AgentTools


@pytest.fixture
def session():
    s = AsyncMock(spec=AsyncSession)
    s.add = MagicMock()
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
