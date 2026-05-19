"""Tests for browser_chat_agent._dispatch."""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.agents.browser_chat_agent import BrowserClosedError, _dispatch, _safe_browser_post


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
