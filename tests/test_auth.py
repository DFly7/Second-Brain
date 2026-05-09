import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport

from app.main import app
from jwt_test_helpers import make_access_token, mock_jwks


@pytest.mark.asyncio
async def test_me_returns_sub_when_authenticated():
    token = make_access_token(sub="abc-123-uuid")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with mock_jwks():
            resp = await client.get("/auth/me", cookies={"access_token": token})
    assert resp.status_code == 200
    assert resp.json()["sub"] == "abc-123-uuid"


@pytest.mark.asyncio
async def test_get_current_user_accepts_bearer_token():
    token = make_access_token(sub="mobile-user-456")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with mock_jwks():
            resp = await client.get(
                "/auth/me",
                headers={"Authorization": f"Bearer {token}"},
            )
    assert resp.status_code == 200
    assert resp.json()["sub"] == "mobile-user-456"


@pytest.mark.asyncio
async def test_get_current_user_cookie_takes_precedence_over_bearer():
    cookie_token = make_access_token(sub="cookie-user")
    bearer_token = make_access_token(sub="bearer-user")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with mock_jwks():
            resp = await client.get(
                "/auth/me",
                cookies={"access_token": cookie_token},
                headers={"Authorization": f"Bearer {bearer_token}"},
            )
    assert resp.status_code == 200
    assert resp.json()["sub"] == "cookie-user"


@pytest.mark.asyncio
async def test_get_current_user_returns_401_with_no_token():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with mock_jwks():
            resp = await client.get("/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_returns_401_with_no_cookie():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with mock_jwks():
            resp = await client.get("/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_returns_401_with_expired_token():
    token = make_access_token(expired=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with mock_jwks():
            resp = await client.get("/auth/me", cookies={"access_token": token})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_callback_sets_cookies_on_success():
    fake_tokens = {
        "access_token": make_access_token(),
        "refresh_token": "fake-refresh-token",
        "token_type": "Bearer",
    }
    mock_response = MagicMock()
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
    mock_response = MagicMock()
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


@pytest.mark.asyncio
async def test_refresh_sets_new_cookies():
    fake_tokens = {
        "access_token": make_access_token(),
        "refresh_token": "new-refresh-token",
        "token_type": "Bearer",
    }
    mock_response = MagicMock()
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


@pytest.mark.asyncio
async def test_logout_clears_cookies():
    token = make_access_token()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with mock_jwks():
            resp = await client.post("/auth/logout", cookies={"access_token": token})
    assert resp.status_code == 200
    assert resp.cookies.get("access_token", "") == ""
    assert resp.cookies.get("refresh_token", "") == ""
