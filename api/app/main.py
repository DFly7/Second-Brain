import os
from contextlib import asynccontextmanager
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
from app.routes.chat import router as chat_router  # noqa: E402
from app.routes.health import router as health_router  # noqa: E402
from app.routes.ingest import router as ingest_router  # noqa: E402
from app.routes.wiki import router as wiki_router  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.sse import broadcaster

    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379")
    log.info("startup", redis_url=_sanitize_redis_url_for_log(redis_url))
    await broadcaster.connect(redis_url)
    yield
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


@app.get("/health")
async def health():
    return {"status": "ok"}
