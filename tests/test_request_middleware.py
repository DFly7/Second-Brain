import structlog
import structlog.testing
import pytest
from httpx import AsyncClient, ASGITransport

from app.logging_config import configure_logging
from app.main import app
import app.middleware as request_middleware


@pytest.mark.asyncio
async def test_request_middleware_logs_request():
    configure_logging()
    with structlog.testing.capture_logs() as cap:
        # Rebind so this logger uses the capture_logs processor chain (module log may be stale).
        request_middleware.log = structlog.get_logger()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/health")

    assert response.status_code == 200
    request_logs = [e for e in cap if e.get("event") == "request"]
    assert len(request_logs) == 1
    log = request_logs[0]
    assert log["method"] == "GET"
    assert log["path"] == "/health"
    assert log["status"] == 200
    assert "latency_ms" in log
