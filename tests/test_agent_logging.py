import pytest
import structlog.testing
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_ingest_agent_logs_start_and_done():
    mock_source = MagicMock()
    mock_source.id = "src-1"

    mock_page = MagicMock()
    mock_page.page_num = 1
    mock_page.markdown = "hello"

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock()
    mock_session.execute.return_value.scalar_one_or_none = MagicMock(return_value=mock_source)
    mock_session.execute.return_value.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[mock_page])))
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    mock_broadcaster = AsyncMock()

    with structlog.testing.capture_logs() as cap:
        with patch("app.agents.ingest_agent.AsyncSessionLocal", return_value=mock_session):
            with patch("app.agents.ingest_agent.broadcaster", mock_broadcaster):
                with patch("app.agents.ingest_agent.litellm.acompletion", new_callable=AsyncMock) as mock_llm:
                    mock_msg = MagicMock()
                    mock_msg.tool_calls = None
                    mock_msg.content = "done"
                    mock_resp = MagicMock()
                    mock_resp.choices = [MagicMock(message=mock_msg)]
                    mock_llm.return_value = mock_resp
                    from app.agents import ingest_agent
                    await ingest_agent.run("src-1", "ws-1", "user-1")

    events = [e["event"] for e in cap]
    assert "ingest_agent_start" in events
    assert "ingest_agent_done" in events


@pytest.mark.asyncio
async def test_query_agent_logs_start_and_answer():
    mock_session = AsyncMock()
    mock_tools = AsyncMock()
    mock_tools.as_litellm_tools = MagicMock(return_value=[])
    mock_tools.read_page = AsyncMock(return_value="[Page 'system/memory' not found]")
    mock_tools.dispatch = AsyncMock(return_value="result")

    mock_broadcaster = AsyncMock()

    with structlog.testing.capture_logs() as cap:
        with patch("app.agents.query_agent.AgentTools", return_value=mock_tools):
            with patch("app.agents.query_agent.broadcaster", mock_broadcaster):
                with patch("app.agents.query_agent.litellm.acompletion", new_callable=AsyncMock) as mock_llm:
                    mock_msg = MagicMock()
                    mock_msg.tool_calls = None
                    mock_msg.content = "The answer is 42."
                    mock_resp = MagicMock()
                    mock_resp.choices = [MagicMock(message=mock_msg)]
                    mock_llm.return_value = mock_resp
                    from app.agents import query_agent
                    answer, _ = await query_agent.run("ws-1", "what is 42?", [], mock_session, "user-1")

    events = [e["event"] for e in cap]
    assert "query_agent_start" in events
    assert "query_agent_answer" in events
