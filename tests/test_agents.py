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


@pytest.mark.asyncio
async def test_orchestrator_reads_directly_for_small_docs():
    """Docs with <=20 pages go direct - no spawn_page_reader tool offered."""
    from app.agents import ingest_agent
    from unittest.mock import AsyncMock, MagicMock, patch

    final_resp = MagicMock()
    final_resp.choices[0].message.content = "done"
    final_resp.choices[0].message.tool_calls = []

    with (
        patch(
            "app.agents.ingest_agent.litellm.acompletion",
            new_callable=AsyncMock,
            return_value=final_resp,
        ) as mock_acompletion,
        patch("app.agents.ingest_agent.litellm.completion_cost", return_value=0.001),
        patch("app.agents.ingest_agent.AsyncSessionLocal") as MockSession,
        patch("app.agents.ingest_agent.broadcaster") as mock_broadcaster,
    ):
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.add = MagicMock()
        mock_broadcaster.publish = AsyncMock(return_value=None)

        # Simulate 5 source pages in DB
        from app.models import SourcePage

        pages = [MagicMock(spec=SourcePage, page_num=i) for i in range(1, 6)]
        page_result = MagicMock()
        page_result.scalars.return_value.all.return_value = pages

        source_result = MagicMock()
        source_result.scalar_one_or_none.return_value = MagicMock(id="src-1")

        mock_session.execute = AsyncMock(side_effect=[source_result, page_result])
        MockSession.return_value = mock_session

        await ingest_agent.run("src-1", "ws-1")

    call_args = mock_acompletion.call_args
    tools_passed = call_args.kwargs.get("tools", [])
    tool_names = [t["function"]["name"] for t in tools_passed]
    assert "spawn_page_reader" not in tool_names
    assert "read_source_page" in tool_names


@pytest.mark.asyncio
async def test_orchestrator_offers_spawn_for_large_docs():
    """Docs with >20 pages get the spawn_page_reader tool."""
    from app.agents import ingest_agent
    from unittest.mock import AsyncMock, MagicMock, patch

    final_resp = MagicMock()
    final_resp.choices[0].message.content = "done"
    final_resp.choices[0].message.tool_calls = []

    with (
        patch(
            "app.agents.ingest_agent.litellm.acompletion",
            new_callable=AsyncMock,
            return_value=final_resp,
        ) as mock_acompletion,
        patch("app.agents.ingest_agent.litellm.completion_cost", return_value=0.001),
        patch("app.agents.ingest_agent.AsyncSessionLocal") as MockSession,
        patch("app.agents.ingest_agent.broadcaster") as mock_broadcaster,
    ):
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.add = MagicMock()
        mock_broadcaster.publish = AsyncMock(return_value=None)

        from app.models import SourcePage

        pages = [MagicMock(spec=SourcePage, page_num=i) for i in range(1, 25)]  # 24 pages
        page_result = MagicMock()
        page_result.scalars.return_value.all.return_value = pages

        source_result = MagicMock()
        source_result.scalar_one_or_none.return_value = MagicMock(id="src-1")

        mock_session.execute = AsyncMock(side_effect=[source_result, page_result])
        MockSession.return_value = mock_session

        await ingest_agent.run("src-1", "ws-1")

    call_args = mock_acompletion.call_args
    tools_passed = call_args.kwargs.get("tools", [])
    tool_names = [t["function"]["name"] for t in tools_passed]
    assert "spawn_page_reader" in tool_names
