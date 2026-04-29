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
async def test_create_and_get_page():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        token = await _token(client)
        headers = {"Authorization": f"Bearer {token}"}

        create = await client.post(
            "/wiki/pages",
            json={
                "slug": "test-page",
                "title": "Test Page",
                "body_md": "# Test\n\nHello [[other-page]].",
            },
            headers=headers,
        )
        assert create.status_code == 201

        get = await client.get("/wiki/pages/test-page", headers=headers)
        assert get.status_code == 200
        assert get.json()["title"] == "Test Page"


@pytest.mark.asyncio
async def test_list_pages():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        token = await _token(client)
        headers = {"Authorization": f"Bearer {token}"}

        resp = await client.get("/wiki/pages", headers=headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_update_page():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        token = await _token(client)
        headers = {"Authorization": f"Bearer {token}"}

        await client.post(
            "/wiki/pages",
            json={"slug": "update-me", "title": "Old", "body_md": "old"},
            headers=headers,
        )

        resp = await client.put(
            "/wiki/pages/update-me",
            json={"title": "New", "body_md": "new content"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "New"


@pytest.mark.asyncio
async def test_folder_slug_create_and_get():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        token = await _token(client)
        headers = {"Authorization": f"Bearer {token}"}

        create = await client.post(
            "/wiki/pages",
            json={
                "slug": "people/alice-jones",
                "title": "Alice Jones",
                "body_md": "# Alice Jones\n\nFounder.",
                "summary": "Co-founder of Acme Corp",
            },
            headers=headers,
        )
        assert create.status_code == 201

        get = await client.get("/wiki/pages/people/alice-jones", headers=headers)
        assert get.status_code == 200
        assert get.json()["slug"] == "people/alice-jones"

        update = await client.put(
            "/wiki/pages/people/alice-jones",
            json={"summary": "Updated summary"},
            headers=headers,
        )
        assert update.status_code == 200

        delete = await client.delete(
            "/wiki/pages/people/alice-jones", headers=headers
        )
        assert delete.status_code == 204
