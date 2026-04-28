import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_marker_client_convert_returns_page_data():
    from app.marker_client import MarkerClient, PageData

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {"page_num": 1, "markdown": "# Hello\n\nWorld", "images": []},
        {
            "page_num": 2,
            "markdown": "## Section 2\n\nContent",
            "images": [{"filename": "img0.png", "b64": "abc123"}],
        },
    ]

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("app.marker_client.httpx.AsyncClient", return_value=mock_client):
        client = MarkerClient(base_url="http://marker:8001")
        pages = await client.convert(b"fake-pdf-bytes", "doc.pdf")

    assert len(pages) == 2
    assert isinstance(pages[0], PageData)
    assert pages[0].page_num == 1
    assert pages[0].markdown == "# Hello\n\nWorld"
    assert pages[0].images == []
    assert pages[1].images[0].filename == "img0.png"
    assert pages[1].images[0].b64 == "abc123"


@pytest.mark.asyncio
async def test_marker_client_passes_llm_config():
    from app.marker_client import MarkerClient

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [{"page_num": 1, "markdown": "text", "images": []}]

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("app.marker_client.httpx.AsyncClient", return_value=mock_client):
        client = MarkerClient(
            base_url="http://marker:8001",
            use_llm=True,
            llm_service="marker.services.claude.ClaudeService",
            llm_model="claude-3-5-haiku",
            llm_api_key="sk-ant-test",
        )
        await client.convert(b"bytes", "doc.pdf")

    assert mock_client.post.called

    call_kwargs = mock_client.post.call_args.kwargs
    assert call_kwargs["data"]["use_llm"] == "true"
    assert call_kwargs["data"]["llm_service"] == "marker.services.claude.ClaudeService"
    assert call_kwargs["data"]["llm_model"] == "claude-3-5-haiku"
    assert call_kwargs["data"]["llm_api_key"] == "sk-ant-test"
    assert call_kwargs["files"]["file"] == ("doc.pdf", b"bytes", "application/octet-stream")
