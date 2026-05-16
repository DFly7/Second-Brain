# Files Section Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Files tab to the app where users can browse all ingested sources, view original files inline, and read the converted markdown with a rendered/raw toggle.

**Architecture:** React Router v6 introduces `/wiki` and `/files` routes; a shared `TopBar` component links between them. Three new FastAPI endpoints (`GET /sources`, `GET /sources/{id}/file`, `GET /sources/{id}/markdown`) proxy source data from MinIO through the auth layer. The `Source` model gains a `filename` column populated at ingest time.

**Tech Stack:** FastAPI + SQLAlchemy (backend), React 18 + Vite + react-router-dom v6 + React Query v5 + ReactMarkdown (frontend), MinIO via boto3 (storage), pytest-asyncio + httpx (tests)

---

## File Map

**Backend — created:**
- `api/app/routes/sources.py` — three new endpoints
- `api/alembic/versions/<hash>_add_filename_to_sources.py` — auto-generated migration
- `tests/test_sources.py` — all backend tests for this feature

**Backend — modified:**
- `api/app/models.py` — add `filename` column to `Source`
- `api/app/routes/ingest.py` — populate `filename` in all three ingest handlers
- `api/app/main.py` — register sources router

**Frontend — created:**
- `frontend/src/components/TopBar.tsx`
- `frontend/src/components/FilesView.tsx`
- `frontend/src/components/FilesList.tsx`
- `frontend/src/components/FileViewer.tsx`
- `frontend/src/hooks/useSse.ts`
- `frontend/src/hooks/useSources.ts`

**Frontend — modified:**
- `frontend/src/App.tsx` — add BrowserRouter + Routes
- `frontend/src/components/Layout.tsx` — use TopBar + useSse
- `frontend/src/api/client.ts` — add listSources, fetchSourceFile, fetchSourceMarkdown

---

## Task 1: Add `filename` to Source model

**Files:**
- Modify: `api/app/models.py`
- Create: migration via `alembic revision --autogenerate`

- [ ] **Step 1: Add the column to the model**

In `api/app/models.py`, add `filename` to the `Source` class after the `kind` line:

```python
class Source(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    kind: Mapped[str] = mapped_column(String)
    filename: Mapped[str | None] = mapped_column(String, nullable=True)   # ADD THIS LINE
    s3_key: Mapped[str | None] = mapped_column(String, nullable=True)
    extracted_text: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String, default="done")
    markdown_s3_key: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

- [ ] **Step 2: Generate the migration**

```bash
docker compose run --rm api alembic revision --autogenerate -m "add filename to sources"
```

Expected: a new file in `api/alembic/versions/` named something like `<hash>_add_filename_to_sources.py`.

Open it and confirm it contains:

```python
op.add_column('sources', sa.Column('filename', sa.String(), nullable=True))
```

- [ ] **Step 3: Run the migration**

```bash
docker compose run --rm api alembic upgrade head
```

Expected output ends with: `Running upgrade ... -> <hash>, add filename to sources`

- [ ] **Step 4: Verify the column exists**

```bash
docker compose exec db psql -U wiki -c "\d sources"
```

Expected: `filename` appears in the column list with type `character varying` and `nullable`.

- [ ] **Step 5: Commit**

```bash
git add api/app/models.py api/alembic/versions/
git commit -m "feat(sources): add filename column to Source model"
```

---

## Task 2: Populate `filename` in ingest routes

**Files:**
- Modify: `api/app/routes/ingest.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_sources.py` (create new file):

```python
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch

from jwt_test_helpers import make_access_token, mock_jwks


@pytest.mark.asyncio
async def test_ingest_file_stores_filename():
    from app.main import app
    from app.database import AsyncSessionLocal
    from app.models import Source
    from sqlalchemy import select

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with mock_jwks():
            token = make_access_token(sub="fileuser@test.example")
            with patch("app.routes.ingest._run_pipeline"):
                r = await client.post(
                    "/ingest/file",
                    files={"file": ("my-report.pdf", b"%PDF-1.4", "application/pdf")},
                    cookies={"access_token": token},
                )
    assert r.status_code == 200
    source_id = r.json()["source_id"]

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Source).where(Source.id == source_id))
        source = result.scalar_one()
    assert source.filename == "my-report.pdf"
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
docker compose run --rm api pytest tests/test_sources.py::test_ingest_file_stores_filename -v
```

Expected: FAIL — `assert None == "my-report.pdf"`

- [ ] **Step 3: Update the file ingest handler**

In `api/app/routes/ingest.py`, in the `ingest_file` function, add `filename=file.filename` to the `Source(...)` constructor:

```python
source = Source(
    workspace_id=ws.id,
    kind=suffix,
    s3_key=s3_key,
    status="converting",
    filename=file.filename,   # ADD THIS
)
```

- [ ] **Step 4: Update the URL ingest handler**

In the `ingest_url` function, add `filename=body.url`:

```python
source = Source(workspace_id=ws.id, kind="url", s3_key=None, status="converting", filename=body.url)
```

- [ ] **Step 5: Update the text ingest handler**

In the `ingest_text` function, add `filename=body.title`:

```python
source = Source(workspace_id=ws.id, kind="text", s3_key=None, status="converting", filename=body.title)
```

- [ ] **Step 6: Run the test to confirm it passes**

```bash
docker compose run --rm api pytest tests/test_sources.py::test_ingest_file_stores_filename -v
```

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add api/app/routes/ingest.py tests/test_sources.py
git commit -m "feat(ingest): store original filename on Source"
```

---

## Task 3: `GET /sources` endpoint

**Files:**
- Create: `api/app/routes/sources.py`
- Modify: `api/app/main.py`
- Modify: `tests/test_sources.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_sources.py`:

```python
@pytest.mark.asyncio
async def test_list_sources_empty():
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with mock_jwks():
            token = make_access_token(sub="listuser@test.example")
            r = await client.get("/sources", cookies={"access_token": token})
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_list_sources_returns_own_newest_first():
    from app.main import app
    from app.database import AsyncSessionLocal
    from app.models import Source, Workspace
    from app.routes.wiki import _workspace_id
    import asyncio

    user = "listorder@test.example"
    ws_id = _workspace_id(user)

    async with AsyncSessionLocal() as session:
        session.add(Workspace(id=ws_id, user_id=user))
        session.add(Source(workspace_id=ws_id, kind="pdf", filename="old.pdf", status="done"))
        await session.flush()
        await asyncio.sleep(0.01)  # ensure distinct created_at
        session.add(Source(workspace_id=ws_id, kind="md", filename="new.md", status="done"))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with mock_jwks():
            token = make_access_token(sub=user)
            r = await client.get("/sources", cookies={"access_token": token})

    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    assert data[0]["filename"] == "new.md"
    assert data[1]["filename"] == "old.pdf"


@pytest.mark.asyncio
async def test_list_sources_workspace_isolation():
    from app.main import app
    from app.database import AsyncSessionLocal
    from app.models import Source, Workspace
    from app.routes.wiki import _workspace_id

    user_a = "usera@test.example"
    ws_a = _workspace_id(user_a)

    async with AsyncSessionLocal() as session:
        session.add(Workspace(id=ws_a, user_id=user_a))
        session.add(Source(workspace_id=ws_a, kind="pdf", filename="secret.pdf", status="done"))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with mock_jwks():
            # user_b has never ingested anything
            token_b = make_access_token(sub="userb@test.example")
            r = await client.get("/sources", cookies={"access_token": token_b})

    assert r.status_code == 200
    assert r.json() == []
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
docker compose run --rm api pytest tests/test_sources.py::test_list_sources_empty tests/test_sources.py::test_list_sources_returns_own_newest_first tests/test_sources.py::test_list_sources_workspace_isolation -v
```

Expected: FAIL — `404 Not Found` (route doesn't exist yet)

- [ ] **Step 3: Create the sources route file**

Create `api/app/routes/sources.py`:

```python
from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import Source
from app.routes.wiki import _ensure_workspace
from app.storage import download_file

router = APIRouter(prefix="/sources", tags=["sources"])

_log = structlog.get_logger()

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
    status: str
    has_file: bool
    has_markdown: bool
    created_at: datetime


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
    return [
        SourceOut(
            id=s.id,
            kind=s.kind,
            filename=s.filename,
            status=s.status,
            has_file=s.s3_key is not None,
            has_markdown=s.markdown_s3_key is not None,
            created_at=s.created_at,
        )
        for s in sources
    ]
```

- [ ] **Step 4: Register the router in main.py**

In `api/app/main.py`, add after the other router imports:

```python
from app.routes.sources import router as sources_router  # noqa: E402
```

And after the other `app.include_router(...)` calls:

```python
app.include_router(sources_router)
```

- [ ] **Step 5: Run tests to confirm they pass**

```bash
docker compose run --rm api pytest tests/test_sources.py::test_list_sources_empty tests/test_sources.py::test_list_sources_returns_own_newest_first tests/test_sources.py::test_list_sources_workspace_isolation -v
```

Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add api/app/routes/sources.py api/app/main.py tests/test_sources.py
git commit -m "feat(sources): add GET /sources list endpoint"
```

---

## Task 4: `GET /sources/{id}/file` endpoint

**Files:**
- Modify: `api/app/routes/sources.py`
- Modify: `tests/test_sources.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_sources.py`:

```python
@pytest.mark.asyncio
async def test_get_source_file_returns_bytes():
    from app.main import app
    from app.database import AsyncSessionLocal
    from app.models import Source, Workspace
    from app.routes.wiki import _workspace_id

    user = "filedownload@test.example"
    ws_id = _workspace_id(user)
    file_data = b"%PDF-1.4 fake content"

    async with AsyncSessionLocal() as session:
        session.add(Workspace(id=ws_id, user_id=user))
        source = Source(
            workspace_id=ws_id,
            kind="pdf",
            filename="report.pdf",
            s3_key=f"{ws_id}/report.pdf",
            status="done",
        )
        session.add(source)
        await session.commit()
        source_id = source.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with mock_jwks():
            token = make_access_token(sub=user)
            with patch("app.routes.sources.download_file", return_value=file_data):
                r = await client.get(f"/sources/{source_id}/file", cookies={"access_token": token})

    assert r.status_code == 200
    assert r.content == file_data
    assert r.headers["content-type"] == "application/pdf"


@pytest.mark.asyncio
async def test_get_source_file_404_no_s3_key():
    from app.main import app
    from app.database import AsyncSessionLocal
    from app.models import Source, Workspace
    from app.routes.wiki import _workspace_id

    user = "fileno@test.example"
    ws_id = _workspace_id(user)

    async with AsyncSessionLocal() as session:
        session.add(Workspace(id=ws_id, user_id=user))
        source = Source(workspace_id=ws_id, kind="url", filename="https://example.com", s3_key=None, status="done")
        session.add(source)
        await session.commit()
        source_id = source.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with mock_jwks():
            token = make_access_token(sub=user)
            r = await client.get(f"/sources/{source_id}/file", cookies={"access_token": token})

    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_source_file_404_wrong_workspace():
    from app.main import app
    from app.database import AsyncSessionLocal
    from app.models import Source, Workspace
    from app.routes.wiki import _workspace_id

    owner = "fileowner@test.example"
    ws_id = _workspace_id(owner)

    async with AsyncSessionLocal() as session:
        session.add(Workspace(id=ws_id, user_id=owner))
        source = Source(workspace_id=ws_id, kind="pdf", filename="private.pdf", s3_key=f"{ws_id}/f.pdf", status="done")
        session.add(source)
        await session.commit()
        source_id = source.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with mock_jwks():
            token = make_access_token(sub="intruder@test.example")
            r = await client.get(f"/sources/{source_id}/file", cookies={"access_token": token})

    assert r.status_code == 404
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
docker compose run --rm api pytest tests/test_sources.py::test_get_source_file_returns_bytes tests/test_sources.py::test_get_source_file_404_no_s3_key tests/test_sources.py::test_get_source_file_404_wrong_workspace -v
```

Expected: FAIL — `404 Not Found` (endpoint doesn't exist)

- [ ] **Step 3: Add the endpoint to sources.py**

Append to `api/app/routes/sources.py`:

```python
@router.get("/{source_id}/file")
async def get_source_file(
    source_id: str,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)
    result = await db.execute(
        select(Source).where(Source.id == source_id, Source.workspace_id == ws.id)
    )
    source = result.scalar_one_or_none()
    if source is None or source.s3_key is None:
        raise HTTPException(status_code=404, detail="File not found")
    data = download_file(source.s3_key)
    content_type = _CONTENT_TYPE.get(source.kind, "application/octet-stream")
    return Response(content=data, media_type=content_type)
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
docker compose run --rm api pytest tests/test_sources.py::test_get_source_file_returns_bytes tests/test_sources.py::test_get_source_file_404_no_s3_key tests/test_sources.py::test_get_source_file_404_wrong_workspace -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add api/app/routes/sources.py tests/test_sources.py
git commit -m "feat(sources): add GET /sources/{id}/file endpoint"
```

---

## Task 5: `GET /sources/{id}/markdown` endpoint

**Files:**
- Modify: `api/app/routes/sources.py`
- Modify: `tests/test_sources.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_sources.py`:

```python
@pytest.mark.asyncio
async def test_get_source_markdown_returns_text():
    from app.main import app
    from app.database import AsyncSessionLocal
    from app.models import Source, Workspace
    from app.routes.wiki import _workspace_id

    user = "mddownload@test.example"
    ws_id = _workspace_id(user)
    md_content = b"# Hello\n\nThis is the markdown."

    async with AsyncSessionLocal() as session:
        session.add(Workspace(id=ws_id, user_id=user))
        source = Source(
            workspace_id=ws_id,
            kind="pdf",
            filename="report.pdf",
            s3_key=f"{ws_id}/report.pdf",
            markdown_s3_key=f"{ws_id}/converted.md",
            status="done",
        )
        session.add(source)
        await session.commit()
        source_id = source.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with mock_jwks():
            token = make_access_token(sub=user)
            with patch("app.routes.sources.download_file", return_value=md_content):
                r = await client.get(f"/sources/{source_id}/markdown", cookies={"access_token": token})

    assert r.status_code == 200
    assert b"# Hello" in r.content
    assert "text/markdown" in r.headers["content-type"]


@pytest.mark.asyncio
async def test_get_source_markdown_404_no_key():
    from app.main import app
    from app.database import AsyncSessionLocal
    from app.models import Source, Workspace
    from app.routes.wiki import _workspace_id

    user = "mdnone@test.example"
    ws_id = _workspace_id(user)

    async with AsyncSessionLocal() as session:
        session.add(Workspace(id=ws_id, user_id=user))
        source = Source(workspace_id=ws_id, kind="pdf", filename="r.pdf", s3_key=f"{ws_id}/r.pdf", status="converting")
        session.add(source)
        await session.commit()
        source_id = source.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with mock_jwks():
            token = make_access_token(sub=user)
            r = await client.get(f"/sources/{source_id}/markdown", cookies={"access_token": token})

    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_source_markdown_404_wrong_workspace():
    from app.main import app
    from app.database import AsyncSessionLocal
    from app.models import Source, Workspace
    from app.routes.wiki import _workspace_id

    owner = "mdowner@test.example"
    ws_id = _workspace_id(owner)

    async with AsyncSessionLocal() as session:
        session.add(Workspace(id=ws_id, user_id=owner))
        source = Source(
            workspace_id=ws_id,
            kind="pdf",
            filename="private.pdf",
            s3_key=f"{ws_id}/p.pdf",
            markdown_s3_key=f"{ws_id}/p.md",
            status="done",
        )
        session.add(source)
        await session.commit()
        source_id = source.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with mock_jwks():
            token = make_access_token(sub="intruder2@test.example")
            r = await client.get(f"/sources/{source_id}/markdown", cookies={"access_token": token})

    assert r.status_code == 404
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
docker compose run --rm api pytest tests/test_sources.py::test_get_source_markdown_returns_text tests/test_sources.py::test_get_source_markdown_404_no_key tests/test_sources.py::test_get_source_markdown_404_wrong_workspace -v
```

Expected: FAIL — `404 Not Found` (endpoint doesn't exist)

- [ ] **Step 3: Add the endpoint to sources.py**

Append to `api/app/routes/sources.py`:

```python
@router.get("/{source_id}/markdown")
async def get_source_markdown(
    source_id: str,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)
    result = await db.execute(
        select(Source).where(Source.id == source_id, Source.workspace_id == ws.id)
    )
    source = result.scalar_one_or_none()
    if source is None or source.markdown_s3_key is None:
        raise HTTPException(status_code=404, detail="Markdown not found")
    data = download_file(source.markdown_s3_key)
    return Response(content=data, media_type="text/markdown")
```

- [ ] **Step 4: Run all source tests**

```bash
docker compose run --rm api pytest tests/test_sources.py -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add api/app/routes/sources.py tests/test_sources.py
git commit -m "feat(sources): add GET /sources/{id}/markdown endpoint"
```

---

## Task 6: Install react-router-dom and wire routing in App.tsx

**Files:**
- Modify: `frontend/package.json` (via npm install)
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Install the dependency**

```bash
cd frontend && npm install react-router-dom
```

Expected: `react-router-dom` appears in `package.json` `dependencies`.

- [ ] **Step 2: Update App.tsx**

Replace the authenticated return value in `App.tsx`. Currently it returns `<Layout />` directly. Wrap it with a router. The full replacement for the authenticated branch:

```tsx
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import FilesView from './components/FilesView'
```

Add these imports at the top of `App.tsx`, then change:

```tsx
if (authState === 'authenticated') return <Layout />
```

to:

```tsx
if (authState === 'authenticated') return (
  <BrowserRouter>
    <Routes>
      <Route path="/wiki" element={<Layout />} />
      <Route path="/files" element={<FilesView />} />
      <Route path="*" element={<Navigate to="/wiki" replace />} />
    </Routes>
  </BrowserRouter>
)
```

Note: `FilesView` doesn't exist yet — TypeScript will error until Task 9 creates it. Leave the import commented out for now and uncomment in Task 9:

```tsx
// import FilesView from './components/FilesView'  // uncomment in Task 9
```

And use a placeholder for now:

```tsx
<Route path="/files" element={<div style={{color:'#e6edf3',padding:24}}>Files coming soon</div>} />
```

- [ ] **Step 3: Verify the app still loads**

```bash
docker compose up --build
```

Open `http://localhost:5173` — the wiki should still work. Manually navigate to `http://localhost:5173/files` in the browser — should show "Files coming soon". Navigate back to `/wiki` — wiki still works.

- [ ] **Step 4: Commit**

```bash
cd frontend && git add package.json package-lock.json src/App.tsx
git commit -m "feat(routing): add react-router-dom with /wiki and /files routes"
```

---

## Task 7: Extract TopBar component

**Files:**
- Create: `frontend/src/components/TopBar.tsx`
- Modify: `frontend/src/components/Layout.tsx`

- [ ] **Step 1: Create TopBar.tsx**

Create `frontend/src/components/TopBar.tsx`:

```tsx
import type React from 'react'
import { Link, useMatch } from 'react-router-dom'
import { logout } from '../auth'

interface TopBarProps {
  agentStatus?: string | null
  onShowIngest?: () => void
}

export default function TopBar({ agentStatus, onShowIngest }: TopBarProps) {
  const onWiki = useMatch('/wiki')

  return (
    <div style={{
      display: 'flex', alignItems: 'center', padding: '8px 16px',
      background: '#161b22', borderBottom: '1px solid #30363d',
      gap: 12, flexShrink: 0,
    }}>
      <span style={{ fontWeight: 600, fontSize: 15, color: '#e6edf3' }}>LLM Wiki</span>

      <div style={{ display: 'flex', gap: 4, marginLeft: 8 }}>
        <Link
          to="/wiki"
          style={{
            padding: '4px 12px', borderRadius: 6, fontSize: 13, textDecoration: 'none',
            border: `1px solid ${onWiki ? '#58a6ff' : '#30363d'}`,
            color: onWiki ? '#58a6ff' : '#8b949e',
            background: onWiki ? '#1f3a5f' : 'transparent',
          }}
        >
          Wiki
        </Link>
        <Link
          to="/files"
          style={{
            padding: '4px 12px', borderRadius: 6, fontSize: 13, textDecoration: 'none',
            border: `1px solid ${onWiki ? '#30363d' : '#58a6ff'}`,
            color: onWiki ? '#8b949e' : '#58a6ff',
            background: onWiki ? 'transparent' : '#1f3a5f',
          }}
        >
          Files
        </Link>
      </div>

      {agentStatus && (
        <span style={{ fontSize: 12, color: '#58a6ff', marginLeft: 8 }}>⟳ {agentStatus}</span>
      )}

      <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
        {onWiki && onShowIngest && (
          <button type="button" onClick={onShowIngest} style={btnStyle}>+ Ingest</button>
        )}
        <button type="button" onClick={logout} style={btnStyle}>Sign out</button>
      </div>
    </div>
  )
}

const btnStyle: React.CSSProperties = {
  padding: '4px 12px', background: '#21262d', border: '1px solid #30363d',
  borderRadius: 6, color: '#e6edf3', cursor: 'pointer', fontSize: 13,
}
```

- [ ] **Step 2: Update Layout.tsx to use TopBar**

In `frontend/src/components/Layout.tsx`:

1. Add import at the top:
```tsx
import TopBar from './TopBar'
```

2. Remove the `logout` import (it moves into TopBar):
```tsx
import { logout } from '../auth'   // DELETE this line
```

3. Replace the entire `{/* Topbar */}` div block with:
```tsx
<TopBar agentStatus={agentStatus} onShowIngest={() => setShowIngest(true)} />
```

The topbar block to remove is:
```tsx
{/* Topbar */}
<div style={{
  display: 'flex', alignItems: 'center', padding: '8px 16px',
  background: '#161b22', borderBottom: '1px solid #30363d',
  gap: 12, flexShrink: 0,
}}>
  <span style={{ fontWeight: 600, fontSize: 15, color: '#e6edf3' }}>LLM Wiki</span>
  {agentStatus && (
    <span style={{ fontSize: 12, color: '#58a6ff', marginLeft: 8 }}>⟳ {agentStatus}</span>
  )}
  <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
    <button type="button" onClick={() => setShowIngest(true)} style={topBtnStyle}>+ Ingest</button>
    <button type="button" onClick={() => setShowActivity(!showActivity)} style={topBtnStyle}>Activity</button>
    <button type="button" onClick={logout} style={topBtnStyle}>Sign out</button>
  </div>
</div>
```

Also remove the `topBtnStyle` const at the bottom of `Layout.tsx` (it moves to `TopBar.tsx`), and update the Activity button — it's no longer in TopBar, so keep a separate Activity button in Layout's return. Add an Activity button back inside the Layout return, outside the TopBar, perhaps as a floating button or re-add it to a local inline div. Simplest: add an Activity button directly in Layout after the TopBar:

```tsx
<div style={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
  <TopBar agentStatus={agentStatus} onShowIngest={() => setShowIngest(true)} />
  <div style={{ display: 'flex', justifyContent: 'flex-end', padding: '4px 16px', background: '#161b22', borderBottom: '1px solid #30363d' }}>
    <button type="button" onClick={() => setShowActivity(!showActivity)} style={{ padding: '2px 10px', background: '#21262d', border: '1px solid #30363d', borderRadius: 6, color: '#e6edf3', cursor: 'pointer', fontSize: 12 }}>Activity</button>
  </div>
  {/* Resizable panels ... */}
```

- [ ] **Step 3: Verify the wiki still works**

```bash
docker compose up --build
```

Open `http://localhost:5173/wiki` — top bar shows Wiki (active, highlighted) and Files tabs. Clicking Files navigates to `/files`. Clicking Wiki navigates back. Activity button still visible. Sign out works.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/TopBar.tsx frontend/src/components/Layout.tsx
git commit -m "feat(nav): extract TopBar with Wiki/Files nav tabs"
```

---

## Task 8: Extract useSse hook + wire it into Layout

**Files:**
- Create: `frontend/src/hooks/useSse.ts`
- Modify: `frontend/src/components/Layout.tsx`

- [ ] **Step 1: Create useSse.ts**

Create `frontend/src/hooks/useSse.ts`:

```ts
import { useEffect, useRef } from 'react'
import { createSSE } from '../api/client'

export function useSse(onEvent: (data: unknown) => void): void {
  const handlerRef = useRef(onEvent)
  handlerRef.current = onEvent
  useEffect(() => {
    return createSSE((data) => handlerRef.current(data))
  }, [])
}
```

The `handlerRef` pattern means the effect only runs once (no re-subscriptions on re-render), but always calls the latest version of the handler.

- [ ] **Step 2: Update Layout.tsx to use useSse**

In `frontend/src/components/Layout.tsx`:

1. Add import:
```tsx
import { useSse } from '../hooks/useSse'
```

2. Find the existing SSE useEffect:
```tsx
useEffect(() => {
  const unsub = createSSE((data: unknown) => {
    // ... all the event handling ...
  })
  return unsub
}, [qc, queueActions])
```

Replace the entire block with:
```tsx
useSse((data: unknown) => {
  const event = data as {
    event: string
    slug?: string
    source_id?: string
    filename?: string
    pages_touched?: string[]
    context?: string
  }
  if (event.context === 'chat') {
    if (event.event === 'agent:done') {
      qc.invalidateQueries({ queryKey: ['pages'] })
      qc.invalidateQueries({ queryKey: ['activity'] })
    } else {
      setChatSseEvent({ event: event.event, slug: event.slug })
    }
    return
  }
  const STATUS_MAP: Partial<Record<string, QueueItem['status']>> = {
    'agent:queued': 'queued',
    'agent:converting': 'converting',
    'agent:ingesting': 'processing',
    'agent:done': 'done',
    'agent:error': 'error',
  }
  const queueStatus = STATUS_MAP[event.event]
  if (queueStatus && event.source_id) {
    queueActions.patchBySource(event.source_id, { status: queueStatus })
  }
  if (event.event === 'agent:error') {
    setHighlightedSlug(null)
    setAgentStatus(null)
  }
  if (event.event === 'agent:queued') {
    const label = event.filename ?? (event.source_id ? `source ${event.source_id.slice(0, 8)}…` : null)
    setAgentStatus(label ? `Queued ${label}…` : 'Queued…')
  } else if (event.event === 'agent:converting') {
    const label = event.filename ?? (event.source_id ? `source ${event.source_id.slice(0, 8)}…` : null)
    setAgentStatus(label ? `Converting ${label}…` : 'Converting document…')
  } else if (event.event === 'agent:ingesting') {
    const label = event.filename ?? (event.source_id ? `source ${event.source_id.slice(0, 8)}…` : null)
    setAgentStatus(label ? `Updating wiki from ${label}…` : 'Updating wiki from ingested source…')
  } else if (event.event === 'agent:reading') {
    setHighlightedSlug(event.slug || null)
    setAgentStatus(`Reading ${event.slug}…`)
  } else if (event.event === 'agent:writing') {
    setHighlightedSlug(event.slug || null)
    setAgentStatus(`Writing ${event.slug}…`)
  } else if (event.event === 'agent:moving') {
    const e = event as { event: string; from?: string; to?: string }
    setHighlightedSlug(e.to || null)
    setAgentStatus(e.from && e.to ? `Moving ${e.from} → ${e.to}…` : 'Moving page…')
  } else if (event.event === 'agent:deleting') {
    setHighlightedSlug(null)
    setAgentStatus(event.slug ? `Deleting ${event.slug}…` : 'Deleting page…')
  } else if (event.event === 'agent:moved_folder') {
    const e = event as { event: string; from?: string; to?: string; count?: number }
    setHighlightedSlug(null)
    setAgentStatus(
      e.from && e.to
        ? `Moved ${e.count ?? '?'} pages: ${e.from} → ${e.to}`
        : 'Folder move complete',
    )
  } else if (event.event === 'agent:done') {
    setHighlightedSlug(null)
    setAgentStatus(null)
    qc.invalidateQueries({ queryKey: ['pages'] })
    qc.invalidateQueries({ queryKey: ['activity'] })
  }
})
```

3. Remove the now-unused `createSSE` import from `Layout.tsx` if it's no longer used directly.

- [ ] **Step 3: Verify wiki SSE still works**

Ingest a file and confirm the status bar in the top bar updates live (`Converting…`, `Updating wiki…`, etc.). The wiki page list should refresh when ingestion completes.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/hooks/useSse.ts frontend/src/components/Layout.tsx
git commit -m "refactor: extract useSse hook from Layout"
```

---

## Task 9: Add source API functions and useSources hook

**Files:**
- Modify: `frontend/src/api/client.ts`
- Create: `frontend/src/hooks/useSources.ts`

- [ ] **Step 1: Add API functions to client.ts**

Append to `frontend/src/api/client.ts`:

```ts
export interface SourceItem {
  id: string
  kind: string
  filename: string | null
  status: string
  has_file: boolean
  has_markdown: boolean
  created_at: string
}

export async function listSources(): Promise<SourceItem[]> {
  const r = await fetchWithAuth(`${BASE}/sources`)
  if (!r.ok) throw new Error(`listSources failed: ${r.status}`)
  return r.json()
}

export async function fetchSourceFile(sourceId: string): Promise<Blob> {
  const r = await fetchWithAuth(`${BASE}/sources/${sourceId}/file`)
  if (!r.ok) throw new Error(`fetchSourceFile failed: ${r.status}`)
  return r.blob()
}

export async function fetchSourceMarkdown(sourceId: string): Promise<string> {
  const r = await fetchWithAuth(`${BASE}/sources/${sourceId}/markdown`)
  if (!r.ok) throw new Error(`fetchSourceMarkdown failed: ${r.status}`)
  return r.text()
}
```

- [ ] **Step 2: Create useSources.ts**

Create `frontend/src/hooks/useSources.ts`:

```ts
import { useQuery } from '@tanstack/react-query'
import { listSources, fetchSourceMarkdown } from '../api/client'
import type { SourceItem } from '../api/client'

export type { SourceItem }

export function useSources() {
  return useQuery<SourceItem[]>({
    queryKey: ['sources'],
    queryFn: listSources,
    refetchOnWindowFocus: true,
    initialData: [],
  })
}

export function useSourceMarkdown(sourceId: string | null, enabled: boolean) {
  return useQuery<string>({
    queryKey: ['source-markdown', sourceId],
    queryFn: () => fetchSourceMarkdown(sourceId!),
    enabled: enabled && !!sourceId,
  })
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/hooks/useSources.ts
git commit -m "feat(sources): add API client functions and useSources hook"
```

---

## Task 10: Create FilesView and FilesList components

**Files:**
- Create: `frontend/src/components/FilesView.tsx`
- Create: `frontend/src/components/FilesList.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Create FilesList.tsx**

Create `frontend/src/components/FilesList.tsx`:

```tsx
import type { SourceItem } from '../hooks/useSources'

export interface SourceSelection {
  sourceId: string
  view: 'original' | 'markdown'
}

interface FilesListProps {
  sources: SourceItem[]
  selection: SourceSelection | null
  onSelect: (sel: SourceSelection) => void
}

const STATUS_COLOR: Record<string, string> = {
  done: '#3fb950',
  error: '#f85149',
  converting: '#d29922',
  ingesting: '#58a6ff',
}

function fileIcon(kind: string): string {
  if (kind === 'pdf') return '📄'
  if (['png', 'jpg', 'jpeg', 'webp'].includes(kind)) return '🖼'
  if (['docx', 'doc'].includes(kind)) return '📝'
  if (['pptx', 'ppt', 'xlsx', 'xls'].includes(kind)) return '📊'
  if (kind === 'url') return '🔗'
  return '📄'
}

export default function FilesList({ sources, selection, onSelect }: FilesListProps) {
  if (sources.length === 0) {
    return (
      <div style={{ width: 240, borderRight: '1px solid #21262d', padding: 16, color: '#8b949e', fontSize: 13 }}>
        No files ingested yet.
      </div>
    )
  }

  return (
    <div style={{ width: 240, borderRight: '1px solid #21262d', overflowY: 'auto', padding: 8, flexShrink: 0 }}>
      {sources.map(source => {
        const label = source.filename ?? `${source.kind} · ${source.id.slice(0, 8)}`
        const isOriginalSelected = selection?.sourceId === source.id && selection?.view === 'original'
        const isMarkdownSelected = selection?.sourceId === source.id && selection?.view === 'markdown'
        const dotColor = STATUS_COLOR[source.status] ?? '#8b949e'

        return (
          <div key={source.id} style={{ marginBottom: 10 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3, paddingLeft: 4 }}>
              <span style={{
                color: '#6e7681', fontSize: 10, textTransform: 'uppercase',
                letterSpacing: '.05em', overflow: 'hidden', textOverflow: 'ellipsis',
                whiteSpace: 'nowrap', flex: 1,
              }}>
                {label}
              </span>
              <span
                style={{ width: 6, height: 6, borderRadius: '50%', background: dotColor, flexShrink: 0 }}
                title={source.status}
              />
            </div>

            {source.has_file && (
              <div
                role="button"
                tabIndex={0}
                onClick={() => onSelect({ sourceId: source.id, view: 'original' })}
                onKeyDown={e => e.key === 'Enter' && onSelect({ sourceId: source.id, view: 'original' })}
                style={rowStyle(isOriginalSelected)}
              >
                <span>{fileIcon(source.kind)}</span>
                <span style={{ fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
                  {label}
                </span>
                <span style={{ marginLeft: 'auto', fontSize: 10, color: '#6e7681', flexShrink: 0 }}>original</span>
              </div>
            )}

            <div
              role="button"
              tabIndex={0}
              onClick={() => onSelect({ sourceId: source.id, view: 'markdown' })}
              onKeyDown={e => e.key === 'Enter' && onSelect({ sourceId: source.id, view: 'markdown' })}
              style={rowStyle(isMarkdownSelected)}
            >
              <span>📝</span>
              <span style={{ fontSize: 12, flex: 1 }}>converted.md</span>
              <span style={{ marginLeft: 'auto', fontSize: 10, color: '#6e7681', flexShrink: 0 }}>markdown</span>
            </div>
          </div>
        )
      })}
    </div>
  )
}

function rowStyle(active: boolean): React.CSSProperties {
  return {
    padding: '4px 8px', borderRadius: 4, cursor: 'pointer',
    display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2,
    background: active ? '#1f3a5f' : 'transparent',
    color: active ? '#58a6ff' : '#8b949e',
    border: `1px solid ${active ? '#58a6ff33' : 'transparent'}`,
  }
}
```

Add the missing React import at the top of `FilesList.tsx`:
```tsx
import type React from 'react'
```

- [ ] **Step 2: Create FilesView.tsx**

Create `frontend/src/components/FilesView.tsx`:

```tsx
import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import TopBar from './TopBar'
import FilesList from './FilesList'
import FileViewer from './FileViewer'
import { useSources } from '../hooks/useSources'
import { useSse } from '../hooks/useSse'
import type { SourceSelection } from './FilesList'

export default function FilesView() {
  const [selection, setSelection] = useState<SourceSelection | null>(null)
  const { data: sources } = useSources()
  const qc = useQueryClient()

  useSse((data: unknown) => {
    const event = data as { event: string }
    if (event.event === 'agent:done') {
      qc.invalidateQueries({ queryKey: ['sources'] })
    }
  })

  const selectedSource = sources?.find(s => s.id === selection?.sourceId) ?? null

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
      <TopBar />
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <FilesList
          sources={sources ?? []}
          selection={selection}
          onSelect={setSelection}
        />
        <FileViewer source={selectedSource} view={selection?.view ?? 'markdown'} />
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Wire FilesView into App.tsx**

In `frontend/src/App.tsx`, replace the placeholder comment and import:

```tsx
// import FilesView from './components/FilesView'  // uncomment in Task 9
```

with:

```tsx
import FilesView from './components/FilesView'
```

And replace the placeholder route:

```tsx
<Route path="/files" element={<div style={{color:'#e6edf3',padding:24}}>Files coming soon</div>} />
```

with:

```tsx
<Route path="/files" element={<FilesView />} />
```

- [ ] **Step 4: Verify navigation works**

Open the app. Clicking "Files" in the top bar navigates to `/files` and shows the file list (or "No files ingested yet."). Clicking "Wiki" navigates back. Ingest a file and navigate to Files — it should appear in the list with the correct status badge.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/FilesView.tsx frontend/src/components/FilesList.tsx frontend/src/App.tsx
git commit -m "feat(files): add FilesView and FilesList components"
```

---

## Task 11: Create FileViewer component

**Files:**
- Create: `frontend/src/components/FileViewer.tsx`

- [ ] **Step 1: Create FileViewer.tsx**

Create `frontend/src/components/FileViewer.tsx`:

```tsx
import { useState, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'
import { fetchSourceFile } from '../api/client'
import { useSourceMarkdown } from '../hooks/useSources'
import type { SourceItem } from '../hooks/useSources'

const IMAGE_KINDS = ['png', 'jpg', 'jpeg', 'webp']
const NO_FILE_KINDS = ['url', 'text', 'md', 'markdown', 'txt']

interface FileViewerProps {
  source: SourceItem | null
  view: 'original' | 'markdown'
}

export default function FileViewer({ source, view }: FileViewerProps) {
  if (!source) {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#8b949e', fontSize: 13 }}>
        Select a file to view it.
      </div>
    )
  }

  if (view === 'markdown') return <MarkdownPane source={source} />
  return <OriginalPane source={source} />
}

function MarkdownPane({ source }: { source: SourceItem }) {
  const [rawMode, setRawMode] = useState(false)
  const canFetch = source.status === 'done' && source.has_markdown
  const { data: markdown, isLoading, isError, refetch } = useSourceMarkdown(source.id, canFetch)

  if (source.status === 'converting' || source.status === 'ingesting') {
    return <Centered>Still processing…</Centered>
  }
  if (source.status === 'error') {
    return <Centered>Conversion failed — no markdown available.</Centered>
  }
  if (!source.has_markdown) {
    return <Centered>No markdown available yet.</Centered>
  }
  if (isLoading) return <Centered>Loading…</Centered>
  if (isError) {
    return (
      <Centered>
        Could not load file.{' '}
        <button onClick={() => refetch()} style={btnStyle}>Retry</button>
      </Centered>
    )
  }

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <div style={headerStyle}>
        <span style={{ color: '#e6edf3', fontWeight: 600 }}>
          {source.filename ?? source.kind} — markdown
        </span>
        <button onClick={() => setRawMode(m => !m)} style={{ ...btnStyle, marginLeft: 'auto' }}>
          {rawMode ? 'Rendered' : 'Raw'}
        </button>
      </div>
      <div style={{ flex: 1, overflowY: 'auto', padding: 24 }}>
        {rawMode ? (
          <pre style={{ color: '#c9d1d9', fontSize: 13, lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
            {markdown}
          </pre>
        ) : (
          <div style={{ lineHeight: 1.7, fontSize: 14, color: '#c9d1d9' }}>
            <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}>
              {markdown ?? ''}
            </ReactMarkdown>
          </div>
        )}
      </div>
    </div>
  )
}

function OriginalPane({ source }: { source: SourceItem }) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(false)
  const [retryCount, setRetryCount] = useState(0)

  useEffect(() => {
    if (NO_FILE_KINDS.includes(source.kind) || !source.has_file) return
    let objectUrl: string | null = null
    setLoading(true)
    setError(false)
    setBlobUrl(null)

    fetchSourceFile(source.id)
      .then(blob => {
        objectUrl = URL.createObjectURL(blob)
        setBlobUrl(objectUrl)
        setLoading(false)
      })
      .catch(() => {
        setError(true)
        setLoading(false)
      })

    return () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [source.id, source.kind, source.has_file, retryCount])

  if (NO_FILE_KINDS.includes(source.kind)) {
    return <Centered>Web or text source — no original file to display.</Centered>
  }
  if (!source.has_file) return <Centered>No original file.</Centered>
  if (loading) return <Centered>Loading…</Centered>
  if (error) {
    return (
      <Centered>
        Could not load file.{' '}
        <button onClick={() => setRetryCount(c => c + 1)} style={btnStyle}>Retry</button>
      </Centered>
    )
  }

  const filename = source.filename ?? `file.${source.kind}`

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <div style={headerStyle}>
        <span style={{ color: '#e6edf3', fontWeight: 600 }}>{filename}</span>
        {blobUrl && (
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
            <a href={blobUrl} download={filename} style={linkBtnStyle}>⬇ Download</a>
            <a href={blobUrl} target="_blank" rel="noreferrer" style={linkBtnStyle}>↗ Open in tab</a>
          </div>
        )}
      </div>

      {blobUrl && source.kind === 'pdf' && (
        <iframe src={blobUrl} style={{ flex: 1, border: 'none' }} title={filename} />
      )}
      {blobUrl && IMAGE_KINDS.includes(source.kind) && (
        <div style={{ flex: 1, overflowY: 'auto', padding: 16, display: 'flex', alignItems: 'flex-start', justifyContent: 'center' }}>
          <img src={blobUrl} alt={filename} style={{ maxWidth: '100%' }} />
        </div>
      )}
      {blobUrl && !IMAGE_KINDS.includes(source.kind) && source.kind !== 'pdf' && (
        <Centered>This file type cannot be previewed. Use the buttons above to download or open it.</Centered>
      )}
    </div>
  )
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#8b949e', fontSize: 13, gap: 8 }}>
      {children}
    </div>
  )
}

const headerStyle: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 8,
  padding: '8px 16px', borderBottom: '1px solid #21262d',
  background: '#161b22', flexShrink: 0,
}

const btnStyle: React.CSSProperties = {
  padding: '3px 10px', background: '#21262d', border: '1px solid #30363d',
  borderRadius: 4, color: '#e6edf3', cursor: 'pointer', fontSize: 12,
}

const linkBtnStyle: React.CSSProperties = {
  padding: '3px 10px', background: '#21262d', border: '1px solid #30363d',
  borderRadius: 4, color: '#e6edf3', cursor: 'pointer', fontSize: 12,
  textDecoration: 'none',
}
```

Add missing React import at the top:
```tsx
import type React from 'react'
```

- [ ] **Step 2: Verify end-to-end in the browser**

Open the app, navigate to `/files`. For each action below, verify the correct behaviour:

1. Select a `converted.md` for a done source → rendered markdown appears
2. Click "Raw" toggle → raw markdown text shown; click "Rendered" → back to rendered
3. Select original for a PDF source → PDF renders inline; download and open-in-tab buttons work
4. Select original for a PNG → image renders inline
5. Select original for a DOCX → "cannot be previewed" message + download/open buttons
6. Select a still-processing source's markdown → "Still processing…" shown
7. Select an error source's markdown → "Conversion failed" shown

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/FileViewer.tsx
git commit -m "feat(files): add FileViewer with markdown toggle and file embed"
```

---

## Task 12: Run full test suite + final check

- [ ] **Step 1: Run all backend tests**

```bash
docker compose run --rm api pytest tests/ -v
```

Expected: all tests pass, including the new `tests/test_sources.py`.

- [ ] **Step 2: TypeScript check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Final commit**

If there are any loose files not yet committed:

```bash
git status
git add <any remaining files>
git commit -m "feat(files): complete Files section implementation"
```
