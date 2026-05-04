import pytest
from unittest.mock import AsyncMock, patch

from app.agents.health_agent import run


@pytest.mark.asyncio
async def test_health_run_writes_report(db_session, workspace_id):
    """Running the health agent should create meta/health-report."""
    from app.agents.tools import AgentTools

    # Create some pages first
    tools = AgentTools(session=db_session, workspace_id=workspace_id, broadcaster=None)
    await tools.write_page("people/alice", "# Alice\n\n[[concepts/missing-page]]", "A person", "Alice")
    await tools.write_page("concepts/knowledge", "# Knowledge\n\n", "Knowledge page", "Knowledge")

    # Run health agent (with LLM mocked to avoid real API calls)
    with (
        patch("app.agents.health_agent.litellm.acompletion", new_callable=AsyncMock) as mock_llm,
        patch("app.agents.health_agent.litellm.completion_cost", return_value=0.0),
    ):
        mock_response = AsyncMock()
        mock_response.choices = [AsyncMock()]
        mock_response.choices[0].message.tool_calls = None
        mock_response.choices[0].message.content = "Health check complete."
        mock_llm.return_value = mock_response

        await run(workspace_id=workspace_id, audience_user_id="test-user")

    # meta/health-report should now exist
    report = await tools.read_page("meta/health-report")
    assert not report.startswith("[Page 'meta/health-report' not found]")
