import logging
import os
import time

import httpx

log = logging.getLogger("app.auth")
from authlib.jose import JsonWebKey, jwt
from authlib.jose.errors import JoseError
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from app.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])

_jwks_cache = None
_jwks_fetched_at: float = 0.0
_JWKS_TTL = 300  # 5 minutes


def reset_jwks_cache() -> None:
    global _jwks_cache, _jwks_fetched_at
    _jwks_cache = None
    _jwks_fetched_at = 0.0


def _cookie_secure() -> bool:
    if os.environ.get("PYTEST_VERSION") is not None:
        return False
    return settings.authentik_redirect_uri.startswith("https://")


async def _fetch_jwks():
    async with httpx.AsyncClient() as client:
        r = await client.get(settings.authentik_jwks_uri)
        r.raise_for_status()
    return JsonWebKey.import_key_set(r.json())


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
    except JoseError:
        # Key may have rotated — bust cache and retry once
        reset_jwks_cache()
        try:
            jwks = await _get_jwks()
            claims = jwt.decode(token, jwks)
            claims.validate()
            payload = dict(claims)
        except JoseError:
            raise HTTPException(status_code=401, detail="Invalid token")
    if payload.get("iss") != settings.authentik_issuer:
        raise HTTPException(status_code=401, detail="Invalid token")
    if payload.get("sub") is None:
        raise HTTPException(status_code=401, detail="Invalid token")
    return payload


async def get_current_user(request: Request) -> str:
    token = request.cookies.get("access_token")
    if not token:
        log.warning("get_current_user: no access_token cookie on %s", request.url.path)
        raise HTTPException(status_code=401, detail="Not authenticated")
    if settings.dev_auth_bypass:
        if token == "dev":
            return "dev-user"
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = await _decode_token(token)
    except HTTPException as e:
        log.warning("get_current_user: token validation failed on %s: %s", request.url.path, e.detail)
        raise
    return str(payload["sub"])


_REFRESH_MAX_AGE = 30 * 24 * 3600  # 30 days — match typical authentik refresh token lifetime


def _set_auth_cookies(
    response: Response, access_token: str, refresh_token: str, access_token_ttl: int | None = None
) -> None:
    sec = _cookie_secure()
    response.set_cookie(
        "access_token",
        access_token,
        httponly=True,
        secure=sec,
        samesite="strict",
        max_age=access_token_ttl,  # None = session cookie; set from token response expires_in
    )
    response.set_cookie(
        "refresh_token",
        refresh_token,
        httponly=True,
        secure=sec,
        samesite="strict",
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
        samesite="strict",
        max_age=_REFRESH_MAX_AGE,
    )


def _clear_auth_cookies(response: Response) -> None:
    sec = _cookie_secure()
    response.delete_cookie(
        "access_token",
        path="/",
        secure=sec,
        httponly=True,
        samesite="strict",
    )
    response.delete_cookie(
        "refresh_token",
        path="/",
        secure=sec,
        httponly=True,
        samesite="strict",
    )
    response.delete_cookie(
        "logged_in",
        path="/",
        secure=sec,
        httponly=False,
        samesite="strict",
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
    _set_auth_cookies(response, tokens["access_token"], tokens.get("refresh_token", ""), tokens.get("expires_in"))
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
    _set_auth_cookies(response, tokens["access_token"], tokens["refresh_token"], tokens.get("expires_in"))
    return {"ok": True}


@router.post("/logout")
async def auth_logout(response: Response):
    _clear_auth_cookies(response)
    return {"ok": True}


@router.get("/me")
async def auth_me(request: Request):
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if settings.dev_auth_bypass:
        if token == "dev":
            return {"sub": "dev-user", "email": "dev@local"}
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = await _decode_token(token)
    return {"sub": payload["sub"], "email": payload.get("email")}
