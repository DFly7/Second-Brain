"""Tests for browser_chat_agent._dispatch."""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.agents.browser_chat_agent import BrowserClosedError, _dispatch, _extract_text, _safe_browser_post


def _make_http_response(json_data: dict):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = json_data
    return resp


def _make_http(json_data: dict | None = None):
    resp = _make_http_response(json_data or {"ok": True})
    http = MagicMock()
    http.post = AsyncMock(return_value=resp)
    return http


def test_extract_text_plain_string():
    assert _extract_text("hello world") == "hello world"


def test_extract_text_list_extracts_text_blocks():
    content = [
        {"type": "thinking", "thinking": "let me think"},
        {"type": "text", "text": "Here are the results."},
    ]
    assert _extract_text(content) == "Here are the results."


def test_extract_text_multiple_text_blocks():
    content = [
        {"type": "text", "text": "Part one."},
        {"type": "text", "text": "Part two."},
    ]
    assert _extract_text(content) == "Part one. Part two."


def test_extract_text_list_with_no_text_blocks_returns_done():
    content = [{"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}}]
    assert _extract_text(content) == "Done."


def test_extract_text_empty_list_returns_done():
    assert _extract_text([]) == "Done."


def test_extract_text_none_returns_done():
    assert _extract_text(None) == "Done."


@pytest.fixture
def wiki():
    w = MagicMock()
    w.dispatch = AsyncMock(return_value="wiki result")
    w.as_litellm_tools = MagicMock(return_value=[])
    return w


@pytest.fixture(autouse=True)
def patch_broadcaster():
    with patch("app.agents.browser_chat_agent.broadcaster") as mock_b:
        mock_b.publish = AsyncMock()
        yield mock_b


@pytest.mark.asyncio
async def test_click_without_selector_or_text_returns_error_without_http_call(wiki):
    http = _make_http()
    result = await _dispatch("browser_click", {}, "sid", http, wiki, "chat-1", "u1")
    assert "Error" in result
    http.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_wait_for_without_args_returns_error_without_http_call(wiki):
    http = _make_http()
    result = await _dispatch("browser_wait_for", {}, "sid", http, wiki, "chat-1", "u1")
    assert "Error" in result
    http.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_screenshot_returns_list_content_shape(wiki):
    http = _make_http({"image_b64": "abc123=="})
    result = await _dispatch("browser_screenshot", {}, "sid", http, wiki, "chat-1", "u1")
    assert isinstance(result, list)
    image_blocks = [b for b in result if b.get("type") == "image_url"]
    assert len(image_blocks) == 1
    assert image_blocks[0]["image_url"]["url"] == "data:image/png;base64,abc123=="
    text_blocks = [b for b in result if b.get("type") == "text"]
    assert len(text_blocks) == 1


@pytest.mark.asyncio
async def test_wiki_read_delegates_to_agent_tools(wiki):
    result = await _dispatch("read_page", {"slug": "projects/alpha"}, "sid", _make_http(), wiki, "chat-1", "u1")
    assert result == "wiki result"
    wiki.dispatch.assert_awaited_once_with("read_page", {"slug": "projects/alpha"})


@pytest.mark.asyncio
async def test_click_at_posts_to_click_endpoint_with_coordinates(wiki, patch_broadcaster):
    http = _make_http({"ok": True})
    result = await _dispatch("browser_click_at", {"x": 400.0, "y": 300.0}, "sid", http, wiki, "chat-1", "u1")
    assert result == "clicked"
    http.post.assert_awaited_once_with("/session/sid/click", json={"x": 400.0, "y": 300.0})
    published = patch_broadcaster.publish.call_args[0][0]
    assert published["type"] == "click_at"
    assert "400" in published["detail"]
    assert "300" in published["detail"]


@pytest.mark.asyncio
async def test_mouse_move_posts_to_mouse_move_endpoint(wiki, patch_broadcaster):
    http = _make_http({"ok": True})
    result = await _dispatch("browser_mouse_move", {"x": 200.0, "y": 150.0}, "sid", http, wiki, "chat-1", "u1")
    assert result == "moved"
    http.post.assert_awaited_once_with("/session/sid/mouse_move", json={"x": 200.0, "y": 150.0})
    published = patch_broadcaster.publish.call_args[0][0]
    assert published["type"] == "mouse_move"
    assert "200" in published["detail"]
    assert "150" in published["detail"]


@pytest.mark.asyncio
async def test_safe_browser_post_raises_browser_closed_error_on_target_closed():
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 500
    mock_response.text = "playwright._impl._errors.TargetClosedError: Page.goto: Target page, context or browser has been closed"

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_response)

    with pytest.raises(BrowserClosedError):
        await _safe_browser_post(mock_client, "/session/abc/navigate", json={"url": "https://example.com"})


@pytest.mark.asyncio
async def test_safe_browser_post_raises_http_error_on_other_500():
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 500
    mock_response.text = "Internal Server Error - something unrelated"
    mock_response.raise_for_status = MagicMock(side_effect=httpx.HTTPStatusError("500", request=MagicMock(), response=mock_response))

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_response)

    with pytest.raises(httpx.HTTPStatusError):
        await _safe_browser_post(mock_client, "/session/abc/navigate", json={"url": "https://example.com"})


@pytest.mark.asyncio
async def test_safe_browser_post_returns_response_on_success():
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_response)

    result = await _safe_browser_post(mock_client, "/session/abc/screenshot")
    assert result is mock_response


@pytest.mark.asyncio
async def test_navigate_publishes_sse_action(wiki, patch_broadcaster):
    http = _make_http({"title": "Example"})
    await _dispatch("browser_navigate", {"url": "https://example.com"}, "sid", http, wiki, "chat-1", "u1")
    patch_broadcaster.publish.assert_awaited_once()
    published = patch_broadcaster.publish.call_args[0][0]
    assert published["event"] == "browser_chat:action"
    assert published["session_id"] == "chat-1"
    assert published["type"] == "navigate"
    _, kwargs = patch_broadcaster.publish.call_args
    assert kwargs["audience_user_id"] == "u1"


@pytest.mark.asyncio
async def test_run_turn_publishes_error_action_on_dispatch_exception(patch_broadcaster):
    """run_turn publishes an error action SSE event when _dispatch raises."""
    from unittest.mock import patch as upatch

    from app.agents.browser_chat_agent import run_turn

    tool_call = MagicMock()
    tool_call.id = "tc1"
    tool_call.function.name = "browser_navigate"
    tool_call.function.arguments = '{"url": "https://example.com"}'

    first_msg = MagicMock()
    first_msg.tool_calls = [tool_call]
    first_msg.content = None

    second_msg = MagicMock()
    second_msg.tool_calls = []
    second_msg.content = "Done navigating."

    first_resp = MagicMock()
    first_resp.choices = [MagicMock(message=first_msg)]
    second_resp = MagicMock()
    second_resp.choices = [MagicMock(message=second_msg)]

    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))

    with upatch("litellm.acompletion", new=AsyncMock(side_effect=[first_resp, second_resp])):
        with upatch("httpx.AsyncClient") as mock_client_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.post = AsyncMock(side_effect=Exception("network error"))
            mock_client_cls.return_value = mock_http

            await run_turn(
                chat_session_id="chat-1",
                workspace_id="ws-1",
                browser_session_id="b-1",
                conversation_history=[{"role": "user", "content": "go to example.com"}],
                audience_user_id="u1",
                db_session=db,
            )

    calls = [c[0][0] for c in patch_broadcaster.publish.call_args_list]
    error_actions = [c for c in calls if c.get("event") == "browser_chat:action" and c.get("error") is True]
    assert len(error_actions) == 1
    assert "network error" in error_actions[0]["detail"]


@pytest.mark.asyncio
async def test_await_cloudflare_cleared(wiki):
    http = _make_http({"cleared": True, "method": "passive"})
    result = await _dispatch("browser_await_cloudflare", {}, "sid", http, wiki, "chat-1", "u1")
    http.post.assert_awaited_once()
    assert http.post.await_args[0][0].endswith("/session/sid/await_cloudflare")
    assert "cleared" in result.lower()


@pytest.mark.asyncio
async def test_await_cloudflare_not_cleared(wiki):
    http = _make_http({"cleared": False, "error": "Cloudflare challenge did not clear"})
    result = await _dispatch("browser_await_cloudflare", {}, "sid", http, wiki, "chat-1", "u1")
    assert "did not clear" in result.lower()
