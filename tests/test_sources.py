import asyncio
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.main import app
from app.models import Source, Workspace
from app.routes.wiki import _workspace_id
from jwt_test_helpers import make_access_token, mock_jwks


@pytest.mark.asyncio
async def test_ingest_file_stores_filename():
    cookies = {"access_token": make_access_token(sub="sources-filename-test")}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with mock_jwks():
            with patch("app.routes.ingest._run_pipeline"):
                r = await client.post(
                    "/ingest/file",
                    files={
                        "file": (
                            "My Report.pdf",
                            b"%PDF-1.4",
                            "application/pdf",
                        )
                    },
                    cookies=cookies,
                )
                assert r.status_code == 200
                source_id = r.json()["source_id"]
                async with AsyncSessionLocal() as session:
                    result = await session.execute(
                        select(Source).where(Source.id == source_id)
                    )
                    row = result.scalar_one_or_none()
                    assert row is not None
                    assert row.filename == "My Report.pdf"


@pytest.mark.asyncio
async def test_list_sources_empty():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with mock_jwks():
            token = make_access_token(sub="listuser@test.example")
            r = await client.get("/sources", cookies={"access_token": token})
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_list_sources_returns_own_newest_first():
    user = "listorder@test.example"
    ws_id = _workspace_id(user)

    async with AsyncSessionLocal() as session:
        session.add(Workspace(id=ws_id, user_id=user))
        session.add(Source(workspace_id=ws_id, kind="pdf", filename="old.pdf", status="done"))
        await session.flush()
        await asyncio.sleep(0.01)  # ensure distinct created_at
        session.add(Source(workspace_id=ws_id, kind="md", filename="new.md", status="done"))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with mock_jwks():
            token = make_access_token(sub=user)
            r = await client.get("/sources", cookies={"access_token": token})

    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    assert data[0]["filename"] == "new.md"
    assert data[1]["filename"] == "old.pdf"


@pytest.mark.asyncio
async def test_list_sources_workspace_isolation():
    user_a = "usera@test.example"
    ws_a = _workspace_id(user_a)

    async with AsyncSessionLocal() as session:
        session.add(Workspace(id=ws_a, user_id=user_a))
        session.add(
            Source(workspace_id=ws_a, kind="pdf", filename="secret.pdf", status="done")
        )
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with mock_jwks():
            token_b = make_access_token(sub="userb@test.example")
            r = await client.get("/sources", cookies={"access_token": token_b})

    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_get_source_file_returns_bytes():
    user = "filedownload@test.example"
    ws_id = _workspace_id(user)
    file_data = b"%PDF-1.4 fake content"

    async with AsyncSessionLocal() as session:
        session.add(Workspace(id=ws_id, user_id=user))
        source = Source(
            workspace_id=ws_id,
            kind="pdf",
            filename="report.pdf",
            s3_key=f"{ws_id}/report.pdf",
            status="done",
        )
        session.add(source)
        await session.commit()
        source_id = source.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with mock_jwks():
            token = make_access_token(sub=user)
            with patch("app.routes.sources.download_file", return_value=file_data):
                r = await client.get(
                    f"/sources/{source_id}/file", cookies={"access_token": token}
                )

    assert r.status_code == 200
    assert r.content == file_data
    assert r.headers["content-type"] == "application/pdf"


@pytest.mark.asyncio
async def test_get_source_file_404_no_s3_key():
    user = "fileno@test.example"
    ws_id = _workspace_id(user)

    async with AsyncSessionLocal() as session:
        session.add(Workspace(id=ws_id, user_id=user))
        source = Source(
            workspace_id=ws_id,
            kind="url",
            filename="https://example.com",
            s3_key=None,
            status="done",
        )
        session.add(source)
        await session.commit()
        source_id = source.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with mock_jwks():
            token = make_access_token(sub=user)
            r = await client.get(
                f"/sources/{source_id}/file", cookies={"access_token": token}
            )

    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_source_file_404_wrong_workspace():
    owner = "fileowner@test.example"
    ws_id = _workspace_id(owner)

    async with AsyncSessionLocal() as session:
        session.add(Workspace(id=ws_id, user_id=owner))
        source = Source(
            workspace_id=ws_id,
            kind="pdf",
            filename="private.pdf",
            s3_key=f"{ws_id}/f.pdf",
            status="done",
        )
        session.add(source)
        await session.commit()
        source_id = source.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with mock_jwks():
            token = make_access_token(sub="intruder@test.example")
            r = await client.get(
                f"/sources/{source_id}/file", cookies={"access_token": token}
            )

    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_source_markdown_returns_text():
    user = "mddownload@test.example"
    ws_id = _workspace_id(user)
    md_content = b"# Hello\n\nThis is the markdown."

    async with AsyncSessionLocal() as session:
        session.add(Workspace(id=ws_id, user_id=user))
        source = Source(
            workspace_id=ws_id,
            kind="pdf",
            filename="report.pdf",
            s3_key=f"{ws_id}/report.pdf",
            markdown_s3_key=f"{ws_id}/converted.md",
            status="done",
        )
        session.add(source)
        await session.commit()
        source_id = source.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with mock_jwks():
            token = make_access_token(sub=user)
            with patch("app.routes.sources.download_file", return_value=md_content):
                r = await client.get(
                    f"/sources/{source_id}/markdown",
                    cookies={"access_token": token},
                )

    assert r.status_code == 200
    assert b"# Hello" in r.content
    assert "text/markdown" in r.headers["content-type"]


@pytest.mark.asyncio
async def test_get_source_markdown_404_no_key():
    user = "mdnone@test.example"
    ws_id = _workspace_id(user)

    async with AsyncSessionLocal() as session:
        session.add(Workspace(id=ws_id, user_id=user))
        source = Source(
            workspace_id=ws_id,
            kind="pdf",
            filename="r.pdf",
            s3_key=f"{ws_id}/r.pdf",
            status="converting",
        )
        session.add(source)
        await session.commit()
        source_id = source.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with mock_jwks():
            token = make_access_token(sub=user)
            r = await client.get(
                f"/sources/{source_id}/markdown",
                cookies={"access_token": token},
            )

    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_source_markdown_404_wrong_workspace():
    owner = "mdowner@test.example"
    ws_id = _workspace_id(owner)

    async with AsyncSessionLocal() as session:
        session.add(Workspace(id=ws_id, user_id=owner))
        source = Source(
            workspace_id=ws_id,
            kind="pdf",
            filename="private.pdf",
            s3_key=f"{ws_id}/p.pdf",
            markdown_s3_key=f"{ws_id}/p.md",
            status="done",
        )
        session.add(source)
        await session.commit()
        source_id = source.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with mock_jwks():
            token = make_access_token(sub="intruder2@test.example")
            r = await client.get(
                f"/sources/{source_id}/markdown",
                cookies={"access_token": token},
            )

    assert r.status_code == 404
