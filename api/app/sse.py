import json
import logging
from typing import AsyncIterator

import redis.asyncio as aioredis
from redis.asyncio.client import PubSub

log = logging.getLogger("app.sse")


class SSEBroadcaster:
    """Fan-out of SSE events via Redis Pub/Sub, scoped by authenticated user id (OIDC sub)."""

    def __init__(self):
        self._pool: aioredis.ConnectionPool | None = None

    def connect(self, redis_url: str) -> None:
        self._pool = aioredis.ConnectionPool.from_url(redis_url)

    async def disconnect(self) -> None:
        if self._pool:
            await self._pool.disconnect()
            self._pool = None

    def _client(self) -> aioredis.Redis:
        return aioredis.Redis(connection_pool=self._pool)

    async def subscribe(self, user_id: str) -> PubSub:
        pubsub = self._client().pubsub()
        await pubsub.subscribe(f"sse:{user_id}")
        # Drain subscribe acknowledgement so the next get_message sees published data.
        await pubsub.get_message(ignore_subscribe_messages=False, timeout=2.0)
        return pubsub

    async def unsubscribe(self, pubsub: PubSub) -> None:
        await pubsub.unsubscribe()
        await pubsub.aclose()

    async def publish(self, event: dict, *, audience_user_id: str) -> None:
        try:
            client = self._client()
            try:
                await client.publish(f"sse:{audience_user_id}", json.dumps(event))
            finally:
                await client.aclose()
        except Exception as exc:
            # Redis being unavailable must not abort ingest, chat, or health pipelines.
            # The user just won't see the real-time UI update for this event.
            log.warning("SSE publish failed (Redis unavailable?): %s", exc)

    async def stream(self, pubsub: PubSub, keepalive_timeout: float = 30.0) -> AsyncIterator[str]:
        while True:
            msg = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=keepalive_timeout
            )
            if msg is not None:
                data = msg["data"]
                text = data.decode() if isinstance(data, bytes) else data
                yield f"data: {text}\n\n"
            else:
                yield ": keepalive\n\n"


broadcaster = SSEBroadcaster()
