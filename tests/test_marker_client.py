import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import os


# ── DatalabMarkerClient ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_datalab_client_submits_and_polls():
    from app.marker_client import DatalabMarkerClient, PageData

    submit_response = MagicMock()
    submit_response.raise_for_status = MagicMock()
    submit_response.json.return_value = {
        "success": True,
        "request_id": "req123",
        "request_check_url": "https://www.datalab.to/api/v1/convert/req123",
    }

    poll_response = MagicMock()
    poll_response.raise_for_status = MagicMock()
    poll_response.json.return_value = {
        "status": "complete",
        "markdown": "# Page 1\n\nHello\n\n1\n" + "-" * 48 + "\n\n# Page 2\n\nWorld",
        "images": {},
    }

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=submit_response)
    mock_client.get = AsyncMock(return_value=poll_response)

    with patch("app.marker_client.httpx.AsyncClient", return_value=mock_client):
        with patch("app.marker_client.asyncio.sleep", new_callable=AsyncMock):
            client = DatalabMarkerClient(api_key="test-key", mode="fast")
            pages = await client.convert(b"fake-pdf", "doc.pdf", source_id="s1")

    assert len(pages) == 2
    assert isinstance(pages[0], PageData)
    assert pages[0].page_num == 1
    assert "Hello" in pages[0].markdown
    assert pages[1].page_num == 2
    assert "World" in pages[1].markdown


@pytest.mark.asyncio
async def test_datalab_client_raises_on_failed_status():
    from app.marker_client import DatalabMarkerClient

    submit_response = MagicMock()
    submit_response.raise_for_status = MagicMock()
    submit_response.json.return_value = {
        "success": True,
        "request_id": "req456",
        "request_check_url": "https://www.datalab.to/api/v1/convert/req456",
    }

    poll_response = MagicMock()
    poll_response.raise_for_status = MagicMock()
    poll_response.json.return_value = {"status": "failed", "error": "unsupported format"}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=submit_response)
    mock_client.get = AsyncMock(return_value=poll_response)

    with patch("app.marker_client.httpx.AsyncClient", return_value=mock_client):
        with patch("app.marker_client.asyncio.sleep", new_callable=AsyncMock):
            client = DatalabMarkerClient(api_key="test-key", mode="fast")
            with pytest.raises(RuntimeError, match="unsupported format"):
                await client.convert(b"bytes", "doc.pdf")


@pytest.mark.asyncio
async def test_datalab_client_attaches_images_to_pages():
    from app.marker_client import DatalabMarkerClient

    submit_response = MagicMock()
    submit_response.raise_for_status = MagicMock()
    submit_response.json.return_value = {
        "success": True,
        "request_id": "req789",
        "request_check_url": "https://www.datalab.to/api/v1/convert/req789",
    }

    poll_response = MagicMock()
    poll_response.raise_for_status = MagicMock()
    poll_response.json.return_value = {
        "status": "complete",
        "markdown": "# Page 1\n\n![fig](img0.png)\n\n1\n" + "-" * 48 + "\n\n# Page 2\n\nno images",
        "images": {"img0.png": "base64data=="},
    }

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=submit_response)
    mock_client.get = AsyncMock(return_value=poll_response)

    with patch("app.marker_client.httpx.AsyncClient", return_value=mock_client):
        with patch("app.marker_client.asyncio.sleep", new_callable=AsyncMock):
            client = DatalabMarkerClient(api_key="test-key", mode="fast")
            pages = await client.convert(b"bytes", "doc.pdf")

    assert len(pages[0].images) == 1
    assert pages[0].images[0].filename == "img0.png"
    assert pages[0].images[0].b64 == "base64data=="
    assert pages[1].images == []


@pytest.mark.asyncio
async def test_datalab_client_sends_correct_form_fields():
    from app.marker_client import DatalabMarkerClient

    submit_response = MagicMock()
    submit_response.raise_for_status = MagicMock()
    submit_response.json.return_value = {
        "success": True,
        "request_id": "reqabc",
        "request_check_url": "https://www.datalab.to/api/v1/convert/reqabc",
    }
    poll_response = MagicMock()
    poll_response.raise_for_status = MagicMock()
    poll_response.json.return_value = {"status": "complete", "markdown": "text", "images": {}}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=submit_response)
    mock_client.get = AsyncMock(return_value=poll_response)

    with patch("app.marker_client.httpx.AsyncClient", return_value=mock_client):
        with patch("app.marker_client.asyncio.sleep", new_callable=AsyncMock):
            client = DatalabMarkerClient(api_key="my-key", mode="accurate")
            await client.convert(b"bytes", "report.pdf")

    post_call = mock_client.post.call_args
    assert post_call.kwargs["headers"] == {"X-API-Key": "my-key"}
    assert post_call.kwargs["data"]["output_format"] == "markdown"
    assert post_call.kwargs["data"]["paginate"] == "true"
    assert post_call.kwargs["data"]["mode"] == "accurate"
    assert post_call.kwargs["files"]["file"][0] == "report.pdf"


# ── LocalMarkerClient ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_local_client_returns_page_data():
    from app.marker_client import LocalMarkerClient, PageData

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
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
        client = LocalMarkerClient(base_url="http://marker:8001")
        pages = await client.convert(b"fake-pdf-bytes", "doc.pdf")

    assert len(pages) == 2
    assert isinstance(pages[0], PageData)
    assert pages[0].page_num == 1
    assert pages[0].markdown == "# Hello\n\nWorld"
    assert pages[0].images == []
    assert pages[1].images[0].filename == "img0.png"
    assert pages[1].images[0].b64 == "abc123"


@pytest.mark.asyncio
async def test_local_client_passes_llm_config():
    from app.marker_client import LocalMarkerClient

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = [{"page_num": 1, "markdown": "text", "images": []}]

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("app.marker_client.httpx.AsyncClient", return_value=mock_client):
        client = LocalMarkerClient(
            base_url="http://marker:8001",
            use_llm=True,
            llm_service="marker.services.claude.ClaudeService",
            llm_model="claude-3-5-haiku",
            llm_api_key="sk-ant-test",
        )
        await client.convert(b"bytes", "doc.pdf")

    call_kwargs = mock_client.post.call_args.kwargs
    assert call_kwargs["data"]["use_llm"] == "true"
    assert call_kwargs["data"]["llm_service"] == "marker.services.claude.ClaudeService"
    assert call_kwargs["data"]["llm_model"] == "claude-3-5-haiku"
    assert call_kwargs["data"]["llm_api_key"] == "sk-ant-test"
    assert call_kwargs["files"]["file"] == ("doc.pdf", b"bytes", "application/octet-stream")


# ── make_client factory ───────────────────────────────────────────────────

def test_make_client_returns_datalab_by_default(monkeypatch):
    monkeypatch.setenv("MARKER_BACKEND", "datalab")
    monkeypatch.setenv("DATALAB_API_KEY", "key")
    # Force settings reload
    import importlib, app.config, app.marker_client
    importlib.reload(app.config)
    importlib.reload(app.marker_client)
    from app.marker_client import make_client, DatalabMarkerClient
    assert isinstance(make_client(), DatalabMarkerClient)


def test_make_client_returns_local_when_configured(monkeypatch):
    monkeypatch.setenv("MARKER_BACKEND", "local")
    import importlib, app.config, app.marker_client
    importlib.reload(app.config)
    importlib.reload(app.marker_client)
    from app.marker_client import make_client, LocalMarkerClient
    assert isinstance(make_client(), LocalMarkerClient)
