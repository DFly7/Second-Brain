import os
from contextlib import asynccontextmanager
from datetime import datetime
from urllib.parse import urlparse, urlunparse

import litellm
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.logging_config import configure_logging

configure_logging()

import structlog  # noqa: E402 — must import after configure_logging()
from app.middleware import RequestLoggingMiddleware  # noqa: E402

litellm.suppress_debug_info = True

log = structlog.get_logger()


def _sanitize_redis_url_for_log(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.password:
        return url
    user = parsed.username or ""
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    if user:
        netloc = f"{user}:****@{host}{port}"
    elif host:
        netloc = f":****@{host}{port}"
    else:
        netloc = ":****"
    sanitized = parsed._replace(netloc=netloc)
    return urlunparse(sanitized)

from app.auth import router as auth_router  # noqa: E402
from app.routes.activity import router as activity_router  # noqa: E402
from app.routes.automations import router as automations_router  # noqa: E402
from app.routes.browser_chat import router as browser_chat_router  # noqa: E402
from app.routes.chat import router as chat_router  # noqa: E402
from app.routes.health import router as health_router  # noqa: E402
from app.routes.ingest import router as ingest_router  # noqa: E402
from app.routes.sources import router as sources_router  # noqa: E402
from app.routes.wiki import router as wiki_router  # noqa: E402


async def _browser_chat_reaper() -> None:
    import asyncio
    from datetime import timedelta

    import httpx
    from sqlalchemy import select

    from app.database import AsyncSessionLocal
    from app.models import BrowserChatSession

    while True:
        await asyncio.sleep(300)  # every 5 minutes
        try:
            async with AsyncSessionLocal() as db:
                cutoff = datetime.utcnow() - timedelta(minutes=20)
                result = await db.execute(
                    select(BrowserChatSession).where(
                        BrowserChatSession.status == "active",
                        BrowserChatSession.last_activity_at < cutoff,
                    )
                )
                stale = result.scalars().all()
                for sess in stale:
                    if sess.browser_session_id:
                        from app.config import settings as _s

                        async with httpx.AsyncClient(base_url=_s.browser_agent_url, timeout=10.0) as http:
                            try:
                                await http.post(f"/session/{sess.browser_session_id}/close")
                            except Exception:
                                pass
                    sess.status = "completed"
                    sess.completed_at = datetime.utcnow()
                    log.warning("browser_chat_session_reaped", session_id=sess.id)
                if stale:
                    await db.commit()
        except Exception as exc:
            log.error("browser_chat_reaper_error", error=str(exc))


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio

    from app.sse import broadcaster

    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379")
    from app.config import settings
    log.info("startup", redis_url=_sanitize_redis_url_for_log(redis_url))
    if settings.dev_auth_bypass:
        log.warning("dev_auth_bypass_enabled", hint="all JWT validation is disabled — set DEV_AUTH_BYPASS=false in production")
    await broadcaster.connect(redis_url)
    reaper_task = asyncio.create_task(_browser_chat_reaper())
    yield
    reaper_task.cancel()
    await broadcaster.disconnect()
    log.info("shutdown")


app = FastAPI(title="LLM Wiki", lifespan=lifespan)

app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "https://smoothstudy.ai"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(wiki_router)
app.include_router(ingest_router)
app.include_router(chat_router)
app.include_router(activity_router)
app.include_router(health_router)
app.include_router(sources_router)
app.include_router(automations_router)
app.include_router(browser_chat_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
