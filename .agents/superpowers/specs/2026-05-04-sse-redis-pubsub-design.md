# SSE Redis Pub/Sub Design

**Date:** 2026-05-04  
**Status:** Approved

## Problem

The `SSEBroadcaster` in `api/app/sse.py` uses in-memory `asyncio.Queue` objects. Events published by a background task in worker N are only visible to SSE clients connected to worker N. This forces gunicorn to run a single worker (`-w 1`), limiting throughput and reliability.

## Goal

Enable multiple gunicorn workers on a single Docker host while keeping SSE event delivery correct and user-scoped.

## Approach: Redis Pub/Sub

Each connected SSE client subscribes to a Redis channel named `sse:{user_id}`. Any worker can publish to that channel. The worker holding the SSE connection receives the message via its Redis subscription and forwards it to the client.

## Components

### Redis service
- New `redis` service in `docker-compose.yml` and `docker-compose.prod.yml`
- Image: `redis:7-alpine`
- No persistence needed (events are ephemeral)
- Exposed only on the internal Docker network

### Dependency
- Add `redis[asyncio]` (redis-py ≥ 4.0) to `requirements.txt` and `requirements-prod.txt`

### `api/app/sse.py` — rewrite `SSEBroadcaster`

**Channel naming:** `sse:{user_id}`

**Publishing** (called from background tasks / agents):
- Create a single shared async Redis connection pool for publishing
- `publish(event, user_id)` serialises the event to JSON and calls `redis.publish(f"sse:{user_id}", payload)`

**Subscribing** (called from the SSE endpoint per connected client):
- `subscribe(user_id)` opens a new `redis.asyncio.client.PubSub` instance and subscribes to `sse:{user_id}`
- Returns the pubsub handle to the caller
- `stream(pubsub)` is an async generator that calls `pubsub.get_message(ignore_subscribe_messages=True, timeout=30)` in a loop, yielding SSE-formatted data; sends `: keepalive\n\n` on timeout
- `unsubscribe(pubsub)` calls `pubsub.unsubscribe()` and `pubsub.close()`

**Lifespan:**
- Redis connection pool is initialised in the FastAPI lifespan startup and torn down on shutdown
- Pool is injected into `SSEBroadcaster` (or stored as a module-level singleton — same pattern as today)

### `api/app/routes/chat.py` — no changes to route logic
The route already calls `broadcaster.subscribe`, `broadcaster.stream`, and `broadcaster.unsubscribe`. Only the signatures of those methods change (they accept/return a pubsub handle instead of an `asyncio.Queue`).

### `api/Dockerfile.prod` — increase workers
Change `-w 1` to `-w 4` (or make it an env var `WEB_CONCURRENCY`).

## Data Flow

```
Background task (any worker)
  → broadcaster.publish(event, user_id)
    → redis PUBLISH sse:{user_id} <json>
      → Redis server fans out to all subscribers on that channel
        → worker holding SSE connection receives message
          → stream() yields SSE line to client
```

## What Does Not Change

- SSE endpoint path and authentication
- Event payload format (same JSON dicts)
- All agent/ingest/chat code that calls `broadcaster.publish()`
- 30-second keepalive behaviour

## Not In Scope

- Redis persistence / AOF
- Replaying missed events on reconnect
- Extracting agents to a separate container
- Horizontal multi-host scaling (single Docker host only)
