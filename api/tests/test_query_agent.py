import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import app.agents.query_agent as query_agent_mod
from app.agents.query_agent import run


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tool_call(name: str, arguments: dict, call_id: str = "call-1"):
    """Build a fake litellm tool_call object."""
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = name
    tc.function.arguments = json.dumps(arguments)
    return tc


def _make_llm_response(content: str | None = None, tool_calls: list | None = None):
    """Build a fake litellm acompletion response."""
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls or []
    resp = MagicMock()
    resp.choices = [MagicMock(message=msg)]
    return resp


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def session():
    s = AsyncMock(spec=AsyncSession)
    s.add = MagicMock()
    s.delete = AsyncMock()
    # Default: no system/memory page found
    s.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    return s


@pytest.fixture
def mock_broadcaster():
    b = MagicMock()
    b.publish = AsyncMock()
    return b


# Patch broadcaster used inside the module so tests never hit Redis.
@pytest.fixture(autouse=True)
def patch_broadcaster(mock_broadcaster):
    with patch.object(query_agent_mod, "broadcaster", mock_broadcaster):
        yield mock_broadcaster


# ---------------------------------------------------------------------------
# Happy path — LLM answers immediately (no tool calls)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_returns_answer_and_empty_cited_pages_when_no_tool_calls(session):
    llm_resp = _make_llm_response(content="Here is your answer.")

    with patch("litellm.acompletion", new_callable=AsyncMock, return_value=llm_resp), \
         patch("litellm.completion_cost", return_value=0.0), \
         patch("app.agents.query_agent.AgentTools") as MockTools:

        tools_instance = MagicMock()
        tools_instance.as_litellm_tools.return_value = []
        tools_instance.dispatch = AsyncMock(return_value="")
        MockTools.return_value = tools_instance

        answer, sources = await run(
            workspace_id="ws-1",
            question="What is 2+2?",
            history=[],
            session=session,
            audience_user_id="user-1",
        )

    assert answer == "Here is your answer."
    assert sources == []


@pytest.mark.asyncio
async def test_run_extracts_cited_pages_from_wikilinks(session):
    content = "See [[projects/alpha]] and [[people/alice]] for details."
    llm_resp = _make_llm_response(content=content)

    with patch("litellm.acompletion", new_callable=AsyncMock, return_value=llm_resp), \
         patch("litellm.completion_cost", return_value=0.0), \
         patch("app.agents.query_agent.AgentTools") as MockTools:

        tools_instance = MagicMock()
        tools_instance.as_litellm_tools.return_value = []
        MockTools.return_value = tools_instance

        answer, sources = await run(
            workspace_id="ws-1",
            question="Summarise the project",
            history=[],
            session=session,
            audience_user_id="user-1",
        )

    assert sources == ["projects/alpha", "people/alice"]
    assert answer == content


# ---------------------------------------------------------------------------
# Tool-call round-trip — LLM calls read_page, then answers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_dispatches_tool_calls_and_adds_tool_result_to_messages(session):
    tool_call = _make_tool_call("read_page", {"slug": "projects/alpha"})
    first_resp = _make_llm_response(tool_calls=[tool_call])
    # cited_pages is overwritten by re.findall on the final answer, so include the wikilink there
    second_resp = _make_llm_response(content="See [[projects/alpha]] — it's done.")

    acompletion_mock = AsyncMock(side_effect=[first_resp, second_resp])

    with patch("litellm.acompletion", acompletion_mock), \
         patch("litellm.completion_cost", return_value=0.0), \
         patch("app.agents.query_agent.AgentTools") as MockTools:

        tools_instance = MagicMock()
        tools_instance.as_litellm_tools.return_value = []
        tools_instance.dispatch = AsyncMock(return_value="# Alpha\nContent here.")
        MockTools.return_value = tools_instance

        answer, sources = await run(
            workspace_id="ws-1",
            question="What is in alpha?",
            history=[],
            session=session,
            audience_user_id="user-1",
        )

    assert answer == "See [[projects/alpha]] — it's done."
    assert "projects/alpha" in sources
    tools_instance.dispatch.assert_awaited_once_with("read_page", {"slug": "projects/alpha"})

    # Second acompletion call should include the tool result message
    second_call_messages = acompletion_mock.call_args_list[1][1]["messages"]
    tool_result_msg = next(
        (m for m in second_call_messages if m.get("role") == "tool"), None
    )
    assert tool_result_msg is not None
    assert tool_result_msg["tool_call_id"] == "call-1"
    assert "# Alpha" in tool_result_msg["content"]


# ---------------------------------------------------------------------------
# LLM called with correct parameters
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_passes_system_prompt_and_question_to_llm(session):
    llm_resp = _make_llm_response(content="Answer.")
    acompletion_mock = AsyncMock(return_value=llm_resp)

    with patch("litellm.acompletion", acompletion_mock), \
         patch("litellm.completion_cost", return_value=0.0), \
         patch("app.agents.query_agent.AgentTools") as MockTools:

        tools_instance = MagicMock()
        tools_instance.as_litellm_tools.return_value = []
        MockTools.return_value = tools_instance

        await run(
            workspace_id="ws-1",
            question="Tell me about Python.",
            history=[],
            session=session,
            audience_user_id="user-1",
        )

    call_kwargs = acompletion_mock.call_args[1]
    messages = call_kwargs["messages"]
    # messages is a mutable list; an assistant message is appended after the call,
    # so messages[-1] is now the assistant turn. User question is at index 1 (no history).
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "Tell me about Python."
    assert call_kwargs["tool_choice"] == "auto"


@pytest.mark.asyncio
async def test_run_includes_up_to_10_history_messages(session):
    """History is capped at the last 10 entries before the user question."""
    history = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"}
        for i in range(15)
    ]
    llm_resp = _make_llm_response(content="Got it.")
    acompletion_mock = AsyncMock(return_value=llm_resp)

    with patch("litellm.acompletion", acompletion_mock), \
         patch("litellm.completion_cost", return_value=0.0), \
         patch("app.agents.query_agent.AgentTools") as MockTools:

        tools_instance = MagicMock()
        tools_instance.as_litellm_tools.return_value = []
        MockTools.return_value = tools_instance

        await run(
            workspace_id="ws-1",
            question="Latest?",
            history=history,
            session=session,
            audience_user_id="user-1",
        )

    messages = acompletion_mock.call_args[1]["messages"]
    # messages is mutated after the call (assistant appended), so verify via content not count
    history_msgs = [m for m in messages if isinstance(m.get("content"), str) and m["content"].startswith("msg ")]
    assert len(history_msgs) == 10
    assert history_msgs[-1]["content"] == "msg 14"
    assert not any(m["content"] == "msg 4" for m in history_msgs)


# ---------------------------------------------------------------------------
# system/memory injected into system prompt when present
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_injects_user_memory_into_system_prompt(session):
    # Override the default session fixture to return memory content
    session.execute.return_value = MagicMock(
        scalar_one_or_none=MagicMock(return_value="I prefer concise answers.")
    )

    llm_resp = _make_llm_response(content="Concise answer.")
    acompletion_mock = AsyncMock(return_value=llm_resp)

    with patch("litellm.acompletion", acompletion_mock), \
         patch("litellm.completion_cost", return_value=0.0), \
         patch("app.agents.query_agent.AgentTools") as MockTools:

        tools_instance = MagicMock()
        tools_instance.as_litellm_tools.return_value = []
        MockTools.return_value = tools_instance

        await run(
            workspace_id="ws-1",
            question="Anything?",
            history=[],
            session=session,
            audience_user_id="user-1",
        )

    system_content = acompletion_mock.call_args[1]["messages"][0]["content"]
    assert "I prefer concise answers." in system_content
    assert "<user_context>" in system_content


@pytest.mark.asyncio
async def test_run_skips_user_context_block_when_no_memory(session):
    # session fixture default: scalar_one_or_none returns None
    llm_resp = _make_llm_response(content="Answer.")
    acompletion_mock = AsyncMock(return_value=llm_resp)

    with patch("litellm.acompletion", acompletion_mock), \
         patch("litellm.completion_cost", return_value=0.0), \
         patch("app.agents.query_agent.AgentTools") as MockTools:

        tools_instance = MagicMock()
        tools_instance.as_litellm_tools.return_value = []
        MockTools.return_value = tools_instance

        await run(
            workspace_id="ws-1",
            question="Anything?",
            history=[],
            session=session,
            audience_user_id="user-1",
        )

    system_content = acompletion_mock.call_args[1]["messages"][0]["content"]
    # query.md mentions <user_context> in its instruction prose, so we can't assert the tag is absent.
    # Instead verify the actual injection pattern (tag immediately followed by newline+content) is absent.
    assert "<user_context>\n" not in system_content


# ---------------------------------------------------------------------------
# broadcaster.publish called with agent:done on success
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_publishes_agent_done_on_success(session, patch_broadcaster):
    content = "Answer with [[some/page]]."
    llm_resp = _make_llm_response(content=content)

    with patch("litellm.acompletion", new_callable=AsyncMock, return_value=llm_resp), \
         patch("litellm.completion_cost", return_value=0.0), \
         patch("app.agents.query_agent.AgentTools") as MockTools:

        tools_instance = MagicMock()
        tools_instance.as_litellm_tools.return_value = []
        MockTools.return_value = tools_instance

        await run(
            workspace_id="ws-1",
            question="Any?",
            history=[],
            session=session,
            audience_user_id="user-1",
        )

    patch_broadcaster.publish.assert_awaited_once_with(
        {"event": "agent:done", "context": "chat", "pages_touched": ["some/page"]},
        audience_user_id="user-1",
    )


# ---------------------------------------------------------------------------
# Max-turns fallback — LLM keeps returning tool calls for 10 turns
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_returns_fallback_message_after_max_turns(session, patch_broadcaster):
    """If the LLM never stops calling tools, run() returns the fallback string."""
    tool_call = _make_tool_call("list_pages", {})
    always_calls_tool = _make_llm_response(tool_calls=[tool_call])

    with patch("litellm.acompletion", new_callable=AsyncMock, return_value=always_calls_tool), \
         patch("litellm.completion_cost", return_value=0.0), \
         patch("app.agents.query_agent.AgentTools") as MockTools:

        tools_instance = MagicMock()
        tools_instance.as_litellm_tools.return_value = []
        tools_instance.dispatch = AsyncMock(return_value="[]")
        MockTools.return_value = tools_instance

        answer, sources = await run(
            workspace_id="ws-1",
            question="Loop forever?",
            history=[],
            session=session,
            audience_user_id="user-1",
        )

    assert "wasn't able" in answer
    assert sources == []
    # agent:done must be published even on the fallback path
    patch_broadcaster.publish.assert_awaited_once_with(
        {"event": "agent:done", "context": "chat", "pages_touched": []},
        audience_user_id="user-1",
    )


# ---------------------------------------------------------------------------
# AgentTools instantiated with correct parameters
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_creates_agent_tools_with_correct_context(session):
    llm_resp = _make_llm_response(content="Done.")

    with patch("litellm.acompletion", new_callable=AsyncMock, return_value=llm_resp), \
         patch("litellm.completion_cost", return_value=0.0), \
         patch("app.agents.query_agent.AgentTools") as MockTools:

        tools_instance = MagicMock()
        tools_instance.as_litellm_tools.return_value = []
        MockTools.return_value = tools_instance

        await run(
            workspace_id="ws-42",
            question="?",
            history=[],
            session=session,
            audience_user_id="user-99",
        )

    MockTools.assert_called_once()
    call_kwargs = MockTools.call_args[1]
    assert call_kwargs["workspace_id"] == "ws-42"
    assert call_kwargs["session"] is session
    assert call_kwargs["context"] == "chat"
    assert call_kwargs["audience_user_id"] == "user-99"


# ---------------------------------------------------------------------------
# completion_cost exception is swallowed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_tolerates_completion_cost_exception(session):
    """litellm.completion_cost raising should not abort the run."""
    llm_resp = _make_llm_response(content="Still works.")

    with patch("litellm.acompletion", new_callable=AsyncMock, return_value=llm_resp), \
         patch("litellm.completion_cost", side_effect=Exception("pricing error")), \
         patch("app.agents.query_agent.AgentTools") as MockTools:

        tools_instance = MagicMock()
        tools_instance.as_litellm_tools.return_value = []
        MockTools.return_value = tools_instance

        answer, _ = await run(
            workspace_id="ws-1",
            question="Cost test",
            history=[],
            session=session,
            audience_user_id="user-1",
        )

    assert answer == "Still works."


# ---------------------------------------------------------------------------
# Non-read_page tool calls do not add to cited_pages
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_only_cites_read_page_slugs_not_other_tools(session):
    search_call = _make_tool_call("search_pages", {"query": "alpha"}, call_id="c1")
    first_resp = _make_llm_response(tool_calls=[search_call])
    final_resp = _make_llm_response(content="Found something.")

    with patch("litellm.acompletion", new_callable=AsyncMock, side_effect=[first_resp, final_resp]), \
         patch("litellm.completion_cost", return_value=0.0), \
         patch("app.agents.query_agent.AgentTools") as MockTools:

        tools_instance = MagicMock()
        tools_instance.as_litellm_tools.return_value = []
        tools_instance.dispatch = AsyncMock(return_value="[{'slug': 'projects/alpha'}]")
        MockTools.return_value = tools_instance

        _, sources = await run(
            workspace_id="ws-1",
            question="Find alpha",
            history=[],
            session=session,
            audience_user_id="user-1",
        )

    # search_pages should not add anything to cited_pages
    assert sources == []
