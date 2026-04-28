import pytest
from unittest.mock import AsyncMock, MagicMock

from app.agents.tools import AgentTools


@pytest.mark.asyncio
async def test_list_pages_returns_list():
    mock_session = AsyncMock()

    mapping_result = MagicMock()
    mapping_result.all.return_value = [
        {"slug": "one", "title": "One", "summary": "First"},
        {"slug": "two", "title": "Two", "summary": "Second"},
    ]
    mock_result = MagicMock()
    mock_result.mappings.return_value = mapping_result
    mock_session.execute = AsyncMock(return_value=mock_result)

    tools = AgentTools(session=mock_session, workspace_id="ws-1", broadcaster=None)

    result = await tools.list_pages()

    assert isinstance(result, list)
    assert result[0]["slug"] == "one"
    assert result[1]["title"] == "Two"


@pytest.mark.asyncio
async def test_dispatch_create_page_passes_title():
    tools = AgentTools(session=AsyncMock(), workspace_id="ws-1", broadcaster=None)
    tools.create_page = AsyncMock(return_value="ok")

    result = await tools.dispatch(
        "create_page",
        {"slug": "slug-1", "title": "My Title", "body_md": "body", "summary": "sum"},
    )

    tools.create_page.assert_awaited_with("slug-1", "My Title", "body", "sum")
    assert result == "ok"


@pytest.mark.asyncio
async def test_extract_slugs_from_wikilinks():
    from app.wikilinks import extract_slugs

    slugs = extract_slugs("Hello [[page-one]] and [[page-two]].")
    assert "page-one" in slugs
    assert "page-two" in slugs
