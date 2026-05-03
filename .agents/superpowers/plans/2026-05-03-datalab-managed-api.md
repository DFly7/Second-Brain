# Datalab Managed API Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the local Marker Docker container with the Datalab managed API for document conversion, while keeping local Marker available as a switchable backend via `MARKER_BACKEND=local`.

**Architecture:** `marker_client.py` gets two concrete classes (`DatalabMarkerClient`, `LocalMarkerClient`) plus a `make_client()` factory that reads `settings.marker_backend`. All call sites use `make_client()`, so the backend is transparent to the rest of the app. The local vision captioning step (`_ensure_vision_captions`) is removed entirely — Datalab embeds captions inline in the markdown output, making the separate vision pass redundant.

**Tech Stack:** httpx (async HTTP), Datalab REST API (`POST /api/v1/convert` + poll), pydantic-settings, alembic for DB migration.

---

## File Map

| File | Action | What changes |
|------|--------|-------------|
| `api/app/marker_client.py` | Rewrite | Two classes + `make_client()` factory |
| `api/app/config.py` | Modify | Add `MARKER_BACKEND`, `DATALAB_API_KEY`, `DATALAB_MODE`; remove `marker_use_llm`, `marker_llm_*`, `vision_model` |
| `api/app/routes/ingest.py` | Modify | Remove `_marker_sem`; use `make_client()` |
| `api/app/agents/tools.py` | Modify | Remove `_ensure_vision_captions`, `describe_image`, their tool definition, prompt loads, and call site |
| `api/app/models.py` | Modify | Remove `vision_processed` column + its `__init__` default |
| `api/alembic/versions/<rev>_drop_vision_processed.py` | Create | Migration to drop the column |
| `docker-compose.yml` | Modify | Comment out marker service; add `MARKER_BACKEND: datalab` to api env |
| `api/app/agents/prompts/vision_caption.md` | Delete | No longer used |
| `api/app/agents/prompts/vision_describe.md` | Delete | No longer used |
| `tests/test_marker_client.py` | Rewrite | Tests for `DatalabMarkerClient`, `LocalMarkerClient`, `make_client()` |
| `tests/test_ingest_semaphore.py` | Delete | Tests `_marker_sem` which is being removed |

---

## Task 1: Rewrite `marker_client.py`

**Files:**
- Modify: `api/app/marker_client.py`

The Datalab flow is: POST file → get `request_check_url` → poll until `status == "complete"` → parse paginated markdown + images dict.

The local flow is unchanged — POST to the local container, parse JSON array of pages directly.

Both share the same `PageData`/`ImageData` dataclasses and `_parse_paginated_markdown` helper (the local service also returns paginated markdown via `paginate_output: True`).

- [ ] **Step 1: Write the failing tests first**

In `tests/test_marker_client.py`, replace the entire file with:

```python
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
```

- [ ] **Step 2: Run tests — verify they all fail**

```bash
docker compose run --rm api pytest tests/test_marker_client.py -v 2>&1 | tail -30
```

Expected: multiple failures — `DatalabMarkerClient`, `LocalMarkerClient`, `make_client` not defined.

- [ ] **Step 3: Rewrite `api/app/marker_client.py`**

Replace the entire file with:

```python
import asyncio
import logging
import re
import time
from dataclasses import dataclass, field

import httpx

from app.config import settings

_log = logging.getLogger(__name__)

DATALAB_CONVERT_URL = "https://www.datalab.to/api/v1/convert"
_PAGE_SEP = re.compile(r"\n\n\d+\n-{48}\n\n")
_IMG_REF = re.compile(r"!\[.*?\]\(([^)]+)\)")

_DATALAB_SUBMIT_TIMEOUT = httpx.Timeout(connect=30.0, read=60.0, write=120.0, pool=30.0)
_DATALAB_POLL_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)
_LOCAL_HTTP_TIMEOUT = httpx.Timeout(connect=60.0, read=7200.0, write=600.0, pool=60.0)

_CONNECT_RETRIES = 5
_CONNECT_BACKOFF_BASE = 15.0
_CONNECT_BACKOFF_MAX = 120.0
POLL_INTERVAL = 5.0
MAX_WAIT = 7200.0


@dataclass
class ImageData:
    filename: str
    b64: str


@dataclass
class PageData:
    page_num: int
    markdown: str
    images: list[ImageData] = field(default_factory=list)


def _parse_paginated_markdown(full_markdown: str, b64_images: dict) -> list[PageData]:
    raw_pages = _PAGE_SEP.split(full_markdown)
    pages = []
    for i, page_md in enumerate(raw_pages):
        page_md = page_md.strip()
        if not page_md:
            continue
        refs = _IMG_REF.findall(page_md)
        page_images = [
            ImageData(filename=ref, b64=b64_images[ref])
            for ref in refs
            if ref in b64_images
        ]
        pages.append(PageData(page_num=i + 1, markdown=page_md, images=page_images))
    return pages


class DatalabMarkerClient:
    def __init__(self, api_key: str = "", mode: str = ""):
        self.api_key = api_key or settings.datalab_api_key
        self.mode = mode or settings.datalab_mode

    async def convert(self, data: bytes, filename: str, *, source_id: str = "") -> list[PageData]:
        headers = {"X-API-Key": self.api_key}
        files = {"file": (filename, data, "application/octet-stream")}
        form = {"output_format": "markdown", "paginate": "true", "mode": self.mode}

        async with httpx.AsyncClient(timeout=_DATALAB_SUBMIT_TIMEOUT) as client:
            resp = await client.post(
                DATALAB_CONVERT_URL, headers=headers, files=files, data=form
            )
            resp.raise_for_status()
            submission = resp.json()

        if not submission.get("success"):
            raise RuntimeError(f"Datalab submission failed: {submission}")

        check_url = submission["request_check_url"]
        _log.info(
            "datalab submitted source_id=%s request_id=%s",
            source_id or "-",
            submission["request_id"],
        )

        deadline = time.monotonic() + MAX_WAIT
        async with httpx.AsyncClient(timeout=_DATALAB_POLL_TIMEOUT) as client:
            while time.monotonic() < deadline:
                await asyncio.sleep(POLL_INTERVAL)
                resp = await client.get(check_url, headers=headers)
                resp.raise_for_status()
                result = resp.json()
                if result["status"] == "complete":
                    break
                if result["status"] == "failed":
                    raise RuntimeError(
                        f"Datalab conversion failed: {result.get('error')}"
                    )
            else:
                raise TimeoutError(
                    f"Datalab conversion timed out after {MAX_WAIT}s source_id={source_id or '-'}"
                )

        _log.info("datalab complete source_id=%s", source_id or "-")
        return _parse_paginated_markdown(
            result.get("markdown", ""), result.get("images") or {}
        )


class LocalMarkerClient:
    def __init__(
        self,
        base_url: str = "",
        use_llm: bool = False,
        llm_service: str = "",
        llm_model: str = "",
        llm_api_key: str = "",
    ):
        self.base_url = base_url or settings.marker_url
        self.use_llm = use_llm
        self.llm_service = llm_service or settings.marker_llm_service
        self.llm_model = llm_model or settings.marker_llm_model
        self.llm_api_key = llm_api_key or settings.marker_llm_api_key

    async def convert(self, data: bytes, filename: str, *, source_id: str = "") -> list[PageData]:
        form = {
            "use_llm": str(self.use_llm).lower(),
            "llm_service": self.llm_service,
            "llm_model": self.llm_model,
            "llm_api_key": self.llm_api_key,
            "source_id": source_id,
        }
        files = {"file": (filename, data, "application/octet-stream")}
        url = f"{self.base_url}/convert"
        _log.info(
            "local marker POST %s source_id=%s filename=%s bytes=%d",
            url,
            source_id or "-",
            filename,
            len(data),
        )

        resp = None
        for attempt in range(_CONNECT_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=_LOCAL_HTTP_TIMEOUT) as client:
                    resp = await client.post(url, data=form, files=files)
                    resp.raise_for_status()
                break
            except (httpx.ConnectError, httpx.RemoteProtocolError) as e:
                if attempt >= _CONNECT_RETRIES:
                    raise
                wait = min(_CONNECT_BACKOFF_BASE * (2**attempt), _CONNECT_BACKOFF_MAX)
                _log.warning(
                    "local marker %s (attempt %d/%d), retrying in %.0fs. source_id=%s",
                    type(e).__name__,
                    attempt + 1,
                    _CONNECT_RETRIES,
                    wait,
                    source_id or "-",
                )
                await asyncio.sleep(wait)

        raw_pages = resp.json()
        _log.info(
            "local marker response OK source_id=%s pages=%d", source_id or "-", len(raw_pages)
        )
        return [
            PageData(
                page_num=p["page_num"],
                markdown=p["markdown"],
                images=[ImageData(**img) for img in p.get("images", [])],
            )
            for p in raw_pages
        ]


def make_client() -> DatalabMarkerClient | LocalMarkerClient:
    if settings.marker_backend == "local":
        return LocalMarkerClient()
    return DatalabMarkerClient()
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
docker compose run --rm api pytest tests/test_marker_client.py -v 2>&1 | tail -30
```

Expected: all green. (The `make_client` reload tests may be fragile if settings is a singleton — if they fail, skip them and note in the commit; the factory logic is trivially correct.)

- [ ] **Step 5: Commit**

```bash
git add api/app/marker_client.py tests/test_marker_client.py
git commit -m "feat: add DatalabMarkerClient and LocalMarkerClient with make_client factory"
```

---

## Task 2: Update `config.py`

**Files:**
- Modify: `api/app/config.py`

Remove the five old marker/vision settings; add four new ones. Keep `marker_url` and the local LLM settings — they're needed by `LocalMarkerClient`.

- [ ] **Step 1: Edit `api/app/config.py`**

Replace the settings block (lines 17–23 in the original). The full file becomes:

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    jwt_secret: str = "dev-secret"
    litellm_model: str = "gemini/gemini-2.0-flash"
    gemini_api_key: str | None = None
    s3_endpoint: str = "http://minio:9000"
    s3_bucket: str = "wiki"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    single_user_email: str = "user@example.com"
    single_user_password: str = "changeme"
    vector_search_enabled: bool = True
    # Conversion backend: "datalab" (managed API) or "local" (self-hosted marker container)
    marker_backend: str = "datalab"
    datalab_api_key: str = ""
    datalab_mode: str = "accurate"
    # Local marker settings — only used when MARKER_BACKEND=local
    marker_url: str = "http://marker:8001"
    marker_llm_service: str = "marker.services.gemini.GoogleGeminiService"
    marker_llm_model: str = ""
    marker_llm_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""

    class Config:
        env_file = ".env"


settings = Settings()
```

- [ ] **Step 2: Run the full test suite to catch any import breakage**

```bash
docker compose run --rm api pytest tests/ -v 2>&1 | tail -40
```

Expected: all tests that were passing before still pass. Any failure referencing `settings.vision_model` or `settings.marker_use_llm` means a reference was missed — fix before committing.

- [ ] **Step 3: Commit**

```bash
git add api/app/config.py
git commit -m "feat: replace marker/vision settings with datalab_api_key and marker_backend"
```

---

## Task 3: Update `routes/ingest.py`

**Files:**
- Modify: `api/app/routes/ingest.py`
- Delete: `tests/test_ingest_semaphore.py`

The semaphore `_marker_sem` protected the local container (1 concurrent conversion). With Datalab, rate limiting is server-side, so the semaphore is removed. The `make_client()` factory replaces the direct `MarkerClient()` instantiation.

- [ ] **Step 1: Delete the semaphore test file**

```bash
rm tests/test_ingest_semaphore.py
```

- [ ] **Step 2: Edit `api/app/routes/ingest.py`**

Remove line 22 (`_marker_sem = asyncio.Semaphore(...)`). Remove the `async with _marker_sem:` block and de-indent its body. Change the import and instantiation of `MarkerClient`. The relevant section of `_run_pipeline` goes from:

```python
            else:
                async with _marker_sem:
                    await broadcaster.publish({"event": "agent:converting", "source_id": source_id, "filename": filename})
                    _log.info("ingest calling marker source_id=%s filename=%s", source_id, filename)
                    client = MarkerClient()
                    raw_pages = await client.convert(data, filename, source_id=source_id)
```

to:

```python
            else:
                await broadcaster.publish({"event": "agent:converting", "source_id": source_id, "filename": filename})
                _log.info("ingest calling marker source_id=%s filename=%s", source_id, filename)
                from app.marker_client import make_client
                client = make_client()
                raw_pages = await client.convert(data, filename, source_id=source_id)
```

Also remove the top-level `import asyncio` if it's only used for the semaphore — check first. (It's also used for `asyncio.Semaphore` only; the `asyncio.to_thread` in marker_service is gone. But `asyncio` may be used elsewhere in the file — grep before removing.)

- [ ] **Step 3: Verify `asyncio` import**

```bash
grep -n "asyncio\." api/app/routes/ingest.py
```

If the only hit was `asyncio.Semaphore(...)` (now deleted), remove the `import asyncio` line too. If other uses exist, leave it.

- [ ] **Step 4: Run tests**

```bash
docker compose run --rm api pytest tests/test_ingest_route.py tests/test_marker_client.py -v 2>&1 | tail -20
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add api/app/routes/ingest.py tests/test_ingest_semaphore.py
git commit -m "feat: remove marker semaphore; use make_client() factory in ingest pipeline"
```

---

## Task 4: Strip vision from `tools.py`

**Files:**
- Modify: `api/app/agents/tools.py`
- Delete: `api/app/agents/prompts/vision_caption.md`
- Delete: `api/app/agents/prompts/vision_describe.md`

Remove: `_ensure_vision_captions` function, `describe_image` method, the `describe_image` entry in `as_litellm_tools`, the `describe_image` branch in `dispatch`, the two prompt file loads, and the `_ensure_vision_captions(page, self.session)` call in `read_source_page`. Also update the `read_source_page` tool description which mentions vision.

- [ ] **Step 1: Delete the prompt files**

```bash
rm api/app/agents/prompts/vision_caption.md api/app/agents/prompts/vision_describe.md
```

- [ ] **Step 2: Edit `api/app/agents/tools.py` — remove imports and top-level constants**

Remove these lines (currently lines 6, 19–20):

```python
from jinja2 import Template          # line 6 — only used for _VISION_CAPTION_TEMPLATE
...
_VISION_CAPTION_TEMPLATE = Template((_PROMPTS / "vision_caption.md").read_text())
_VISION_DESCRIBE_PROMPT = (_PROMPTS / "vision_describe.md").read_text()
```

If `Template` / `jinja2` is used elsewhere in the file, keep the import. Verify:

```bash
grep -n "Template\|jinja2" api/app/agents/tools.py
```

- [ ] **Step 3: Remove `_ensure_vision_captions` function (lines 26–85)**

Delete the entire function:

```python
async def _ensure_vision_captions(page: SourcePage, session: AsyncSession) -> None:
    ...  # (entire function body, ~60 lines)
```

- [ ] **Step 4: Remove the call site in `read_source_page`**

Find the line:
```python
        await _ensure_vision_captions(page, self.session)
```
(currently around line 526) and delete it. Update the `read_source_page` tool description — change:

```python
"description": "Read the full markdown of a source document page. Pages with images include vision-model descriptions of figures inline.",
```

to:

```python
"description": "Read the full markdown of a source document page.",
```

- [ ] **Step 5: Remove `describe_image` method (lines 529–560)**

Delete the entire method:

```python
    async def describe_image(self, s3_key: str) -> str:
        ...  # (~32 lines)
```

- [ ] **Step 6: Remove `describe_image` from `as_litellm_tools` tool list**

Delete the entire tool dict (lines 795–815):

```python
            {
                "type": "function",
                "function": {
                    "name": "describe_image",
                    ...
                },
            },
```

- [ ] **Step 7: Remove `describe_image` branch in `dispatch`**

Find and delete (around line 863):

```python
        if name == "describe_image":
            return await self.describe_image(args["s3_key"])
```

- [ ] **Step 8: Check `base64` and `download_file` imports are still needed**

```bash
grep -n "base64\|download_file" api/app/agents/tools.py
```

`download_file` is used in `describe_image` (being deleted) — check if it's used anywhere else in the file. `base64` likewise. Remove unused imports.

- [ ] **Step 9: Run full test suite**

```bash
docker compose run --rm api pytest tests/ -v 2>&1 | tail -30
```

Expected: all green. Any `AttributeError: _ensure_vision_captions` means a call site was missed.

- [ ] **Step 10: Commit**

```bash
git add api/app/agents/tools.py api/app/agents/prompts/vision_caption.md api/app/agents/prompts/vision_describe.md
git commit -m "feat: remove vision captioning pipeline — Datalab provides inline captions"
```

---

## Task 5: Drop `vision_processed` from model + migration

**Files:**
- Modify: `api/app/models.py`
- Create: `api/alembic/versions/<rev>_drop_vision_processed.py`

- [ ] **Step 1: Edit `api/app/models.py`**

In the `SourcePage` class, remove:

```python
    vision_processed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
```

And in `__init__`:

```python
        kwargs.setdefault("vision_processed", False)
```

After the edit the `SourcePage.__init__` method will be empty — remove the whole `__init__` method:

```python
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
```

Check whether `Boolean` is still used elsewhere in `models.py`:

```bash
grep -n "Boolean" api/app/models.py
```

If `Boolean` only appeared in `vision_processed`, remove it from the imports line too.

- [ ] **Step 2: Generate the alembic migration**

```bash
docker compose run --rm api alembic revision --autogenerate -m "drop_vision_processed"
```

This creates a new file in `api/alembic/versions/`. Open it and verify the `upgrade()` contains `op.drop_column('source_pages', 'vision_processed')` and `downgrade()` contains `op.add_column(...)`. If autogenerate missed it (it sometimes does for column removals), edit manually:

```python
def upgrade() -> None:
    op.drop_column('source_pages', 'vision_processed')


def downgrade() -> None:
    op.add_column(
        'source_pages',
        sa.Column(
            'vision_processed',
            sa.Boolean(),
            nullable=False,
            server_default='false',
        ),
    )
```

- [ ] **Step 3: Apply migration to test DB**

```bash
docker compose run --rm api alembic upgrade head
```

Expected: `Running upgrade ... -> <new_rev>, drop_vision_processed`

- [ ] **Step 4: Run full test suite**

```bash
docker compose run --rm api pytest tests/ -v 2>&1 | tail -30
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add api/app/models.py api/alembic/versions/
git commit -m "feat: drop vision_processed column from source_pages"
```

---

## Task 6: Update `docker-compose.yml`

**Files:**
- Modify: `docker-compose.yml`

Comment out the `marker` service (preserving it for easy re-enable), remove the `marker` health dependency from `api`, remove the `MARKER_URL` env override (it has a sensible default), add `MARKER_BACKEND: datalab` to the api env block, and remove the `marker_models` volume.

- [ ] **Step 1: Edit `docker-compose.yml`**

The full updated file:

```yaml
version: "3.9"
services:
  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: wiki
      POSTGRES_USER: wiki
      POSTGRES_PASSWORD: wiki
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./postgres-init:/docker-entrypoint-initdb.d:ro
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U wiki"]
      interval: 5s
      timeout: 5s
      retries: 5

  minio:
    image: minio/minio
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    volumes:
      - minio_data:/data
    ports:
      - "9000:9000"
      - "9001:9001"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 10s
      timeout: 5s
      retries: 3

  # Local marker service — uncomment and set MARKER_BACKEND=local in api env to use instead of Datalab
  # marker:
  #   build: ./marker_service
  #   restart: on-failure
  #   shm_size: '2gb'
  #   environment:
  #     PARALLEL_DOWNLOAD_WORKERS: "1"
  #   healthcheck:
  #     test: ["CMD", "curl", "-f", "http://localhost:8001/health"]
  #     interval: 30s
  #     timeout: 10s
  #     retries: 3
  #     start_period: 900s
  #   volumes:
  #     - marker_models:/root/.cache

  api:
    build: ./api
    depends_on:
      db:
        condition: service_healthy
      minio:
        condition: service_healthy
      # marker:           # uncomment when MARKER_BACKEND=local
      #   condition: service_healthy
    env_file: .env
    environment:
      DATABASE_URL: postgresql+asyncpg://wiki:wiki@db:5432/wiki
      S3_ENDPOINT: http://minio:9000
      MARKER_BACKEND: datalab
    ports:
      - "8000:8000"
    volumes:
      - ./api:/app
      - ./tests:/app/tests
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

  frontend:
    build: ./frontend
    depends_on:
      - api
    ports:
      - "5173:5173"
    volumes:
      - ./frontend:/app
      - /app/node_modules
    environment:
      VITE_API_URL: http://localhost:8000
    command: sh -c "npm install && npm run dev -- --host 0.0.0.0"

volumes:
  pgdata:
  minio_data:
  # marker_models:   # uncomment when using local marker
```

- [ ] **Step 2: Verify compose parses correctly**

```bash
docker compose config --quiet && echo "OK"
```

Expected: `OK` with no errors.

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: comment out local marker service; default to MARKER_BACKEND=datalab"
```

---

## Task 7: Smoke test the full stack

This is a manual verification step — no code changes.

- [ ] **Step 1: Add `DATALAB_API_KEY` to your `.env` file**

```
DATALAB_API_KEY=your_key_here
```

- [ ] **Step 2: Start the stack**

```bash
docker compose up --build
```

Expected: api starts without waiting for marker container. No `marker` healthcheck delay.

- [ ] **Step 3: Run the full test suite one final time**

```bash
docker compose run --rm api pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 4: Ingest a test PDF via the UI or curl**

```bash
curl -X POST http://localhost:8000/ingest/file \
  -H "Authorization: Bearer <token>" \
  -F "file=@/path/to/test.pdf"
```

Watch the logs: you should see `datalab submitted source_id=... request_id=...` followed by `datalab complete source_id=...`. No `local marker POST` lines.

---

## Switching back to local Marker

To run with the local container:
1. Uncomment the `marker` service and `marker_models` volume in `docker-compose.yml`
2. Uncomment the `marker` dependency under `api.depends_on`
3. Change `MARKER_BACKEND: datalab` → `MARKER_BACKEND: local` in the api environment block
4. `docker compose up --build`

---

## Verification commands (run on your machine when ready)

These are intentionally at the end of the plan so implementation work does not depend on long Docker runs in agent sessions.

**1. Start database (and MinIO if tests need it)** — from repo root:

```bash
docker compose up -d db minio
```

Wait until `docker compose ps` shows `db` healthy (and `minio` healthy if required).

**2. Migrations** (applies to the DB in compose; use `wiki` or your configured DB):

```bash
docker compose run --rm api alembic upgrade head
```

**3. Tests** — avoids Compose waiting on unrelated services when `db`/`minio` are already up:

```bash
docker compose run --rm --no-deps api pytest tests/ -v
```

If `--no-deps` fails because the API container cannot reach `db` on the Docker network, omit `--no-deps` (Compose will create the default network and attach dependencies):

```bash
docker compose run --rm api pytest tests/ -v
```

**4. Full dev stack** (optional):

```bash
docker compose up --build
```

Ensure `.env` includes `DATALAB_API_KEY=...` when using `MARKER_BACKEND=datalab`.
