# LLM Wiki v0 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single-user, web-only, LLM-maintained markdown wiki that auto-ingests sources and answers questions using whole-page wiki navigation.

**Architecture:** FastAPI backend with asyncio background workers, React frontend in a split-view layout (wiki left, chat right), Postgres with pgvector for hybrid search, three LiteLLM-powered agents sharing one tool surface, all wired together via Docker Compose.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy (async), Alembic, pgvector, LiteLLM, pypdf, python-docx, trafilatura, React 18, TypeScript, Vite, Docker Compose, MinIO, Postgres 16

---

## File Structure

```
repo/
├── docker-compose.yml
├── docker-compose.prod.yml
├── .env.example
├── .gitignore
├── api/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── alembic.ini
│   ├── alembic/
│   │   └── versions/
│   └── app/
│       ├── main.py              # FastAPI app, all routers mounted
│       ├── config.py            # Pydantic-settings config
│       ├── database.py          # Async SQLAlchemy engine + session dep
│       ├── models.py            # All ORM models
│       ├── auth.py              # Single-user JWT auth
│       ├── storage.py           # S3/MinIO client
│       ├── search.py            # Hybrid tsvector + pgvector search
│       ├── wikilinks.py         # [[wikilinks]] parser + page_links sync
│       ├── sse.py               # SSE event broadcaster
│       ├── routes/
│       │   ├── wiki.py          # Wiki CRUD
│       │   ├── ingest.py        # Upload + trigger ingest
│       │   ├── chat.py          # Chat sessions + SSE stream
│       │   └── activity.py      # Activity log
│       ├── agents/
│       │   ├── tools.py         # Shared tool surface (5 functions)
│       │   ├── ingest_agent.py  # Ingest agent loop
│       │   ├── query_agent.py   # Query agent loop
│       │   └── chat_monitor.py  # Chat monitor agent loop
│       └── extractors/
│           ├── pdf.py
│           ├── docx.py
│           └── url.py
├── tests/
│   ├── conftest.py
│   ├── test_wiki.py
│   ├── test_search.py
│   ├── test_wikilinks.py
│   ├── test_extractors.py
│   └── test_agents.py
└── frontend/
    ├── Dockerfile
    ├── package.json
    ├── vite.config.ts
    ├── tsconfig.json
    └── src/
        ├── main.tsx
        ├── App.tsx
        ├── api/
        │   └── client.ts
        ├── hooks/
        │   ├── useSSE.ts
        │   └── useWiki.ts
        └── components/
            ├── Layout.tsx         # Split view shell
            ├── WikiPanel.tsx      # Page list + markdown editor
            ├── ChatPanel.tsx      # Chat messages + input
            ├── ActivityLog.tsx    # Collapsible drawer
            ├── IngestModal.tsx    # Upload / paste / URL form
            └── AgentStatus.tsx    # Live "reading X..." indicator
```

---

## Task 1: Repo structure + Docker Compose

**Files:**
- Create: `docker-compose.yml`
- Create: `docker-compose.prod.yml`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `api/Dockerfile`
- Create: `frontend/Dockerfile`
- Create: `api/requirements.txt`

- [ ] **Step 1: Create root `.gitignore`**

```
.env
__pycache__/
*.pyc
.venv/
node_modules/
dist/
.superpowers/
```

- [ ] **Step 2: Create `.env.example`**

```
GEMINI_API_KEY=your-key-here
LITELLM_MODEL=gemini/gemini-2.0-flash
JWT_SECRET=change-me-in-prod
DATABASE_URL=postgresql+asyncpg://wiki:wiki@db:5432/wiki
S3_ENDPOINT=http://minio:9000
S3_BUCKET=wiki
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
SINGLE_USER_EMAIL=you@example.com
SINGLE_USER_PASSWORD=changeme
```

- [ ] **Step 3: Create `docker-compose.yml`**

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

  api:
    build: ./api
    depends_on:
      db:
        condition: service_healthy
      minio:
        condition: service_healthy
    env_file: .env
    environment:
      DATABASE_URL: postgresql+asyncpg://wiki:wiki@db:5432/wiki
      S3_ENDPOINT: http://minio:9000
    ports:
      - "8000:8000"
    volumes:
      - ./api:/app
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

volumes:
  pgdata:
  minio_data:
```

- [ ] **Step 4: Create `api/Dockerfile`**

```dockerfile
FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y gcc libpq-dev && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
```

- [ ] **Step 5: Create `api/requirements.txt`**

```
fastapi==0.115.0
uvicorn[standard]==0.30.0
sqlalchemy[asyncio]==2.0.36
asyncpg==0.29.0
alembic==1.13.3
pgvector==0.3.5
pydantic-settings==2.5.2
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
python-multipart==0.0.12
boto3==1.35.0
httpx==0.27.2
trafilatura==1.12.1
pypdf==5.1.0
python-docx==1.1.2
litellm==1.52.0
pytest==8.3.3
pytest-asyncio==0.24.0
httpx==0.27.2
```

- [ ] **Step 6: Create `frontend/Dockerfile`**

```dockerfile
FROM node:22-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
```

- [ ] **Step 7: Copy `.env.example` to `.env` and fill in your Gemini API key**

```bash
cp .env.example .env
# Edit .env — set GEMINI_API_KEY and SINGLE_USER_PASSWORD
```

- [ ] **Step 8: Verify compose file parses**

```bash
docker compose config
```

Expected: no errors, full merged config printed.

- [ ] **Step 9: Commit**

```bash
git add docker-compose.yml docker-compose.prod.yml .env.example .gitignore api/Dockerfile api/requirements.txt frontend/Dockerfile
git commit -m "feat: docker compose stack skeleton"
```

---

## Task 2: Postgres schema + Alembic migrations

**Files:**
- Create: `api/app/models.py`
- Create: `api/app/database.py`
- Create: `api/app/config.py`
- Create: `api/alembic.ini`
- Create: `api/alembic/env.py`
- Create: `api/alembic/versions/0001_initial.py`

- [ ] **Step 1: Create `api/app/config.py`**

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str
    jwt_secret: str = "dev-secret"
    litellm_model: str = "gemini/gemini-2.0-flash"
    s3_endpoint: str = "http://minio:9000"
    s3_bucket: str = "wiki"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    single_user_email: str = "user@example.com"
    single_user_password: str = "changeme"

    class Config:
        env_file = ".env"

settings = Settings()
```

- [ ] **Step 2: Create `api/app/database.py`**

```python
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from app.config import settings

engine = create_async_engine(settings.database_url, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
```

- [ ] **Step 3: Create `api/app/models.py`**

```python
import uuid
from datetime import datetime
from sqlalchemy import String, Text, DateTime, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB
from pgvector.sqlalchemy import Vector
from app.database import Base

def _uuid():
    return str(uuid.uuid4())

class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    pages: Mapped[list["Page"]] = relationship(back_populates="workspace")

class Page(Base):
    __tablename__ = "pages"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    slug: Mapped[str] = mapped_column(String, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="")
    body_md: Mapped[str] = mapped_column(Text, default="")
    embedding: Mapped[list[float]] = mapped_column(Vector(1536), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    workspace: Mapped["Workspace"] = relationship(back_populates="pages")
    revisions: Mapped[list["Revision"]] = relationship(back_populates="page")

class PageLink(Base):
    __tablename__ = "page_links"
    from_page_id: Mapped[str] = mapped_column(ForeignKey("pages.id"), primary_key=True)
    to_page_id: Mapped[str] = mapped_column(ForeignKey("pages.id"), primary_key=True)

class Revision(Base):
    __tablename__ = "revisions"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    page_id: Mapped[str] = mapped_column(ForeignKey("pages.id"))
    parent_revision_id: Mapped[str | None] = mapped_column(String, nullable=True)
    body_md: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    page: Mapped["Page"] = relationship(back_populates="revisions")

class Source(Base):
    __tablename__ = "sources"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    kind: Mapped[str] = mapped_column(String)  # pdf | docx | text | url
    s3_key: Mapped[str | None] = mapped_column(String, nullable=True)
    extracted_text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class ActivityLog(Base):
    __tablename__ = "activity_log"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    event_type: Mapped[str] = mapped_column(String)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class ChatSession(Base):
    __tablename__ = "chat_sessions"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    messages: Mapped[list["ChatMessage"]] = relationship(back_populates="session")

class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("chat_sessions.id"))
    role: Mapped[str] = mapped_column(String)  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    session: Mapped["ChatSession"] = relationship(back_populates="messages")
```

- [ ] **Step 4: Initialise Alembic inside the api container**

```bash
docker compose run --rm api alembic init alembic
```

- [ ] **Step 5: Update `api/alembic/env.py`** — replace the `target_metadata` block so Alembic sees your models:

```python
# In env.py, replace the two lines near "target_metadata = None" with:
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app.database import Base
from app import models  # noqa: F401 — ensures models register on Base
target_metadata = Base.metadata
```

Also update the `run_migrations_online` block to use `asyncpg` via a sync adapter:

```python
from sqlalchemy import pool, create_engine
from app.config import settings

def run_migrations_online() -> None:
    # Alembic needs a sync engine; strip the +asyncpg prefix
    sync_url = settings.database_url.replace("+asyncpg", "")
    connectable = create_engine(sync_url, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
```

- [ ] **Step 6: Create the initial migration**

```bash
docker compose run --rm api alembic revision --autogenerate -m "initial schema"
```

Expected: a new file created in `api/alembic/versions/`.

- [ ] **Step 7: Open the generated migration and add pgvector extension creation at the top of `upgrade()`**

```python
def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    # ... rest of autogenerated tables ...
```

Also add a `tsvector` column for full-text search on pages after the autogenerated table creation:

```python
    op.execute("""
        ALTER TABLE pages
        ADD COLUMN IF NOT EXISTS tsv tsvector
            GENERATED ALWAYS AS (
                to_tsvector('english', coalesce(title, '') || ' ' || coalesce(body_md, ''))
            ) STORED
    """)
    op.execute("CREATE INDEX IF NOT EXISTS pages_tsv_idx ON pages USING GIN(tsv)")
    op.execute("CREATE INDEX IF NOT EXISTS pages_embedding_idx ON pages USING hnsw(embedding vector_cosine_ops)")
```

- [ ] **Step 8: Run migrations**

```bash
docker compose run --rm api alembic upgrade head
```

Expected: `INFO  [alembic.runtime.migration] Running upgrade  -> xxxx, initial schema`

- [ ] **Step 9: Commit**

```bash
git add api/app/config.py api/app/database.py api/app/models.py api/alembic.ini api/alembic/
git commit -m "feat: postgres schema + alembic migrations"
```

---

## Task 3: FastAPI app skeleton + auth

**Files:**
- Create: `api/app/main.py`
- Create: `api/app/auth.py`
- Create: `tests/conftest.py`
- Create: `tests/test_auth.py`

- [ ] **Step 1: Write the failing auth test**

```python
# tests/test_auth.py
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.asyncio
async def test_login_returns_token():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/auth/login", json={
            "email": "user@example.com",
            "password": "changeme"
        })
    assert resp.status_code == 200
    assert "access_token" in resp.json()

@pytest.mark.asyncio
async def test_wrong_password_rejected():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/auth/login", json={
            "email": "user@example.com",
            "password": "wrong"
        })
    assert resp.status_code == 401
```

- [ ] **Step 2: Create `tests/conftest.py`**

```python
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://wiki:wiki@localhost:5432/wiki")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("SINGLE_USER_EMAIL", "user@example.com")
os.environ.setdefault("SINGLE_USER_PASSWORD", "changeme")
os.environ.setdefault("LITELLM_MODEL", "gemini/gemini-2.0-flash")
os.environ.setdefault("S3_ENDPOINT", "http://localhost:9000")
os.environ.setdefault("S3_BUCKET", "wiki")
os.environ.setdefault("S3_ACCESS_KEY", "minioadmin")
os.environ.setdefault("S3_SECRET_KEY", "minioadmin")
```

- [ ] **Step 3: Run test to verify it fails**

```bash
docker compose run --rm api pytest tests/test_auth.py -v
```

Expected: `ModuleNotFoundError` or `ImportError` — `app.main` doesn't exist yet.

- [ ] **Step 4: Create `api/app/auth.py`**

```python
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from pydantic import BaseModel
from app.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
ALGORITHM = "HS256"
TOKEN_EXPIRE_DAYS = 30

class LoginRequest(BaseModel):
    email: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest):
    if req.email != settings.single_user_email or req.password != settings.single_user_password:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    expire = datetime.utcnow() + timedelta(days=TOKEN_EXPIRE_DAYS)
    token = jwt.encode({"sub": req.email, "exp": expire}, settings.jwt_secret, algorithm=ALGORITHM)
    return TokenResponse(access_token=token)

async def get_current_user(token: str = Depends(oauth2_scheme)) -> str:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        return payload["sub"]
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
```

- [ ] **Step 5: Create `api/app/main.py`**

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.auth import router as auth_router

app = FastAPI(title="LLM Wiki")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)

@app.get("/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
docker compose run --rm api pytest tests/test_auth.py -v
```

Expected: both tests pass.

- [ ] **Step 7: Commit**

```bash
git add api/app/main.py api/app/auth.py tests/conftest.py tests/test_auth.py
git commit -m "feat: fastapi skeleton + single-user JWT auth"
```

---

## Task 4: Wiki CRUD endpoints

**Files:**
- Create: `api/app/routes/wiki.py`
- Create: `api/app/wikilinks.py`
- Create: `tests/test_wiki.py`
- Modify: `api/app/main.py`

- [ ] **Step 1: Write the failing wiki tests**

```python
# tests/test_wiki.py
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

async def _token(client):
    r = await client.post("/auth/login", json={"email": "user@example.com", "password": "changeme"})
    return r.json()["access_token"]

@pytest.mark.asyncio
async def test_create_and_get_page():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _token(client)
        headers = {"Authorization": f"Bearer {token}"}
        create = await client.post("/wiki/pages", json={
            "slug": "test-page",
            "title": "Test Page",
            "body_md": "# Test\n\nHello [[other-page]]."
        }, headers=headers)
        assert create.status_code == 201
        get = await client.get("/wiki/pages/test-page", headers=headers)
        assert get.status_code == 200
        assert get.json()["title"] == "Test Page"

@pytest.mark.asyncio
async def test_list_pages():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _token(client)
        headers = {"Authorization": f"Bearer {token}"}
        r = await client.get("/wiki/pages", headers=headers)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

@pytest.mark.asyncio
async def test_update_page():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _token(client)
        headers = {"Authorization": f"Bearer {token}"}
        await client.post("/wiki/pages", json={"slug": "update-me", "title": "Old", "body_md": "old"}, headers=headers)
        r = await client.put("/wiki/pages/update-me", json={"title": "New", "body_md": "new content"}, headers=headers)
        assert r.status_code == 200
        assert r.json()["title"] == "New"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker compose run --rm api pytest tests/test_wiki.py -v
```

Expected: 404 on all wiki routes.

- [ ] **Step 3: Create `api/app/wikilinks.py`**

```python
import re
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from app.models import Page, PageLink

WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")

def extract_slugs(body_md: str) -> list[str]:
    return WIKILINK_RE.findall(body_md)

async def sync_links(session: AsyncSession, page: Page) -> None:
    slugs = extract_slugs(page.body_md)
    await session.execute(delete(PageLink).where(PageLink.from_page_id == page.id))
    for slug in slugs:
        result = await session.execute(select(Page).where(Page.slug == slug, Page.workspace_id == page.workspace_id))
        target = result.scalar_one_or_none()
        if target:
            session.add(PageLink(from_page_id=page.id, to_page_id=target.id))
```

- [ ] **Step 4: Create `api/app/routes/wiki.py`**

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from app.database import get_db
from app.auth import get_current_user
from app.models import Workspace, Page, Revision, ActivityLog
from app.wikilinks import sync_links
from datetime import datetime
import uuid

router = APIRouter(prefix="/wiki", tags=["wiki"])

def _workspace_id(user: str) -> str:
    # Deterministic workspace per user for single-user setup
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"workspace:{user}"))

async def _ensure_workspace(session: AsyncSession, user: str) -> Workspace:
    ws_id = _workspace_id(user)
    result = await session.execute(select(Workspace).where(Workspace.id == ws_id))
    ws = result.scalar_one_or_none()
    if not ws:
        ws = Workspace(id=ws_id, user_id=user)
        session.add(ws)
        await session.commit()
    return ws

class PageCreate(BaseModel):
    slug: str
    title: str
    body_md: str = ""
    summary: str = ""

class PageUpdate(BaseModel):
    title: str | None = None
    body_md: str | None = None
    summary: str | None = None

class PageOut(BaseModel):
    id: str
    slug: str
    title: str
    summary: str
    body_md: str
    updated_at: datetime
    model_config = {"from_attributes": True}

@router.get("/pages", response_model=list[PageOut])
async def list_pages(
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user)
):
    ws = await _ensure_workspace(db, user)
    result = await db.execute(select(Page).where(Page.workspace_id == ws.id).order_by(Page.updated_at.desc()))
    return result.scalars().all()

@router.post("/pages", response_model=PageOut, status_code=201)
async def create_page(
    body: PageCreate,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user)
):
    ws = await _ensure_workspace(db, user)
    existing = await db.execute(select(Page).where(Page.slug == body.slug, Page.workspace_id == ws.id))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Page with this slug already exists")
    page = Page(workspace_id=ws.id, **body.model_dump())
    db.add(page)
    await db.flush()
    await sync_links(db, page)
    db.add(ActivityLog(workspace_id=ws.id, event_type="page_created", payload={"slug": page.slug, "title": page.title}))
    await db.commit()
    await db.refresh(page)
    return page

@router.get("/pages/{slug}", response_model=PageOut)
async def get_page(
    slug: str,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user)
):
    ws = await _ensure_workspace(db, user)
    result = await db.execute(select(Page).where(Page.slug == slug, Page.workspace_id == ws.id))
    page = result.scalar_one_or_none()
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    return page

@router.put("/pages/{slug}", response_model=PageOut)
async def update_page(
    slug: str,
    body: PageUpdate,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user)
):
    ws = await _ensure_workspace(db, user)
    result = await db.execute(select(Page).where(Page.slug == slug, Page.workspace_id == ws.id))
    page = result.scalar_one_or_none()
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    # Save revision before updating
    db.add(Revision(page_id=page.id, body_md=page.body_md))
    if body.title is not None:
        page.title = body.title
    if body.body_md is not None:
        page.body_md = body.body_md
        await sync_links(db, page)
    if body.summary is not None:
        page.summary = body.summary
    page.updated_at = datetime.utcnow()
    db.add(ActivityLog(workspace_id=ws.id, event_type="page_updated", payload={"slug": page.slug}))
    await db.commit()
    await db.refresh(page)
    return page

@router.delete("/pages/{slug}", status_code=204)
async def delete_page(
    slug: str,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user)
):
    ws = await _ensure_workspace(db, user)
    result = await db.execute(select(Page).where(Page.slug == slug, Page.workspace_id == ws.id))
    page = result.scalar_one_or_none()
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    await db.delete(page)
    await db.commit()
```

- [ ] **Step 5: Mount wiki router in `api/app/main.py`**

```python
from app.routes.wiki import router as wiki_router
app.include_router(wiki_router)
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
docker compose run --rm api pytest tests/test_wiki.py -v
```

Expected: all 3 tests pass.

- [ ] **Step 7: Commit**

```bash
git add api/app/routes/wiki.py api/app/wikilinks.py api/app/main.py tests/test_wiki.py
git commit -m "feat: wiki CRUD endpoints + wikilinks sync"
```

---

## Task 5: Hybrid search (tsvector + pgvector)

**Files:**
- Create: `api/app/search.py`
- Create: `tests/test_search.py`

- [ ] **Step 1: Write the failing search test**

```python
# tests/test_search.py
import pytest
from app.search import parse_search_results

def test_parse_search_results_empty():
    assert parse_search_results([]) == []

def test_parse_search_results_deduplicates():
    rows = [
        {"id": "1", "slug": "a", "title": "A", "summary": "", "score": 0.9},
        {"id": "1", "slug": "a", "title": "A", "summary": "", "score": 0.8},
        {"id": "2", "slug": "b", "title": "B", "summary": "", "score": 0.7},
    ]
    results = parse_search_results(rows)
    assert len(results) == 2
    assert results[0]["slug"] == "a"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker compose run --rm api pytest tests/test_search.py -v
```

Expected: `ImportError` — `app.search` doesn't exist.

- [ ] **Step 3: Create `api/app/search.py`**

```python
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from litellm import aembedding
from app.config import settings

async def embed(text_input: str) -> list[float]:
    resp = await aembedding(model="gemini/text-embedding-004", input=[text_input])
    return resp.data[0]["embedding"]

async def search_pages(
    session: AsyncSession,
    workspace_id: str,
    query: str,
    limit: int = 5
) -> list[dict]:
    query_embedding = await embed(query)
    embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
    sql = text("""
        WITH fts AS (
            SELECT id, slug, title, summary,
                   ts_rank(tsv, plainto_tsquery('english', :query)) AS score
            FROM pages
            WHERE workspace_id = :ws_id
              AND tsv @@ plainto_tsquery('english', :query)
        ),
        vec AS (
            SELECT id, slug, title, summary,
                   1 - (embedding <=> :embedding::vector) AS score
            FROM pages
            WHERE workspace_id = :ws_id
              AND embedding IS NOT NULL
        ),
        combined AS (
            SELECT id, slug, title, summary, score FROM fts
            UNION ALL
            SELECT id, slug, title, summary, score FROM vec
        )
        SELECT id, slug, title, summary, MAX(score) as score
        FROM combined
        GROUP BY id, slug, title, summary
        ORDER BY score DESC
        LIMIT :limit
    """)
    result = await session.execute(sql, {
        "query": query,
        "ws_id": workspace_id,
        "embedding": embedding_str,
        "limit": limit
    })
    return [dict(row._mapping) for row in result]

def parse_search_results(rows: list[dict]) -> list[dict]:
    seen = {}
    for row in rows:
        if row["id"] not in seen or row["score"] > seen[row["id"]]["score"]:
            seen[row["id"]] = row
    return sorted(seen.values(), key=lambda r: r["score"], reverse=True)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker compose run --rm api pytest tests/test_search.py -v
```

Expected: both pass (no DB needed for unit tests).

- [ ] **Step 5: Commit**

```bash
git add api/app/search.py tests/test_search.py
git commit -m "feat: hybrid tsvector + pgvector search"
```

---

## Task 6: Source extractors + S3 storage

**Files:**
- Create: `api/app/extractors/pdf.py`
- Create: `api/app/extractors/docx.py`
- Create: `api/app/extractors/url.py`
- Create: `api/app/storage.py`
- Create: `api/app/routes/ingest.py`
- Create: `tests/test_extractors.py`
- Modify: `api/app/main.py`

- [ ] **Step 1: Write extractor tests**

```python
# tests/test_extractors.py
import pytest
from app.extractors.url import extract_main_content

@pytest.mark.asyncio
async def test_extract_url_returns_text():
    # Use a stable, simple URL
    text = await extract_main_content("https://example.com")
    assert isinstance(text, str)
    assert len(text) > 10
```

- [ ] **Step 2: Create `api/app/extractors/pdf.py`**

```python
import io
from pypdf import PdfReader

def extract_pdf(file_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(file_bytes))
    return "\n\n".join(page.extract_text() or "" for page in reader.pages)
```

- [ ] **Step 3: Create `api/app/extractors/docx.py`**

```python
import io
from docx import Document

def extract_docx(file_bytes: bytes) -> str:
    doc = Document(io.BytesIO(file_bytes))
    return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
```

- [ ] **Step 4: Create `api/app/extractors/url.py`**

```python
import httpx
import trafilatura

async def extract_main_content(url: str) -> str:
    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
    text = trafilatura.extract(resp.text, include_comments=False, include_tables=True)
    return text or resp.text[:8000]
```

- [ ] **Step 5: Create `api/app/storage.py`**

```python
import boto3
from botocore.exceptions import ClientError
from app.config import settings

def _client():
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
    )

def ensure_bucket():
    s3 = _client()
    try:
        s3.head_bucket(Bucket=settings.s3_bucket)
    except ClientError:
        s3.create_bucket(Bucket=settings.s3_bucket)

def upload_file(key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    s3 = _client()
    ensure_bucket()
    s3.put_object(Bucket=settings.s3_bucket, Key=key, Body=data, ContentType=content_type)
    return key
```

- [ ] **Step 6: Create `api/app/routes/ingest.py`**

```python
import asyncio
import uuid
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from app.database import get_db
from app.auth import get_current_user
from app.models import Source, Workspace
from app.storage import upload_file
from app.extractors.pdf import extract_pdf
from app.extractors.docx import extract_docx
from app.extractors.url import extract_main_content
from app.routes.wiki import _ensure_workspace

router = APIRouter(prefix="/ingest", tags=["ingest"])

class URLIngest(BaseModel):
    url: str

class TextIngest(BaseModel):
    text: str
    title: str = "Pasted note"

async def _run_ingest_agent(source_id: str, workspace_id: str):
    # Imported here to avoid circular imports
    from app.agents.ingest_agent import run as run_ingest
    await run_ingest(source_id, workspace_id)

@router.post("/file")
async def ingest_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user)
):
    ws = await _ensure_workspace(db, user)
    data = await file.read()
    suffix = file.filename.rsplit(".", 1)[-1].lower() if file.filename else ""
    if suffix == "pdf":
        kind = "pdf"
        text = extract_pdf(data)
        s3_key = f"{ws.id}/{uuid.uuid4()}.pdf"
        upload_file(s3_key, data, "application/pdf")
    elif suffix in ("docx", "doc"):
        kind = "docx"
        text = extract_docx(data)
        s3_key = f"{ws.id}/{uuid.uuid4()}.docx"
        upload_file(s3_key, data, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    else:
        raise HTTPException(status_code=400, detail="Unsupported file type. Upload PDF or DOCX.")
    source = Source(workspace_id=ws.id, kind=kind, s3_key=s3_key, extracted_text=text[:50000])
    db.add(source)
    await db.commit()
    await db.refresh(source)
    background_tasks.add_task(_run_ingest_agent, source.id, ws.id)
    return {"source_id": source.id, "status": "ingesting"}

@router.post("/url")
async def ingest_url(
    body: URLIngest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user)
):
    ws = await _ensure_workspace(db, user)
    text = await extract_main_content(body.url)
    source = Source(workspace_id=ws.id, kind="url", s3_key=None, extracted_text=text[:50000])
    db.add(source)
    await db.commit()
    await db.refresh(source)
    background_tasks.add_task(_run_ingest_agent, source.id, ws.id)
    return {"source_id": source.id, "status": "ingesting"}

@router.post("/text")
async def ingest_text(
    body: TextIngest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user)
):
    ws = await _ensure_workspace(db, user)
    source = Source(workspace_id=ws.id, kind="text", s3_key=None, extracted_text=body.text[:50000])
    db.add(source)
    await db.commit()
    await db.refresh(source)
    background_tasks.add_task(_run_ingest_agent, source.id, ws.id)
    return {"source_id": source.id, "status": "ingesting"}
```

- [ ] **Step 7: Mount ingest router in `api/app/main.py`**

```python
from app.routes.ingest import router as ingest_router
app.include_router(ingest_router)
```

- [ ] **Step 8: Run extractor tests**

```bash
docker compose run --rm api pytest tests/test_extractors.py -v
```

Expected: URL extraction test passes.

- [ ] **Step 9: Commit**

```bash
git add api/app/extractors/ api/app/storage.py api/app/routes/ingest.py api/app/main.py tests/test_extractors.py
git commit -m "feat: source extractors (pdf/docx/url) + ingest endpoints"
```

---

## Task 7: Shared agent tool surface

**Files:**
- Create: `api/app/agents/tools.py`
- Create: `api/app/sse.py`
- Create: `tests/test_agents.py`

- [ ] **Step 1: Create `api/app/sse.py`** — simple in-process SSE broadcaster

```python
import asyncio
import json
from typing import AsyncIterator

class SSEBroadcaster:
    def __init__(self):
        self._queues: list[asyncio.Queue] = []

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        self._queues.remove(q)

    async def publish(self, event: dict):
        data = json.dumps(event)
        for q in list(self._queues):
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                pass

    async def stream(self, q: asyncio.Queue) -> AsyncIterator[str]:
        try:
            while True:
                data = await asyncio.wait_for(q.get(), timeout=30)
                yield f"data: {data}\n\n"
        except asyncio.TimeoutError:
            yield ": keepalive\n\n"

broadcaster = SSEBroadcaster()
```

- [ ] **Step 2: Write failing agent tool tests**

```python
# tests/test_agents.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.agents.tools import AgentTools

@pytest.mark.asyncio
async def test_list_pages_returns_list():
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)
    tools = AgentTools(session=mock_session, workspace_id="ws-1", broadcaster=None)
    result = await tools.list_pages()
    assert isinstance(result, list)

@pytest.mark.asyncio
async def test_extract_slugs_from_wikilinks():
    from app.wikilinks import extract_slugs
    slugs = extract_slugs("Hello [[page-one]] and [[page-two]].")
    assert "page-one" in slugs
    assert "page-two" in slugs
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
docker compose run --rm api pytest tests/test_agents.py -v
```

Expected: `ImportError` — `app.agents.tools` doesn't exist.

- [ ] **Step 4: Create `api/app/agents/__init__.py`** (empty)

```bash
touch api/app/agents/__init__.py
```

- [ ] **Step 5: Create `api/app/agents/tools.py`**

```python
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models import Page, ActivityLog
from app.search import search_pages as _search
from app.wikilinks import sync_links
from app.sse import SSEBroadcaster
from datetime import datetime

class AgentTools:
    def __init__(self, session: AsyncSession, workspace_id: str, broadcaster: SSEBroadcaster | None):
        self.session = session
        self.workspace_id = workspace_id
        self.broadcaster = broadcaster

    async def _broadcast(self, event: dict):
        if self.broadcaster:
            await self.broadcaster.publish(event)

    async def list_pages(self) -> list[dict]:
        result = await self.session.execute(
            select(Page.slug, Page.title, Page.summary)
            .where(Page.workspace_id == self.workspace_id)
            .order_by(Page.updated_at.desc())
        )
        return [{"slug": r.slug, "title": r.title, "summary": r.summary} for r in result]

    async def search_pages(self, query: str) -> list[dict]:
        return await _search(self.session, self.workspace_id, query, limit=5)

    async def read_page(self, slug: str) -> str:
        await self._broadcast({"event": "agent:reading", "slug": slug})
        result = await self.session.execute(
            select(Page).where(Page.slug == slug, Page.workspace_id == self.workspace_id)
        )
        page = result.scalar_one_or_none()
        return page.body_md if page else f"[Page '{slug}' not found]"

    async def write_page(self, slug: str, body_md: str, summary: str = "") -> str:
        await self._broadcast({"event": "agent:writing", "slug": slug})
        result = await self.session.execute(
            select(Page).where(Page.slug == slug, Page.workspace_id == self.workspace_id)
        )
        page = result.scalar_one_or_none()
        if page:
            from app.models import Revision
            self.session.add(Revision(page_id=page.id, body_md=page.body_md))
            page.body_md = body_md
            page.summary = summary or page.summary
            page.updated_at = datetime.utcnow()
            await sync_links(self.session, page)
            self.session.add(ActivityLog(workspace_id=self.workspace_id, event_type="page_updated", payload={"slug": slug}))
        else:
            page = Page(workspace_id=self.workspace_id, slug=slug,
                        title=slug.replace("-", " ").title(), body_md=body_md, summary=summary)
            self.session.add(page)
            await self.session.flush()
            await sync_links(self.session, page)
            self.session.add(ActivityLog(workspace_id=self.workspace_id, event_type="page_created", payload={"slug": slug}))
        await self.session.commit()
        return f"Page '{slug}' saved."

    async def create_page(self, slug: str, title: str, body_md: str, summary: str = "") -> str:
        return await self.write_page(slug, body_md, summary)

    def as_litellm_tools(self, allowed: list[str] | None = None) -> list[dict]:
        all_tools = [
            {"type": "function", "function": {
                "name": "list_pages",
                "description": "List all pages in the wiki with their slugs, titles, and summaries.",
                "parameters": {"type": "object", "properties": {}, "required": []}
            }},
            {"type": "function", "function": {
                "name": "search_pages",
                "description": "Search wiki pages by query using hybrid full-text + semantic search.",
                "parameters": {"type": "object", "properties": {
                    "query": {"type": "string", "description": "Search query"}
                }, "required": ["query"]}
            }},
            {"type": "function", "function": {
                "name": "read_page",
                "description": "Read the full markdown content of a wiki page by slug.",
                "parameters": {"type": "object", "properties": {
                    "slug": {"type": "string", "description": "Page slug"}
                }, "required": ["slug"]}
            }},
            {"type": "function", "function": {
                "name": "write_page",
                "description": "Create or update a wiki page. Creates if slug doesn't exist, updates if it does.",
                "parameters": {"type": "object", "properties": {
                    "slug": {"type": "string"},
                    "body_md": {"type": "string", "description": "Full markdown content"},
                    "summary": {"type": "string", "description": "One-sentence summary"}
                }, "required": ["slug", "body_md"]}
            }},
            {"type": "function", "function": {
                "name": "create_page",
                "description": "Create a new wiki page.",
                "parameters": {"type": "object", "properties": {
                    "slug": {"type": "string"},
                    "title": {"type": "string"},
                    "body_md": {"type": "string"},
                    "summary": {"type": "string"}
                }, "required": ["slug", "title", "body_md"]}
            }},
        ]
        if allowed:
            return [t for t in all_tools if t["function"]["name"] in allowed]
        return all_tools

    async def dispatch(self, name: str, args: dict) -> str:
        if name == "list_pages":
            pages = await self.list_pages()
            return str(pages)
        elif name == "search_pages":
            results = await self.search_pages(args["query"])
            return str(results)
        elif name == "read_page":
            return await self.read_page(args["slug"])
        elif name in ("write_page", "create_page"):
            return await self.write_page(args["slug"], args["body_md"], args.get("summary", ""))
        return f"Unknown tool: {name}"
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
docker compose run --rm api pytest tests/test_agents.py -v
```

Expected: both pass.

- [ ] **Step 7: Commit**

```bash
git add api/app/agents/ api/app/sse.py tests/test_agents.py
git commit -m "feat: shared agent tool surface + SSE broadcaster"
```

---

## Task 8: Ingest agent

**Files:**
- Create: `api/app/agents/ingest_agent.py`

- [ ] **Step 1: Create `api/app/agents/ingest_agent.py`**

```python
import json
import litellm
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models import Source, ActivityLog
from app.agents.tools import AgentTools
from app.sse import broadcaster
from app.config import settings

SYSTEM_PROMPT = """You are an agent that maintains a personal knowledge wiki.
You have been given a new source document. Your job is to integrate its knowledge into the wiki.

Process:
1. Call list_pages() to see what exists.
2. Call search_pages() to find pages related to the source content.
3. Read the most relevant pages with read_page().
4. Decide: does this content belong in an existing page, or does it need a new page?
   - Update an existing page if the source adds to, refines, or contradicts something already there.
   - Create a new page if the topic has no home yet, or if the content is substantial enough to stand alone.
   - Prefer updating over creating — a wiki with 50 developed pages beats 200 stubs.
5. Write changes using write_page(). You may update multiple pages.
6. When done, stop calling tools.

Write in clear markdown. Use [[wikilinks]] to link related pages. Keep summaries to one sentence."""

COST_CEILING_USD = 2.0

async def run(source_id: str, workspace_id: str):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Source).where(Source.id == source_id))
        source = result.scalar_one_or_none()
        if not source:
            return

        tools = AgentTools(session=session, workspace_id=workspace_id, broadcaster=broadcaster)
        tool_defs = tools.as_litellm_tools()

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"New source to integrate:\n\n{source.extracted_text[:12000]}"}
        ]

        total_cost = 0.0
        pages_touched = []

        for _ in range(20):  # max iterations
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
            messages.append(msg.model_dump(exclude_none=True))

            if not msg.tool_calls:
                break

            for tc in msg.tool_calls:
                name = tc.function.name
                args = json.loads(tc.function.arguments)
                result_str = await tools.dispatch(name, args)
                if name in ("write_page", "create_page") and "slug" in args:
                    pages_touched.append(args["slug"])
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_str
                })

        session.add(ActivityLog(
            workspace_id=workspace_id,
            event_type="source_ingested",
            payload={"source_id": source_id, "pages_touched": pages_touched, "cost_usd": round(total_cost, 4)}
        ))
        await session.commit()
        await broadcaster.publish({"event": "agent:done", "pages_touched": pages_touched})
```

- [ ] **Step 2: Start the full stack and test ingest manually**

```bash
docker compose up -d
# Wait for healthy, then:
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","password":"changeme"}' \
  | jq .
# Copy the token, then:
curl -X POST http://localhost:8000/ingest/text \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"text": "The LLM Wiki is a personal second brain that ingests sources and maintains a structured wiki. It uses whole-page navigation instead of chunked RAG.", "title": "About LLM Wiki"}'
# Check activity log after ~10 seconds:
curl http://localhost:8000/wiki/pages -H "Authorization: Bearer <token>" | jq .
```

Expected: one or more pages created in the wiki.

- [ ] **Step 3: Commit**

```bash
git add api/app/agents/ingest_agent.py
git commit -m "feat: ingest agent with cost ceiling"
```

---

## Task 9: Query agent + chat endpoints

**Files:**
- Create: `api/app/agents/query_agent.py`
- Create: `api/app/routes/chat.py`
- Create: `api/app/routes/activity.py`
- Modify: `api/app/main.py`

- [ ] **Step 1: Create `api/app/agents/query_agent.py`**

```python
import json
import litellm
from app.agents.tools import AgentTools
from app.sse import broadcaster
from app.config import settings

SYSTEM_PROMPT = """You are a knowledgeable assistant with access to the user's personal wiki.
When answering questions:
1. Use search_pages() to find relevant pages.
2. Use read_page() to read up to 5 of the most relevant pages in full.
3. Answer based on what you find. Cite pages by their slug in your answer like [[slug]].
4. If the wiki doesn't contain the answer, say so clearly.
You may only read pages — do not write or create anything."""

READ_ONLY_TOOLS = ["list_pages", "search_pages", "read_page"]

async def run(
    workspace_id: str,
    question: str,
    history: list[dict],
    session,
) -> tuple[str, list[str]]:
    tools = AgentTools(session=session, workspace_id=workspace_id, broadcaster=broadcaster)
    tool_defs = tools.as_litellm_tools(allowed=READ_ONLY_TOOLS)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *history[-10:],  # last 10 messages for context
        {"role": "user", "content": question}
    ]

    cited_pages = []

    for _ in range(10):
        resp = await litellm.acompletion(
            model=settings.litellm_model,
            messages=messages,
            tools=tool_defs,
            tool_choice="auto",
        )
        msg = resp.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))

        if not msg.tool_calls:
            answer = msg.content or ""
            import re
            cited_pages = re.findall(r"\[\[([^\]]+)\]\]", answer)
            await broadcaster.publish({"event": "agent:done", "pages_touched": cited_pages})
            return answer, cited_pages

        for tc in msg.tool_calls:
            name = tc.function.name
            args = json.loads(tc.function.arguments)
            result_str = await tools.dispatch(name, args)
            if name == "read_page":
                cited_pages.append(args.get("slug", ""))
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result_str
            })

    return "I wasn't able to find a good answer in your wiki.", []
```

- [ ] **Step 2: Create `api/app/routes/chat.py`**

```python
from fastapi import APIRouter, Depends, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from app.database import get_db
from app.auth import get_current_user
from app.models import ChatSession, ChatMessage, ActivityLog
from app.routes.wiki import _ensure_workspace
from app.agents.query_agent import run as run_query
from app.sse import broadcaster
import json

router = APIRouter(prefix="/chat", tags=["chat"])

class MessageRequest(BaseModel):
    message: str
    session_id: str | None = None

@router.post("/message")
async def send_message(
    body: MessageRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user)
):
    ws = await _ensure_workspace(db, user)

    # Get or create session
    if body.session_id:
        result = await db.execute(select(ChatSession).where(ChatSession.id == body.session_id))
        session_obj = result.scalar_one_or_none()
    else:
        session_obj = None

    if not session_obj:
        session_obj = ChatSession(workspace_id=ws.id)
        db.add(session_obj)
        await db.flush()

    # Save user message
    user_msg = ChatMessage(session_id=session_obj.id, role="user", content=body.message)
    db.add(user_msg)
    await db.commit()

    # Load history
    history_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_obj.id)
        .order_by(ChatMessage.created_at)
    )
    history = [{"role": m.role, "content": m.content} for m in history_result.scalars()]

    # Run query agent
    answer, cited = await run_query(ws.id, body.message, history[:-1], db)

    # Save assistant message
    assistant_msg = ChatMessage(session_id=session_obj.id, role="assistant", content=answer)
    db.add(assistant_msg)
    db.add(ActivityLog(workspace_id=ws.id, event_type="chat_message", payload={"session_id": session_obj.id}))
    await db.commit()

    # Trigger chat monitor in background
    background_tasks.add_task(_run_chat_monitor, session_obj.id, ws.id)

    return {
        "session_id": session_obj.id,
        "answer": answer,
        "cited_pages": cited
    }

@router.get("/sessions/{session_id}/messages")
async def get_messages(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user)
):
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
    )
    return [{"role": m.role, "content": m.content, "id": m.id} for m in result.scalars()]

@router.get("/sse")
async def sse_stream(user: str = Depends(get_current_user)):
    q = broadcaster.subscribe()
    async def event_gen():
        try:
            async for chunk in broadcaster.stream(q):
                yield chunk
        finally:
            broadcaster.unsubscribe(q)
    return StreamingResponse(event_gen(), media_type="text/event-stream",
                              headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

async def _run_chat_monitor(session_id: str, workspace_id: str):
    from app.agents.chat_monitor import run as run_monitor
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        await run_monitor(session_id, workspace_id, session)
```

- [ ] **Step 3: Create `api/app/routes/activity.py`**

```python
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.auth import get_current_user
from app.models import ActivityLog
from app.routes.wiki import _ensure_workspace

router = APIRouter(prefix="/activity", tags=["activity"])

@router.get("/")
async def get_activity(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user)
):
    ws = await _ensure_workspace(db, user)
    result = await db.execute(
        select(ActivityLog)
        .where(ActivityLog.workspace_id == ws.id)
        .order_by(ActivityLog.created_at.desc())
        .limit(limit)
    )
    logs = result.scalars().all()
    return [{"id": l.id, "event_type": l.event_type, "payload": l.payload, "created_at": l.created_at} for l in logs]
```

- [ ] **Step 4: Mount new routers in `api/app/main.py`**

```python
from app.routes.chat import router as chat_router
from app.routes.activity import router as activity_router
app.include_router(chat_router)
app.include_router(activity_router)
```

- [ ] **Step 5: Test chat endpoint manually**

```bash
curl -X POST http://localhost:8000/chat/message \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"message": "What is the LLM Wiki?"}'
```

Expected: JSON response with `answer`, `session_id`, and `cited_pages`.

- [ ] **Step 6: Commit**

```bash
git add api/app/agents/query_agent.py api/app/routes/chat.py api/app/routes/activity.py api/app/main.py
git commit -m "feat: query agent + chat endpoints + SSE stream + activity log"
```

---

## Task 10: Chat monitor agent

**Files:**
- Create: `api/app/agents/chat_monitor.py`

- [ ] **Step 1: Create `api/app/agents/chat_monitor.py`**

```python
import json
import litellm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models import ChatMessage, ActivityLog
from app.agents.tools import AgentTools
from app.sse import broadcaster
from app.config import settings

SYSTEM_PROMPT = """You are a background agent that reads chat transcripts and decides what to save to the user's wiki.

Review the conversation and identify anything worth retaining permanently:
- Decisions made ("I decided to...", "We agreed that...")
- Facts learned or confirmed
- Ideas worth developing
- Commitments or plans
- Insights or realisations

Do NOT ingest casual back-and-forth, clarifying questions, or content already well-covered in the wiki.

If you find something worth saving:
1. Use search_pages() to check if it already exists.
2. Use write_page() to add it to an existing page, or create a new one.

If nothing in the conversation is worth saving, do nothing."""

async def run(session_id: str, workspace_id: str, session: AsyncSession):
    result = await session.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
    )
    messages = result.scalars().all()
    if not messages:
        return

    transcript = "\n".join(f"{m.role.upper()}: {m.content}" for m in messages)

    tools_obj = AgentTools(session=session, workspace_id=workspace_id, broadcaster=broadcaster)
    tool_defs = tools_obj.as_litellm_tools()

    llm_messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Chat transcript to review:\n\n{transcript[:8000]}"}
    ]

    pages_saved = []

    for _ in range(10):
        resp = await litellm.acompletion(
            model=settings.litellm_model,
            messages=llm_messages,
            tools=tool_defs,
            tool_choice="auto",
        )
        msg = resp.choices[0].message
        llm_messages.append(msg.model_dump(exclude_none=True))

        if not msg.tool_calls:
            break

        for tc in msg.tool_calls:
            name = tc.function.name
            args = json.loads(tc.function.arguments)
            result_str = await tools_obj.dispatch(name, args)
            if name in ("write_page", "create_page"):
                pages_saved.append(args.get("slug", ""))
            llm_messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result_str
            })

    if pages_saved:
        session.add(ActivityLog(
            workspace_id=workspace_id,
            event_type="chat_ingested",
            payload={"session_id": session_id, "pages_saved": pages_saved}
        ))
        await session.commit()
```

- [ ] **Step 2: Commit**

```bash
git add api/app/agents/chat_monitor.py
git commit -m "feat: chat monitor agent — auto-ingests noteworthy chat content"
```

---

## Task 11: Frontend skeleton

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/api/client.ts`

- [ ] **Step 1: Create `frontend/package.json`**

```json
{
  "name": "llm-wiki-frontend",
  "version": "0.1.0",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "@tanstack/react-query": "^5.56.2",
    "react-markdown": "^9.0.1",
    "remark-gfm": "^4.0.0",
    "@codemirror/view": "^6.0.0",
    "@codemirror/lang-markdown": "^6.0.0",
    "@uiw/react-codemirror": "^4.23.0"
  },
  "devDependencies": {
    "@types/react": "^18.3.5",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "typescript": "^5.5.3",
    "vite": "^5.4.2"
  }
}
```

- [ ] **Step 2: Create `frontend/vite.config.ts`**

```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': { target: 'http://api:8000', rewrite: (p) => p.replace(/^\/api/, '') }
    }
  }
})
```

- [ ] **Step 3: Create `frontend/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true
  },
  "include": ["src"]
}
```

- [ ] **Step 4: Create `frontend/index.html`**

```html
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>LLM Wiki</title>
    <style>
      *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
      body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
             background: #0d1117; color: #e6edf3; height: 100vh; overflow: hidden; }
      #root { height: 100vh; display: flex; flex-direction: column; }
    </style>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 5: Create `frontend/src/api/client.ts`**

```typescript
const BASE = '/api'

function token() {
  return localStorage.getItem('token') || ''
}

function headers(extra: Record<string, string> = {}) {
  return { 'Content-Type': 'application/json', Authorization: `Bearer ${token()}`, ...extra }
}

export async function login(email: string, password: string) {
  const r = await fetch(`${BASE}/auth/login`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password })
  })
  if (!r.ok) throw new Error('Login failed')
  const data = await r.json()
  localStorage.setItem('token', data.access_token)
  return data
}

export async function listPages() {
  const r = await fetch(`${BASE}/wiki/pages`, { headers: headers() })
  return r.json()
}

export async function getPage(slug: string) {
  const r = await fetch(`${BASE}/wiki/pages/${slug}`, { headers: headers() })
  if (r.status === 404) return null
  return r.json()
}

export async function updatePage(slug: string, body: { title?: string; body_md?: string; summary?: string }) {
  const r = await fetch(`${BASE}/wiki/pages/${slug}`, {
    method: 'PUT', headers: headers(), body: JSON.stringify(body)
  })
  return r.json()
}

export async function sendMessage(message: string, sessionId?: string) {
  const r = await fetch(`${BASE}/chat/message`, {
    method: 'POST', headers: headers(),
    body: JSON.stringify({ message, session_id: sessionId })
  })
  return r.json()
}

export async function ingestText(text: string, title?: string) {
  const r = await fetch(`${BASE}/ingest/text`, {
    method: 'POST', headers: headers(), body: JSON.stringify({ text, title })
  })
  return r.json()
}

export async function ingestUrl(url: string) {
  const r = await fetch(`${BASE}/ingest/url`, {
    method: 'POST', headers: headers(), body: JSON.stringify({ url })
  })
  return r.json()
}

export async function ingestFile(file: File) {
  const fd = new FormData()
  fd.append('file', file)
  const r = await fetch(`${BASE}/ingest/file`, {
    method: 'POST', headers: { Authorization: `Bearer ${token()}` }, body: fd
  })
  return r.json()
}

export async function getActivity(limit = 50) {
  const r = await fetch(`${BASE}/activity/?limit=${limit}`, { headers: headers() })
  return r.json()
}

export function createSSE(onEvent: (data: unknown) => void): () => void {
  const es = new EventSource(`${BASE}/chat/sse?token=${token()}`)
  es.onmessage = (e) => { try { onEvent(JSON.parse(e.data)) } catch {} }
  return () => es.close()
}
```

- [ ] **Step 6: Create `frontend/src/main.tsx`**

```typescript
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App'

const queryClient = new QueryClient()
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>
)
```

- [ ] **Step 7: Create placeholder `frontend/src/App.tsx`** (will be replaced in next task)

```typescript
import { useState } from 'react'
import { login } from './api/client'

export default function App() {
  const [authed, setAuthed] = useState(!!localStorage.getItem('token'))
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')

  if (!authed) return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh' }}>
      <div style={{ background: '#161b22', padding: 32, borderRadius: 12, width: 320, border: '1px solid #30363d' }}>
        <h2 style={{ marginBottom: 24, color: '#e6edf3' }}>LLM Wiki</h2>
        <input value={email} onChange={e => setEmail(e.target.value)}
          placeholder="Email" style={inputStyle} />
        <input value={password} onChange={e => setPassword(e.target.value)}
          placeholder="Password" type="password" style={inputStyle} />
        <button onClick={() => login(email, password).then(() => setAuthed(true))}
          style={btnStyle}>Login</button>
      </div>
    </div>
  )

  return <div style={{ padding: 24 }}>Logged in — UI coming next.</div>
}

const inputStyle = { width: '100%', marginBottom: 12, padding: '8px 12px', background: '#0d1117',
  border: '1px solid #30363d', borderRadius: 6, color: '#e6edf3', fontSize: 14, display: 'block' }
const btnStyle = { width: '100%', padding: '10px 0', background: '#238636', border: 'none',
  borderRadius: 6, color: '#fff', fontSize: 14, cursor: 'pointer' }
```

- [ ] **Step 8: Build and verify frontend starts**

```bash
docker compose up frontend --build
```

Open http://localhost:5173 — you should see the login form.

- [ ] **Step 9: Commit**

```bash
git add frontend/
git commit -m "feat: react frontend skeleton with login + API client"
```

---

## Task 12: Split-view layout + wiki panel

**Files:**
- Create: `frontend/src/components/Layout.tsx`
- Create: `frontend/src/components/WikiPanel.tsx`
- Create: `frontend/src/hooks/useWiki.ts`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Create `frontend/src/hooks/useWiki.ts`**

```typescript
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { listPages, getPage, updatePage } from '../api/client'

export function usePages() {
  return useQuery({ queryKey: ['pages'], queryFn: listPages, refetchInterval: 10000 })
}

export function usePage(slug: string | null) {
  return useQuery({ queryKey: ['page', slug], queryFn: () => getPage(slug!), enabled: !!slug })
}

export function useUpdatePage() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ slug, ...body }: { slug: string; title?: string; body_md?: string }) =>
      updatePage(slug, body),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ['pages'] })
      qc.invalidateQueries({ queryKey: ['page', vars.slug] })
    }
  })
}
```

- [ ] **Step 2: Create `frontend/src/components/WikiPanel.tsx`**

```typescript
import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { usePages, usePage, useUpdatePage } from '../hooks/useWiki'

interface Props {
  highlightedSlug: string | null
}

export default function WikiPanel({ highlightedSlug }: Props) {
  const { data: pages = [] } = usePages()
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [editBody, setEditBody] = useState('')
  const { data: page } = usePage(selectedSlug)
  const updatePage = useUpdatePage()

  function startEdit() {
    setEditBody(page?.body_md || '')
    setEditing(true)
  }

  function saveEdit() {
    if (!selectedSlug) return
    updatePage.mutate({ slug: selectedSlug, body_md: editBody })
    setEditing(false)
  }

  return (
    <div style={{ display: 'flex', height: '100%', borderRight: '1px solid #30363d' }}>
      {/* Sidebar */}
      <div style={{ width: 220, overflowY: 'auto', background: '#161b22', padding: '12px 0' }}>
        <div style={{ padding: '0 16px 12px', fontSize: 11, color: '#8b949e', textTransform: 'uppercase', letterSpacing: 1 }}>
          Pages
        </div>
        {pages.map((p: { slug: string; title: string }) => (
          <div key={p.slug} onClick={() => { setSelectedSlug(p.slug); setEditing(false) }}
            style={{
              padding: '6px 16px', cursor: 'pointer', fontSize: 13,
              color: selectedSlug === p.slug ? '#e6edf3' : '#8b949e',
              background: selectedSlug === p.slug ? '#21262d' : 'transparent',
              borderLeft: highlightedSlug === p.slug ? '2px solid #58a6ff' : '2px solid transparent',
              transition: 'all 0.15s'
            }}>
            {p.title}
          </div>
        ))}
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflowY: 'auto', padding: 24 }}>
        {page ? (
          <>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <h1 style={{ fontSize: 20, color: '#e6edf3' }}>{page.title}</h1>
              <button onClick={editing ? saveEdit : startEdit}
                style={{ padding: '4px 14px', background: editing ? '#238636' : '#21262d',
                  border: '1px solid #30363d', borderRadius: 6, color: '#e6edf3', cursor: 'pointer', fontSize: 13 }}>
                {editing ? 'Save' : 'Edit'}
              </button>
            </div>
            {editing ? (
              <textarea value={editBody} onChange={e => setEditBody(e.target.value)}
                style={{ width: '100%', minHeight: 400, background: '#0d1117', border: '1px solid #30363d',
                  borderRadius: 6, color: '#e6edf3', padding: 16, fontFamily: 'monospace', fontSize: 13,
                  resize: 'vertical' }} />
            ) : (
              <div style={{ lineHeight: 1.7, fontSize: 14 }}>
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{page.body_md}</ReactMarkdown>
              </div>
            )}
          </>
        ) : (
          <div style={{ color: '#8b949e', marginTop: 40, textAlign: 'center' }}>
            Select a page to read it, or ingest your first source.
          </div>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Create `frontend/src/components/Layout.tsx`**

```typescript
import { useState, useEffect, useRef } from 'react'
import WikiPanel from './WikiPanel'
import ChatPanel from './ChatPanel'
import IngestModal from './IngestModal'
import ActivityLog from './ActivityLog'
import { createSSE } from '../api/client'
import { useQueryClient } from '@tanstack/react-query'

export default function Layout() {
  const [highlightedSlug, setHighlightedSlug] = useState<string | null>(null)
  const [agentStatus, setAgentStatus] = useState<string | null>(null)
  const [showActivity, setShowActivity] = useState(false)
  const [showIngest, setShowIngest] = useState(false)
  const qc = useQueryClient()

  useEffect(() => {
    const unsub = createSSE((data: unknown) => {
      const event = data as { event: string; slug?: string; pages_touched?: string[] }
      if (event.event === 'agent:reading') {
        setHighlightedSlug(event.slug || null)
        setAgentStatus(`Reading ${event.slug}…`)
      } else if (event.event === 'agent:writing') {
        setHighlightedSlug(event.slug || null)
        setAgentStatus(`Writing ${event.slug}…`)
      } else if (event.event === 'agent:done') {
        setHighlightedSlug(null)
        setAgentStatus(null)
        qc.invalidateQueries({ queryKey: ['pages'] })
        qc.invalidateQueries({ queryKey: ['activity'] })
      }
    })
    return unsub
  }, [qc])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
      {/* Topbar */}
      <div style={{ display: 'flex', alignItems: 'center', padding: '8px 16px',
        background: '#161b22', borderBottom: '1px solid #30363d', gap: 12, flexShrink: 0 }}>
        <span style={{ fontWeight: 600, fontSize: 15, color: '#e6edf3' }}>LLM Wiki</span>
        {agentStatus && (
          <span style={{ fontSize: 12, color: '#58a6ff', marginLeft: 8 }}>⟳ {agentStatus}</span>
        )}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
          <button onClick={() => setShowIngest(true)} style={topBtnStyle}>+ Ingest</button>
          <button onClick={() => setShowActivity(!showActivity)} style={topBtnStyle}>Activity</button>
        </div>
      </div>

      {/* Main split view */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <div style={{ flex: 1, overflow: 'hidden' }}>
          <WikiPanel highlightedSlug={highlightedSlug} />
        </div>
        <div style={{ width: 380, flexShrink: 0, overflow: 'hidden' }}>
          <ChatPanel />
        </div>
      </div>

      {showActivity && <ActivityLog onClose={() => setShowActivity(false)} />}
      {showIngest && <IngestModal onClose={() => setShowIngest(false)} />}
    </div>
  )
}

const topBtnStyle: React.CSSProperties = {
  padding: '4px 12px', background: '#21262d', border: '1px solid #30363d',
  borderRadius: 6, color: '#e6edf3', cursor: 'pointer', fontSize: 13
}
```

- [ ] **Step 4: Update `frontend/src/App.tsx`** to use Layout when authed

```typescript
import { useState } from 'react'
import { login } from './api/client'
import Layout from './components/Layout'

export default function App() {
  const [authed, setAuthed] = useState(!!localStorage.getItem('token'))
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')

  if (!authed) return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh' }}>
      <div style={{ background: '#161b22', padding: 32, borderRadius: 12, width: 320, border: '1px solid #30363d' }}>
        <h2 style={{ marginBottom: 24, color: '#e6edf3' }}>LLM Wiki</h2>
        <input value={email} onChange={e => setEmail(e.target.value)}
          placeholder="Email" style={inputStyle} />
        <input value={password} onChange={e => setPassword(e.target.value)}
          placeholder="Password" type="password" style={inputStyle} />
        <button onClick={() => login(email, password).then(() => setAuthed(true))}
          style={btnStyle}>Login</button>
      </div>
    </div>
  )

  return <Layout />
}

const inputStyle: React.CSSProperties = { width: '100%', marginBottom: 12, padding: '8px 12px',
  background: '#0d1117', border: '1px solid #30363d', borderRadius: 6, color: '#e6edf3',
  fontSize: 14, display: 'block' }
const btnStyle: React.CSSProperties = { width: '100%', padding: '10px 0', background: '#238636',
  border: 'none', borderRadius: 6, color: '#fff', fontSize: 14, cursor: 'pointer' }
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/
git commit -m "feat: split-view layout + wiki panel with live agent highlights"
```

---

## Task 13: Chat panel + ingest modal + activity log

**Files:**
- Create: `frontend/src/components/ChatPanel.tsx`
- Create: `frontend/src/components/IngestModal.tsx`
- Create: `frontend/src/components/ActivityLog.tsx`

- [ ] **Step 1: Create `frontend/src/components/ChatPanel.tsx`**

```typescript
import { useState, useRef, useEffect } from 'react'
import { sendMessage } from '../api/client'

interface Message { role: 'user' | 'assistant'; content: string; cited?: string[] }

export default function ChatPanel() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [sessionId, setSessionId] = useState<string | undefined>()
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  async function submit() {
    if (!input.trim() || loading) return
    const text = input.trim()
    setInput('')
    setMessages(m => [...m, { role: 'user', content: text }])
    setLoading(true)
    try {
      const resp = await sendMessage(text, sessionId)
      setSessionId(resp.session_id)
      setMessages(m => [...m, { role: 'assistant', content: resp.answer, cited: resp.cited_pages }])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: '#0d1117',
      borderLeft: '1px solid #30363d' }}>
      <div style={{ padding: '12px 16px', borderBottom: '1px solid #30363d', fontSize: 13,
        color: '#8b949e', background: '#161b22' }}>
        Chat
      </div>
      <div style={{ flex: 1, overflowY: 'auto', padding: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
        {messages.length === 0 && (
          <div style={{ color: '#8b949e', fontSize: 13, textAlign: 'center', marginTop: 40 }}>
            Ask anything — the agent will search your wiki.
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} style={{ maxWidth: '90%', alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start' }}>
            <div style={{
              padding: '8px 12px', borderRadius: 8, fontSize: 13, lineHeight: 1.6,
              background: m.role === 'user' ? '#1f6feb' : '#161b22',
              color: '#e6edf3', border: m.role === 'assistant' ? '1px solid #30363d' : 'none'
            }}>
              {m.content}
            </div>
            {m.cited && m.cited.length > 0 && (
              <div style={{ fontSize: 11, color: '#8b949e', marginTop: 4, paddingLeft: 4 }}>
                Sources: {m.cited.join(', ')}
              </div>
            )}
          </div>
        ))}
        {loading && (
          <div style={{ color: '#8b949e', fontSize: 13, alignSelf: 'flex-start' }}>Thinking…</div>
        )}
        <div ref={bottomRef} />
      </div>
      <div style={{ padding: 12, borderTop: '1px solid #30363d', display: 'flex', gap: 8 }}>
        <input value={input} onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && !e.shiftKey && submit()}
          placeholder="Ask your wiki..." style={{
            flex: 1, padding: '8px 12px', background: '#161b22', border: '1px solid #30363d',
            borderRadius: 6, color: '#e6edf3', fontSize: 13
          }} />
        <button onClick={submit} disabled={loading} style={{
          padding: '8px 16px', background: '#238636', border: 'none', borderRadius: 6,
          color: '#fff', cursor: loading ? 'not-allowed' : 'pointer', fontSize: 13
        }}>Send</button>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Create `frontend/src/components/IngestModal.tsx`**

```typescript
import { useState } from 'react'
import { ingestText, ingestUrl, ingestFile } from '../api/client'
import { useQueryClient } from '@tanstack/react-query'

export default function IngestModal({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<'text' | 'url' | 'file'>('text')
  const [text, setText] = useState('')
  const [url, setUrl] = useState('')
  const [status, setStatus] = useState('')
  const qc = useQueryClient()

  async function submit() {
    setStatus('Ingesting…')
    try {
      if (tab === 'text') await ingestText(text)
      else if (tab === 'url') await ingestUrl(url)
      setStatus('Ingested! Agent is updating your wiki.')
      qc.invalidateQueries({ queryKey: ['activity'] })
      setTimeout(onClose, 1500)
    } catch {
      setStatus('Failed — check the console.')
    }
  }

  async function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setStatus('Uploading…')
    await ingestFile(file)
    setStatus('Uploaded! Agent is processing.')
    qc.invalidateQueries({ queryKey: ['activity'] })
    setTimeout(onClose, 1500)
  }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', display: 'flex',
      alignItems: 'center', justifyContent: 'center', zIndex: 100 }}
      onClick={e => e.target === e.currentTarget && onClose()}>
      <div style={{ background: '#161b22', border: '1px solid #30363d', borderRadius: 12,
        padding: 24, width: 480, maxWidth: '90vw' }}>
        <h3 style={{ marginBottom: 16, color: '#e6edf3' }}>Ingest</h3>
        <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
          {(['text', 'url', 'file'] as const).map(t => (
            <button key={t} onClick={() => setTab(t)} style={{
              padding: '4px 14px', background: tab === t ? '#238636' : '#21262d',
              border: '1px solid #30363d', borderRadius: 6, color: '#e6edf3', cursor: 'pointer', fontSize: 13
            }}>{t}</button>
          ))}
        </div>
        {tab === 'text' && (
          <textarea value={text} onChange={e => setText(e.target.value)}
            placeholder="Paste any text, note, or idea…" rows={6}
            style={{ width: '100%', padding: 12, background: '#0d1117', border: '1px solid #30363d',
              borderRadius: 6, color: '#e6edf3', fontSize: 13, resize: 'vertical' }} />
        )}
        {tab === 'url' && (
          <input value={url} onChange={e => setUrl(e.target.value)} placeholder="https://…"
            style={{ width: '100%', padding: '8px 12px', background: '#0d1117', border: '1px solid #30363d',
              borderRadius: 6, color: '#e6edf3', fontSize: 13 }} />
        )}
        {tab === 'file' && (
          <input type="file" accept=".pdf,.docx" onChange={handleFile}
            style={{ color: '#e6edf3', fontSize: 13 }} />
        )}
        {status && <div style={{ marginTop: 12, fontSize: 13, color: '#58a6ff' }}>{status}</div>}
        {tab !== 'file' && (
          <button onClick={submit} style={{ marginTop: 16, width: '100%', padding: '10px 0',
            background: '#238636', border: 'none', borderRadius: 6, color: '#fff', cursor: 'pointer', fontSize: 14 }}>
            Ingest
          </button>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Create `frontend/src/components/ActivityLog.tsx`**

```typescript
import { useQuery } from '@tanstack/react-query'
import { getActivity } from '../api/client'

const labels: Record<string, string> = {
  page_created: 'Page created',
  page_updated: 'Page updated',
  source_ingested: 'Source ingested',
  chat_ingested: 'Saved from chat',
  chat_message: 'Chat message',
}

export default function ActivityLog({ onClose }: { onClose: () => void }) {
  const { data: events = [] } = useQuery({ queryKey: ['activity'], queryFn: getActivity, refetchInterval: 5000 })

  return (
    <div style={{ position: 'fixed', right: 0, top: 0, bottom: 0, width: 360, background: '#161b22',
      borderLeft: '1px solid #30363d', zIndex: 50, display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '12px 16px', borderBottom: '1px solid #30363d' }}>
        <span style={{ fontWeight: 600, fontSize: 14, color: '#e6edf3' }}>Activity</span>
        <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#8b949e',
          cursor: 'pointer', fontSize: 18 }}>×</button>
      </div>
      <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
        {events.map((e: { id: string; event_type: string; payload: Record<string, unknown>; created_at: string }) => (
          <div key={e.id} style={{ marginBottom: 12, padding: '8px 12px', background: '#0d1117',
            borderRadius: 6, border: '1px solid #21262d' }}>
            <div style={{ fontSize: 12, color: '#3fb950', marginBottom: 4 }}>
              {labels[e.event_type] || e.event_type}
            </div>
            <div style={{ fontSize: 11, color: '#8b949e' }}>
              {e.payload.slug ? `[[${e.payload.slug}]]` : ''}
              {e.payload.pages_touched ? ` → ${(e.payload.pages_touched as string[]).join(', ')}` : ''}
            </div>
            <div style={{ fontSize: 10, color: '#484f58', marginTop: 4 }}>
              {new Date(e.created_at).toLocaleString()}
            </div>
          </div>
        ))}
        {events.length === 0 && (
          <div style={{ color: '#8b949e', fontSize: 13, textAlign: 'center', marginTop: 40 }}>
            No activity yet. Ingest something!
          </div>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Verify full stack works end-to-end**

```bash
docker compose up
```

1. Open http://localhost:5173
2. Login
3. Click "Ingest" → paste any text → click Ingest
4. Watch the wiki panel — pages should appear within 15–30 seconds
5. Type a question in chat — agent should answer with cited pages

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/
git commit -m "feat: chat panel + ingest modal + activity log drawer"
```

---

## Task 14: SSE auth + cost ceiling

**Files:**
- Modify: `api/app/routes/chat.py` (SSE auth via query param)
- Modify: `api/app/agents/ingest_agent.py` (already has ceiling — verify)

The SSE endpoint currently uses `Depends(get_current_user)` which reads from the `Authorization` header. `EventSource` in the browser can't set headers, so we need to accept the token as a query param for the SSE route only.

- [ ] **Step 1: Update SSE route in `api/app/routes/chat.py`**

```python
from fastapi import Query
from jose import jwt, JWTError
from app.config import settings

@router.get("/sse")
async def sse_stream(token: str = Query(...)):
    # Validate token from query param (EventSource can't set headers)
    try:
        jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except JWTError:
        from fastapi.responses import Response
        return Response(status_code=401)
    q = broadcaster.subscribe()
    async def event_gen():
        try:
            async for chunk in broadcaster.stream(q):
                yield chunk
        finally:
            broadcaster.unsubscribe(q)
    return StreamingResponse(event_gen(), media_type="text/event-stream",
                              headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
```

- [ ] **Step 2: Verify cost ceiling is in place in `api/app/agents/ingest_agent.py`**

The `COST_CEILING_USD = 2.0` constant and the `if total_cost > COST_CEILING_USD: break` check should already be there from Task 8. Confirm it is. No change needed if so.

- [ ] **Step 3: Commit**

```bash
git add api/app/routes/chat.py
git commit -m "fix: SSE auth via query param (EventSource can't set headers)"
```

---

## Task 15: Production compose + final wiring

**Files:**
- Create: `docker-compose.prod.yml`
- Create: `api/Dockerfile.prod`
- Create: `frontend/nginx.conf`
- Create: `frontend/Dockerfile.prod`

- [ ] **Step 1: Create `api/Dockerfile.prod`**

```dockerfile
FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y gcc libpq-dev && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn
COPY . .
CMD ["gunicorn", "app.main:app", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000"]
```

- [ ] **Step 2: Create `frontend/nginx.conf`**

```nginx
server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;
    location /api/ {
        proxy_pass http://api:8000/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection '';
        proxy_buffering off;
    }
    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

- [ ] **Step 3: Create `frontend/Dockerfile.prod`**

```dockerfile
FROM node:22-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
```

- [ ] **Step 4: Create `docker-compose.prod.yml`**

```yaml
version: "3.9"
services:
  db:
    image: pgvector/pgvector:pg16
    env_file: .env
    volumes:
      - pgdata:/var/lib/postgresql/data
    restart: unless-stopped

  api:
    build:
      context: ./api
      dockerfile: Dockerfile.prod
    depends_on: [db]
    env_file: .env
    restart: unless-stopped

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile.prod
    depends_on: [api]
    ports:
      - "80:80"
    restart: unless-stopped

volumes:
  pgdata:
```

- [ ] **Step 5: Test prod build locally**

```bash
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up
```

Open http://localhost:80 — should show the full app with no Vite dev server.

- [ ] **Step 6: Final commit**

```bash
git add api/Dockerfile.prod frontend/nginx.conf frontend/Dockerfile.prod docker-compose.prod.yml
git commit -m "feat: production docker compose with gunicorn + nginx"
```

---

## Self-review checklist

**Spec coverage:**
- [x] Ingest: PDF, Word, text, URL — Tasks 6, 8
- [x] Wiki CRUD + [[wikilinks]] — Tasks 4, 7
- [x] Hybrid search — Task 5
- [x] Chat interface — Tasks 9, 13
- [x] Background chat monitor — Task 10
- [x] Activity log — Task 9, 13
- [x] Agent transparency via SSE — Tasks 7, 12
- [x] Docker Compose stack — Tasks 1, 15
- [x] Auth (single user JWT) — Task 3
- [x] S3/MinIO storage — Task 6
- [x] Cost ceiling — Task 8
- [x] LiteLLM abstraction (no vendor lock-in) — Tasks 8, 9, 10

**No placeholders:** confirmed — all steps have actual code or commands.

**Type consistency:**
- `AgentTools.dispatch()` matches all tool names defined in `as_litellm_tools()`
- `_ensure_workspace()` used consistently across routes
- `broadcaster` imported from `app.sse` in all agents
