import logging
import sys

import litellm
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth import router as auth_router
from app.routes.activity import router as activity_router
from app.routes.chat import router as chat_router
from app.routes.health import router as health_router
from app.routes.ingest import router as ingest_router
from app.routes.wiki import router as wiki_router


def _configure_app_logging() -> None:
    log = logging.getLogger("app")
    if log.handlers:
        return
    log.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    )
    log.addHandler(handler)
    log.propagate = False


_configure_app_logging()
logging.getLogger("LiteLLM").setLevel(logging.WARNING)
logging.getLogger("litellm").setLevel(logging.WARNING)
litellm.suppress_debug_info = True

app = FastAPI(title="LLM Wiki")

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
