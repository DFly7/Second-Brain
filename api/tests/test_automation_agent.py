"""Tests for automation_agent._dispatch and run()."""
import json
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

import app.agents.automation_agent as agent_mod
from app.agents.automation_agent import _dispatch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_http_response(json_data: dict):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = json_data
    return resp


def _make_http(json_data: dict | None = None):
    """Return a mock httpx.AsyncClient whose post() returns a single JSON response."""
    resp = _make_http_response(json_data or {"ok": True})
    http = MagicMock()
    http.post = AsyncMock(return_value=resp)
    return http


def _make_tool_call(name: str, arguments: dict, call_id: str = "call-1"):
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = name
    tc.function.arguments = json.dumps(arguments)
    return tc


def _make_llm_response(content: str | None = None, tool_calls: list | None = None):
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
def db():
    """Minimal AsyncSession mock for _dispatch (add + commit only)."""
    s = MagicMock()
    s.add = MagicMock()
    s.commit = AsyncMock()
    return s


@pytest.fixture
def wiki():
    w = MagicMock()
    w.dispatch = AsyncMock(return_value="wiki result")
    w.as_litellm_tools = MagicMock(return_value=[])
    return w


@pytest.fixture(autouse=True)
def patch_broadcaster():
    with patch("app.agents.automation_agent.broadcaster") as mock_b:
        mock_b.publish = AsyncMock()
        yield mock_b


# ---------------------------------------------------------------------------
# browser_navigate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_navigate_returns_page_title(db, wiki, patch_broadcaster):
    http = _make_http({"title": "Google", "url": "https://google.com"})
    result = await _dispatch("browser_navigate", {"url": "https://google.com"}, "sid", http, wiki, "run-1", db, "u1")
    assert result == "Google"
    http.post.assert_awaited_once()
    db.add.assert_called_once()
    patch_broadcaster.publish.assert_awaited_once()


@pytest.mark.asyncio
async def test_navigate_sends_correct_url(db, wiki):
    http = _make_http({"title": "Example", "url": "https://example.com"})
    await _dispatch("browser_navigate", {"url": "https://example.com"}, "sid", http, wiki, "run-1", db, "u1")
    _, kwargs = http.post.call_args
    assert kwargs["json"]["url"] == "https://example.com"


# ---------------------------------------------------------------------------
# browser_get_page_state
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_page_state_returns_json_string(db, wiki):
    data = {"url": "https://example.com", "title": "Ex", "interactive_elements": [{"tag": "button", "text": "OK", "selector": "#ok"}]}
    http = _make_http(data)
    result = await _dispatch("browser_get_page_state", {}, "sid", http, wiki, "run-1", db, "u1")
    parsed = json.loads(result)
    assert parsed["url"] == "https://example.com"
    assert parsed["interactive_elements"][0]["selector"] == "#ok"


# ---------------------------------------------------------------------------
# browser_click
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_click_by_selector_sends_selector(db, wiki):
    http = _make_http({"ok": True})
    result = await _dispatch("browser_click", {"selector": "#submit"}, "sid", http, wiki, "run-1", db, "u1")
    assert result == "clicked"
    _, kwargs = http.post.call_args
    assert kwargs["json"] == {"selector": "#submit"}


@pytest.mark.asyncio
async def test_click_by_text_sends_text(db, wiki):
    http = _make_http({"ok": True})
    result = await _dispatch("browser_click", {"text": "Sign in"}, "sid", http, wiki, "run-1", db, "u1")
    assert result == "clicked"
    _, kwargs = http.post.call_args
    assert kwargs["json"] == {"text": "Sign in"}


@pytest.mark.asyncio
async def test_click_without_selector_or_text_returns_error_without_http_call(db, wiki):
    http = _make_http()
    result = await _dispatch("browser_click", {}, "sid", http, wiki, "run-1", db, "u1")
    assert "Error" in result
    http.post.assert_not_awaited()


# ---------------------------------------------------------------------------
# browser_type
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_type_returns_typed(db, wiki):
    http = _make_http({"ok": True})
    result = await _dispatch("browser_type", {"text": "hello"}, "sid", http, wiki, "run-1", db, "u1")
    assert result == "typed"
    _, kwargs = http.post.call_args
    assert kwargs["json"]["text"] == "hello"


@pytest.mark.asyncio
async def test_type_truncates_detail_preview_at_40_chars(db, wiki, patch_broadcaster):
    http = _make_http({"ok": True})
    long_text = "a" * 60
    await _dispatch("browser_type", {"text": long_text}, "sid", http, wiki, "run-1", db, "u1")
    published = patch_broadcaster.publish.call_args[0][0]
    assert len(published["detail"]) < len(long_text) + 10  # detail is truncated


# ---------------------------------------------------------------------------
# browser_press_key
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_press_key_sends_key_and_returns_confirmation(db, wiki):
    http = _make_http({"ok": True})
    result = await _dispatch("browser_press_key", {"key": "Enter"}, "sid", http, wiki, "run-1", db, "u1")
    assert result == "key pressed"
    _, kwargs = http.post.call_args
    assert kwargs["json"]["key"] == "Enter"


@pytest.mark.asyncio
async def test_press_key_escape(db, wiki):
    http = _make_http({"ok": True})
    result = await _dispatch("browser_press_key", {"key": "Escape"}, "sid", http, wiki, "run-1", db, "u1")
    assert result == "key pressed"


# ---------------------------------------------------------------------------
# browser_focus
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_focus_sends_selector_and_returns_focused(db, wiki):
    http = _make_http({"ok": True})
    result = await _dispatch("browser_focus", {"selector": "#email"}, "sid", http, wiki, "run-1", db, "u1")
    assert result == "focused"
    _, kwargs = http.post.call_args
    assert kwargs["json"]["selector"] == "#email"


# ---------------------------------------------------------------------------
# browser_hover
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hover_sends_selector_and_returns_hovered(db, wiki):
    http = _make_http({"ok": True})
    result = await _dispatch("browser_hover", {"selector": "nav.menu"}, "sid", http, wiki, "run-1", db, "u1")
    assert result == "hovered"
    _, kwargs = http.post.call_args
    assert kwargs["json"]["selector"] == "nav.menu"


# ---------------------------------------------------------------------------
# browser_select_option
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_select_option_sends_selector_and_value(db, wiki):
    http = _make_http({"selected": ["US"]})
    result = await _dispatch("browser_select_option", {"selector": "select#country", "value": "US"}, "sid", http, wiki, "run-1", db, "u1")
    assert "selected" in result
    _, kwargs = http.post.call_args
    assert kwargs["json"]["selector"] == "select#country"
    assert kwargs["json"]["value"] == "US"


# ---------------------------------------------------------------------------
# browser_scroll
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scroll_down_default_amount(db, wiki):
    http = _make_http({"ok": True})
    result = await _dispatch("browser_scroll", {"direction": "down"}, "sid", http, wiki, "run-1", db, "u1")
    assert result == "scrolled"
    _, kwargs = http.post.call_args
    assert kwargs["json"]["direction"] == "down"


@pytest.mark.asyncio
async def test_scroll_up_custom_amount(db, wiki):
    http = _make_http({"ok": True})
    await _dispatch("browser_scroll", {"direction": "up", "amount": 500}, "sid", http, wiki, "run-1", db, "u1")
    _, kwargs = http.post.call_args
    assert kwargs["json"]["direction"] == "up"
    assert kwargs["json"]["amount"] == 500


# ---------------------------------------------------------------------------
# browser_wait_for
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_wait_for_by_selector(db, wiki):
    http = _make_http({"found": True})
    result = await _dispatch("browser_wait_for", {"selector": ".loaded"}, "sid", http, wiki, "run-1", db, "u1")
    assert result == "found"
    _, kwargs = http.post.call_args
    assert kwargs["json"]["selector"] == ".loaded"


@pytest.mark.asyncio
async def test_wait_for_by_text(db, wiki):
    http = _make_http({"found": True})
    result = await _dispatch("browser_wait_for", {"text": "Welcome back"}, "sid", http, wiki, "run-1", db, "u1")
    assert result == "found"
    _, kwargs = http.post.call_args
    assert kwargs["json"]["text"] == "Welcome back"


@pytest.mark.asyncio
async def test_wait_for_passes_custom_timeout(db, wiki):
    http = _make_http({"found": True})
    await _dispatch("browser_wait_for", {"selector": "#ready", "timeout": 5000}, "sid", http, wiki, "run-1", db, "u1")
    _, kwargs = http.post.call_args
    assert kwargs["json"]["timeout"] == 5000


@pytest.mark.asyncio
async def test_wait_for_without_args_returns_error_without_http_call(db, wiki):
    http = _make_http()
    result = await _dispatch("browser_wait_for", {}, "sid", http, wiki, "run-1", db, "u1")
    assert "Error" in result
    http.post.assert_not_awaited()


# ---------------------------------------------------------------------------
# browser_read
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_returns_page_text(db, wiki):
    http = _make_http({"text": "Hello from the page"})
    result = await _dispatch("browser_read", {}, "sid", http, wiki, "run-1", db, "u1")
    assert result == "Hello from the page"


# ---------------------------------------------------------------------------
# browser_execute_js
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_js_returns_json_encoded_result(db, wiki):
    http = _make_http({"result": 42})
    result = await _dispatch("browser_execute_js", {"script": "1 + 1"}, "sid", http, wiki, "run-1", db, "u1")
    assert json.loads(result) == 42


@pytest.mark.asyncio
async def test_execute_js_handles_null_result(db, wiki):
    http = _make_http({"result": None})
    result = await _dispatch("browser_execute_js", {"script": "void 0"}, "sid", http, wiki, "run-1", db, "u1")
    assert json.loads(result) is None


@pytest.mark.asyncio
async def test_execute_js_sends_script(db, wiki):
    http = _make_http({"result": "ok"})
    script = "document.title"
    await _dispatch("browser_execute_js", {"script": script}, "sid", http, wiki, "run-1", db, "u1")
    _, kwargs = http.post.call_args
    assert kwargs["json"]["script"] == script


# ---------------------------------------------------------------------------
# browser_screenshot — critical: must return image content block, not a string
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_screenshot_returns_list_not_string(db, wiki):
    http = _make_http({"image_b64": "abc123=="})
    result = await _dispatch("browser_screenshot", {}, "sid", http, wiki, "run-1", db, "u1")
    assert isinstance(result, list), "screenshot must return a list for multimodal LLM consumption"


@pytest.mark.asyncio
async def test_screenshot_result_contains_image_url_block(db, wiki):
    http = _make_http({"image_b64": "abc123=="})
    result = await _dispatch("browser_screenshot", {}, "sid", http, wiki, "run-1", db, "u1")
    image_blocks = [b for b in result if b.get("type") == "image_url"]
    assert len(image_blocks) == 1
    assert image_blocks[0]["image_url"]["url"] == "data:image/png;base64,abc123=="


@pytest.mark.asyncio
async def test_screenshot_result_contains_text_block(db, wiki):
    http = _make_http({"image_b64": "abc=="})
    result = await _dispatch("browser_screenshot", {}, "sid", http, wiki, "run-1", db, "u1")
    text_blocks = [b for b in result if b.get("type") == "text"]
    assert len(text_blocks) == 1


@pytest.mark.asyncio
async def test_screenshot_sse_event_carries_raw_base64(db, wiki, patch_broadcaster):
    http = _make_http({"image_b64": "deadbeef=="})
    await _dispatch("browser_screenshot", {}, "sid", http, wiki, "run-1", db, "u1")
    published = patch_broadcaster.publish.call_args[0][0]
    assert published["event"] == "automation:screenshot"
    assert published["image_b64"] == "deadbeef=="


# ---------------------------------------------------------------------------
# Wiki tool delegation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_wiki_read_delegates_to_agent_tools(db, wiki):
    result = await _dispatch("read_page", {"slug": "projects/alpha"}, "sid", _make_http(), wiki, "run-1", db, "u1")
    assert result == "wiki result"
    wiki.dispatch.assert_awaited_once_with("read_page", {"slug": "projects/alpha"})


@pytest.mark.asyncio
async def test_wiki_write_records_action_and_publishes_sse(db, wiki, patch_broadcaster):
    wiki.dispatch = AsyncMock(return_value="saved")
    await _dispatch("write_page", {"slug": "my/page", "content": "# Hi"}, "sid", _make_http(), wiki, "run-1", db, "u1")
    db.add.assert_called()
    events = [c[0][0]["type"] for c in patch_broadcaster.publish.call_args_list]
    assert "wiki_write" in events


@pytest.mark.asyncio
async def test_non_write_wiki_tool_does_not_publish_wiki_write_event(db, wiki, patch_broadcaster):
    await _dispatch("list_pages", {}, "sid", _make_http(), wiki, "run-1", db, "u1")
    events = [c[0][0].get("type") for c in patch_broadcaster.publish.call_args_list]
    assert "wiki_write" not in events


# ---------------------------------------------------------------------------
# _record: AutomationAction written and committed for every browser tool
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_action_recorded_to_db_on_navigate(db, wiki):
    http = _make_http({"title": "T", "url": "https://t.com"})
    await _dispatch("browser_navigate", {"url": "https://t.com"}, "sid", http, wiki, "run-1", db, "u1")
    db.add.assert_called_once()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_action_recorded_to_db_on_screenshot(db, wiki):
    http = _make_http({"image_b64": "x"})
    await _dispatch("browser_screenshot", {}, "sid", http, wiki, "run-1", db, "u1")
    db.add.assert_called_once()
    db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# HTTP errors propagate out of _dispatch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_http_error_propagates(db, wiki):
    import httpx
    resp = MagicMock()
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "500 Server Error", request=MagicMock(), response=MagicMock()
    )
    http = MagicMock()
    http.post = AsyncMock(return_value=resp)
    with pytest.raises(httpx.HTTPStatusError):
        await _dispatch("browser_navigate", {"url": "https://example.com"}, "sid", http, wiki, "run-1", db, "u1")


# ---------------------------------------------------------------------------
# run() — end-to-end flow
# ---------------------------------------------------------------------------

@pytest.fixture
def run_session():
    s = MagicMock()
    s.add = MagicMock()
    s.expire_all = MagicMock()
    s.commit = AsyncMock()
    return s


def _make_run_session(statuses: list[str], run_obj: MagicMock):
    """
    Build an AsyncSession mock where:
    - The first N-1 execute() calls return stop-check results (scalar_one_or_none → status string).
    - The last execute() call returns the AutomationRun object for the finally block.
    """
    s = MagicMock()
    s.add = MagicMock()
    s.expire_all = MagicMock()
    s.commit = AsyncMock()

    stop_results = []
    for status in statuses:
        r = MagicMock()
        r.scalar_one_or_none.return_value = status
        stop_results.append(r)

    final_result = MagicMock()
    final_result.scalar_one_or_none.return_value = run_obj

    s.execute = AsyncMock(side_effect=stop_results + [final_result])
    return s


@pytest.mark.asyncio
async def test_run_completes_when_llm_returns_no_tool_calls():
    llm_resp = _make_llm_response(content="All done.")

    run_obj = MagicMock()
    run_obj.status = "running"
    run_obj.recording_url = None
    session = _make_run_session(["running"], run_obj)

    new_resp = _make_http_response({"session_id": "sess-abc"})
    close_resp = _make_http_response({"recording_url": None})
    mock_http = MagicMock()
    mock_http.post = AsyncMock(side_effect=[new_resp, close_resp])
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_http)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("litellm.acompletion", new_callable=AsyncMock, return_value=llm_resp), \
         patch("httpx.AsyncClient", return_value=mock_ctx), \
         patch("app.agents.automation_agent.AgentTools") as MockTools:

        tools_instance = MagicMock()
        tools_instance.as_litellm_tools.return_value = []
        MockTools.return_value = tools_instance

        await agent_mod.run(
            run_id="run-1",
            workspace_id="ws-1",
            goal="do a thing",
            session=session,
            audience_user_id="user-1",
        )

    assert run_obj.status == "completed"
    assert run_obj.completed_at is not None


@pytest.mark.asyncio
async def test_run_stops_when_status_is_stopping():
    run_obj = MagicMock()
    run_obj.status = "stopping"
    run_obj.recording_url = None
    session = _make_run_session(["stopping"], run_obj)

    new_resp = _make_http_response({"session_id": "sess-1"})
    close_resp = _make_http_response({"recording_url": None})
    mock_http = MagicMock()
    mock_http.post = AsyncMock(side_effect=[new_resp, close_resp])
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_http)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("litellm.acompletion", new_callable=AsyncMock) as mock_llm, \
         patch("httpx.AsyncClient", return_value=mock_ctx), \
         patch("app.agents.automation_agent.AgentTools") as MockTools:

        tools_instance = MagicMock()
        tools_instance.as_litellm_tools.return_value = []
        MockTools.return_value = tools_instance

        await agent_mod.run(
            run_id="run-1",
            workspace_id="ws-1",
            goal="do a thing",
            session=session,
            audience_user_id="user-1",
        )

    mock_llm.assert_not_awaited()
    assert run_obj.status == "stopped"


@pytest.mark.asyncio
async def test_run_dispatches_browser_tool_call_from_llm():
    """LLM calls browser_navigate on turn 1, then finishes on turn 2."""
    nav_call = _make_tool_call("browser_navigate", {"url": "https://example.com"})
    first_resp = _make_llm_response(tool_calls=[nav_call])
    second_resp = _make_llm_response(content="Done.")

    run_obj = MagicMock()
    run_obj.status = "running"
    run_obj.recording_url = None
    session = _make_run_session(["running", "running"], run_obj)

    new_resp = _make_http_response({"session_id": "sess-1"})
    nav_resp = _make_http_response({"title": "Example", "url": "https://example.com"})
    close_resp = _make_http_response({"recording_url": None})
    mock_http = MagicMock()
    mock_http.post = AsyncMock(side_effect=[new_resp, nav_resp, close_resp])
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_http)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("litellm.acompletion", new_callable=AsyncMock, side_effect=[first_resp, second_resp]) as mock_llm, \
         patch("httpx.AsyncClient", return_value=mock_ctx), \
         patch("app.agents.automation_agent.AgentTools") as MockTools:

        tools_instance = MagicMock()
        tools_instance.as_litellm_tools.return_value = []
        MockTools.return_value = tools_instance

        await agent_mod.run(
            run_id="run-1",
            workspace_id="ws-1",
            goal="visit example.com",
            session=session,
            audience_user_id="user-1",
        )

        # Tool result message must appear in the second LLM call (assert inside patch scope)
        second_call_messages = mock_llm.call_args_list[1][1]["messages"]
        tool_msg = next((m for m in second_call_messages if m.get("role") == "tool"), None)
        assert tool_msg is not None
        assert tool_msg["tool_call_id"] == "call-1"
        assert tool_msg["content"] == "Example"


@pytest.mark.asyncio
async def test_run_screenshot_tool_result_is_list_in_messages():
    """The screenshot tool result passed to the LLM must be a list, not a string."""
    shot_call = _make_tool_call("browser_screenshot", {})
    first_resp = _make_llm_response(tool_calls=[shot_call])
    second_resp = _make_llm_response(content="I can see the page.")

    run_obj = MagicMock()
    run_obj.status = "running"
    run_obj.recording_url = None
    session = _make_run_session(["running", "running"], run_obj)

    new_resp = _make_http_response({"session_id": "sess-1"})
    shot_resp = _make_http_response({"image_b64": "abc123=="})
    close_resp = _make_http_response({"recording_url": None})
    mock_http = MagicMock()
    mock_http.post = AsyncMock(side_effect=[new_resp, shot_resp, close_resp])
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_http)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("litellm.acompletion", new_callable=AsyncMock, side_effect=[first_resp, second_resp]) as mock_llm, \
         patch("httpx.AsyncClient", return_value=mock_ctx), \
         patch("app.agents.automation_agent.AgentTools") as MockTools:

        tools_instance = MagicMock()
        tools_instance.as_litellm_tools.return_value = []
        MockTools.return_value = tools_instance

        await agent_mod.run(
            run_id="run-1",
            workspace_id="ws-1",
            goal="take a screenshot",
            session=session,
            audience_user_id="user-1",
        )

        # Assert inside patch scope so mock_llm.call_args_list is still the patched object
        second_call_messages = mock_llm.call_args_list[1][1]["messages"]
        tool_msg = next((m for m in second_call_messages if m.get("role") == "tool"), None)
        assert tool_msg is not None
        assert isinstance(tool_msg["content"], list), "screenshot content must be a list for multimodal consumption"
        image_blocks = [b for b in tool_msg["content"] if b.get("type") == "image_url"]
        assert len(image_blocks) == 1
        assert "abc123==" in image_blocks[0]["image_url"]["url"]


@pytest.mark.asyncio
async def test_run_browser_session_always_closed_on_error():
    """Session/close must be called even when the LLM raises."""
    run_obj = MagicMock()
    run_obj.status = "running"
    run_obj.recording_url = None
    session = _make_run_session(["running"], run_obj)

    new_resp = _make_http_response({"session_id": "sess-err"})
    close_resp = _make_http_response({"recording_url": None})
    mock_http = MagicMock()
    mock_http.post = AsyncMock(side_effect=[new_resp, close_resp])
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_http)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("litellm.acompletion", new_callable=AsyncMock, side_effect=RuntimeError("LLM boom")), \
         patch("httpx.AsyncClient", return_value=mock_ctx), \
         patch("app.agents.automation_agent.AgentTools") as MockTools:

        tools_instance = MagicMock()
        tools_instance.as_litellm_tools.return_value = []
        MockTools.return_value = tools_instance

        await agent_mod.run(
            run_id="run-1",
            workspace_id="ws-1",
            goal="boom",
            session=session,
            audience_user_id="user-1",
        )

    call_urls = [c.args[0] for c in mock_http.post.call_args_list]
    assert any("close" in url for url in call_urls)
    assert run_obj.status == "failed"


@pytest.mark.asyncio
async def test_run_publishes_automation_status_on_completion():
    llm_resp = _make_llm_response(content="Done.")

    run_obj = MagicMock()
    run_obj.status = "running"
    run_obj.recording_url = None
    session = _make_run_session(["running"], run_obj)

    mock_http = MagicMock()
    mock_http.post = AsyncMock(side_effect=[
        _make_http_response({"session_id": "sess-1"}),
        _make_http_response({"recording_url": None}),
    ])
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_http)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("litellm.acompletion", new_callable=AsyncMock, return_value=llm_resp), \
         patch("httpx.AsyncClient", return_value=mock_ctx), \
         patch("app.agents.automation_agent.AgentTools") as MockTools, \
         patch("app.agents.automation_agent.broadcaster") as mock_b:

        mock_b.publish = AsyncMock()
        tools_instance = MagicMock()
        tools_instance.as_litellm_tools.return_value = []
        MockTools.return_value = tools_instance

        await agent_mod.run(
            run_id="run-1",
            workspace_id="ws-1",
            goal="go",
            session=session,
            audience_user_id="user-1",
        )

    status_events = [
        c[0][0] for c in mock_b.publish.call_args_list
        if c[0][0].get("event") == "automation:status"
    ]
    assert len(status_events) == 1
    assert status_events[0]["run_id"] == "run-1"
