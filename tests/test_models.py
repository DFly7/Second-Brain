import pytest


@pytest.mark.asyncio
async def test_source_page_can_be_created():
    from app.database import AsyncSessionLocal
    from app.models import Source, SourcePage, Workspace

    async with AsyncSessionLocal() as session:
        ws = Workspace(user_id="u1")
        session.add(ws)
        await session.flush()
        src = Source(workspace_id=ws.id, kind="pdf", status="done")
        session.add(src)
        await session.flush()
        page = SourcePage(
            source_id=src.id,
            page_num=1,
            markdown="# Hello",
            preview="# Hello",
            image_s3_keys=[],
        )
        session.add(page)
        await session.commit()
        await session.refresh(page)
        assert page.id is not None
        assert page.page_num == 1
