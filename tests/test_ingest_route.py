import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport


@pytest.fixture
def auth_headers():
    import os
    from jose import jwt

    token = jwt.encode(
        {"sub": os.environ["SINGLE_USER_EMAIL"]},
        os.environ["JWT_SECRET"],
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_ingest_file_accepts_pdf(auth_headers):
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch("app.routes.ingest._run_pipeline"):
            response = await client.post(
                "/ingest/file",
                files={"file": ("doc.pdf", b"%PDF-1.4", "application/pdf")},
                headers=auth_headers,
            )
    assert response.status_code == 200
    assert response.json()["status"] == "converting"


@pytest.mark.asyncio
async def test_ingest_file_accepts_pptx(auth_headers):
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch("app.routes.ingest._run_pipeline"):
            response = await client.post(
                "/ingest/file",
                files={"file": ("slides.pptx", b"PK\x03\x04", "application/octet-stream")},
                headers=auth_headers,
            )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_ingest_file_accepts_png(auth_headers):
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch("app.routes.ingest._run_pipeline"):
            response = await client.post(
                "/ingest/file",
                files={"file": ("photo.png", b"\x89PNG\r\n", "image/png")},
                headers=auth_headers,
            )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_ingest_file_rejects_unsupported(auth_headers):
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch("app.routes.ingest._run_pipeline"):
            response = await client.post(
                "/ingest/file",
                files={"file": ("script.exe", b"MZ", "application/octet-stream")},
                headers=auth_headers,
            )
    assert response.status_code == 400
