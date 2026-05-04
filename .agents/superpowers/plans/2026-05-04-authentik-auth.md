# Authentik Auth Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace hardcoded single-user JWT auth with Authentik OIDC — HttpOnly cookies, refresh tokens, PKCE — across two repos: `auth-config` (Authentik stack) and `Second-Brain` (app changes).

**Architecture:** Authentik runs as an independent Docker Compose stack in the `auth-config` repo, exposed via a second Cloudflare tunnel at `auth.smoothstudy.ai`. The Second Brain FastAPI backend validates access tokens from HttpOnly cookies using Authentik's public JWKS keys (cached). The React frontend never touches raw tokens — it calls `/api/auth/me` on boot to determine auth state.

**Tech Stack:** Python `authlib` (JWKS + RS256 validation), FastAPI cookies, React + Web Crypto API (PKCE), Authentik `ghcr.io/goauthentik/server:2026.2.2`, Cloudflare Tunnel.

---

## File Map

### auth-config repo (`~/Documents/auth-config/`)
| Action | File | Purpose |
|---|---|---|
| Create | `docker-compose.yml` | Authentik stack: db, server, worker, cloudflared |
| Create | `.env.example` | Required secrets template |
| Create | `.gitignore` | Ignore `.env` |

### Second Brain repo (`~/Documents/Second-Brain/`)
| Action | File | Purpose |
|---|---|---|
| Modify | `tests/conftest.py` | Replace old auth env vars with Authentik env vars |
| Modify | `api/app/config.py` | Remove old auth fields, add Authentik fields |
| Rewrite | `api/app/auth.py` | JWKS validation, cookie auth, OIDC endpoints |
| Rewrite | `tests/test_auth.py` | Full test suite for new auth endpoints |
| Modify | `api/app/main.py` | CORS: add smoothstudy.ai, allow_credentials=True |
| Modify | `api/requirements.txt` | Add `authlib`, remove `passlib`, remove `python-jose` |
| Create | `frontend/src/auth.ts` | PKCE helpers: generateVerifier, generateChallenge, redirectToAuthentik |
| Rewrite | `frontend/src/App.tsx` | OIDC flow: /auth/me check, callback handling, redirect |
| Modify | `frontend/src/api/client.ts` | Remove Bearer headers, add credentials: 'include', 401 refresh flow |
| Modify | `frontend/.env.example` | Add VITE_AUTHENTIK_URL, VITE_AUTHENTIK_CLIENT_ID, VITE_REDIRECT_URI |

---

## Task 1: auth-config repo — Authentik Docker Compose stack

**Files:**
- Create: `docker-compose.yml` (in `~/Documents/auth-config/`)
- Create: `.env.example`
- Create: `.gitignore`

- [ ] **Step 1: Create docker-compose.yml**

```yaml
# ~/Documents/auth-config/docker-compose.yml
services:
  authentik-db:
    image: docker.io/library/postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_USER: authentik
      POSTGRES_DB: authentik
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U authentik"]
      interval: 5s
      timeout: 5s
      retries: 5

  authentik-server:
    image: ghcr.io/goauthentik/server:2026.2.2
    restart: unless-stopped
    command: server
    environment:
      AUTHENTIK_REDIS__HOST: ""
      AUTHENTIK_POSTGRESQL__HOST: authentik-db
      AUTHENTIK_POSTGRESQL__USER: authentik
      AUTHENTIK_POSTGRESQL__NAME: authentik
      AUTHENTIK_POSTGRESQL__PASSWORD: ${POSTGRES_PASSWORD}
      AUTHENTIK_SECRET_KEY: ${AUTHENTIK_SECRET_KEY}
      AUTHENTIK_ERROR_REPORTING__ENABLED: "false"
    ports:
      - "9000:9000"
    depends_on:
      authentik-db:
        condition: service_healthy
    volumes:
      - ./data/media:/media
      - ./data/custom-templates:/templates

  authentik-worker:
    image: ghcr.io/goauthentik/server:2026.2.2
    restart: unless-stopped
    command: worker
    user: root
    environment:
      AUTHENTIK_REDIS__HOST: ""
      AUTHENTIK_POSTGRESQL__HOST: authentik-db
      AUTHENTIK_POSTGRESQL__USER: authentik
      AUTHENTIK_POSTGRESQL__NAME: authentik
      AUTHENTIK_POSTGRESQL__PASSWORD: ${POSTGRES_PASSWORD}
      AUTHENTIK_SECRET_KEY: ${AUTHENTIK_SECRET_KEY}
      AUTHENTIK_ERROR_REPORTING__ENABLED: "false"
    depends_on:
      authentik-db:
        condition: service_healthy
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ./data/media:/media
      - ./data/certs:/certs
      - ./data/custom-templates:/templates

  cloudflared:
    image: cloudflare/cloudflared:latest
    restart: unless-stopped
    command: tunnel --no-autoupdate run
    environment:
      TUNNEL_TOKEN: ${CLOUDFLARE_TUNNEL_TOKEN}
    depends_on:
      - authentik-server

volumes:
  pgdata:
```

- [ ] **Step 2: Create .env.example**

```env
# Generate with: openssl rand -hex 32
AUTHENTIK_SECRET_KEY=

# Same value used in both vars
AUTHENTIK_POSTGRESQL__PASSWORD=
POSTGRES_PASSWORD=

# From Cloudflare Zero Trust dashboard (Tunnel B)
CLOUDFLARE_TUNNEL_TOKEN=
```

- [ ] **Step 3: Create .gitignore**

```
.env
data/
```

- [ ] **Step 4: Commit**

```bash
cd ~/Documents/auth-config
git add docker-compose.yml .env.example .gitignore
git commit -m "feat: add Authentik Docker Compose stack"
```

---

## Task 2: Update conftest.py and config.py

**Files:**
- Modify: `tests/conftest.py`
- Modify: `api/app/config.py`
- Modify: `api/requirements.txt`

- [ ] **Step 1: Update `tests/conftest.py`**

Replace the old auth env vars block. Remove `JWT_SECRET`, `SINGLE_USER_EMAIL`, `SINGLE_USER_PASSWORD`. Add Authentik vars:

```python
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ["DATABASE_URL"] = "postgresql+asyncpg://wiki:wiki@db:5432/wiki_test"
os.environ["AUTHENTIK_ISSUER"] = "https://auth.example.com/application/o/second-brain/"
os.environ["AUTHENTIK_JWKS_URI"] = "https://auth.example.com/application/o/second-brain/jwks/"
os.environ["AUTHENTIK_CLIENT_ID"] = "second-brain"
os.environ["AUTHENTIK_TOKEN_URL"] = "https://auth.example.com/application/o/token/"
os.environ["AUTHENTIK_REDIRECT_URI"] = "https://smoothstudy.ai/callback"
os.environ.setdefault("LITELLM_MODEL", "gemini/gemini-2.0-flash")
os.environ.setdefault("S3_ENDPOINT", "http://localhost:9000")
os.environ["S3_BUCKET"] = "wiki-test"
os.environ.setdefault("S3_ACCESS_KEY", "minioadmin")
os.environ.setdefault("VECTOR_SEARCH_ENABLED", "true")
os.environ.setdefault("MARKER_URL", "http://marker:8001")
os.environ.setdefault("VISION_MODEL", "")

assert "test" in os.environ["DATABASE_URL"]
assert "test" in os.environ["S3_BUCKET"]

import pytest
import pytest_asyncio
from unittest.mock import MagicMock, patch
from sqlalchemy import text

from app.database import AsyncSessionLocal, Base, engine
import app.models  # noqa: F401
from app.models import Workspace


@pytest_asyncio.fixture(loop_scope="function")
async def db_session():
    async with AsyncSessionLocal() as session:
        yield session


@pytest_asyncio.fixture(loop_scope="function")
async def workspace_id(db_session):
    ws = Workspace(user_id="test-user")
    db_session.add(ws)
    await db_session.flush()
    return ws.id


@pytest.fixture(autouse=True)
def _mock_s3():
    ingest_upload = patch(
        "app.routes.ingest.upload_file",
        MagicMock(return_value="s3://mock"),
    )
    tools_dl = patch(
        "app.agents.tools.download_file",
        side_effect=RuntimeError(
            "Real S3 call in tests — mock app.agents.tools.download_file explicitly"
        ),
    )
    with patch(
        "app.storage.download_file",
        side_effect=RuntimeError(
            "Real S3 call in tests — mock app.storage.download_file explicitly"
        ),
    ):
        with patch(
            "app.storage.upload_file",
            side_effect=RuntimeError(
                "Real S3 call in tests — mock app.storage.upload_file explicitly"
            ),
        ):
            with patch("app.storage.ensure_bucket"):
                with ingest_upload:
                    with tools_dl:
                        yield


@pytest_asyncio.fixture(autouse=True, loop_scope="function")
async def clean_db():
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        reg = await conn.execute(text("SELECT to_regclass('public.chat_sessions')"))
        if reg.scalar() is not None:
            await conn.execute(
                text(
                    "ALTER TABLE chat_sessions DROP CONSTRAINT IF EXISTS "
                    "fk_chat_sessions_last_monitored_message_id"
                )
            )
            await conn.execute(
                text(
                    "ALTER TABLE chat_sessions DROP CONSTRAINT IF EXISTS "
                    "chat_sessions_last_monitored_message_id_fkey"
                )
            )
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
```

- [ ] **Step 2: Update `api/app/config.py`**

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    litellm_model: str = "gemini/gemini-2.0-flash"
    gemini_api_key: str | None = None
    s3_endpoint: str = "http://minio:9000"
    s3_bucket: str = "wiki"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    vector_search_enabled: bool = True
    marker_backend: str = "datalab"
    datalab_api_key: str = ""
    datalab_mode: str = "accurate"
    marker_url: str = "http://marker:8001"
    marker_llm_service: str = "marker.services.gemini.GoogleGeminiService"
    marker_llm_model: str = ""
    marker_llm_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    # Authentik OIDC
    authentik_issuer: str
    authentik_jwks_uri: str
    authentik_client_id: str
    authentik_token_url: str
    authentik_redirect_uri: str

    class Config:
        env_file = ".env"


settings = Settings()
```

- [ ] **Step 3: Update `api/requirements.txt`**

Remove `python-jose[cryptography]==3.3.0` and `passlib[bcrypt]==1.7.4`. Add `authlib==1.3.2`:

```
fastapi==0.115.0
uvicorn[standard]==0.30.0
sqlalchemy[asyncio]==2.0.36
asyncpg==0.29.0
alembic==1.13.3
pgvector==0.3.5
pydantic-settings==2.5.2
authlib==1.3.2
python-multipart==0.0.12
boto3==1.35.0
httpx==0.28.1
trafilatura==1.12.1
pypdf==5.1.0
python-docx==1.1.2
litellm==1.83.14
jinja2==3.1.6
pytest==8.3.3
pytest-asyncio==0.24.0
psycopg2-binary==2.9.9
cryptography==43.0.3
```

Note: `cryptography` is added explicitly — `authlib` uses it for RSA operations and it's needed in tests to generate test keys.

- [ ] **Step 4: Commit**

```bash
cd ~/Documents/Second-Brain
git add tests/conftest.py api/app/config.py api/requirements.txt
git commit -m "feat: update config and deps for Authentik OIDC"
```

---

## Task 3: Rewrite auth.py (TDD)

**Files:**
- Rewrite: `tests/test_auth.py`
- Rewrite: `api/app/auth.py`

- [ ] **Step 1: Write all failing tests in `tests/test_auth.py`**

```python
import time
import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend
from authlib.jose import JsonWebKey, jwt

from app.main import app

# --- Test RSA key pair (generated once per test session) ---

_private_key = rsa.generate_private_key(
    public_exponent=65537,
    key_size=2048,
    backend=default_backend(),
)
_public_key = _private_key.public_key()
_test_private = JsonWebKey.import_key(_private_key, {"use": "sig", "kid": "test-key-1"})
_test_public = JsonWebKey.import_key(_public_key, {"use": "sig", "kid": "test-key-1"})
_test_key_set = JsonWebKey.import_key_set({"keys": [_test_public.as_dict()]})


def make_token(sub: str = "abc-123-uuid", email: str = "user@example.com", expired: bool = False) -> str:
    now = int(time.time())
    payload = {
        "sub": sub,
        "email": email,
        "iss": "https://auth.example.com/application/o/second-brain/",
        "exp": now - 1 if expired else now + 3600,
        "iat": now,
    }
    return jwt.encode({"alg": "RS256", "kid": "test-key-1"}, payload, _test_private).decode()


def mock_jwks():
    return patch("app.auth._get_jwks", new=AsyncMock(return_value=_test_key_set))


# --- /auth/me ---

@pytest.mark.asyncio
async def test_me_returns_sub_when_authenticated():
    token = make_token(sub="abc-123-uuid")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with mock_jwks():
            resp = await client.get("/auth/me", cookies={"access_token": token})
    assert resp.status_code == 200
    assert resp.json()["sub"] == "abc-123-uuid"


@pytest.mark.asyncio
async def test_me_returns_401_with_no_cookie():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with mock_jwks():
            resp = await client.get("/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_returns_401_with_expired_token():
    token = make_token(expired=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with mock_jwks():
            resp = await client.get("/auth/me", cookies={"access_token": token})
    assert resp.status_code == 401


# --- /auth/callback ---

@pytest.mark.asyncio
async def test_callback_sets_cookies_on_success():
    fake_tokens = {
        "access_token": make_token(),
        "refresh_token": "fake-refresh-token",
        "token_type": "Bearer",
    }
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = fake_tokens

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch("app.auth.httpx.AsyncClient", return_value=mock_client):
            resp = await client.post(
                "/auth/callback",
                json={"code": "test-code", "code_verifier": "test-verifier"},
            )
    assert resp.status_code == 200
    assert "access_token" in resp.cookies
    assert "refresh_token" in resp.cookies


@pytest.mark.asyncio
async def test_callback_returns_401_when_authentik_rejects():
    mock_response = AsyncMock()
    mock_response.status_code = 400
    mock_response.json.return_value = {"error": "invalid_grant"}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch("app.auth.httpx.AsyncClient", return_value=mock_client):
            resp = await client.post(
                "/auth/callback",
                json={"code": "bad-code", "code_verifier": "verifier"},
            )
    assert resp.status_code == 401


# --- /auth/refresh ---

@pytest.mark.asyncio
async def test_refresh_sets_new_cookies():
    fake_tokens = {
        "access_token": make_token(),
        "refresh_token": "new-refresh-token",
        "token_type": "Bearer",
    }
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = fake_tokens

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch("app.auth.httpx.AsyncClient", return_value=mock_client):
            resp = await client.post(
                "/auth/refresh",
                cookies={"refresh_token": "old-refresh-token"},
            )
    assert resp.status_code == 200
    assert "access_token" in resp.cookies


@pytest.mark.asyncio
async def test_refresh_returns_401_with_no_cookie():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/auth/refresh")
    assert resp.status_code == 401


# --- /auth/logout ---

@pytest.mark.asyncio
async def test_logout_clears_cookies():
    token = make_token()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with mock_jwks():
            resp = await client.post("/auth/logout", cookies={"access_token": token})
    assert resp.status_code == 200
    # Cookies cleared by Set-Cookie with empty value
    assert resp.cookies.get("access_token", "") == ""
    assert resp.cookies.get("refresh_token", "") == ""
```

- [ ] **Step 2: Run tests to confirm they all fail**

```bash
docker compose run --rm api pytest tests/test_auth.py -v
```

Expected: All tests FAIL — `ImportError` or `404` since the endpoints don't exist yet.

- [ ] **Step 3: Rewrite `api/app/auth.py`**

```python
import httpx
from authlib.jose import JsonWebKey, jwt
from authlib.jose.errors import JoseError
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from app.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])

_jwks_cache = None


async def _get_jwks():
    global _jwks_cache
    if _jwks_cache is None:
        async with httpx.AsyncClient() as client:
            r = await client.get(settings.authentik_jwks_uri)
            r.raise_for_status()
        _jwks_cache = JsonWebKey.import_key_set(r.json())
    return _jwks_cache


async def _decode_token(token: str) -> dict:
    jwks = await _get_jwks()
    try:
        claims = jwt.decode(token, jwks)
        claims.validate()
        return dict(claims)
    except JoseError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def get_current_user(request: Request) -> str:
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = await _decode_token(token)
    return payload["sub"]


def _set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    response.set_cookie("access_token", access_token, httponly=True, secure=True, samesite="strict")
    response.set_cookie("refresh_token", refresh_token, httponly=True, secure=True, samesite="strict")


class CallbackRequest(BaseModel):
    code: str
    code_verifier: str


@router.post("/callback")
async def auth_callback(req: CallbackRequest, response: Response):
    async with httpx.AsyncClient() as client:
        r = await client.post(
            settings.authentik_token_url,
            data={
                "grant_type": "authorization_code",
                "client_id": settings.authentik_client_id,
                "code": req.code,
                "code_verifier": req.code_verifier,
                "redirect_uri": settings.authentik_redirect_uri,
            },
        )
    if r.status_code != 200:
        raise HTTPException(status_code=401, detail="Token exchange failed")
    tokens = r.json()
    _set_auth_cookies(response, tokens["access_token"], tokens["refresh_token"])
    return {"ok": True}


@router.post("/refresh")
async def auth_refresh(request: Request, response: Response):
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=401, detail="No refresh token")
    async with httpx.AsyncClient() as client:
        r = await client.post(
            settings.authentik_token_url,
            data={
                "grant_type": "refresh_token",
                "client_id": settings.authentik_client_id,
                "refresh_token": refresh_token,
            },
        )
    if r.status_code != 200:
        raise HTTPException(status_code=401, detail="Refresh failed")
    tokens = r.json()
    _set_auth_cookies(response, tokens["access_token"], tokens["refresh_token"])
    return {"ok": True}


@router.post("/logout")
async def auth_logout(response: Response):
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")
    return {"ok": True}


@router.get("/me")
async def auth_me(request: Request):
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = await _decode_token(token)
    return {"sub": payload["sub"], "email": payload.get("email")}
```

- [ ] **Step 4: Run tests — all must pass**

```bash
docker compose run --rm api pytest tests/test_auth.py -v
```

Expected: All 9 tests PASS.

- [ ] **Step 5: Confirm existing test suite still passes**

```bash
docker compose run --rm api pytest tests/ -v --ignore=tests/test_auth.py
```

Expected: All other tests PASS. (The existing routes use `get_current_user` which is still exported from `app.auth` — no change to the dependency injection pattern.)

- [ ] **Step 6: Commit**

```bash
git add api/app/auth.py tests/test_auth.py
git commit -m "feat: rewrite auth — OIDC JWKS validation, HttpOnly cookies, refresh flow"
```

---

## Task 4: Update main.py CORS

**Files:**
- Modify: `api/app/main.py`

- [ ] **Step 1: Update CORS in `api/app/main.py`**

Find the `CORSMiddleware` block and replace it:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "https://smoothstudy.ai"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

- [ ] **Step 2: Run full test suite to confirm nothing broken**

```bash
docker compose run --rm api pytest tests/ -v
```

Expected: All tests PASS.

- [ ] **Step 3: Commit**

```bash
git add api/app/main.py
git commit -m "feat: update CORS for cookie-based auth and smoothstudy.ai origin"
```

---

## Task 5: Create frontend/src/auth.ts

**Files:**
- Create: `frontend/src/auth.ts`

- [ ] **Step 1: Create `frontend/src/auth.ts`**

```typescript
const AUTHENTIK_URL = import.meta.env.VITE_AUTHENTIK_URL as string
const CLIENT_ID = import.meta.env.VITE_AUTHENTIK_CLIENT_ID as string
const REDIRECT_URI = import.meta.env.VITE_REDIRECT_URI as string

export function generateVerifier(): string {
  const array = new Uint8Array(32)
  crypto.getRandomValues(array)
  return btoa(String.fromCharCode(...array))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=/g, '')
}

export async function generateChallenge(verifier: string): Promise<string> {
  const data = new TextEncoder().encode(verifier)
  const digest = await crypto.subtle.digest('SHA-256', data)
  return btoa(String.fromCharCode(...new Uint8Array(digest)))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=/g, '')
}

export async function redirectToAuthentik(): Promise<void> {
  const verifier = generateVerifier()
  const challenge = await generateChallenge(verifier)
  sessionStorage.setItem('pkce_verifier', verifier)
  const params = new URLSearchParams({
    client_id: CLIENT_ID,
    redirect_uri: REDIRECT_URI,
    response_type: 'code',
    scope: 'openid profile email offline_access',
    code_challenge: challenge,
    code_challenge_method: 'S256',
  })
  window.location.href = `${AUTHENTIK_URL}/application/o/authorize/?${params}`
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/auth.ts
git commit -m "feat: add PKCE auth helpers"
```

---

## Task 6: Rewrite frontend/src/App.tsx

**Files:**
- Rewrite: `frontend/src/App.tsx`

- [ ] **Step 1: Rewrite `frontend/src/App.tsx`**

```tsx
import { useEffect, useState } from 'react'
import { redirectToAuthentik } from './auth'
import Layout from './components/Layout'

type AuthState = 'loading' | 'authenticated' | 'unauthenticated'

export default function App() {
  const [authState, setAuthState] = useState<AuthState>('loading')

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const code = params.get('code')

    if (code) {
      const verifier = sessionStorage.getItem('pkce_verifier') ?? ''
      sessionStorage.removeItem('pkce_verifier')
      fetch('/api/auth/callback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ code, code_verifier: verifier }),
      }).then(r => {
        window.history.replaceState({}, '', '/')
        setAuthState(r.ok ? 'authenticated' : 'unauthenticated')
      })
      return
    }

    fetch('/api/auth/me', { credentials: 'include' }).then(async r => {
      if (r.ok) { setAuthState('authenticated'); return }
      const refresh = await fetch('/api/auth/refresh', { method: 'POST', credentials: 'include' })
      setAuthState(refresh.ok ? 'authenticated' : 'unauthenticated')
    })
  }, [])

  useEffect(() => {
    if (authState === 'unauthenticated') redirectToAuthentik()
  }, [authState])

  if (authState !== 'authenticated') return null
  return <Layout />
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "feat: replace login form with OIDC redirect flow"
```

---

## Task 7: Update frontend/src/api/client.ts

**Files:**
- Modify: `frontend/src/api/client.ts`

- [ ] **Step 1: Rewrite `frontend/src/api/client.ts`**

Remove `token()`, remove `login()`, remove all `Authorization: Bearer` headers. Add `credentials: 'include'` to all fetch calls. Add a `fetchWithAuth` wrapper that handles 401 by attempting a refresh then retrying once.

```typescript
const BASE = '/api'

async function fetchWithAuth(url: string, options: RequestInit = {}): Promise<Response> {
  const opts: RequestInit = { ...options, credentials: 'include' }
  const r = await fetch(url, opts)
  if (r.status !== 401) return r
  const refresh = await fetch(`${BASE}/auth/refresh`, { method: 'POST', credentials: 'include' })
  if (!refresh.ok) {
    window.location.href = '/'
    return r
  }
  return fetch(url, opts)
}

function jsonHeaders(extra: Record<string, string> = {}): Record<string, string> {
  return { 'Content-Type': 'application/json', ...extra }
}

export async function listPages() {
  const r = await fetchWithAuth(`${BASE}/wiki/pages`)
  return r.json()
}

export async function getPage(slug: string) {
  const r = await fetchWithAuth(`${BASE}/wiki/pages/${slug}`)
  if (r.status === 404) return null
  return r.json()
}

export async function updatePage(slug: string, body: { title?: string; body_md?: string; summary?: string }) {
  const r = await fetchWithAuth(`${BASE}/wiki/pages/${slug}`, {
    method: 'PUT',
    headers: jsonHeaders(),
    body: JSON.stringify(body),
  })
  return r.json()
}

export async function sendMessage(message: string, sessionId?: string, mode: 'query' | 'edit' = 'query') {
  const r = await fetchWithAuth(`${BASE}/chat/message`, {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify({ message, session_id: sessionId, mode }),
  })
  return r.json()
}

export async function ingestText(text: string, title?: string) {
  const r = await fetchWithAuth(`${BASE}/ingest/text`, {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify({ text, title }),
  })
  return r.json()
}

export async function ingestUrl(url: string) {
  const r = await fetchWithAuth(`${BASE}/ingest/url`, {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify({ url }),
  })
  return r.json()
}

export async function ingestFile(file: File) {
  const fd = new FormData()
  fd.append('file', file)
  const r = await fetchWithAuth(`${BASE}/ingest/file`, { method: 'POST', body: fd })
  if (!r.ok) throw new Error(`ingestFile failed: ${r.status}`)
  return r.json()
}

export async function getActivity(limit = 50) {
  const r = await fetchWithAuth(`${BASE}/activity/?limit=${limit}`)
  return r.json()
}

export function createSSE(onEvent: (data: unknown) => void): () => void {
  const es = new EventSource(`${BASE}/chat/sse`, { withCredentials: true })
  es.onmessage = (e) => { try { onEvent(JSON.parse(e.data)) } catch {} }
  return () => es.close()
}

export async function runHealthCheck() {
  const r = await fetchWithAuth(`${BASE}/health/run`, { method: 'POST', headers: jsonHeaders() })
  if (!r.ok) throw new Error('Health check failed to start')
  return r.json()
}

export async function listSessions(): Promise<{ id: string; created_at: string }[]> {
  const r = await fetchWithAuth(`${BASE}/chat/sessions`)
  if (!r.ok) throw new Error('Failed to load sessions')
  return r.json()
}

export async function getSessionMessages(sessionId: string): Promise<{ id: string; role: string; content: string }[]> {
  const r = await fetchWithAuth(`${BASE}/chat/sessions/${sessionId}/messages`)
  if (!r.ok) return []
  return r.json()
}
```

Note: `createSSE` now uses `withCredentials: true` on the `EventSource` so the session cookie is sent with the SSE connection. The old `?token=` query param is removed.

- [ ] **Step 2: Commit**

```bash
git add frontend/src/api/client.ts
git commit -m "feat: remove Bearer auth, use cookie-based requests with refresh retry"
```

---

## Task 8: Update .env files

**Files:**
- Modify: `frontend/.env.example` (if it exists) or create it
- Modify: `Second-Brain/.env` (local, not committed)

- [ ] **Step 1: Add Vite env vars to `frontend/.env.example`**

Check if `frontend/.env.example` exists. If not, create it. Add:

```env
VITE_AUTHENTIK_URL=https://auth.smoothstudy.ai
VITE_AUTHENTIK_CLIENT_ID=second-brain
VITE_REDIRECT_URI=https://smoothstudy.ai/callback
```

- [ ] **Step 2: Add backend vars to `.env`** (local file, not committed — do NOT commit this)

Add to `Second-Brain/.env`:
```env
AUTHENTIK_ISSUER=https://auth.smoothstudy.ai/application/o/second-brain/
AUTHENTIK_JWKS_URI=https://auth.smoothstudy.ai/application/o/second-brain/jwks/
AUTHENTIK_CLIENT_ID=second-brain
AUTHENTIK_TOKEN_URL=https://auth.smoothstudy.ai/application/o/token/
AUTHENTIK_REDIRECT_URI=https://smoothstudy.ai/callback
```

Remove from `.env`: `JWT_SECRET`, `SINGLE_USER_EMAIL`, `SINGLE_USER_PASSWORD`

- [ ] **Step 3: Commit .env.example only**

```bash
git add frontend/.env.example
git commit -m "feat: add Vite env vars for Authentik OIDC"
```

---

## Task 9: SSE cookie fix — check chat routes

**Files:**
- Check: `api/app/routes/chat.py`

The old SSE endpoint read `?token=` from the query string to authenticate (since `EventSource` can't set headers). Now that we use cookies, the SSE endpoint must read from the cookie instead.

- [ ] **Step 1: Check the SSE route**

```bash
grep -n "token\|cookie\|get_current_user" ~/Documents/Second-Brain/api/app/routes/chat.py
```

- [ ] **Step 2: If SSE uses `?token=` query param, update it**

Find the SSE endpoint in `api/app/routes/chat.py`. Replace any `token: str = Query(...)` auth with cookie-based auth using `get_current_user`:

```python
@router.get("/sse")
async def sse_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),  # reads access_token cookie
):
    ...
```

- [ ] **Step 3: Run full test suite**

```bash
docker compose run --rm api pytest tests/ -v
```

Expected: All tests PASS.

- [ ] **Step 4: Commit if changed**

```bash
git add api/app/routes/chat.py
git commit -m "fix: use cookie auth for SSE endpoint"
```

---

## Task 10: Pi deployment checklist

These are manual one-time steps — not automated. Execute in order.

- [ ] **Step 1: Create Cloudflare Tunnel B**

In Cloudflare Zero Trust dashboard:
1. Go to Networks → Tunnels → Create tunnel
2. Name: `authentik`
3. Copy the tunnel token
4. Add public hostname: `auth.smoothstudy.ai` → Service: `http://authentik-server:9000`

- [ ] **Step 2: Set up auth-config on Pi**

```bash
ssh darragh@pi-server.local
git clone <auth-config-repo-url> ~/authentik
cd ~/authentik
cp .env.example .env
# Fill in .env:
# AUTHENTIK_SECRET_KEY=$(openssl rand -hex 32)
# POSTGRES_PASSWORD=<strong-password>
# AUTHENTIK_POSTGRESQL__PASSWORD=<same-strong-password>
# CLOUDFLARE_TUNNEL_TOKEN=<token from Step 1>
nano .env
docker compose up -d
```

- [ ] **Step 3: Authentik first-boot setup**

Wait ~60 seconds for Authentik to initialise, then:

1. Visit `https://auth.smoothstudy.ai/if/flow/initial-setup/`
2. Create admin account
3. Go to Applications → Providers → Create → OAuth2/OpenID Provider:
   - Name: `second-brain`
   - Client type: `Public`
   - Client ID: `second-brain`
   - Redirect URIs: `https://smoothstudy.ai/callback`
   - Scopes: `openid`, `profile`, `email`, `offline_access`
   - Signing Key: select the auto-generated key
4. Go to Applications → Applications → Create:
   - Name: `Second Brain`
   - Slug: `second-brain`
   - Provider: `second-brain`
5. Go to Directory → Users → Create user for each person (up to 5):
   - Set username + email
   - Set password via "Update password"

- [ ] **Step 4: Wipe Pi database and redeploy Second Brain**

```bash
cd ~/second-brain
git pull
# Stop the stack
docker compose down
# Wipe the database volume (destroys all existing data — confirmed dev data only)
docker volume rm second-brain_pgdata
# Rebuild and start
docker compose up --build -d
# Run migrations on the fresh database
docker compose run --rm api alembic upgrade head
```

- [ ] **Step 5: Verify end-to-end**

1. Visit `https://smoothstudy.ai` — should redirect to `https://auth.smoothstudy.ai`
2. Log in with a user you created in Step 3
3. Should redirect back to `https://smoothstudy.ai` and show the app
4. Open DevTools → Application → Cookies — confirm `access_token` and `refresh_token` are present with `HttpOnly` flag set
5. Confirm no token in `localStorage`

---

## Self-Review

**Spec coverage check:**
- ✅ auth-config Docker Compose stack (Task 1)
- ✅ JWKS validation with `authlib` (Task 3)
- ✅ HttpOnly cookie auth (Task 3)
- ✅ `/auth/callback` — OIDC code exchange (Task 3)
- ✅ `/auth/refresh` — silent token renewal (Task 3)
- ✅ `/auth/logout` — cookie clearing (Task 3)
- ✅ `/auth/me` — boot-time auth check (Task 3)
- ✅ CORS updated (Task 4)
- ✅ PKCE helpers (Task 5)
- ✅ App.tsx OIDC flow (Task 6)
- ✅ client.ts Bearer removal + credentials: include (Task 7)
- ✅ SSE cookie auth fix (Task 9)
- ✅ Pi deployment + DB wipe (Task 10)
- ✅ Authentik first-boot setup (Task 10)
- ✅ `sub` used as user identity, not `email` (Task 3 — `payload["sub"]`)

**Type consistency:** `get_current_user` returns `str` (sub) throughout — all existing route signatures unchanged. `_decode_token` returns `dict` — used internally only.

**Placeholder scan:** No TBDs. All code steps include full implementation.
