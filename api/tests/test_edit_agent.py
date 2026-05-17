import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession

import app.agents.edit_agent as edit_agent_mod
from app.agents.edit_agent import run, EDIT_TOOLS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tool_call(name: str, arguments: dict, call_id: str = "tc-1") -> MagicMock:
    """Build a fake litellm tool_call object."""
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = name
    tc.function.arguments = json.dumps(arguments)
    return tc


def _make_llm_response(content: str | None = None, tool_calls: list | None = None) -> MagicMock:
    """Build a fake litellm response object."""
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls or []
    resp = MagicMock()
    resp.choices = [MagicMock(message=msg)]
    return resp


@pytest.fixture
def session():
    s = AsyncMock(spec=AsyncSession)
    s.add = MagicMock()
    s.delete = AsyncMock()
    return s


@pytest.fixture
def mock_broadcaster():
    b = MagicMock()
    b.publish = AsyncMock()
    return b


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plain_text_response_returns_immediately(session, mock_broadcaster):
    """When the LLM returns text with no tool calls the answer is returned directly."""
    plain_resp = _make_llm_response(content="Here is my answer.", tool_calls=None)

    with (
        patch("app.agents.edit_agent.litellm.acompletion", new_callable=AsyncMock, return_value=plain_resp) as mock_llm,
        patch("app.agents.edit_agent.litellm.completion_cost", return_value=0.001),
        patch("app.agents.edit_agent.broadcaster", mock_broadcaster),
        patch("app.agents.edit_agent.AgentTools") as MockTools,
        patch("app.agents.edit_agent.render_system_prompt", return_value="system"),
        patch("app.agents.edit_agent.assistant_message_for_litellm", return_value={"role": "assistant", "content": "Here is my answer."}),
    ):
        mock_tools_instance = MagicMock()
        mock_tools_instance.as_litellm_tools.return_value = []
        mock_tools_instance.dispatch = AsyncMock()
        MockTools.return_value = mock_tools_instance

        answer, touched = await run(
            workspace_id="ws-1",
            question="What is 2+2?",
            history=[],
            session=session,
            audience_user_id="u-1",
        )

        assert answer == "Here is my answer."
        assert touched == []
        mock_llm.assert_awaited_once()
        mock_tools_instance.dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_plain_text_extracts_wikilink_touched_pages(session, mock_broadcaster):
    """Wikilinks in the final answer are parsed into touched_pages."""
    content = "See [[notes/topic-a]] and [[notes/topic-b]] for details."
    plain_resp = _make_llm_response(content=content)

    with (
        patch("app.agents.edit_agent.litellm.acompletion", new_callable=AsyncMock, return_value=plain_resp),
        patch("app.agents.edit_agent.litellm.completion_cost", return_value=0.0),
        patch("app.agents.edit_agent.broadcaster", mock_broadcaster),
        patch("app.agents.edit_agent.AgentTools") as MockTools,
        patch("app.agents.edit_agent.render_system_prompt", return_value="system"),
        patch("app.agents.edit_agent.assistant_message_for_litellm", return_value={"role": "assistant"}),
    ):
        mock_tools_instance = MagicMock()
        mock_tools_instance.as_litellm_tools.return_value = []
        MockTools.return_value = mock_tools_instance

        answer, touched = await run(
            workspace_id="ws-1",
            question="Give me the links",
            history=[],
            session=session,
            audience_user_id="u-1",
        )

    assert "notes/topic-a" in touched
    assert "notes/topic-b" in touched


@pytest.mark.asyncio
async def test_plain_text_publishes_agent_done(session, mock_broadcaster):
    """A plain-text response publishes agent:done with the expected shape."""
    plain_resp = _make_llm_response(content="Done.", tool_calls=None)

    with (
        patch("app.agents.edit_agent.litellm.acompletion", new_callable=AsyncMock, return_value=plain_resp),
        patch("app.agents.edit_agent.litellm.completion_cost", return_value=0.0),
        patch("app.agents.edit_agent.broadcaster", mock_broadcaster),
        patch("app.agents.edit_agent.AgentTools") as MockTools,
        patch("app.agents.edit_agent.render_system_prompt", return_value="system"),
        patch("app.agents.edit_agent.assistant_message_for_litellm", return_value={"role": "assistant"}),
    ):
        mock_tools_instance = MagicMock()
        mock_tools_instance.as_litellm_tools.return_value = []
        MockTools.return_value = mock_tools_instance

        await run(
            workspace_id="ws-1",
            question="Hello",
            history=[],
            session=session,
            audience_user_id="u-1",
        )

    mock_broadcaster.publish.assert_awaited_once_with(
        {"event": "agent:done", "context": "chat", "pages_touched": []},
        audience_user_id="u-1",
    )


@pytest.mark.asyncio
async def test_tool_call_dispatched_and_result_appended(session, mock_broadcaster):
    """LLM returns a tool call → dispatch is called → result appended → second turn returns text."""
    tc = _make_tool_call("write_page", {"slug": "notes/foo", "body_md": "# Foo"}, call_id="tc-1")

    first_resp = _make_llm_response(tool_calls=[tc])
    second_resp = _make_llm_response(content="Page written successfully.", tool_calls=None)

    call_seq = [first_resp, second_resp]

    with (
        patch("app.agents.edit_agent.litellm.acompletion", new_callable=AsyncMock, side_effect=call_seq) as mock_llm,
        patch("app.agents.edit_agent.litellm.completion_cost", return_value=0.0),
        patch("app.agents.edit_agent.broadcaster", mock_broadcaster),
        patch("app.agents.edit_agent.AgentTools") as MockTools,
        patch("app.agents.edit_agent.render_system_prompt", return_value="system"),
        patch("app.agents.edit_agent.assistant_message_for_litellm", return_value={"role": "assistant"}),
    ):
        mock_tools_instance = MagicMock()
        mock_tools_instance.as_litellm_tools.return_value = []
        mock_tools_instance.dispatch = AsyncMock(return_value="Page 'notes/foo' saved.")
        MockTools.return_value = mock_tools_instance

        answer, touched = await run(
            workspace_id="ws-1",
            question="Write a page",
            history=[],
            session=session,
            audience_user_id="u-1",
        )

        assert answer == "Page written successfully."
        mock_tools_instance.dispatch.assert_awaited_once_with(
            "write_page", {"slug": "notes/foo", "body_md": "# Foo"}
        )
        assert mock_llm.await_count == 2


@pytest.mark.asyncio
async def test_read_page_tool_call_tracks_touched_pages(session, mock_broadcaster):
    """read_page tool calls add the slug to touched_pages."""
    tc = _make_tool_call("read_page", {"slug": "notes/bar"}, call_id="tc-2")

    first_resp = _make_llm_response(tool_calls=[tc])
    # touched_pages is overwritten by re.findall on the final answer, so include the wikilink there
    second_resp = _make_llm_response(content="Here is [[notes/bar]].", tool_calls=None)

    with (
        patch("app.agents.edit_agent.litellm.acompletion", new_callable=AsyncMock, side_effect=[first_resp, second_resp]),
        patch("app.agents.edit_agent.litellm.completion_cost", return_value=0.0),
        patch("app.agents.edit_agent.broadcaster", mock_broadcaster),
        patch("app.agents.edit_agent.AgentTools") as MockTools,
        patch("app.agents.edit_agent.render_system_prompt", return_value="system"),
        patch("app.agents.edit_agent.assistant_message_for_litellm", return_value={"role": "assistant"}),
    ):
        mock_tools_instance = MagicMock()
        mock_tools_instance.as_litellm_tools.return_value = []
        mock_tools_instance.dispatch = AsyncMock(return_value="# Bar content")
        MockTools.return_value = mock_tools_instance

        _, touched = await run(
            workspace_id="ws-1",
            question="Read a page",
            history=[],
            session=session,
            audience_user_id="u-1",
        )

    assert "notes/bar" in touched


@pytest.mark.asyncio
async def test_tool_result_message_appended_to_conversation(session, mock_broadcaster):
    """Tool result is appended as a role=tool message with the correct tool_call_id."""
    tc = _make_tool_call("list_pages", {}, call_id="tc-list")

    first_resp = _make_llm_response(tool_calls=[tc])
    second_resp = _make_llm_response(content="Listed.", tool_calls=None)

    captured_messages: list = []

    async def capture_acompletion(**kwargs):
        captured_messages.extend(kwargs["messages"])
        return second_resp if edit_agent_mod.litellm.acompletion.await_count > 1 else first_resp

    # Use side_effect list instead of the capture approach for simplicity
    call_seq = [first_resp, second_resp]

    with (
        patch("app.agents.edit_agent.litellm.acompletion", new_callable=AsyncMock, side_effect=call_seq) as mock_llm,
        patch("app.agents.edit_agent.litellm.completion_cost", return_value=0.0),
        patch("app.agents.edit_agent.broadcaster", mock_broadcaster),
        patch("app.agents.edit_agent.AgentTools") as MockTools,
        patch("app.agents.edit_agent.render_system_prompt", return_value="system"),
        patch("app.agents.edit_agent.assistant_message_for_litellm", return_value={"role": "assistant", "tool_calls": []}),
    ):
        mock_tools_instance = MagicMock()
        mock_tools_instance.as_litellm_tools.return_value = []
        mock_tools_instance.dispatch = AsyncMock(return_value="[page list]")
        MockTools.return_value = mock_tools_instance

        await run(
            workspace_id="ws-1",
            question="List pages",
            history=[],
            session=session,
            audience_user_id="u-1",
        )

    # Second LLM call should include a tool-result message
    second_call_messages = mock_llm.call_args_list[1].kwargs["messages"]
    tool_result_msgs = [m for m in second_call_messages if m.get("role") == "tool"]
    assert len(tool_result_msgs) == 1
    assert tool_result_msgs[0]["tool_call_id"] == "tc-list"
    assert tool_result_msgs[0]["content"] == "[page list]"


@pytest.mark.asyncio
async def test_agent_tools_constructed_with_correct_params(session, mock_broadcaster):
    """AgentTools is constructed with the workspace_id, session and correct context."""
    plain_resp = _make_llm_response(content="ok")

    with (
        patch("app.agents.edit_agent.litellm.acompletion", new_callable=AsyncMock, return_value=plain_resp),
        patch("app.agents.edit_agent.litellm.completion_cost", return_value=0.0),
        patch("app.agents.edit_agent.broadcaster", mock_broadcaster),
        patch("app.agents.edit_agent.AgentTools") as MockTools,
        patch("app.agents.edit_agent.render_system_prompt", return_value="system"),
        patch("app.agents.edit_agent.assistant_message_for_litellm", return_value={"role": "assistant"}),
    ):
        mock_tools_instance = MagicMock()
        mock_tools_instance.as_litellm_tools.return_value = []
        MockTools.return_value = mock_tools_instance

        await run(
            workspace_id="ws-42",
            question="Hi",
            history=[],
            session=session,
            audience_user_id="u-99",
        )

    MockTools.assert_called_once_with(
        session=session,
        workspace_id="ws-42",
        broadcaster=mock_broadcaster,
        context="chat",
        audience_user_id="u-99",
    )


@pytest.mark.asyncio
async def test_edit_tools_allowed_list_passed_to_as_litellm_tools(session, mock_broadcaster):
    """as_litellm_tools is called with the EDIT_TOOLS allowlist."""
    plain_resp = _make_llm_response(content="ok")

    with (
        patch("app.agents.edit_agent.litellm.acompletion", new_callable=AsyncMock, return_value=plain_resp),
        patch("app.agents.edit_agent.litellm.completion_cost", return_value=0.0),
        patch("app.agents.edit_agent.broadcaster", mock_broadcaster),
        patch("app.agents.edit_agent.AgentTools") as MockTools,
        patch("app.agents.edit_agent.render_system_prompt", return_value="system"),
        patch("app.agents.edit_agent.assistant_message_for_litellm", return_value={"role": "assistant"}),
    ):
        mock_tools_instance = MagicMock()
        mock_tools_instance.as_litellm_tools.return_value = []
        MockTools.return_value = mock_tools_instance

        await run(
            workspace_id="ws-1",
            question="Hi",
            history=[],
            session=session,
            audience_user_id="u-1",
        )

    mock_tools_instance.as_litellm_tools.assert_called_once_with(allowed=EDIT_TOOLS)


@pytest.mark.asyncio
async def test_history_trimmed_to_last_10(session, mock_broadcaster):
    """Only the last 10 history messages are included in the LLM request."""
    plain_resp = _make_llm_response(content="ok")
    history = [{"role": "user", "content": f"msg-{i}"} for i in range(15)]

    with (
        patch("app.agents.edit_agent.litellm.acompletion", new_callable=AsyncMock, return_value=plain_resp) as mock_llm,
        patch("app.agents.edit_agent.litellm.completion_cost", return_value=0.0),
        patch("app.agents.edit_agent.broadcaster", mock_broadcaster),
        patch("app.agents.edit_agent.AgentTools") as MockTools,
        patch("app.agents.edit_agent.render_system_prompt", return_value="system"),
        patch("app.agents.edit_agent.assistant_message_for_litellm", return_value={"role": "assistant"}),
    ):
        mock_tools_instance = MagicMock()
        mock_tools_instance.as_litellm_tools.return_value = []
        MockTools.return_value = mock_tools_instance

        await run(
            workspace_id="ws-1",
            question="Hi",
            history=history,
            session=session,
            audience_user_id="u-1",
        )

    sent_messages = mock_llm.call_args.kwargs["messages"]
    # The messages list is mutated in-place after the LLM call (assistant message appended),
    # so call_args reflects the live list: system + 10 history + user + assistant = 13.
    # Verify correct history trimming via content, not count.
    contents = [m["content"] for m in sent_messages if isinstance(m.get("content"), str) and m["content"].startswith("msg-")]
    assert len(contents) == 10
    assert "msg-0" not in contents
    assert "msg-14" in contents


@pytest.mark.asyncio
async def test_max_turns_exceeded_returns_fallback(session, mock_broadcaster):
    """If the LLM keeps calling tools for 20 turns, the fallback message is returned."""
    tc = _make_tool_call("list_pages", {}, call_id="tc-inf")
    looping_resp = _make_llm_response(tool_calls=[tc])

    with (
        patch("app.agents.edit_agent.litellm.acompletion", new_callable=AsyncMock, return_value=looping_resp) as mock_llm,
        patch("app.agents.edit_agent.litellm.completion_cost", return_value=0.0),
        patch("app.agents.edit_agent.broadcaster", mock_broadcaster),
        patch("app.agents.edit_agent.AgentTools") as MockTools,
        patch("app.agents.edit_agent.render_system_prompt", return_value="system"),
        patch("app.agents.edit_agent.assistant_message_for_litellm", return_value={"role": "assistant"}),
    ):
        mock_tools_instance = MagicMock()
        mock_tools_instance.as_litellm_tools.return_value = []
        mock_tools_instance.dispatch = AsyncMock(return_value="[]")
        MockTools.return_value = mock_tools_instance

        answer, touched = await run(
            workspace_id="ws-1",
            question="Loop forever",
            history=[],
            session=session,
            audience_user_id="u-1",
        )

        assert "wasn't able to complete" in answer.lower() or answer != ""
        assert mock_llm.await_count == 20

    mock_broadcaster.publish.assert_awaited_once_with(
        {"event": "agent:done", "context": "chat", "pages_touched": []},
        audience_user_id="u-1",
    )


@pytest.mark.asyncio
async def test_dispatch_error_propagates(session, mock_broadcaster):
    """An exception raised by tools.dispatch propagates out of run."""
    tc = _make_tool_call("write_page", {"slug": "bad/slug", "body_md": "x"}, call_id="tc-err")
    first_resp = _make_llm_response(tool_calls=[tc])

    with (
        patch("app.agents.edit_agent.litellm.acompletion", new_callable=AsyncMock, return_value=first_resp),
        patch("app.agents.edit_agent.litellm.completion_cost", return_value=0.0),
        patch("app.agents.edit_agent.broadcaster", mock_broadcaster),
        patch("app.agents.edit_agent.AgentTools") as MockTools,
        patch("app.agents.edit_agent.render_system_prompt", return_value="system"),
        patch("app.agents.edit_agent.assistant_message_for_litellm", return_value={"role": "assistant"}),
    ):
        mock_tools_instance = MagicMock()
        mock_tools_instance.as_litellm_tools.return_value = []
        mock_tools_instance.dispatch = AsyncMock(side_effect=RuntimeError("DB exploded"))
        MockTools.return_value = mock_tools_instance

        with pytest.raises(RuntimeError, match="DB exploded"):
            await run(
                workspace_id="ws-1",
                question="Write something",
                history=[],
                session=session,
                audience_user_id="u-1",
            )


@pytest.mark.asyncio
async def test_completion_cost_exception_is_swallowed(session, mock_broadcaster):
    """A failure in litellm.completion_cost does not abort the run."""
    plain_resp = _make_llm_response(content="fine")

    with (
        patch("app.agents.edit_agent.litellm.acompletion", new_callable=AsyncMock, return_value=plain_resp),
        patch("app.agents.edit_agent.litellm.completion_cost", side_effect=Exception("no cost data")),
        patch("app.agents.edit_agent.broadcaster", mock_broadcaster),
        patch("app.agents.edit_agent.AgentTools") as MockTools,
        patch("app.agents.edit_agent.render_system_prompt", return_value="system"),
        patch("app.agents.edit_agent.assistant_message_for_litellm", return_value={"role": "assistant"}),
    ):
        mock_tools_instance = MagicMock()
        mock_tools_instance.as_litellm_tools.return_value = []
        MockTools.return_value = mock_tools_instance

        answer, _ = await run(
            workspace_id="ws-1",
            question="Fine?",
            history=[],
            session=session,
            audience_user_id="u-1",
        )

    assert answer == "fine"
