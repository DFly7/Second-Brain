"""Tests for browser_chat_agent._dispatch."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.browser_chat_agent import _dispatch, _extract_text


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
