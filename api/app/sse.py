import asyncio
import json
from collections import defaultdict
from typing import AsyncIterator


class SSEBroadcaster:
    """In-process fan-out of SSE events, scoped by authenticated user id (OIDC sub)."""

    def __init__(self):
        self._queues: dict[str, list[asyncio.Queue]] = defaultdict(list)

    def subscribe(self, user_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._queues[user_id].append(q)
        return q

    def unsubscribe(self, user_id: str, q: asyncio.Queue):
        lst = self._queues.get(user_id)
        if not lst:
            return
        if q in lst:
            lst.remove(q)
        if not lst:
            del self._queues[user_id]

    async def publish(self, event: dict, *, audience_user_id: str):
        data = json.dumps(event)
        for q in list(self._queues.get(audience_user_id, [])):
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                # Drop messages for slow consumers to avoid blocking others.
                pass

    async def stream(self, q: asyncio.Queue) -> AsyncIterator[str]:
        # Timeout handler must stay inside the loop; otherwise the first idle
        # period ends the async generator and the client disconnects (bad for
        # long Marker runs between agent:converting and agent:ingesting).
        while True:
            try:
                data = await asyncio.wait_for(q.get(), timeout=30)
                yield f"data: {data}\n\n"
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"


broadcaster = SSEBroadcaster()
