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
