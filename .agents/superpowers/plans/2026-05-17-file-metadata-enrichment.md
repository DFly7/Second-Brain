# File Metadata Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enrich ingested files with AI-generated titles and descriptions, collapse the Files sidebar to one row per file, add an Original/Markdown pill toggle to the viewer, and provide a metadata modal for editing.

**Architecture:** Add `title`/`description` columns to `Source`, call the LLM at the end of `_run_pipeline()` to populate them, expose via API, then update the frontend: single-row `FilesList`, view-toggle inside `FileViewer`, and a new `SourceMetaModal` triggered from `FilesView`.

**Tech Stack:** Python/FastAPI/SQLAlchemy/Alembic/litellm (backend), React 18/TypeScript/React Query (frontend). Tests use pytest with mock sessions; no Docker needed (`make test-local`).

---

## File Map

| File | Change |
|---|---|
| `api/app/models.py` | Add `title`, `description` to `Source` |
| `api/alembic/versions/b1c2d3e4f5a6_add_title_description_to_sources.py` | New migration |
| `api/app/routes/sources.py` | Add fields to `SourceOut`, add `PATCH /{id}` |
| `api/app/routes/ingest.py` | Add `_generate_metadata()`, call from `_run_pipeline()` |
| `api/tests/test_sources_routes.py` | Update mock helper, add PATCH tests |
| `api/tests/test_ingest_routes.py` | Add `_generate_metadata` unit tests |
| `frontend/src/api/client.ts` | Add `title`/`description` to `SourceItem`, add `patchSource()` |
| `frontend/src/components/FilesList.tsx` | Single-row redesign, remove `SourceSelection.view` |
| `frontend/src/components/FileViewer.tsx` | Remove `view` prop, add internal pill toggle |
| `frontend/src/components/FilesView.tsx` | Update selection state, wire `SourceMetaModal` |
| `frontend/src/components/SourceMetaModal.tsx` | New metadata edit modal |

---

## Task 1: Data model + migration

**Files:**
- Modify: `api/app/models.py`
- Create: `api/alembic/versions/b1c2d3e4f5a6_add_title_description_to_sources.py`

- [ ] **Step 1: Add fields to Source model**

In `api/app/models.py`, add two columns to `Source` after `filename`:

```python
class Source(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    kind: Mapped[str] = mapped_column(String)
    filename: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    s3_key: Mapped[str | None] = mapped_column(String, nullable=True)
    extracted_text: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String, default="done")
    markdown_s3_key: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

- [ ] **Step 2: Create migration file**

Create `api/alembic/versions/b1c2d3e4f5a6_add_title_description_to_sources.py`:

```python
"""add title and description to sources

Revision ID: b1c2d3e4f5a6
Revises: a3f9c2e8b1d7
Create Date: 2026-05-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "a3f9c2e8b1d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("title", sa.String(), nullable=True))
    op.add_column("sources", sa.Column("description", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("sources", "description")
    op.drop_column("sources", "title")
```

- [ ] **Step 3: Verify tests still pass (no migration run needed — tests mock the DB)**

```bash
cd /path/to/repo && make test-local
```

Expected: all tests PASS (new nullable columns don't affect existing tests).

- [ ] **Step 4: Commit**

```bash
git add api/app/models.py api/alembic/versions/b1c2d3e4f5a6_add_title_description_to_sources.py
git commit -m "feat(db): add title and description columns to sources"
```

---

## Task 2: API — SourceOut + PATCH endpoint

**Files:**
- Modify: `api/app/routes/sources.py`
- Modify: `api/tests/test_sources_routes.py`

- [ ] **Step 1: Write failing tests**

Add to `api/tests/test_sources_routes.py`:

```python
# ---------------------------------------------------------------------------
# PATCH /sources/{source_id}
# ---------------------------------------------------------------------------


def test_patch_source_updates_title_and_description(sources_client):
    mock_ws = _make_mock_ws()
    mock_source = _make_mock_source()

    source_result = MagicMock()
    source_result.scalar_one_or_none.return_value = mock_source

    session = MagicMock()
    session.execute = AsyncMock(return_value=source_result)
    session.commit = AsyncMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch(
            "app.routes.sources._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            r = sources_client.patch(
                f"/sources/{SOURCE_ID}",
                json={"title": "My Document", "description": "A great doc"},
            )
            assert r.status_code == 200
            data = r.json()
            assert data["title"] == "My Document"
            assert data["description"] == "A great doc"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_patch_source_updates_title_only(sources_client):
    mock_ws = _make_mock_ws()
    mock_source = _make_mock_source()
    mock_source.title = None
    mock_source.description = "existing desc"

    source_result = MagicMock()
    source_result.scalar_one_or_none.return_value = mock_source

    session = MagicMock()
    session.execute = AsyncMock(return_value=source_result)
    session.commit = AsyncMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch(
            "app.routes.sources._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            r = sources_client.patch(
                f"/sources/{SOURCE_ID}",
                json={"title": "New Title"},
            )
            assert r.status_code == 200
            data = r.json()
            assert data["title"] == "New Title"
            assert data["description"] == "existing desc"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_patch_source_returns_404_when_not_found(sources_client):
    mock_ws = _make_mock_ws()

    source_result = MagicMock()
    source_result.scalar_one_or_none.return_value = None

    session = MagicMock()
    session.execute = AsyncMock(return_value=source_result)

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch(
            "app.routes.sources._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            r = sources_client.patch(
                f"/sources/{SOURCE_ID}",
                json={"title": "Anything"},
            )
            assert r.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_list_sources_includes_title_and_description(sources_client):
    mock_ws = _make_mock_ws()
    src = _make_mock_source()
    src.title = "My PDF"
    src.description = "A great document"

    db_result = MagicMock()
    db_result.scalars.return_value.all.return_value = [src]

    session = MagicMock()
    session.execute = AsyncMock(return_value=db_result)

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch(
            "app.routes.sources._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            r = sources_client.get("/sources")
            assert r.status_code == 200
            data = r.json()
            assert data[0]["title"] == "My PDF"
            assert data[0]["description"] == "A great document"
    finally:
        app.dependency_overrides.pop(get_db, None)
```

Also update `_make_mock_source` to include the new fields:

```python
def _make_mock_source(
    *,
    source_id=SOURCE_ID,
    kind="pdf",
    filename="document.pdf",
    status="ready",
    s3_key="sources/doc.pdf",
    markdown_s3_key="sources/doc.md",
    created_at=None,
    title=None,
    description=None,
):
    s = MagicMock()
    s.id = source_id
    s.kind = kind
    s.filename = filename
    s.status = status
    s.s3_key = s3_key
    s.markdown_s3_key = markdown_s3_key
    s.created_at = created_at or datetime(2026, 5, 1, 10, 0, 0)
    s.title = title
    s.description = description
    return s
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
make test-local 2>&1 | grep -E "FAILED|ERROR|test_patch|test_list_sources_includes"
```

Expected: `test_patch_source_*` and `test_list_sources_includes_title_and_description` fail.

- [ ] **Step 3: Update SourceOut and add PATCH endpoint**

Replace `api/app/routes/sources.py` content for `SourceOut` and add the endpoint:

```python
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import Source, SourcePage
from app.routes.wiki import _ensure_workspace
from app.storage import download_file

router = APIRouter(prefix="/sources", tags=["sources"])

_CONTENT_TYPE: dict[str, str] = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "doc": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "ppt": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xls": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "md": "text/markdown",
    "markdown": "text/markdown",
    "txt": "text/plain",
    "text": "text/plain",
}


class SourceOut(BaseModel):
    id: str
    kind: str
    filename: str | None
    title: str | None
    description: str | None
    status: str
    has_file: bool
    has_markdown: bool
    created_at: datetime


class SourcePatch(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None


def _source_to_out(s: Source) -> SourceOut:
    return SourceOut(
        id=s.id,
        kind=s.kind,
        filename=s.filename,
        title=s.title,
        description=s.description,
        status=s.status,
        has_file=s.s3_key is not None,
        has_markdown=s.markdown_s3_key is not None,
        created_at=s.created_at,
    )


@router.get("", response_model=list[SourceOut])
async def list_sources(
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)
    result = await db.execute(
        select(Source)
        .where(Source.workspace_id == ws.id)
        .order_by(Source.created_at.desc())
    )
    sources = result.scalars().all()
    return [_source_to_out(s) for s in sources]


@router.patch("/{source_id}", response_model=SourceOut)
async def patch_source(
    source_id: str,
    body: SourcePatch,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)
    result = await db.execute(
        select(Source).where(Source.id == source_id, Source.workspace_id == ws.id)
    )
    source = result.scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    if body.title is not None:
        source.title = body.title
    if body.description is not None:
        source.description = body.description
    await db.commit()
    await db.refresh(source)
    return _source_to_out(source)
```

The rest of the file (`get_source_file`, `get_source_image`, `get_source_markdown`) stays unchanged — append them after the new code.

- [ ] **Step 4: Run tests to verify they pass**

```bash
make test-local 2>&1 | grep -E "PASSED|FAILED|ERROR" | grep -E "test_patch|test_list_sources_includes"
```

Expected: all 4 new tests PASS.

- [ ] **Step 5: Run full suite**

```bash
make test-local
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add api/app/routes/sources.py api/tests/test_sources_routes.py
git commit -m "feat(api): add title/description to SourceOut and PATCH /sources/{id}"
```

---

## Task 3: Pipeline — `_generate_metadata()` + integration

**Files:**
- Modify: `api/app/routes/ingest.py`
- Modify: `api/tests/test_ingest_routes.py`

- [ ] **Step 1: Write failing unit tests for `_generate_metadata`**

Add to `api/tests/test_ingest_routes.py`:

```python
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.routes.ingest import _generate_metadata


# ---------------------------------------------------------------------------
# _generate_metadata unit tests
# ---------------------------------------------------------------------------


def _make_litellm_resp(content: str):
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def test_generate_metadata_normal_path_returns_title_and_description():
    long_md = "A" * 200  # >= 100 chars triggers normal path
    resp = _make_litellm_resp('{"title": "My Doc", "description": "A great document."}')

    with patch("app.routes.ingest.litellm.acompletion", new_callable=AsyncMock, return_value=resp):
        title, desc = asyncio.get_event_loop().run_until_complete(
            _generate_metadata(kind="pdf", filename="report.pdf", combined_md=long_md, raw_data=b"")
        )

    assert title == "My Doc"
    assert desc == "A great document."


def test_generate_metadata_image_path_sends_image_content():
    """Sparse markdown + image kind → sends image_url content block."""
    short_md = "   "  # < 100 chars
    resp = _make_litellm_resp('{"title": "Beach photo", "description": "A sunny day."}')
    captured: list = []

    async def fake_acompletion(**kwargs):
        captured.append(kwargs["messages"])
        return resp

    with patch("app.routes.ingest.litellm.acompletion", side_effect=fake_acompletion):
        title, desc = asyncio.get_event_loop().run_until_complete(
            _generate_metadata(kind="png", filename="IMG_001.png", combined_md=short_md, raw_data=b"\x89PNG")
        )

    assert title == "Beach photo"
    user_content = captured[0][1]["content"]
    assert any(block.get("type") == "image_url" for block in user_content)


def test_generate_metadata_sparse_non_image_sends_text_only():
    """Sparse markdown + non-image kind → text-only content."""
    short_md = "  "
    resp = _make_litellm_resp('{"title": "PDF doc", "description": "No text extracted."}')
    captured: list = []

    async def fake_acompletion(**kwargs):
        captured.append(kwargs["messages"])
        return resp

    with patch("app.routes.ingest.litellm.acompletion", side_effect=fake_acompletion):
        title, _ = asyncio.get_event_loop().run_until_complete(
            _generate_metadata(kind="pdf", filename="scan.pdf", combined_md=short_md, raw_data=b"%PDF")
        )

    assert title == "PDF doc"
    user_content = captured[0][1]["content"]
    assert isinstance(user_content, list)
    assert all(block.get("type") == "text" for block in user_content)


def test_generate_metadata_returns_none_on_llm_exception():
    with patch(
        "app.routes.ingest.litellm.acompletion",
        new_callable=AsyncMock,
        side_effect=Exception("LLM error"),
    ):
        title, desc = asyncio.get_event_loop().run_until_complete(
            _generate_metadata(kind="pdf", filename="doc.pdf", combined_md="x" * 200, raw_data=b"")
        )

    assert title is None
    assert desc is None


def test_generate_metadata_returns_none_on_bad_json():
    resp = _make_litellm_resp("not json at all")

    with patch("app.routes.ingest.litellm.acompletion", new_callable=AsyncMock, return_value=resp):
        title, desc = asyncio.get_event_loop().run_until_complete(
            _generate_metadata(kind="pdf", filename="doc.pdf", combined_md="x" * 200, raw_data=b"")
        )

    assert title is None
    assert desc is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
make test-local 2>&1 | grep -E "FAILED|ERROR|ImportError" | grep "generate_metadata"
```

Expected: `ImportError` or `FAILED` because `_generate_metadata` doesn't exist yet.

- [ ] **Step 3: Add `_generate_metadata` to `ingest.py`**

First add three missing top-level imports to `api/app/routes/ingest.py`. Insert after `import base64`:

```python
import json
import re
```

And insert after `import structlog`:

```python
import litellm
```

And insert after `from app.auth import get_current_user`:

```python
from app.config import settings
```

Then add the following after `CHUNK_SIZE = 4000`:

```python
_IMAGE_KINDS = {"png", "jpg", "jpeg", "webp"}

_METADATA_SYSTEM_PROMPT = (
    "You are generating metadata for a file in a personal knowledge base.\n\n"
    "Given the file content, return a JSON object with exactly two fields:\n"
    '- "title": a short descriptive name (max 80 chars). If the original filename is already '
    "a clear human-readable description of the actual content, derive a clean title from it "
    "(strip extension, fix casing). Otherwise generate a better title from the content.\n"
    '- "description": one sentence summarising what this file contains (max 200 chars).\n\n'
    "Respond with only valid JSON, no markdown fences."
)


async def _generate_metadata(
    kind: str,
    filename: str | None,
    combined_md: str,
    raw_data: bytes,
) -> tuple[str | None, str | None]:
    """Call LLM to generate title and description. Returns (None, None) on any failure."""
    try:
        md_stripped = combined_md.strip()

        if len(md_stripped) >= 100:
            content: list = [
                {
                    "type": "text",
                    "text": (
                        f"Original filename: {filename or 'unknown'}\n\n"
                        f"Content preview:\n{md_stripped[:2000]}"
                    ),
                }
            ]
        elif kind in _IMAGE_KINDS:
            ext = "jpeg" if kind == "jpg" else kind
            b64 = base64.b64encode(raw_data).decode()
            content = [
                {"type": "image_url", "image_url": {"url": f"data:image/{ext};base64,{b64}"}},
                {"type": "text", "text": f"Original filename: {filename or 'unknown'}"},
            ]
        else:
            content = [
                {
                    "type": "text",
                    "text": (
                        f"File type: {kind}\n"
                        f"Original filename: {filename or 'unknown'}\n"
                        "Note: no text content was extracted from this file."
                    ),
                }
            ]

        resp = await litellm.acompletion(
            model=settings.litellm_model,
            messages=[
                {"role": "system", "content": _METADATA_SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
        )

        raw = resp.choices[0].message.content or ""
        # Strip markdown fences if the model wrapped the JSON
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
        parsed = json.loads(raw)
        title = str(parsed.get("title", "")).strip()[:80] or None
        description = str(parsed.get("description", "")).strip()[:200] or None
        return title, description

    except Exception:
        _log.exception("metadata_generation_failed", kind=kind, filename=filename)
        return None, None
```

- [ ] **Step 4: Integrate into `_run_pipeline`**

In `_run_pipeline`, initialize `combined_md` before the try block and call `_generate_metadata` in the final session block. The diff to apply:

Before the `try:` inside the first `async with AsyncSessionLocal()` block, add:

```python
        combined_md = ""
```

Then update the final block (currently lines 206-212) to call `_generate_metadata`:

```python
    async with AsyncSessionLocal() as session:
        src_result = await session.execute(select(Source).where(Source.id == source_id))
        source = src_result.scalar_one_or_none()
        if source:
            title, description = await _generate_metadata(
                kind=source.kind,
                filename=source.filename,
                combined_md=combined_md,
                raw_data=data,
            )
            source.title = title
            source.description = description
            source.status = "done"
            await session.commit()
    _log.info("ingest_pipeline_complete", source_id=source_id)
```

- [ ] **Step 5: Run the new tests**

```bash
make test-local 2>&1 | grep -E "PASSED|FAILED|ERROR" | grep "generate_metadata"
```

Expected: all 5 `test_generate_metadata_*` tests PASS.

- [ ] **Step 6: Run full suite**

```bash
make test-local
```

Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add api/app/routes/ingest.py api/tests/test_ingest_routes.py
git commit -m "feat(ingest): generate AI title and description at end of pipeline"
```

---

## Task 4: Frontend — extend SourceItem type + add patchSource()

**Files:**
- Modify: `frontend/src/api/client.ts`

- [ ] **Step 1: Update `SourceItem` interface and add `patchSource`**

In `frontend/src/api/client.ts`, replace the `SourceItem` interface and add the new function:

```typescript
export interface SourceItem {
  id: string
  kind: string
  filename: string | null
  title: string | null
  description: string | null
  status: string
  has_file: boolean
  has_markdown: boolean
  created_at: string
}
```

After `fetchSourceImage`, add:

```typescript
export async function patchSource(
  sourceId: string,
  patch: { title?: string; description?: string },
): Promise<SourceItem> {
  const r = await fetchWithAuth(`${BASE}/sources/${sourceId}`, {
    method: 'PATCH',
    headers: jsonHeaders(),
    body: JSON.stringify(patch),
  })
  if (!r.ok) throw new Error(`patchSource failed: ${r.status}`)
  return r.json()
}
```

- [ ] **Step 2: Check TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors (or only pre-existing errors unrelated to these changes).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/client.ts
git commit -m "feat(frontend): add title/description to SourceItem, add patchSource()"
```

---

## Task 5: Frontend — FilesList single-row redesign

**Files:**
- Modify: `frontend/src/components/FilesList.tsx`

- [ ] **Step 1: Rewrite FilesList**

Replace the entire contents of `frontend/src/components/FilesList.tsx`:

```typescript
import type React from 'react'
import type { SourceItem } from '../api/client'

interface FilesListProps {
  sources: SourceItem[]
  selectedId: string | null
  onSelect: (id: string) => void
  onInfo: (id: string) => void
}

const STATUS_COLOR: Record<string, string> = {
  done: '#3fb950',
  error: '#f85149',
  converting: '#d29922',
  ingesting: '#58a6ff',
  processing: '#58a6ff',
}

const KIND_COLOR: Record<string, string> = {
  pdf: '#d2a8ff',
  png: '#79c0ff',
  jpg: '#79c0ff',
  jpeg: '#79c0ff',
  webp: '#79c0ff',
  docx: '#56d364',
  doc: '#56d364',
  url: '#e3b341',
  text: '#8b949e',
  md: '#8b949e',
  markdown: '#8b949e',
  voice: '#56d364',
}

function fileIcon(kind: string): string {
  if (kind === 'pdf') return '📄'
  if (['png', 'jpg', 'jpeg', 'webp'].includes(kind)) return '🖼️'
  if (['docx', 'doc'].includes(kind)) return '📝'
  if (['pptx', 'ppt', 'xlsx', 'xls'].includes(kind)) return '📊'
  if (kind === 'url') return '🔗'
  if (kind === 'voice') return '🎙️'
  return '📄'
}

export default function FilesList({ sources, selectedId, onSelect, onInfo }: FilesListProps) {
  if (sources.length === 0) {
    return (
      <div style={{ width: 240, borderRight: '1px solid #21262d', padding: 16, color: '#8b949e', fontSize: 13 }}>
        No files ingested yet.
      </div>
    )
  }

  return (
    <div style={{ width: 240, borderRight: '1px solid #21262d', overflowY: 'auto', padding: 8, flexShrink: 0 }}>
      {sources.map((source) => {
        const title = source.title ?? `${source.kind} · ${source.id.slice(0, 8).toUpperCase()}`
        const isSelected = source.id === selectedId
        const dotColor = STATUS_COLOR[source.status] ?? '#8b949e'
        const badgeColor = KIND_COLOR[source.kind] ?? '#8b949e'

        return (
          <div
            key={source.id}
            role="button"
            tabIndex={0}
            onClick={() => onSelect(source.id)}
            onKeyDown={(e) => e.key === 'Enter' && onSelect(source.id)}
            style={{
              padding: '6px 8px',
              borderRadius: 4,
              cursor: 'pointer',
              marginBottom: 2,
              background: isSelected ? '#1f3a5f' : 'transparent',
              border: `1px solid ${isSelected ? '#58a6ff33' : 'transparent'}`,
              position: 'relative',
            }}
            className="file-row"
          >
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: 6 }}>
              <span style={{ flexShrink: 0, marginTop: 1 }}>{fileIcon(source.kind)}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{
                  fontSize: 12,
                  color: isSelected ? '#58a6ff' : '#e6edf3',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}>
                  {title}
                </div>
                {source.description && (
                  <div style={{
                    fontSize: 10,
                    color: '#6e7681',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    marginTop: 2,
                  }}>
                    {source.description}
                  </div>
                )}
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexShrink: 0 }}>
                <span style={{
                  fontSize: 9,
                  padding: '1px 5px',
                  borderRadius: 3,
                  fontWeight: 700,
                  textTransform: 'uppercase',
                  letterSpacing: '0.05em',
                  background: '#21262d',
                  color: badgeColor,
                }}>
                  {source.kind}
                </span>
                <span
                  style={{ width: 6, height: 6, borderRadius: '50%', background: dotColor, flexShrink: 0 }}
                  title={source.status}
                />
              </div>
            </div>
            <button
              type="button"
              className="info-btn"
              onClick={(e) => { e.stopPropagation(); onInfo(source.id) }}
              style={{
                position: 'absolute',
                top: 4,
                right: 28,
                background: 'none',
                border: 'none',
                color: '#6e7681',
                cursor: 'pointer',
                fontSize: 11,
                padding: '0 2px',
                opacity: 0,
                transition: 'opacity 0.1s',
              }}
              aria-label="File info"
            >
              ⓘ
            </button>
          </div>
        )
      })}
      <style>{`
        .file-row:hover .info-btn { opacity: 1 !important; }
      `}</style>
    </div>
  )
}
```

- [ ] **Step 2: Check TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```

Expected: errors only from `FilesView.tsx` (which still passes old `SourceSelection` props) — that's expected and will be fixed in Task 7.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/FilesList.tsx
git commit -m "feat(frontend): redesign FilesList to single-row with title/description/badge"
```

---

## Task 6: Frontend — FileViewer pill toggle

**Files:**
- Modify: `frontend/src/components/FileViewer.tsx`

- [ ] **Step 1: Add pill toggle and remove `view` prop**

Replace the top of `FileViewer.tsx` — from the first line through the closing brace of `export default function FileViewer` — keeping `AuthedImg`, `MarkdownPane`, and `OriginalPane` functions unchanged below it:

```typescript
import { useState, useEffect } from 'react'
import type React from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'
import 'github-markdown-css/github-markdown-dark.css'
import { fetchSourceFile, fetchSourceImage } from '../api/client'
import { useSourceMarkdown } from '../hooks/useSources'
import type { SourceItem } from '../hooks/useSources'

const IMAGE_KINDS = ['png', 'jpg', 'jpeg', 'webp']
const NO_FILE_KINDS = ['url', 'text', 'md', 'markdown', 'txt']

interface FileViewerProps {
  source: SourceItem | null
}

export default function FileViewer({ source }: FileViewerProps) {
  const defaultView = (s: SourceItem | null) =>
    s?.has_markdown ? 'markdown' : 'original'

  const [view, setView] = useState<'original' | 'markdown'>(() => defaultView(source))

  useEffect(() => {
    setView(defaultView(source))
  }, [source?.id])

  if (!source) {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#8b949e', fontSize: 13 }}>
        Select a file to view it.
      </div>
    )
  }

  const showToggle = source.has_file && source.has_markdown

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '8px 14px',
        borderBottom: '1px solid #21262d',
        flexShrink: 0,
      }}>
        <span style={{ flex: 1, fontSize: 13, fontWeight: 600, color: '#e6edf3', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {source.title ?? `${source.kind} · ${source.id.slice(0, 8).toUpperCase()}`}
        </span>
        {showToggle && (
          <div style={{ display: 'flex', background: '#21262d', borderRadius: 6, padding: 2, gap: 2 }}>
            {(['original', 'markdown'] as const).map((v) => (
              <button
                key={v}
                type="button"
                onClick={() => setView(v)}
                style={{
                  padding: '3px 10px',
                  borderRadius: 4,
                  border: 'none',
                  cursor: 'pointer',
                  fontSize: 11,
                  fontWeight: 600,
                  background: view === v ? '#0d1117' : 'transparent',
                  color: view === v ? '#e6edf3' : '#6e7681',
                  boxShadow: view === v ? '0 1px 3px rgba(0,0,0,0.4)' : 'none',
                }}
              >
                {v === 'original' ? 'Original' : 'Markdown'}
              </button>
            ))}
          </div>
        )}
      </div>
      <div style={{ flex: 1, overflow: 'auto' }}>
        {view === 'markdown' ? <MarkdownPane source={source} /> : <OriginalPane source={source} />}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Check TypeScript compiles (errors expected only in FilesView)**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```

Expected: errors in `FilesView.tsx` only (passing old `view` prop) — fixed in Task 7.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/FileViewer.tsx
git commit -m "feat(frontend): add Original/Markdown pill toggle to FileViewer"
```

---

## Task 7: Frontend — FilesView wiring

**Files:**
- Modify: `frontend/src/components/FilesView.tsx`

- [ ] **Step 1: Update FilesView to new selection model**

Replace `frontend/src/components/FilesView.tsx`:

```typescript
import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import TopBar from './TopBar'
import FilesList from './FilesList'
import FileViewer from './FileViewer'
import SourceMetaModal from './SourceMetaModal'
import { useSources } from '../hooks/useSources'
import { useSse } from '../hooks/useSse'

export default function FilesView() {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [infoId, setInfoId] = useState<string | null>(null)
  const { data: sources } = useSources()
  const qc = useQueryClient()

  useSse((data: unknown) => {
    const event = data as { event?: string; context?: string }
    if (event.context === 'chat') return
    if (event.event === 'agent:done') {
      qc.invalidateQueries({ queryKey: ['sources'] })
    }
  })

  const selectedSource = sources?.find((s) => s.id === selectedId) ?? null
  const infoSource = sources?.find((s) => s.id === infoId) ?? null

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
      <TopBar />
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <FilesList
          sources={sources ?? []}
          selectedId={selectedId}
          onSelect={setSelectedId}
          onInfo={setInfoId}
        />
        <FileViewer source={selectedSource} />
      </div>
      {infoSource && (
        <SourceMetaModal
          source={infoSource}
          onClose={() => setInfoId(null)}
        />
      )}
    </div>
  )
}
```

- [ ] **Step 2: Check TypeScript compiles clean**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```

Expected: no errors (except possibly missing `SourceMetaModal` — that's fixed in Task 8).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/FilesView.tsx
git commit -m "feat(frontend): update FilesView to new selection model and wire SourceMetaModal"
```

---

## Task 8: Frontend — SourceMetaModal

**Files:**
- Create: `frontend/src/components/SourceMetaModal.tsx`

- [ ] **Step 1: Create the modal component**

Create `frontend/src/components/SourceMetaModal.tsx`:

```typescript
import { useState, useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import type { SourceItem } from '../api/client'
import { patchSource } from '../api/client'

interface SourceMetaModalProps {
  source: SourceItem
  onClose: () => void
}

export default function SourceMetaModal({ source, onClose }: SourceMetaModalProps) {
  const [title, setTitle] = useState(source.title ?? '')
  const [description, setDescription] = useState(source.description ?? '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const qc = useQueryClient()

  useEffect(() => {
    setTitle(source.title ?? '')
    setDescription(source.description ?? '')
    setError(null)
  }, [source.id])

  async function handleSave() {
    setSaving(true)
    setError(null)
    try {
      await patchSource(source.id, { title: title || undefined, description: description || undefined })
      qc.invalidateQueries({ queryKey: ['sources'] })
      onClose()
    } catch {
      setError('Failed to save. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100,
      }}
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div style={{
        background: '#161b22', border: '1px solid #30363d', borderRadius: 12,
        padding: 0, width: 460, maxWidth: '92vw',
        maxHeight: '90vh', display: 'flex', flexDirection: 'column', overflow: 'hidden',
      }}>
        <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: 24 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
            <h3 style={{ color: '#e6edf3', margin: 0, fontSize: 15 }}>File info</h3>
            <button type="button" onClick={onClose} style={{ background: 'none', border: 'none', color: '#8b949e', cursor: 'pointer', fontSize: 18 }}>✕</button>
          </div>

          {/* Editable fields */}
          <div style={{ marginBottom: 14 }}>
            <label style={{ display: 'block', fontSize: 11, color: '#8b949e', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Title
            </label>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="File title"
              style={{
                width: '100%', boxSizing: 'border-box',
                background: '#0d1117', border: '1px solid #30363d', borderRadius: 6,
                color: '#e6edf3', fontSize: 13, padding: '7px 10px', outline: 'none',
              }}
            />
          </div>

          <div style={{ marginBottom: 20 }}>
            <label style={{ display: 'block', fontSize: 11, color: '#8b949e', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Description
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="One sentence summary"
              rows={3}
              style={{
                width: '100%', boxSizing: 'border-box',
                background: '#0d1117', border: '1px solid #30363d', borderRadius: 6,
                color: '#e6edf3', fontSize: 13, padding: '7px 10px', outline: 'none',
                resize: 'vertical', fontFamily: 'inherit',
              }}
            />
          </div>

          {/* Read-only metadata */}
          <div style={{ borderTop: '1px solid #21262d', paddingTop: 14, display: 'flex', flexDirection: 'column', gap: 8 }}>
            {source.filename && (
              <MetaRow label="Original filename" value={source.filename} />
            )}
            <MetaRow label="Type" value={source.kind.toUpperCase()} />
            <MetaRow label="Status" value={source.status} />
            <MetaRow label="Ingested" value={new Date(source.created_at).toLocaleString()} />
          </div>

          {error && (
            <div style={{ marginTop: 12, color: '#f85149', fontSize: 12 }}>{error}</div>
          )}
        </div>

        <div style={{ padding: '12px 24px', borderTop: '1px solid #21262d', display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button type="button" onClick={onClose} style={{
            padding: '6px 14px', background: '#21262d', border: '1px solid #30363d',
            borderRadius: 6, color: '#e6edf3', cursor: 'pointer', fontSize: 13,
          }}>
            Cancel
          </button>
          <button type="button" onClick={handleSave} disabled={saving} style={{
            padding: '6px 14px', background: saving ? '#1a3a1a' : '#238636', border: '1px solid #2ea043',
            borderRadius: 6, color: '#e6edf3', cursor: saving ? 'not-allowed' : 'pointer', fontSize: 13,
          }}>
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}

function MetaRow({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: 'flex', gap: 8, fontSize: 12 }}>
      <span style={{ color: '#6e7681', minWidth: 120, flexShrink: 0 }}>{label}</span>
      <span style={{ color: '#8b949e', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{value}</span>
    </div>
  )
}
```

- [ ] **Step 2: Check TypeScript compiles clean**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/SourceMetaModal.tsx
git commit -m "feat(frontend): add SourceMetaModal for editing file title and description"
```

---

## Verification

- [ ] **Run full backend test suite**

```bash
make test-local
```

Expected: all tests PASS.

- [ ] **Run lint**

```bash
make lint
```

Expected: no errors.

- [ ] **Manual smoke test**

Start the dev stack (`docker compose up --build`), ingest a PNG image and a PDF, verify:
1. Files list shows AI-generated titles and descriptions after ingestion completes
2. Clicking a file opens the viewer with the pill toggle (PDF has both Original and Markdown; image has toggle; plain text note has no toggle)
3. Toggling between Original and Markdown works
4. Hovering a row in the sidebar reveals the ⓘ icon
5. Clicking ⓘ opens the metadata modal pre-filled with AI title/description
6. Editing and saving updates the sidebar label immediately
