import pytest
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport

from jwt_test_helpers import make_access_token, mock_jwks


@pytest.fixture
def ingest_cookies():
    return {"access_token": make_access_token(sub="ingest@test.example")}


@pytest.mark.asyncio
async def test_ingest_file_accepts_pdf(ingest_cookies):
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with mock_jwks():
            with patch("app.routes.ingest._run_pipeline"):
                response = await client.post(
                    "/ingest/file",
                    files={"file": ("doc.pdf", b"%PDF-1.4", "application/pdf")},
                    cookies=ingest_cookies,
                )
    assert response.status_code == 200
    assert response.json()["status"] == "converting"


@pytest.mark.asyncio
async def test_ingest_file_accepts_pptx(ingest_cookies):
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with mock_jwks():
            with patch("app.routes.ingest._run_pipeline"):
                response = await client.post(
                    "/ingest/file",
                    files={
                        "file": (
                            "slides.pptx",
                            b"PK\x03\x04",
                            "application/octet-stream",
                        )
                    },
                    cookies=ingest_cookies,
                )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_ingest_file_accepts_png(ingest_cookies):
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with mock_jwks():
            with patch("app.routes.ingest._run_pipeline"):
                response = await client.post(
                    "/ingest/file",
                    files={"file": ("photo.png", b"\x89PNG\r\n", "image/png")},
                    cookies=ingest_cookies,
                )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_ingest_file_rejects_unsupported(ingest_cookies):
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with mock_jwks():
            with patch("app.routes.ingest._run_pipeline"):
                response = await client.post(
                    "/ingest/file",
                    files={
                        "file": ("script.exe", b"MZ", "application/octet-stream")
                    },
                    cookies=ingest_cookies,
                )
    assert response.status_code == 400
