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


@pytest.mark.asyncio
async def test_list_source_pages_returns_previews():
    from unittest.mock import AsyncMock, MagicMock

    from app.agents.tools import AgentTools
    from app.models import SourcePage

    page1 = MagicMock(spec=SourcePage)
    page1.page_num = 1
    page1.preview = "# Intro"
    page1.image_s3_keys = []

    page2 = MagicMock(spec=SourcePage)
    page2.page_num = 2
    page2.preview = "## Methods"
    page2.image_s3_keys = ["ws/src/p2-img0.png"]

    mock_session = AsyncMock()
    scalar_result = MagicMock()
    scalar_result.scalars.return_value.all.return_value = [page1, page2]
    mock_session.execute = AsyncMock(return_value=scalar_result)

    tools = AgentTools(
        session=mock_session, workspace_id="ws-1", broadcaster=None, source_id="src-1"
    )
    result = await tools.list_source_pages()

    assert len(result) == 2
    assert result[0] == {"page_num": 1, "has_images": False, "preview": "# Intro"}
    assert result[1]["has_images"] is True


@pytest.mark.asyncio
async def test_read_source_page_no_images_returns_markdown():
    from unittest.mock import AsyncMock, MagicMock

    from app.agents.tools import AgentTools
    from app.models import SourcePage

    page = MagicMock(spec=SourcePage)
    page.markdown = "# Hello\n\nWorld"
    page.image_s3_keys = []

    mock_session = AsyncMock()
    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = page
    mock_session.execute = AsyncMock(return_value=scalar_result)

    tools = AgentTools(
        session=mock_session, workspace_id="ws-1", broadcaster=None, source_id="src-1"
    )
    result = await tools.read_source_page(1)

    assert result == "# Hello\n\nWorld"


@pytest.mark.asyncio
async def test_read_source_page_with_images_calls_vision_model():
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.agents.tools import AgentTools
    from app.models import SourcePage

    page = MagicMock(spec=SourcePage)
    page.markdown = "## Results"
    page.image_s3_keys = ["ws/src/p1-img0.png"]

    mock_session = AsyncMock()
    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = page
    mock_session.execute = AsyncMock(return_value=scalar_result)

    mock_vision_resp = MagicMock()
    mock_vision_resp.choices[0].message.content = "A bar chart showing revenue."

    with (
        patch("app.agents.tools.download_file", return_value=b"\x89PNG\r\n"),
        patch("app.agents.tools.settings") as mock_settings,
        patch(
            "app.agents.tools.litellm.acompletion",
            new_callable=AsyncMock,
            return_value=mock_vision_resp,
        ),
    ):
        mock_settings.vision_model = "gpt-4o"
        tools = AgentTools(
            session=mock_session,
            workspace_id="ws-1",
            broadcaster=None,
            source_id="src-1",
        )
        result = await tools.read_source_page(1)

    assert "## Results" in result
    assert "A bar chart showing revenue." in result


@pytest.mark.asyncio
async def test_dispatch_list_source_pages():
    from unittest.mock import AsyncMock

    from app.agents.tools import AgentTools

    tools = AgentTools(
        session=AsyncMock(), workspace_id="ws-1", broadcaster=None, source_id="src-1"
    )
    tools.list_source_pages = AsyncMock(return_value=[{"page_num": 1}])

    result = await tools.dispatch("list_source_pages", {})
    assert "page_num" in result
