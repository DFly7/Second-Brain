import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_sub_agent_returns_string_summary():
    from app.agents import sub_agent

    # Mock litellm: first call returns tool call to read page 1, second returns final answer
    page_content_resp = MagicMock()
    page_content_resp.choices[0].message.content = None
    page_content_resp.choices[0].message.tool_calls = [
        MagicMock(
            id="tc1",
            function=MagicMock(name="read_source_page", arguments='{"page_num": 1}'),
        )
    ]

    final_resp = MagicMock()
    final_resp.choices[0].message.content = "This document covers neural networks."
    final_resp.choices[0].message.tool_calls = []

    with (
        patch(
            "app.agents.sub_agent.litellm.acompletion",
            new_callable=AsyncMock,
            side_effect=[page_content_resp, final_resp],
        ),
        patch("app.agents.sub_agent.litellm.completion_cost", return_value=0.001),
        patch("app.agents.sub_agent.AgentTools") as MockTools,
    ):
        mock_tools_instance = MagicMock()
        mock_tools_instance.as_litellm_tools.return_value = []
        mock_tools_instance.dispatch = AsyncMock(
            return_value="# Neural Networks\n\nContent here."
        )
        MockTools.return_value = mock_tools_instance

        result = await sub_agent.run(
            source_id="src-1",
            workspace_id="ws-1",
            page_start=1,
            page_end=10,
            focus_hint="introduction",
        )

    assert isinstance(result, str)
    assert "neural networks" in result.lower()
