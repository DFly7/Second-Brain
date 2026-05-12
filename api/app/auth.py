import asyncio
import os
import time

import httpx
import structlog
from authlib.jose import JsonWebKey, jwt
from authlib.jose.errors import JoseError
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from app.config import settings

log = structlog.get_logger()

router = APIRouter(prefix="/auth", tags=["auth"])

_jwks_cache = None
_jwks_fetched_at: float = 0.0
_JWKS_TTL = 300  # 5 minutes

# Authentik is occasionally slow; default httpx timeouts are tight and caused ReadTimeouts in prod.
_HTTP_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
_JWKS_FETCH_RETRIES = 2


def reset_jwks_cache() -> None:
    global _jwks_cache, _jwks_fetched_at
    _jwks_cache = None
    _jwks_fetched_at = 0.0


def _cookie_secure() -> bool:
    if os.environ.get("PYTEST_VERSION") is not None:
        return False
    if settings.dev_auth_bypass:
        return False
    return settings.authentik_redirect_uri.startswith("https://")


async def _fetch_jwks_once():
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        r = await client.get(settings.authentik_jwks_uri)
        r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict) or not data.get("keys"):
        raise ValueError("JWKS response missing keys")
    return JsonWebKey.import_key_set(data)


async def _fetch_jwks():
    last: BaseException | None = None
    for attempt in range(_JWKS_FETCH_RETRIES):
        try:
            return await _fetch_jwks_once()
        except (httpx.HTTPError, JoseError, ValueError, TypeError) as e:
            last = e
            reset_jwks_cache()
            log.warning("jwks_fetch_failed", attempt=attempt, error=str(e))
            if attempt + 1 < _JWKS_FETCH_RETRIES:
                await asyncio.sleep(0.35 * (attempt + 1))
    log.error("jwks_unavailable_after_retries", error=str(last))
    raise HTTPException(status_code=503, detail="Authentication keys unavailable")


async def _get_jwks():
    global _jwks_cache, _jwks_fetched_at
    if _jwks_cache is None or time.monotonic() - _jwks_fetched_at > _JWKS_TTL:
        _jwks_cache = await _fetch_jwks()
        _jwks_fetched_at = time.monotonic()
    return _jwks_cache


async def _decode_token(token: str) -> dict:
    jwks = await _get_jwks()
    try:
        claims = jwt.decode(token, jwks)
        claims.validate()
        payload = dict(claims)
    except (JoseError, ValueError) as first_err:
        log.warning("jwt_decode_first_attempt_failed", error=str(first_err), error_type=type(first_err).__name__)
        reset_jwks_cache()
        try:
            jwks = await _get_jwks()
            claims = jwt.decode(token, jwks)
            claims.validate()
            payload = dict(claims)
        except (JoseError, ValueError) as second_err:
            log.warning("jwt_decode_second_attempt_failed", error=str(second_err), error_type=type(second_err).__name__)
            raise HTTPException(status_code=401, detail="Invalid token")
    if payload.get("iss") != settings.authentik_issuer:
        log.warning("jwt_issuer_mismatch", token_iss=payload.get("iss"), expected=settings.authentik_issuer)
        raise HTTPException(status_code=401, detail="Invalid token")
    if payload.get("sub") is None:
        raise HTTPException(status_code=401, detail="Invalid token")
    return payload


_BEARER_PREFIX = "Bearer "


def _resolve_raw_access_token(request: Request) -> str | None:
    token = request.cookies.get("access_token")
    if token:
        return token
    authorization = request.headers.get("Authorization") or ""
    log.warning(
        "auth_resolve",
        path=request.url.path,
        has_auth_header=bool(authorization),
        has_qp_token=bool(request.query_params.get("token")),
        cookie_keys=list(request.cookies.keys()),
    )
    if authorization.startswith(_BEARER_PREFIX):
        return authorization[len(_BEARER_PREFIX) :].strip() or None
    # EventSource doesn't support custom headers — accept token as query param for SSE endpoints.
    qp_token = request.query_params.get("token")
    if qp_token:
        return qp_token
    return None


async def get_current_user(request: Request) -> str:
    token = _resolve_raw_access_token(request)
    if not token:
        log.warning("no_access_token", path=request.url.path)
        raise HTTPException(status_code=401, detail="Not authenticated")
    if settings.dev_auth_bypass:
        if token == "dev":
            return "dev-user"
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = await _decode_token(token)
    except HTTPException as e:
        log.warning("token_validation_failed", path=request.url.path, detail=e.detail)
        raise
    return str(payload["sub"])


_REFRESH_MAX_AGE = 30 * 24 * 3600  # 30 days — match typical authentik refresh token lifetime


def _set_auth_cookies(
    response: Response, access_token: str, refresh_token: str, access_token_ttl: int | None = None
) -> None:
    import time

    sec = _cookie_secure()
    response.set_cookie(
        "access_token",
        access_token,
        httponly=True,
        secure=sec,
        samesite="lax",
        max_age=access_token_ttl,  # None = session cookie; set from token response expires_in
    )
    response.set_cookie(
        "refresh_token",
        refresh_token,
        httponly=True,
        secure=sec,
        samesite="lax",
        max_age=_REFRESH_MAX_AGE,
    )
    # JS-readable flag so the frontend can skip async auth checks when not logged in.
    # Must be persistent (not a session cookie) so browser restarts don't trigger a
    # spurious redirect-to-authentik-and-back when the refresh token is still valid.
    response.set_cookie(
        "logged_in",
        "1",
        httponly=False,
        secure=sec,
        samesite="lax",
        max_age=_REFRESH_MAX_AGE,
    )
    # JS-readable expiry hint so the frontend can skip the /me round-trip on page load when
    # the access token is still fresh. Falls back to the normal refresh flow if absent/expired.
    if access_token_ttl:
        response.set_cookie(
            "token_expires_at",
            str(int(time.time()) + access_token_ttl),
            httponly=False,
            secure=sec,
            samesite="lax",
            max_age=access_token_ttl,
        )


def _clear_auth_cookies(response: Response) -> None:
    sec = _cookie_secure()
    response.delete_cookie(
        "access_token",
        path="/",
        secure=sec,
        httponly=True,
        samesite="lax",
    )
    response.delete_cookie(
        "refresh_token",
        path="/",
        secure=sec,
        httponly=True,
        samesite="lax",
    )
    response.delete_cookie(
        "logged_in",
        path="/",
        secure=sec,
        httponly=False,
        samesite="lax",
    )
    response.delete_cookie(
        "token_expires_at",
        path="/",
        secure=sec,
        httponly=False,
        samesite="lax",
    )


class CallbackRequest(BaseModel):
    code: str
    code_verifier: str


@router.get("/dev-login")
async def auth_dev_login(response: Response):
    if not settings.dev_auth_bypass:
        raise HTTPException(status_code=404)
    _set_auth_cookies(response, "dev", "dev")
    return {"ok": True}


@router.post("/callback")
async def auth_callback(req: CallbackRequest, response: Response):
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
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
    except httpx.HTTPError as e:
        log.warning("auth_callback_http_error", error=str(e))
        raise HTTPException(status_code=503, detail="Authentication service unreachable")
    if r.status_code != 200:
        raise HTTPException(status_code=401, detail="Token exchange failed")
    tokens = r.json()
    _set_auth_cookies(response, tokens["access_token"], tokens.get("refresh_token", ""), tokens.get("expires_in"))
    return {"ok": True, "access_token": tokens["access_token"], "expires_in": tokens.get("expires_in")}


@router.post("/refresh")
async def auth_refresh(request: Request, response: Response):
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=401, detail="No refresh token")
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            r = await client.post(
                settings.authentik_token_url,
                data={
                    "grant_type": "refresh_token",
                    "client_id": settings.authentik_client_id,
                    "refresh_token": refresh_token,
                },
            )
    except httpx.HTTPError as e:
        log.warning("auth_refresh_http_error", error=str(e))
        raise HTTPException(status_code=503, detail="Authentication service unreachable")
    if r.status_code != 200:
        raise HTTPException(status_code=401, detail="Refresh failed")
    tokens = r.json()
    _set_auth_cookies(response, tokens["access_token"], tokens["refresh_token"], tokens.get("expires_in"))
    return {"ok": True, "access_token": tokens["access_token"], "expires_in": tokens.get("expires_in")}


@router.post("/logout")
async def auth_logout(response: Response):
    _clear_auth_cookies(response)
    return {"ok": True}


@router.get("/me")
async def auth_me(request: Request):
    token = _resolve_raw_access_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if settings.dev_auth_bypass:
        if token == "dev":
            return {"sub": "dev-user", "email": "dev@local"}
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = await _decode_token(token)
    return {"sub": payload["sub"], "email": payload.get("email")}
