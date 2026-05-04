# Authentik Auth Integration — Design Spec
Date: 2026-05-04

## Overview

Replace the current single-user hardcoded JWT auth in Second Brain with Authentik as a centralized OIDC identity provider. Authentik runs as an independent Docker Compose stack (`auth-config` repo, deployed to `~/authentik/` on the Pi), separate from the Second Brain stack. Up to 5 users, managed via the Authentik admin UI.

---

## Architecture

```
Internet
    │
    ├── smoothstudy.ai ──────── Cloudflare Tunnel A ──── frontend:5173 (Second Brain stack)
    │                                                           │
    │                                                     api:8000 (FastAPI)
    │                                                           │
    │                                         validates JWT via JWKS (cached) ───────────┐
    │                                                                                     │
    └── auth.smoothstudy.ai ── Cloudflare Tunnel B ──── authentik-server:9000            │
                                                         (Authentik stack) ◄──────────────┘
                                                               │
                                                         authentik-db (postgres:16-alpine)
                                                         authentik-worker
```

Two completely independent stacks. The only connection between them is FastAPI fetching Authentik's public JWKS keys over HTTPS — no shared Docker networks, no shared volumes.

---

## Login Flow (OIDC Authorization Code + PKCE)

1. User visits `smoothstudy.ai`, frontend sees no auth cookie → generates PKCE `code_verifier` + `code_challenge`, stores verifier in `sessionStorage`
2. Frontend redirects to `https://auth.smoothstudy.ai/application/o/authorize/` with `client_id`, `redirect_uri`, `response_type=code`, `scope=openid profile email offline_access`, `code_challenge`
3. User logs in on Authentik's UI
4. Authentik redirects to `https://smoothstudy.ai/callback?code=...`
5. Frontend sends `code` + `code_verifier` to FastAPI `POST /auth/callback`
6. FastAPI exchanges them server-side with Authentik's token endpoint — receives `access_token` + `refresh_token`
7. FastAPI sets both as **HttpOnly, Secure, SameSite=Strict cookies** in the HTTP response — browser stores them, JavaScript never sees the raw tokens
8. All subsequent API calls automatically include the cookies (browser attaches them)
9. FastAPI validates the access token cookie against Authentik's cached JWKS keys on every request
10. When access token expires → frontend calls `POST /auth/refresh` → FastAPI uses the refresh token cookie to silently get new tokens from Authentik → sets new cookies
11. If refresh token is also expired → frontend redirects to Authentik to re-authenticate

---

## Repo Structure

```
Mac / Pi:
~/Documents/auth-config/    ← GitHub repo, cloned to ~/authentik/ on Pi
~/Documents/Second-Brain/   ← GitHub repo, cloned to ~/second-brain/ on Pi
```

---

## Section 1: Authentik Stack (`auth-config` repo)

### Files
```
auth-config/
├── docker-compose.yml
├── .env.example
└── .env                ← gitignored
```

### Services (`docker-compose.yml`)

| Service | Image | Purpose |
|---|---|---|
| `authentik-db` | `docker.io/library/postgres:16-alpine` | Authentik's own database |
| `authentik-server` | `ghcr.io/goauthentik/server:2026.2.2` | Login UI + OIDC endpoints (port 9000) |
| `authentik-worker` | `ghcr.io/goauthentik/server:2026.2.2` | Background jobs (runs as root, mounts Docker socket) |
| `cloudflared` | `cloudflare/cloudflared:latest` | Tunnel B → `auth.smoothstudy.ai` → `authentik-server:9000` |

### `.env.example`
```env
AUTHENTIK_SECRET_KEY=        # long random string (openssl rand -hex 32)
AUTHENTIK_POSTGRESQL__PASSWORD=
POSTGRES_PASSWORD=           # same value as above
CLOUDFLARE_TUNNEL_TOKEN=     # Tunnel B token from Cloudflare Zero Trust dashboard
```

---

## Section 2: Second Brain Changes

### Backend

**`api/app/auth.py`** — complete rewrite:
- Remove `/auth/login` endpoint entirely (Authentik owns login)
- Add `POST /auth/callback` — receives `code` + `code_verifier` from frontend, exchanges with Authentik token endpoint server-side, sets `access_token` and `refresh_token` as HttpOnly, Secure, SameSite=Strict cookies
- Add `POST /auth/refresh` — reads `refresh_token` cookie, calls Authentik token endpoint, sets new cookies
- Add `POST /auth/logout` — clears both cookies
- Add `GET /auth/me` — protected endpoint, returns `{ sub, email }` from the validated token. Frontend calls this on boot to determine auth state — if 200 the user is logged in, if 401 they are not. JavaScript never reads the cookie directly.
- `get_current_user` reads `access_token` cookie (not Authorization header), validates JWT signature (RS256) against Authentik's cached JWKS keys, returns `payload.get("sub")`
- Uses `authlib` for JWKS URL fetching and RS256 validation (`authlib` has a built-in `JsonWebKey` JWKS client; `python-jose` can validate RS256 but has no JWKS URL fetcher)
- New dependency: `authlib` added to `api/requirements.txt`

**`api/app/config.py`** — remove `jwt_secret`, `single_user_email`, `single_user_password`. Add:
```python
authentik_issuer: str
authentik_jwks_uri: str
authentik_client_id: str
authentik_client_secret: str = ""  # empty for public PKCE clients
```

**`api/app/main.py`** — update CORS: add `https://smoothstudy.ai` to `allow_origins`, set `allow_credentials=True` (required for cookies to be sent cross-origin).

### Frontend

**`frontend/src/App.tsx`** — remove custom login form. On load:
- If `?code=` param in URL → OIDC callback: POST `code` + `code_verifier` to `POST /api/auth/callback`, then redirect to `/`
- Otherwise → call `GET /api/auth/me` to check auth state (browser sends cookie automatically via `credentials: 'include'`)
  - 200 → user is authenticated, render `<Layout />`
  - 401 → attempt `POST /api/auth/refresh` once; if that succeeds render `<Layout />`, if it also 401s → redirect to Authentik
- No localStorage, no token inspection — auth state is determined entirely by server responses

**`frontend/src/api/client.ts`** — remove `login()` function. Remove all `Authorization: Bearer` header logic (cookies are sent automatically by the browser). All fetch calls add `credentials: 'include'` so cookies are included. On 401 response → attempt `/api/auth/refresh`, retry once, if still 401 → redirect to Authentik.

**`frontend/src/auth.ts`** (new small module) — PKCE helpers: `generateVerifier()`, `generateChallenge()`, `buildAuthorizeUrl()`. No token storage — the browser handles cookies.

### Vite env vars (`.env` additions)
```env
VITE_AUTHENTIK_URL=https://auth.smoothstudy.ai
VITE_AUTHENTIK_CLIENT_ID=second-brain
VITE_REDIRECT_URI=https://smoothstudy.ai/callback
```

### Second Brain `.env` additions
```env
AUTHENTIK_ISSUER=https://auth.smoothstudy.ai/application/o/second-brain/
AUTHENTIK_JWKS_URI=https://auth.smoothstudy.ai/application/o/second-brain/jwks/
AUTHENTIK_CLIENT_ID=second-brain
```

---

## Section 3: Cloudflare Setup

| Tunnel | Hostname | Destination |
|---|---|---|
| Tunnel A (existing) | `smoothstudy.ai` | `frontend:5173` |
| Tunnel B (new) | `auth.smoothstudy.ai` | `authentik-server:9000` |

Create Tunnel B in Cloudflare Zero Trust dashboard. Get token → `auth-config/.env` as `CLOUDFLARE_TUNNEL_TOKEN`.

---

## Section 4: Authentik First-Boot Setup (manual, one-time)

After `docker compose up` on the Pi:

1. Visit `https://auth.smoothstudy.ai/if/flow/initial-setup/` — create admin account
2. **Create OAuth2/OIDC Provider:**
   - Client type: `Public` (PKCE, no client secret)
   - Client ID: `second-brain`
   - Redirect URI: `https://smoothstudy.ai/callback`
   - Scopes: `openid`, `profile`, `email`
   - Signing key: use Authentik's default generated key
3. **Create Application:** name `Second Brain`, slug `second-brain`, attach the provider
4. **Create users** (up to 5) with username + password each

This yields:
- JWKS URL: `https://auth.smoothstudy.ai/application/o/second-brain/jwks/`
- Issuer: `https://auth.smoothstudy.ai/application/o/second-brain/`

---

## Section 5: Data & Migration

**On first deploy:** wipe the Pi database clean. All existing data is dev data. Start fresh — all new data is created under the correct Authentik `sub` UUID from day one.

**User identity:** `get_current_user` returns `payload.get("sub")` (Authentik's stable UUID). This is the correct OIDC identifier. Do NOT use `email` — it can change.

**Future migration:** if existing data ever needs to be migrated to a new user identity, a SQL migration script will map old `workspace.user_id` → new Authentik `sub` UUID and cascade through all FK references. Deferred until actually needed.

---

## What Does NOT Change

- All FastAPI route logic — unchanged
- `get_current_user` dependency injection pattern — unchanged
- Workspace/page/chat data model — unchanged
- All other `client.ts` functions — unchanged (except adding `credentials: 'include'`)
- Docker Compose for Second Brain — unchanged (except CORS env and removing old auth env vars)
