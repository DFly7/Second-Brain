import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Force test credentials so docker-compose `env_file: .env` cannot override pytest.
os.environ["DATABASE_URL"] = "postgresql+asyncpg://wiki:wiki@db:5432/wiki_test"
os.environ["AUTHENTIK_ISSUER"] = (
    "https://auth.example.com/application/o/second-brain/"
)
os.environ["AUTHENTIK_JWKS_URI"] = (
    "https://auth.example.com/application/o/second-brain/jwks/"
)
os.environ["AUTHENTIK_CLIENT_ID"] = "second-brain"
os.environ["AUTHENTIK_TOKEN_URL"] = "https://auth.example.com/application/o/token/"
os.environ["AUTHENTIK_REDIRECT_URI"] = "https://smoothstudy.ai/callback"
os.environ.setdefault("LITELLM_MODEL", "gemini/gemini-2.0-flash")
os.environ.setdefault("S3_ENDPOINT", "http://localhost:9000")
os.environ["S3_BUCKET"] = "wiki-test"
os.environ.setdefault("S3_ACCESS_KEY", "minioadmin")
os.environ.setdefault("VECTOR_SEARCH_ENABLED", "true")
os.environ.setdefault("MARKER_URL", "http://marker:8001")
os.environ.setdefault("VISION_MODEL", "")

assert "test" in os.environ["DATABASE_URL"], (
    f"Refusing to run tests against non-test DB: {os.environ['DATABASE_URL']}"
)
assert "test" in os.environ["S3_BUCKET"], (
    f"Refusing to run tests against non-test S3 bucket: {os.environ['S3_BUCKET']}"
)

import pytest
import pytest_asyncio
from unittest.mock import MagicMock, patch
from sqlalchemy import text

from app.database import AsyncSessionLocal, Base, engine
import app.models  # noqa: F401
from app.models import Workspace


@pytest_asyncio.fixture(loop_scope="function")
async def db_session():
    async with AsyncSessionLocal() as session:
        yield session


@pytest_asyncio.fixture(loop_scope="function")
async def workspace_id(db_session):
    ws = Workspace(user_id="test-user")
    db_session.add(ws)
    await db_session.flush()
    return ws.id


@pytest.fixture(autouse=True)
def _mock_s3():
    """Block all real S3 calls in every test. Tests that need storage should mock explicitly."""
    ingest_upload = patch(
        "app.routes.ingest.upload_file",
        MagicMock(return_value="s3://mock"),
    )
    tools_dl = patch(
        "app.agents.tools.download_file",
        side_effect=RuntimeError(
            "Real S3 call in tests — mock app.agents.tools.download_file explicitly"
        ),
    )
    with patch(
        "app.storage.download_file",
        side_effect=RuntimeError(
            "Real S3 call in tests — mock app.storage.download_file explicitly"
        ),
    ):
        with patch(
            "app.storage.upload_file",
            side_effect=RuntimeError(
                "Real S3 call in tests — mock app.storage.upload_file explicitly"
            ),
        ):
            with patch("app.storage.ensure_bucket"):
                with ingest_upload:
                    with tools_dl:
                        yield


@pytest_asyncio.fixture(autouse=True, loop_scope="function")
async def clean_db():
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        # FK from Alembic exists on wiki_test volumes but is not on SQLAlchemy metadata;
        # drop it so metadata.drop_all can order tables (chat_messages ↔ chat_sessions).
        reg = await conn.execute(text("SELECT to_regclass('public.chat_sessions')"))
        if reg.scalar() is not None:
            await conn.execute(
                text(
                    "ALTER TABLE chat_sessions DROP CONSTRAINT IF EXISTS "
                    "fk_chat_sessions_last_monitored_message_id"
                )
            )
            await conn.execute(
                text(
                    "ALTER TABLE chat_sessions DROP CONSTRAINT IF EXISTS "
                    "chat_sessions_last_monitored_message_id_fkey"
                )
            )
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
