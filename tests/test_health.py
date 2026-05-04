import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from jwt_test_helpers import make_access_token, mock_jwks


@pytest.mark.asyncio
async def test_health_run_returns_202():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        with mock_jwks():
            token = make_access_token(sub="user@example.com")
            resp = await client.post(
                "/health/run",
                cookies={"access_token": token},
            )
        assert resp.status_code == 202
        assert resp.json() == {"status": "health check started"}
