import asyncio
import json
from typing import AsyncIterator


class SSEBroadcaster:
    def __init__(self):
        self._queues: list[asyncio.Queue] = []

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        if q in self._queues:
            self._queues.remove(q)

    async def publish(self, event: dict):
        data = json.dumps(event)
        for q in list(self._queues):
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
