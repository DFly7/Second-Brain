import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app


async def _token(client: AsyncClient) -> str:
    resp = await client.post(
        "/auth/login",
        json={"email": "user@example.com", "password": "changeme"},
    )
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_health_run_returns_202():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        token = await _token(client)
        resp = await client.post(
            "/health/run",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 202
        assert resp.json() == {"status": "health check started"}
