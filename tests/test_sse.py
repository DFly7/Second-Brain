import asyncio
import json
import pytest
import pytest_asyncio
from app.sse import SSEBroadcaster


@pytest_asyncio.fixture(loop_scope="function")
async def broadcaster():
    b = SSEBroadcaster()
    b.connect("redis://redis:6379")
    yield b
    await b.disconnect()


@pytest.mark.asyncio
async def test_publish_delivered_to_subscriber(broadcaster):
    pubsub = await broadcaster.subscribe("user-pub-1")
    await broadcaster.publish({"event": "agent:done"}, audience_user_id="user-pub-1")
    await asyncio.sleep(0.05)
    msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
    assert msg is not None
    assert json.loads(msg["data"]) == {"event": "agent:done"}
    await broadcaster.unsubscribe(pubsub)


@pytest.mark.asyncio
async def test_publish_not_delivered_to_wrong_user(broadcaster):
    pubsub = await broadcaster.subscribe("user-other")
    await broadcaster.publish({"event": "agent:done"}, audience_user_id="user-target")
    await asyncio.sleep(0.05)
    msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
    assert msg is None
    await broadcaster.unsubscribe(pubsub)


@pytest.mark.asyncio
async def test_stream_yields_data_chunk(broadcaster):
    pubsub = await broadcaster.subscribe("user-stream-1")
    await broadcaster.publish({"event": "agent:reading", "slug": "my-page"}, audience_user_id="user-stream-1")
    await asyncio.sleep(0.05)
    gen = broadcaster.stream(pubsub, keepalive_timeout=1.0)
    chunk = await gen.__anext__()
    assert chunk == 'data: {"event": "agent:reading", "slug": "my-page"}\n\n'
    await broadcaster.unsubscribe(pubsub)


@pytest.mark.asyncio
async def test_stream_sends_keepalive_when_idle(broadcaster):
    pubsub = await broadcaster.subscribe("user-keepalive")
    gen = broadcaster.stream(pubsub, keepalive_timeout=0.1)
    chunk = await gen.__anext__()
    assert chunk == ": keepalive\n\n"
    await broadcaster.unsubscribe(pubsub)


@pytest.mark.asyncio
async def test_publish_survives_redis_connection_error():
    from unittest.mock import AsyncMock, patch
    b = SSEBroadcaster()
    b.connect("redis://redis:6379")
    with patch.object(b, "_client") as mock_client:
        mock_redis = AsyncMock()
        mock_redis.publish.side_effect = ConnectionError("Redis down")
        mock_client.return_value = mock_redis
        # Must not raise — core pipeline callers must not crash on Redis blip
        await b.publish({"event": "agent:done"}, audience_user_id="user-x")
    await b.disconnect()


@pytest.mark.asyncio
async def test_multiple_subscribers_same_user_both_receive(broadcaster):
    pubsub_a = await broadcaster.subscribe("user-multi")
    pubsub_b = await broadcaster.subscribe("user-multi")
    await broadcaster.publish({"event": "health:done"}, audience_user_id="user-multi")
    await asyncio.sleep(0.05)
    msg_a = await pubsub_a.get_message(ignore_subscribe_messages=True, timeout=1.0)
    msg_b = await pubsub_b.get_message(ignore_subscribe_messages=True, timeout=1.0)
    assert msg_a is not None
    assert msg_b is not None
    await broadcaster.unsubscribe(pubsub_a)
    await broadcaster.unsubscribe(pubsub_b)
