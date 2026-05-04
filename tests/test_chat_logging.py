import pytest
import structlog
import structlog.testing
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport

import app.routes.chat as chat_routes
from app.logging_config import configure_logging
from app.main import app
from jwt_test_helpers import make_access_token, mock_jwks


@pytest.mark.asyncio
async def test_chat_message_logs_query():
    configure_logging()
    with structlog.testing.capture_logs() as cap:
        chat_routes._log = structlog.get_logger()
        with patch("app.routes.chat.run_query", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = ("answer text", ["wiki/page"])
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                with mock_jwks():
                    token = make_access_token(sub="chat-log@test.example")
                    client.cookies.set("access_token", token)
                    response = await client.post(
                        "/chat/message",
                        json={"message": "hello", "mode": "query"},
                    )

    if response.status_code == 200:
        events = [e["event"] for e in cap]
        assert "chat_message_received" in events
        assert "chat_message_answered" in events
