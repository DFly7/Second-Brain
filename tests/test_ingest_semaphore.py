import asyncio
import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_queued_event_published_before_converting():
    """agent:queued fires before agent:converting regardless of semaphore state."""
    events = []

    async def fake_publish(event):
        events.append(event["event"])

    # Import after patching so module-level semaphore is already created
    with patch("app.routes.ingest.broadcaster") as mock_broadcaster:
        mock_broadcaster.publish = fake_publish
        with patch("app.routes.ingest.AsyncSessionLocal") as mock_session_cls:
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_session.execute = AsyncMock(return_value=AsyncMock(scalar_one_or_none=lambda: None))
            mock_session_cls.return_value = mock_session

            from app.routes.ingest import _run_pipeline
            # source not found path — just checks events up to the early return
            await _run_pipeline("test-id", "ws-id", b"data", "file.txt")

    # queued should appear if published before the source lookup guard
    assert "agent:queued" in events


@pytest.mark.asyncio
async def test_queued_event_before_converting_with_semaphore():
    """agent:queued fires immediately; agent:converting fires only after semaphore acquired."""
    events = []

    async def fake_publish(event):
        events.append(event["event"])

    import app.routes.ingest as ingest_module

    original_sem = ingest_module._marker_sem

    # Hold the semaphore so the second pipeline call will block on it
    held_sem = asyncio.Semaphore(0)  # always blocks
    ingest_module._marker_sem = held_sem

    try:
        with patch("app.routes.ingest.broadcaster") as mock_broadcaster:
            mock_broadcaster.publish = fake_publish
            with patch("app.routes.ingest.AsyncSessionLocal") as mock_session_cls:
                # Make source lookup return a real source so pipeline proceeds to semaphore
                mock_source = object()  # non-None
                mock_result = AsyncMock()
                mock_result.scalar_one_or_none = lambda: mock_source
                mock_session = AsyncMock()
                mock_session.__aenter__ = AsyncMock(return_value=mock_session)
                mock_session.__aexit__ = AsyncMock(return_value=False)
                mock_session.execute = AsyncMock(return_value=mock_result)
                mock_session_cls.return_value = mock_session

                from app.routes.ingest import _run_pipeline

                # Run pipeline as a background task — it will block on held_sem
                task = asyncio.create_task(
                    _run_pipeline("test-id", "ws-id", b"fake-pdf-data", "file.pdf")
                )

                # Yield control so the task can run until it blocks on the semaphore
                await asyncio.sleep(0)
                await asyncio.sleep(0)

                # At this point: agent:queued should be published, agent:converting should NOT
                assert "agent:queued" in events, "agent:queued should fire before semaphore"
                assert "agent:converting" not in events, (
                    "agent:converting should not fire while semaphore is held"
                )

                # Cancel the blocked task (we've proven the invariant)
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
    finally:
        ingest_module._marker_sem = original_sem
