# Local Dev Auth

Two options for running the app locally without the Pi's Cloudflare/authentik stack.

---

## Option A — Dev Bypass (no authentik)

Fastest option. A dummy cookie replaces JWT validation entirely.

### Setup

`.env` (repo root):
```
DEV_AUTH_BYPASS=true
```

`frontend/.env.local` (create this file, it overrides `frontend/.env`):
```
VITE_DEV_AUTH_BYPASS=true
```

Leave all `AUTHENTIK_*` vars unset or empty — they're not required when bypass is on.

### How it works

- The app loads → no `logged_in` cookie → shows a **Dev Login** button instead of redirecting to authentik
- Clicking the button hits `GET /api/auth/dev-login`, which sets `access_token=dev` cookie
- All protected API routes accept that cookie and return user ID `"dev-user"`
- Logout clears cookies and reloads the page (no authentik end-session call)

### Files changed

- `api/app/config.py` — `DEV_AUTH_BYPASS: bool = False` added; authentik fields now have empty-string defaults
- `api/app/auth.py` — `get_current_user` short-circuits on `token == "dev"`; `/auth/dev-login` endpoint added; `auth_me` returns `dev-user`/`dev@local`
- `frontend/src/auth.ts` — `DEV_AUTH_BYPASS` export, `devLogin()` function, bypass-aware `logout()`
- `frontend/src/App.tsx` — shows Dev Login button when bypass is on instead of auto-redirecting

---

## Option B — Local Authentik

Runs the real authentik stack locally in Docker. Useful if you want to test the actual OAuth flow.

### Setup

1. **Uncomment** the three authentik services and three volumes in `docker-compose.yml`:
   - `authentik-db`
   - `authentik-server` (exposed on `localhost:9000`)
   - `authentik-worker`

2. **First boot only** — visit `http://localhost:9000/if/flow/initial-setup/` and complete setup. Then:
   - Create an **OAuth2/OIDC Provider** with redirect URI `http://localhost:5173/callback`
   - Create an **Application** with slug `second-brain`, linked to that provider
   - Note the **Client ID** from the provider

3. **`.env`** (repo root):
```
AUTHENTIK_ISSUER=http://localhost:9000/application/o/second-brain/
AUTHENTIK_JWKS_URI=http://authentik-server:9000/application/o/second-brain/jwks/
AUTHENTIK_CLIENT_ID=<client id from authentik UI>
AUTHENTIK_TOKEN_URL=http://authentik-server:9000/application/o/token/
AUTHENTIK_REDIRECT_URI=http://localhost:5173/callback
```

4. **`frontend/.env.local`**:
```
VITE_AUTHENTIK_URL=http://localhost:9000
VITE_AUTHENTIK_CLIENT_ID=<client id from authentik UI>
VITE_REDIRECT_URI=http://localhost:5173/callback
```

### Key detail — split URLs

The API's server-side requests (JWKS fetch, token exchange) use the **internal Docker hostname** `authentik-server:9000`. The browser-facing URLs use `localhost:9000`. That's why `AUTHENTIK_JWKS_URI` and `AUTHENTIK_TOKEN_URL` differ from `VITE_AUTHENTIK_URL`.

The `AUTHENTIK_ISSUER` must match what authentik puts in the JWT `iss` claim — which is based on the public-facing URL (`localhost:9000`), not the internal one.

### Files changed

- `docker-compose.yml` — authentik services added as commented-out blocks with instructions

---

## Quick reference

| | Dev Bypass | Local Authentik |
|---|---|---|
| Authentik running? | No | Yes (Docker) |
| Real OAuth flow? | No | Yes |
| Setup time | 30 seconds | ~10 min (one-time) |
| Use when | Day-to-day dev | Testing auth flows |
