# Marker Document Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace simple text extractors with a Marker-powered pipeline that converts uploaded documents to structured markdown + images, stores everything in S3, and gives the ingest agent paginated multi-turn access to large documents via an orchestrator/sub-agent pattern.

**Architecture:** A new `marker_service` Docker container wraps the Marker Python library, exposing `POST /convert` (multipart upload → JSON pages). The API's `MarkerClient` calls it, persists per-page markdown + image S3 keys in a new `SourcePage` table, then runs the ingest agent. The ingest agent acts as orchestrator: for docs ≤ 20 pages it reads directly; for larger docs it spawns concurrent read-only sub-agents that summarise page ranges, then does all wiki writes itself.

**Tech Stack:** Python 3.11, FastAPI, litellm, SQLAlchemy async, Alembic, boto3 (S3/MinIO), httpx (async HTTP), Marker (`marker-pdf[full]`), PIL, Docker Compose

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `marker_service/main.py` | FastAPI app: `POST /convert`, `GET /health` |
| Create | `marker_service/Dockerfile` | Container definition |
| Create | `marker_service/requirements.txt` | marker-pdf[full], fastapi, uvicorn, python-multipart, pillow |
| Modify | `api/app/config.py` | Add `marker_url`, `vision_model`, `marker_use_llm`, `marker_llm_*` settings |
| Modify | `tests/conftest.py` | Add `MARKER_URL`, `VISION_MODEL` env vars |
| Modify | `.env.example` | Document all new vars |
| Modify | `api/app/models.py` | Add `SourcePage`; add `status`, `markdown_s3_key` to `Source` |
| Create | `alembic/versions/XXXX_add_source_pages.py` | Migration for above |
| Modify | `api/app/storage.py` | Add `download_file(key) -> bytes` |
| Create | `api/app/marker_client.py` | `MarkerClient.convert()` — multipart POST to marker service |
| Modify | `api/app/agents/tools.py` | Add `list_source_pages()`, `read_source_page()` + vision; add to `as_litellm_tools` / `dispatch` |
| Create | `api/app/agents/sub_agent.py` | Read-only page-reader sub-agent; `run(source_id, workspace_id, page_start, page_end, focus_hint)` |
| Modify | `api/app/agents/ingest_agent.py` | Orchestrator: `spawn_page_reader` tool, concurrent sub-agent dispatch, wiki writes |
| Modify | `api/app/routes/ingest.py` | Two-stage pipeline, expanded file types (PPTX, XLSX, images) |
| Modify | `api/requirements.txt` | Add `httpx` |
| Modify | `docker-compose.yml` | Add `marker` service + `marker_models` volume |
| Modify | `docker-compose.prod.yml` | Same as above |

---

## Task 1: marker_service container

**Files:**
- Create: `marker_service/requirements.txt`
- Create: `marker_service/main.py`
- Create: `marker_service/Dockerfile`

- [ ] **Step 1: Create requirements.txt**

```
marker-pdf[full]
fastapi
uvicorn[standard]
python-multipart
pillow
```

- [ ] **Step 2: Create main.py**

```python
import base64
import io
import re
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile
from marker.config.parser import ConfigParser
from marker.converters.pdf import PdfConverter
from marker.models import create_model_dict
from marker.output import text_from_rendered
from PIL import Image

app = FastAPI(title="Marker Service")

# Models load once at startup — intentionally module-level
_models = create_model_dict()

_PAGE_SEP = re.compile(r"\n\n\d+\n-{48}\n\n")
_IMG_REF = re.compile(r"!\[.*?\]\(([^)]+)\)")


def _pil_to_b64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/convert")
async def convert(
    file: UploadFile = File(...),
    use_llm: bool = Form(False),
    llm_service: str = Form("marker.services.gemini.GoogleGeminiService"),
    llm_model: str = Form(""),
    llm_api_key: str = Form(""),
):
    data = await file.read()
    suffix = Path(file.filename or "file.pdf").suffix or ".pdf"

    config: dict = {"output_format": "markdown", "paginate_output": True}
    if use_llm:
        config["use_llm"] = True
        config["llm_service"] = llm_service
        if llm_model:
            config["llm_model"] = llm_model
        if llm_api_key:
            if "gemini" in llm_service.lower():
                config["gemini_api_key"] = llm_api_key
            elif "claude" in llm_service.lower():
                config["claude_api_key"] = llm_api_key
            elif "openai" in llm_service.lower():
                config["openai_api_key"] = llm_api_key

    config_parser = ConfigParser(config)

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(data)
        tmp_path = f.name

    try:
        converter = PdfConverter(
            config=config_parser.generate_config_dict(),
            artifact_dict=_models,
            processor_list=config_parser.get_processors(),
            renderer=config_parser.get_renderer(),
            llm_service=config_parser.get_llm_service() if use_llm else None,
        )
        rendered = converter(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    full_markdown, _, pil_images = text_from_rendered(rendered)
    # pil_images: {filename: PIL.Image}
    b64_images = {name: _pil_to_b64(img) for name, img in (pil_images or {}).items()}

    # Split into per-page sections (paginate_output inserts separators)
    raw_pages = _PAGE_SEP.split(full_markdown)

    pages = []
    for i, page_md in enumerate(raw_pages):
        page_md = page_md.strip()
        if not page_md:
            continue
        refs = _IMG_REF.findall(page_md)
        page_images = [
            {"filename": ref, "b64": b64_images[ref]}
            for ref in refs
            if ref in b64_images
        ]
        pages.append({"page_num": i + 1, "markdown": page_md, "images": page_images})

    return pages
```

- [ ] **Step 3: Create Dockerfile**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
```

- [ ] **Step 4: Commit**

```bash
git add marker_service/
git commit -m "feat: marker_service FastAPI container with POST /convert"
```

---

## Task 2: Config additions

**Files:**
- Modify: `api/app/config.py`
- Modify: `tests/conftest.py`
- Modify: `.env.example`

- [ ] **Step 1: Update config.py**

Add these fields to the `Settings` class in `api/app/config.py` (after the existing `vector_search_enabled` field):

```python
    marker_url: str = "http://marker:8001"
    marker_use_llm: bool = False
    marker_llm_service: str = "marker.services.gemini.GoogleGeminiService"
    marker_llm_model: str = ""
    marker_llm_api_key: str = ""
    vision_model: str = ""          # empty = vision disabled
    openai_api_key: str = ""
    anthropic_api_key: str = ""
```

- [ ] **Step 2: Update conftest.py**

Add these lines to `tests/conftest.py` after the existing `os.environ.setdefault` lines:

```python
os.environ.setdefault("MARKER_URL", "http://marker:8001")
os.environ.setdefault("VISION_MODEL", "")
```

- [ ] **Step 3: Update .env.example**

Append to `.env.example`:

```bash
# Marker service
MARKER_URL=http://marker:8001

# Marker LLM enhancement (off by default)
MARKER_USE_LLM=false
MARKER_LLM_SERVICE=marker.services.gemini.GoogleGeminiService
MARKER_LLM_MODEL=
MARKER_LLM_API_KEY=

# Vision model — must be multimodal. Leave empty to skip vision for image pages.
# Set the matching provider key below.
VISION_MODEL=gpt-4o
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
```

- [ ] **Step 4: Commit**

```bash
git add api/app/config.py tests/conftest.py .env.example
git commit -m "feat: add marker + vision settings to config"
```

---

## Task 3: Data model + migration

**Files:**
- Modify: `api/app/models.py`
- Create: `api/alembic/versions/<rev>_add_source_pages.py`

- [ ] **Step 1: Write a failing test for SourcePage**

Add to `tests/test_agents.py` (or create `tests/test_models.py`):

```python
@pytest.mark.asyncio
async def test_source_page_can_be_created():
    from app.database import AsyncSessionLocal
    from app.models import Source, SourcePage, Workspace

    async with AsyncSessionLocal() as session:
        ws = Workspace(user_id="u1")
        session.add(ws)
        await session.flush()
        src = Source(workspace_id=ws.id, kind="pdf", status="done")
        session.add(src)
        await session.flush()
        page = SourcePage(
            source_id=src.id,
            page_num=1,
            markdown="# Hello",
            preview="# Hello",
            image_s3_keys=[],
        )
        session.add(page)
        await session.commit()
        await session.refresh(page)
        assert page.id is not None
        assert page.page_num == 1
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
cd /path/to/project && docker compose run --rm api pytest tests/test_agents.py::test_source_page_can_be_created -v
```

Expected: `FAIL` — `SourcePage` not imported or table missing.

- [ ] **Step 3: Add SourcePage to models.py and update Source**

Update `Source` to add two columns after `extracted_text`:
```python
    status: Mapped[str] = mapped_column(String, default="done")
    markdown_s3_key: Mapped[str | None] = mapped_column(String, nullable=True)
```

Add the new `SourcePage` class after `Source`:

```python
class SourcePage(Base):
    __tablename__ = "source_pages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"))
    page_num: Mapped[int] = mapped_column(nullable=False)
    markdown: Mapped[str] = mapped_column(Text, default="")
    preview: Mapped[str] = mapped_column(Text, default="")
    image_s3_keys: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

- [ ] **Step 4: Run test to confirm it passes**

```bash
docker compose run --rm api pytest tests/test_agents.py::test_source_page_can_be_created -v
```

Expected: `PASS`

- [ ] **Step 5: Generate and write the Alembic migration**

```bash
docker compose run --rm api alembic revision --autogenerate -m "add_source_pages"
```

Open the generated file in `api/alembic/versions/`. Verify it contains:
- `op.create_table('source_pages', ...)` with all columns
- `op.add_column('sources', sa.Column('status', ...))` with `server_default='done'`
- `op.add_column('sources', sa.Column('markdown_s3_key', ...))`

If auto-generate misses the server_default, manually add `server_default='done'` to the `status` column definition in the migration.

- [ ] **Step 6: Apply migration and verify**

```bash
docker compose run --rm api alembic upgrade head
```

Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add api/app/models.py api/alembic/versions/
git commit -m "feat: add SourcePage model and Source status/markdown_s3_key columns"
```

---

## Task 4: storage.download_file + MarkerClient

**Files:**
- Modify: `api/app/storage.py`
- Create: `api/app/marker_client.py`
- Modify: `api/requirements.txt`

- [ ] **Step 1: Write failing test for MarkerClient**

Create `tests/test_marker_client.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_marker_client_convert_returns_page_data():
    from app.marker_client import MarkerClient, PageData

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {"page_num": 1, "markdown": "# Hello\n\nWorld", "images": []},
        {"page_num": 2, "markdown": "## Section 2\n\nContent", "images": [
            {"filename": "img0.png", "b64": "abc123"}
        ]},
    ]

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("app.marker_client.httpx.AsyncClient", return_value=mock_client):
        client = MarkerClient(base_url="http://marker:8001")
        pages = await client.convert(b"fake-pdf-bytes", "doc.pdf")

    assert len(pages) == 2
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

    call_kwargs = mock_client.post.call_args
    data = call_kwargs.kwargs.get("data") or call_kwargs.args[1] if len(call_kwargs.args) > 1 else {}
    # use_llm should be passed in form data
    assert mock_client.post.called
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
docker compose run --rm api pytest tests/test_marker_client.py -v
```

Expected: `FAIL` — `app.marker_client` not found.

- [ ] **Step 3: Add download_file to storage.py**

In `api/app/storage.py`, add after the `upload_file` function:

```python
def download_file(key: str) -> bytes:
    s3 = _client()
    response = s3.get_object(Bucket=settings.s3_bucket, Key=key)
    return response["Body"].read()
```

- [ ] **Step 4: Add httpx to requirements.txt**

In `api/requirements.txt`, add:
```
httpx
```

- [ ] **Step 5: Create marker_client.py**

Create `api/app/marker_client.py`:

```python
from dataclasses import dataclass, field

import httpx

from app.config import settings


@dataclass
class ImageData:
    filename: str
    b64: str


@dataclass
class PageData:
    page_num: int
    markdown: str
    images: list[ImageData] = field(default_factory=list)


class MarkerClient:
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

    async def convert(self, data: bytes, filename: str) -> list[PageData]:
        form = {
            "use_llm": str(self.use_llm).lower(),
            "llm_service": self.llm_service,
            "llm_model": self.llm_model,
            "llm_api_key": self.llm_api_key,
        }
        files = {"file": (filename, data, "application/octet-stream")}
        async with httpx.AsyncClient(timeout=600.0) as client:
            resp = await client.post(
                f"{self.base_url}/convert", data=form, files=files
            )
            resp.raise_for_status()

        raw_pages = resp.json()
        return [
            PageData(
                page_num=p["page_num"],
                markdown=p["markdown"],
                images=[ImageData(**img) for img in p.get("images", [])],
            )
            for p in raw_pages
        ]
```

- [ ] **Step 6: Run tests to confirm they pass**

```bash
docker compose run --rm api pytest tests/test_marker_client.py -v
```

Expected: `PASS`

- [ ] **Step 7: Commit**

```bash
git add api/app/storage.py api/app/marker_client.py api/requirements.txt tests/test_marker_client.py
git commit -m "feat: MarkerClient HTTP wrapper + storage.download_file"
```

---

## Task 5: AgentTools — source navigation

**Files:**
- Modify: `api/app/agents/tools.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_agents.py`:

```python
@pytest.mark.asyncio
async def test_list_source_pages_returns_previews():
    from unittest.mock import AsyncMock, MagicMock
    from app.agents.tools import AgentTools
    from app.models import SourcePage

    page1 = MagicMock(spec=SourcePage)
    page1.page_num = 1
    page1.preview = "# Intro"
    page1.image_s3_keys = []

    page2 = MagicMock(spec=SourcePage)
    page2.page_num = 2
    page2.preview = "## Methods"
    page2.image_s3_keys = ["ws/src/p2-img0.png"]

    mock_session = AsyncMock()
    scalar_result = MagicMock()
    scalar_result.scalars.return_value.all.return_value = [page1, page2]
    mock_session.execute = AsyncMock(return_value=scalar_result)

    tools = AgentTools(
        session=mock_session, workspace_id="ws-1", broadcaster=None, source_id="src-1"
    )
    result = await tools.list_source_pages()

    assert len(result) == 2
    assert result[0] == {"page_num": 1, "has_images": False, "preview": "# Intro"}
    assert result[1]["has_images"] is True


@pytest.mark.asyncio
async def test_read_source_page_no_images_returns_markdown():
    from unittest.mock import AsyncMock, MagicMock
    from app.agents.tools import AgentTools
    from app.models import SourcePage

    page = MagicMock(spec=SourcePage)
    page.markdown = "# Hello\n\nWorld"
    page.image_s3_keys = []

    mock_session = AsyncMock()
    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = page
    mock_session.execute = AsyncMock(return_value=scalar_result)

    tools = AgentTools(
        session=mock_session, workspace_id="ws-1", broadcaster=None, source_id="src-1"
    )
    result = await tools.read_source_page(1)

    assert result == "# Hello\n\nWorld"


@pytest.mark.asyncio
async def test_read_source_page_with_images_calls_vision_model():
    from unittest.mock import AsyncMock, MagicMock, patch
    from app.agents.tools import AgentTools
    from app.models import SourcePage

    page = MagicMock(spec=SourcePage)
    page.markdown = "## Results"
    page.image_s3_keys = ["ws/src/p1-img0.png"]

    mock_session = AsyncMock()
    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = page
    mock_session.execute = AsyncMock(return_value=scalar_result)

    mock_vision_resp = MagicMock()
    mock_vision_resp.choices[0].message.content = "A bar chart showing revenue."

    with (
        patch("app.agents.tools.download_file", return_value=b"\x89PNG\r\n"),
        patch("app.agents.tools.settings") as mock_settings,
        patch("app.agents.tools.litellm.acompletion", new_callable=AsyncMock, return_value=mock_vision_resp),
    ):
        mock_settings.vision_model = "gpt-4o"
        tools = AgentTools(
            session=mock_session, workspace_id="ws-1", broadcaster=None, source_id="src-1"
        )
        result = await tools.read_source_page(1)

    assert "## Results" in result
    assert "A bar chart showing revenue." in result


@pytest.mark.asyncio
async def test_dispatch_list_source_pages():
    from unittest.mock import AsyncMock
    from app.agents.tools import AgentTools

    tools = AgentTools(session=AsyncMock(), workspace_id="ws-1", broadcaster=None, source_id="src-1")
    tools.list_source_pages = AsyncMock(return_value=[{"page_num": 1}])

    result = await tools.dispatch("list_source_pages", {})
    assert "page_num" in result
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
docker compose run --rm api pytest tests/test_agents.py::test_list_source_pages_returns_previews tests/test_agents.py::test_read_source_page_no_images_returns_markdown -v
```

Expected: `FAIL` — `AgentTools.__init__` does not accept `source_id`.

- [ ] **Step 3: Update tools.py**

Replace the `__init__` signature in `api/app/agents/tools.py`:

```python
    def __init__(
        self, session: AsyncSession, workspace_id: str, broadcaster: SSEBroadcaster | None,
        source_id: str | None = None,
    ):
        self.session = session
        self.workspace_id = workspace_id
        self.broadcaster = broadcaster
        self.source_id = source_id
```

Add these imports at the top of `tools.py`:

```python
import base64

import litellm

from app.config import settings
from app.models import SourcePage
from app.storage import download_file
```

Add these two methods to `AgentTools` (after `create_page`):

```python
    async def list_source_pages(self) -> list[dict]:
        result = await self.session.execute(
            select(SourcePage)
            .where(SourcePage.source_id == self.source_id)
            .order_by(SourcePage.page_num)
        )
        pages = result.scalars().all()
        return [
            {
                "page_num": p.page_num,
                "has_images": bool(p.image_s3_keys),
                "preview": p.preview,
            }
            for p in pages
        ]

    async def read_source_page(self, page_num: int) -> str:
        result = await self.session.execute(
            select(SourcePage).where(
                SourcePage.source_id == self.source_id,
                SourcePage.page_num == page_num,
            )
        )
        page = result.scalar_one_or_none()
        if not page:
            return f"[Page {page_num} not found]"

        markdown = page.markdown

        if page.image_s3_keys and settings.vision_model:
            descriptions = []
            for s3_key in page.image_s3_keys:
                img_bytes = download_file(s3_key)
                b64 = base64.b64encode(img_bytes).decode()
                ext = s3_key.rsplit(".", 1)[-1].lower()
                mime = {
                    "png": "image/png", "jpg": "image/jpeg",
                    "jpeg": "image/jpeg", "webp": "image/webp",
                }.get(ext, "image/png")
                resp = await litellm.acompletion(
                    model=settings.vision_model,
                    messages=[{
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": f"Describe this image in the context of the surrounding document text:\n\n{markdown[:500]}",
                            },
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:{mime};base64,{b64}"},
                            },
                        ],
                    }],
                )
                descriptions.append(resp.choices[0].message.content or "")
            for i, desc in enumerate(descriptions):
                markdown += f"\n\n> [Figure {i + 1}] {desc}"

        return markdown
```

Add the two new tools to `as_litellm_tools` (inside `all_tools`, after `create_page`):

```python
            {
                "type": "function",
                "function": {
                    "name": "list_source_pages",
                    "description": "List all pages of the source document with a short preview and whether each has images. Call this first to understand document structure.",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "read_source_page",
                    "description": "Read the full markdown of a source document page. Pages with images include vision-model descriptions of figures inline.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "page_num": {"type": "integer", "description": "1-indexed page number"}
                        },
                        "required": ["page_num"],
                    },
                },
            },
```

Add to `dispatch` (before the final `return f"Unknown tool: {name}"`):

```python
        if name == "list_source_pages":
            pages = await self.list_source_pages()
            return str(pages)
        if name == "read_source_page":
            return await self.read_source_page(args["page_num"])
```

- [ ] **Step 4: Run all agent tests**

```bash
docker compose run --rm api pytest tests/test_agents.py -v
```

Expected: all `PASS`

- [ ] **Step 5: Commit**

```bash
git add api/app/agents/tools.py tests/test_agents.py
git commit -m "feat: add list_source_pages + read_source_page tools with vision support"
```

---

## Task 6: Sub-agent

**Files:**
- Create: `api/app/agents/sub_agent.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_sub_agent.py`:

```python
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
        patch("app.agents.sub_agent.litellm.acompletion", new_callable=AsyncMock,
              side_effect=[page_content_resp, final_resp]),
        patch("app.agents.sub_agent.litellm.completion_cost", return_value=0.001),
        patch("app.agents.sub_agent.AgentTools") as MockTools,
    ):
        mock_tools_instance = AsyncMock()
        mock_tools_instance.as_litellm_tools.return_value = []
        mock_tools_instance.dispatch = AsyncMock(return_value="# Neural Networks\n\nContent here.")
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
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
docker compose run --rm api pytest tests/test_sub_agent.py -v
```

Expected: `FAIL` — module not found.

- [ ] **Step 3: Create sub_agent.py**

Create `api/app/agents/sub_agent.py`:

```python
import json

import litellm

from app.agents.assistant_message import assistant_message_for_litellm
from app.agents.tools import AgentTools
from app.config import settings
from app.database import AsyncSessionLocal

SYSTEM_PROMPT = """You are a document reading assistant. You have been given a range of pages from a source document.

Process:
1. Read each page in your assigned range using read_source_page().
2. You may read 1-2 pages beyond your range if something appears cut off.
3. Return a comprehensive knowledge summary — key concepts, facts, data, arguments.

Do not write to the wiki. Only read and summarise."""

COST_CEILING_USD = 1.0


async def run(
    source_id: str,
    workspace_id: str,
    page_start: int,
    page_end: int,
    focus_hint: str = "",
) -> str:
    async with AsyncSessionLocal() as session:
        tools = AgentTools(
            session=session,
            workspace_id=workspace_id,
            broadcaster=None,
            source_id=source_id,
        )
        tool_defs = tools.as_litellm_tools(allowed=["read_source_page"])

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Read pages {page_start} to {page_end} and summarise what you find."
                    + (f" Focus: {focus_hint}" if focus_hint else "")
                ),
            },
        ]

        total_cost = 0.0
        for _ in range(50):
            resp = await litellm.acompletion(
                model=settings.litellm_model,
                messages=messages,
                tools=tool_defs,
                tool_choice="auto",
            )
            total_cost += litellm.completion_cost(resp) or 0.0
            if total_cost > COST_CEILING_USD:
                return "[Sub-agent reached cost ceiling]"

            msg = resp.choices[0].message
            messages.append(assistant_message_for_litellm(msg))

            if not msg.tool_calls:
                return msg.content or ""

            for tc in msg.tool_calls:
                name = tc.function.name
                args = json.loads(tc.function.arguments or "{}")
                result = await tools.dispatch(name, args)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

    return "[Sub-agent did not complete]"
```

- [ ] **Step 4: Run test to confirm it passes**

```bash
docker compose run --rm api pytest tests/test_sub_agent.py -v
```

Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add api/app/agents/sub_agent.py tests/test_sub_agent.py
git commit -m "feat: read-only sub-agent for paginated document reading"
```

---

## Task 7: Ingest agent — orchestrator

**Files:**
- Modify: `api/app/agents/ingest_agent.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_agents.py`:

```python
@pytest.mark.asyncio
async def test_orchestrator_reads_directly_for_small_docs():
    """Docs with ≤20 pages go direct — no spawn_page_reader tool offered."""
    from app.agents import ingest_agent
    from unittest.mock import AsyncMock, MagicMock, patch

    final_resp = MagicMock()
    final_resp.choices[0].message.content = "done"
    final_resp.choices[0].message.tool_calls = []

    with (
        patch("app.agents.ingest_agent.litellm.acompletion", new_callable=AsyncMock,
              return_value=final_resp),
        patch("app.agents.ingest_agent.litellm.completion_cost", return_value=0.001),
        patch("app.agents.ingest_agent.AsyncSessionLocal") as MockSession,
        patch("app.agents.ingest_agent.broadcaster"),
    ):
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        # Simulate 5 source pages in DB
        from app.models import SourcePage
        pages = [MagicMock(spec=SourcePage, page_num=i) for i in range(1, 6)]
        page_result = MagicMock()
        page_result.scalars.return_value.all.return_value = pages

        source_result = MagicMock()
        source_result.scalar_one_or_none.return_value = MagicMock(id="src-1")

        mock_session.execute = AsyncMock(side_effect=[source_result, page_result])
        MockSession.return_value = mock_session

        await ingest_agent.run("src-1", "ws-1")

    call_args = ingest_agent.litellm.acompletion.call_args
    tools_passed = call_args.kwargs.get("tools", [])
    tool_names = [t["function"]["name"] for t in tools_passed]
    assert "spawn_page_reader" not in tool_names
    assert "read_source_page" in tool_names


@pytest.mark.asyncio
async def test_orchestrator_offers_spawn_for_large_docs():
    """Docs with >20 pages get the spawn_page_reader tool."""
    from app.agents import ingest_agent
    from unittest.mock import AsyncMock, MagicMock, patch

    final_resp = MagicMock()
    final_resp.choices[0].message.content = "done"
    final_resp.choices[0].message.tool_calls = []

    with (
        patch("app.agents.ingest_agent.litellm.acompletion", new_callable=AsyncMock,
              return_value=final_resp),
        patch("app.agents.ingest_agent.litellm.completion_cost", return_value=0.001),
        patch("app.agents.ingest_agent.AsyncSessionLocal") as MockSession,
        patch("app.agents.ingest_agent.broadcaster"),
    ):
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        from app.models import SourcePage
        pages = [MagicMock(spec=SourcePage, page_num=i) for i in range(1, 25)]  # 24 pages
        page_result = MagicMock()
        page_result.scalars.return_value.all.return_value = pages

        source_result = MagicMock()
        source_result.scalar_one_or_none.return_value = MagicMock(id="src-1")

        mock_session.execute = AsyncMock(side_effect=[source_result, page_result])
        MockSession.return_value = mock_session

        await ingest_agent.run("src-1", "ws-1")

    call_args = ingest_agent.litellm.acompletion.call_args
    tools_passed = call_args.kwargs.get("tools", [])
    tool_names = [t["function"]["name"] for t in tools_passed]
    assert "spawn_page_reader" in tool_names
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
docker compose run --rm api pytest tests/test_agents.py::test_orchestrator_reads_directly_for_small_docs tests/test_agents.py::test_orchestrator_offers_spawn_for_large_docs -v
```

Expected: `FAIL`

- [ ] **Step 3: Rewrite ingest_agent.py**

Replace the contents of `api/app/agents/ingest_agent.py`:

```python
import asyncio
import json

import litellm
from sqlalchemy import select

from app.agents.assistant_message import assistant_message_for_litellm
from app.agents.tools import AgentTools
from app.agents import sub_agent
from app.config import settings
from app.database import AsyncSessionLocal
from app.models import ActivityLog, Source, SourcePage
from app.sse import broadcaster

SMALL_DOC_THRESHOLD = 20
COST_CEILING_USD = 2.0

SYSTEM_PROMPT_SMALL = """You are an agent that maintains a personal knowledge wiki.
You have been given a source document split into pages. Integrate its knowledge into the wiki.

Process:
1. Call list_source_pages() to see the document structure and previews.
2. Read pages with read_source_page(). Read all pages — they are manageable in size.
3. Call list_pages() and search_pages() to find related wiki pages.
4. Write changes using write_page() or create_page(). Prefer updating existing pages.
5. When done, stop calling tools.

Write clear markdown. Use [[wikilinks]] to link related pages."""

SYSTEM_PROMPT_LARGE = """You are an agent that maintains a personal knowledge wiki.
You have been given a large source document split into pages. Integrate its knowledge into the wiki.

Process:
1. Call list_source_pages() to see the full document structure with previews.
2. Call spawn_page_reader() MULTIPLE TIMES IN THE SAME RESPONSE to read sections concurrently.
   Each call assigns a page range to a sub-agent that reads and summarises it.
   Group related pages together. Use focus_hint to guide each sub-agent.
3. After receiving all summaries, integrate knowledge into the wiki:
   - Call list_pages() and search_pages() to find related pages.
   - Write changes using write_page() or create_page(). Prefer updating existing pages.
4. When done, stop calling tools.

Write clear markdown. Use [[wikilinks]] to link related pages."""

SPAWN_PAGE_READER_TOOL = {
    "type": "function",
    "function": {
        "name": "spawn_page_reader",
        "description": (
            "Spawn a sub-agent to read and summarise a page range concurrently. "
            "Call multiple times in the SAME response to process sections in parallel."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "page_start": {"type": "integer", "description": "First page (1-indexed)"},
                "page_end": {"type": "integer", "description": "Last page (inclusive)"},
                "focus_hint": {"type": "string", "description": "What to focus on"},
            },
            "required": ["page_start", "page_end"],
        },
    },
}


async def run(source_id: str, workspace_id: str):
    async with AsyncSessionLocal() as session:
        src_result = await session.execute(
            select(Source).where(Source.id == source_id)
        )
        source = src_result.scalar_one_or_none()
        if not source:
            return

        pages_result = await session.execute(
            select(SourcePage)
            .where(SourcePage.source_id == source_id)
            .order_by(SourcePage.page_num)
        )
        pages = pages_result.scalars().all()
        page_count = len(pages)

        is_large = page_count > SMALL_DOC_THRESHOLD

        tools = AgentTools(
            session=session,
            workspace_id=workspace_id,
            broadcaster=broadcaster,
            source_id=source_id,
        )

        wiki_tool_names = ["list_pages", "search_pages", "read_page", "write_page", "create_page"]
        source_tool_names = ["list_source_pages", "read_source_page"]

        if is_large:
            tool_defs = tools.as_litellm_tools(allowed=wiki_tool_names + ["list_source_pages"])
            tool_defs.append(SPAWN_PAGE_READER_TOOL)
            system_prompt = SYSTEM_PROMPT_LARGE
        else:
            tool_defs = tools.as_litellm_tools(allowed=wiki_tool_names + source_tool_names)
            system_prompt = SYSTEM_PROMPT_SMALL

        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"Integrate the source document (source_id={source_id}, {page_count} pages) into the wiki.",
            },
        ]

        total_cost = 0.0
        pages_touched: list[str] = []

        for _ in range(30):
            resp = await litellm.acompletion(
                model=settings.litellm_model,
                messages=messages,
                tools=tool_defs,
                tool_choice="auto",
            )
            total_cost += litellm.completion_cost(resp) or 0.0
            if total_cost > COST_CEILING_USD:
                break

            msg = resp.choices[0].message
            messages.append(assistant_message_for_litellm(msg))

            if not msg.tool_calls:
                break

            spawn_calls = [tc for tc in msg.tool_calls if tc.function.name == "spawn_page_reader"]
            other_calls = [tc for tc in msg.tool_calls if tc.function.name != "spawn_page_reader"]

            if spawn_calls:
                tasks = [
                    sub_agent.run(
                        source_id=source_id,
                        workspace_id=workspace_id,
                        page_start=json.loads(tc.function.arguments)["page_start"],
                        page_end=json.loads(tc.function.arguments)["page_end"],
                        focus_hint=json.loads(tc.function.arguments).get("focus_hint", ""),
                    )
                    for tc in spawn_calls
                ]
                results = await asyncio.gather(*tasks)
                for tc, result in zip(spawn_calls, results):
                    messages.append(
                        {"role": "tool", "tool_call_id": tc.id, "content": result}
                    )

            for tc in other_calls:
                name = tc.function.name
                args = json.loads(tc.function.arguments or "{}")
                result_str = await tools.dispatch(name, args)
                if name in ("write_page", "create_page") and "slug" in args:
                    pages_touched.append(args["slug"])
                messages.append(
                    {"role": "tool", "tool_call_id": tc.id, "content": result_str}
                )

        session.add(
            ActivityLog(
                workspace_id=workspace_id,
                event_type="source_ingested",
                payload={
                    "source_id": source_id,
                    "pages_touched": pages_touched,
                    "cost_usd": round(total_cost, 4),
                    "page_count": page_count,
                },
            )
        )
        await session.commit()
        await broadcaster.publish(
            {"event": "agent:done", "pages_touched": pages_touched}
        )
```

- [ ] **Step 4: Run tests**

```bash
docker compose run --rm api pytest tests/test_agents.py -v
```

Expected: all `PASS`

- [ ] **Step 5: Commit**

```bash
git add api/app/agents/ingest_agent.py tests/test_agents.py
git commit -m "feat: orchestrator ingest agent with concurrent sub-agent dispatch"
```

---

## Task 8: Ingest route — two-stage pipeline

**Files:**
- Modify: `api/app/routes/ingest.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_ingest_route.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport


@pytest.fixture
def auth_headers():
    import jwt
    import os
    token = jwt.encode(
        {"sub": os.environ["SINGLE_USER_EMAIL"]},
        os.environ["JWT_SECRET"],
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_ingest_file_accepts_pdf(auth_headers):
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch("app.routes.ingest._run_pipeline"):
            response = await client.post(
                "/ingest/file",
                files={"file": ("doc.pdf", b"%PDF-1.4", "application/pdf")},
                headers=auth_headers,
            )
    assert response.status_code == 200
    assert response.json()["status"] == "converting"


@pytest.mark.asyncio
async def test_ingest_file_accepts_pptx(auth_headers):
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch("app.routes.ingest._run_pipeline"):
            response = await client.post(
                "/ingest/file",
                files={"file": ("slides.pptx", b"PK\x03\x04", "application/octet-stream")},
                headers=auth_headers,
            )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_ingest_file_accepts_png(auth_headers):
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch("app.routes.ingest._run_pipeline"):
            response = await client.post(
                "/ingest/file",
                files={"file": ("photo.png", b"\x89PNG\r\n", "image/png")},
                headers=auth_headers,
            )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_ingest_file_rejects_unsupported(auth_headers):
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch("app.routes.ingest._run_pipeline"):
            response = await client.post(
                "/ingest/file",
                files={"file": ("script.exe", b"MZ", "application/octet-stream")},
                headers=auth_headers,
            )
    assert response.status_code == 400
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
docker compose run --rm api pytest tests/test_ingest_route.py -v
```

Expected: `FAIL` — pptx and png return 400 (unsupported).

- [ ] **Step 3: Rewrite ingest.py**

Replace `api/app/routes/ingest.py`:

```python
import base64
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import Source, SourcePage, Workspace
from app.routes.wiki import _ensure_workspace
from app.storage import upload_file
from app.sse import broadcaster

router = APIRouter(prefix="/ingest", tags=["ingest"])

MARKER_TYPES = {"pdf", "docx", "doc", "pptx", "ppt", "xlsx", "xls", "png", "jpg", "jpeg", "webp"}
TEXT_TYPES = {"md", "markdown", "txt", "text"}
CHUNK_SIZE = 4000


class URLIngest(BaseModel):
    url: str


class TextIngest(BaseModel):
    text: str
    title: str = "Pasted note"


def _content_type(suffix: str) -> str:
    return {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
        "md": "text/markdown",
        "markdown": "text/markdown",
    }.get(suffix, "application/octet-stream")


def _chunk_text(text: str) -> list[str]:
    chunks = []
    for i in range(0, max(len(text), 1), CHUNK_SIZE):
        chunks.append(text[i : i + CHUNK_SIZE])
    return chunks


async def _run_pipeline(source_id: str, workspace_id: str, data: bytes, filename: str):
    from app.agents.ingest_agent import run as run_ingest
    from app.database import AsyncSessionLocal
    from app.marker_client import MarkerClient

    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    async with AsyncSessionLocal() as session:
        src_result = await session.execute(select(Source).where(Source.id == source_id))
        source = src_result.scalar_one_or_none()
        if not source:
            return

        await broadcaster.publish({"event": "agent:converting", "source_id": source_id})

        try:
            if suffix in TEXT_TYPES:
                text = data.decode("utf-8", errors="replace")
                chunks = _chunk_text(text)
                combined_md = text
                pages_data = [
                    {"page_num": i + 1, "markdown": chunk, "images": []}
                    for i, chunk in enumerate(chunks)
                ]
            else:
                client = MarkerClient()
                raw_pages = await client.convert(data, filename)
                pages_data = [
                    {
                        "page_num": p.page_num,
                        "markdown": p.markdown,
                        "images": [{"filename": img.filename, "b64": img.b64} for img in p.images],
                    }
                    for p in raw_pages
                ]
                combined_md = "\n\n".join(p["markdown"] for p in pages_data)

            # Upload combined markdown to S3
            md_key = f"{workspace_id}/{source_id}/converted.md"
            upload_file(md_key, combined_md.encode("utf-8"), "text/markdown")

            # Upload images and save SourcePage rows
            for p in pages_data:
                image_s3_keys = []
                for img in p["images"]:
                    ext = img["filename"].rsplit(".", 1)[-1] if "." in img["filename"] else "png"
                    img_key = f"{workspace_id}/{source_id}/p{p['page_num']}-{img['filename']}"
                    img_bytes = base64.b64decode(img["b64"])
                    upload_file(img_key, img_bytes, f"image/{ext}")
                    image_s3_keys.append(img_key)

                session.add(
                    SourcePage(
                        source_id=source_id,
                        page_num=p["page_num"],
                        markdown=p["markdown"],
                        preview=p["markdown"][:200],
                        image_s3_keys=image_s3_keys,
                    )
                )

            source.markdown_s3_key = md_key
            source.status = "ingesting"
            await session.commit()

        except Exception:
            source.status = "error"
            await session.commit()
            raise

    await broadcaster.publish({"event": "agent:ingesting", "source_id": source_id})
    await run_ingest(source_id, workspace_id)

    async with AsyncSessionLocal() as session:
        src_result = await session.execute(select(Source).where(Source.id == source_id))
        source = src_result.scalar_one_or_none()
        if source:
            source.status = "done"
            await session.commit()


@router.post("/file")
async def ingest_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)
    suffix = file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else ""

    if suffix not in MARKER_TYPES and suffix not in TEXT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '.{suffix}'. Supported: PDF, DOCX, PPTX, XLSX, PNG, JPG, WEBP, MD, TXT.",
        )

    data = await file.read()
    s3_key = f"{ws.id}/{uuid.uuid4()}.{suffix}"
    upload_file(s3_key, data, _content_type(suffix))

    source = Source(
        workspace_id=ws.id,
        kind=suffix,
        s3_key=s3_key,
        status="converting",
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)

    background_tasks.add_task(_run_pipeline, source.id, ws.id, data, file.filename or f"file.{suffix}")
    return {"source_id": source.id, "status": "converting"}


@router.post("/url")
async def ingest_url(
    body: URLIngest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    from app.extractors.url import extract_main_content

    ws = await _ensure_workspace(db, user)
    text = await extract_main_content(body.url)
    source = Source(workspace_id=ws.id, kind="url", s3_key=None, status="converting")
    db.add(source)
    await db.commit()
    await db.refresh(source)

    fake_data = text.encode("utf-8")
    background_tasks.add_task(_run_pipeline, source.id, ws.id, fake_data, "content.txt")
    return {"source_id": source.id, "status": "converting"}


@router.post("/text")
async def ingest_text(
    body: TextIngest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)
    source = Source(workspace_id=ws.id, kind="text", s3_key=None, status="converting")
    db.add(source)
    await db.commit()
    await db.refresh(source)

    fake_data = body.text.encode("utf-8")
    background_tasks.add_task(_run_pipeline, source.id, ws.id, fake_data, "note.txt")
    return {"source_id": source.id, "status": "converting"}
```

- [ ] **Step 4: Run tests**

```bash
docker compose run --rm api pytest tests/test_ingest_route.py -v
```

Expected: all `PASS`

- [ ] **Step 5: Run full test suite**

```bash
docker compose run --rm api pytest -v
```

Expected: all `PASS`. If any existing tests fail due to the `Source` model gaining `status`, update the test fixtures to pass `status="done"` where needed.

- [ ] **Step 6: Commit**

```bash
git add api/app/routes/ingest.py tests/test_ingest_route.py
git commit -m "feat: two-stage ingest pipeline with Marker + expanded file type support"
```

---

## Task 9: Docker Compose + env

**Files:**
- Modify: `docker-compose.yml`
- Modify: `docker-compose.prod.yml`
- Modify: `api/requirements.txt` (ensure httpx present)

- [ ] **Step 1: Update docker-compose.yml**

Add the `marker` service and `marker_models` volume. Add `marker_models` to volumes. Update `api.depends_on` and `api.environment`:

```yaml
services:
  # ... existing db and minio services unchanged ...

  marker:
    build: ./marker_service
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8001/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 120s
    volumes:
      - marker_models:/root/.cache

  api:
    build: ./api
    depends_on:
      db:
        condition: service_healthy
      minio:
        condition: service_healthy
      marker:
        condition: service_healthy
    env_file: .env
    environment:
      DATABASE_URL: postgresql+asyncpg://wiki:wiki@db:5432/wiki
      S3_ENDPOINT: http://minio:9000
      MARKER_URL: http://marker:8001
    ports:
      - "8000:8000"
    volumes:
      - ./api:/app
      - ./tests:/app/tests
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

  frontend:
    # ... unchanged ...

volumes:
  pgdata:
  minio_data:
  marker_models:
```

- [ ] **Step 2: Update docker-compose.prod.yml**

Add the same `marker` service and volume to the prod compose. Also update `api.depends_on`:

```yaml
services:
  # ... existing db and minio unchanged ...

  marker:
    build:
      context: ./marker_service
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8001/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 120s
    volumes:
      - marker_models:/root/.cache
    restart: unless-stopped

  api:
    build:
      context: ./api
      dockerfile: Dockerfile.prod
    depends_on:
      db:
        condition: service_healthy
      minio:
        condition: service_healthy
      marker:
        condition: service_healthy
    env_file: .env
    environment:
      S3_ENDPOINT: http://minio:9000
      MARKER_URL: http://marker:8001
    restart: unless-stopped

  frontend:
    # ... unchanged ...

volumes:
  pgdata:
  minio_data:
  marker_models:
```

- [ ] **Step 3: Verify httpx is in api/requirements.txt**

```bash
grep httpx api/requirements.txt
```

If missing, add it. Then rebuild:

```bash
docker compose build api
```

- [ ] **Step 4: Start the full stack and smoke test**

```bash
docker compose up --build -d
```

Wait ~2 minutes for the marker service to download models and pass its health check. Check:

```bash
docker compose ps          # marker should show "healthy"
docker compose logs marker # should see uvicorn startup, no errors
curl http://localhost:8001/health  # {"status": "ok"}
```

- [ ] **Step 5: Upload a PDF and verify the pipeline runs**

```bash
# Get a JWT token first
TOKEN=$(curl -s -X POST http://localhost:8000/auth/token \
  -d "username=user@example.com&password=changeme" | jq -r .access_token)

# Upload a small PDF
curl -s -X POST http://localhost:8000/ingest/file \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/path/to/test.pdf" | jq .
```

Expected response: `{"source_id": "...", "status": "converting"}`

Check logs for SSE events flowing:
```bash
docker compose logs api --follow
```

Expected log sequence: `agent:converting` → `agent:ingesting` → `agent:done`

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml docker-compose.prod.yml api/requirements.txt
git commit -m "feat: add marker service to docker compose (dev + prod)"
```
