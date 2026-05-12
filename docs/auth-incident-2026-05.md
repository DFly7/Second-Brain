# Auth redirect loop — May 2026

## Symptom

Infinite redirect loop between the app (`smoothstudy.ai`) and Authentik. Every login attempt: Authentik redirect → callback returns 200 → all API requests immediately return 401 → app redirects back to Authentik → repeat forever.

## Root cause

`DEV_AUTH_BYPASS=true` was set in the production `.env`. With this flag on, `get_current_user` in `api/app/auth.py` bypasses all JWT validation and only accepts the literal string `"dev"` as a valid token:

```python
if settings.dev_auth_bypass:
    if token == "dev":
        return "dev-user"
    raise HTTPException(status_code=401, detail="Not authenticated")
```

The frontend `.env` does NOT set `VITE_DEV_AUTH_BYPASS`, so the frontend always runs the real PKCE OAuth flow and receives a real Authentik JWT. The backend rejected every real token with 401, triggering the app's unauthenticated redirect.

**Fix:** Set `DEV_AUTH_BYPASS=false` in `.env`, then restart the API container.

## Why it was hard to diagnose

Several red herrings had to be ruled out first:

1. **SameSite=Strict cookies** — the original cookie policy blocked cookies on cross-site navigation (OAuth redirect back to the app counts as cross-site). Fixed: changed all `samesite="strict"` → `samesite="lax"`. This was a real bug but not the loop cause.

2. **Cloudflare Tunnel stripping Set-Cookie headers** — plausible given the architecture. Added sessionStorage-based token store + `Authorization: Bearer` header fallback in `fetchWithAuth` as a defence. This was the right hardening regardless.

3. **`offline_access` scope not configured** — Authentik was not issuing refresh tokens. Fixed in Authentik admin. Also real, but not the loop cause.

4. **Logging apparently missing** — `log.warning()` calls added to `_decode_token` weren't visible, which looked like a structlog misconfiguration. Actually the token was being rejected before JWT decode (in the `dev_auth_bypass` branch), so there was nothing to log at the decode stage.

## Architectural context

```
browser → Cloudflare Tunnel → nginx (frontend) → /api/* proxy_pass → FastAPI (api)
```

Cloudflare Tunnel sits between the browser and nginx. This means:
- Cookies set by the API travel back through nginx → cloudflared → browser; Cloudflare may strip or modify them
- `Authorization: Bearer` headers sent by the frontend travel the same path but are less likely to be interfered with
- SameSite=Lax (not Strict) is required because the OAuth redirect from Authentik back to the app is a cross-site top-level navigation

## Hardening added during investigation

These improvements were made and are worth keeping even though the root cause was simpler:

- **SessionStorage token store** (`frontend/src/auth.ts`): saves the access token + expiry from the callback response body, so auth survives if cookies are stripped
- **Authorization: Bearer fallback** (`frontend/src/api/client.ts`): `fetchWithAuth` sends the stored token as a header on every request; backend's `_resolve_raw_access_token` checks cookie → header → query param in that order
- **SSE query param token** (`createSSE`): EventSource doesn't support custom headers; token is passed as `?token=` for the SSE endpoint
- **JWT decode retry with JWKS refresh** (`api/app/auth.py`): on first decode failure, invalidates the JWKS cache and retries once with fresh keys
- **Retry + deduplication on refresh** (`postRefreshWithRetries`): parallel 401s share a single in-flight refresh request; retries up to 3 times with backoff
