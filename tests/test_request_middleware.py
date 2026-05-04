import json
import logging

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_request_middleware_logs_request(caplog):
    # structlog is configured with stdlib LoggerFactory; capture_logs() does not see those events.
    with caplog.at_level(logging.INFO):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/health")

    assert response.status_code == 200
    request_logs = []
    for r in caplog.records:
        msg = getattr(r, "msg", None)
        if isinstance(msg, dict) and msg.get("event") == "request":
            request_logs.append(msg)
            continue
        try:
            data = json.loads(r.getMessage())
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and data.get("event") == "request":
            request_logs.append(data)

    assert len(request_logs) == 1
    log_entry = request_logs[0]
    assert log_entry["method"] == "GET"
    assert log_entry["path"] == "/health"
    assert log_entry["status"] == 200
    assert "latency_ms" in log_entry
