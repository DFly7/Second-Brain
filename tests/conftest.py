import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Force test credentials so docker-compose `env_file: .env` cannot override pytest.
os.environ["DATABASE_URL"] = "postgresql+asyncpg://wiki:wiki@db:5432/wiki"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["SINGLE_USER_EMAIL"] = "user@example.com"
os.environ["SINGLE_USER_PASSWORD"] = "changeme"
os.environ.setdefault("LITELLM_MODEL", "gemini/gemini-2.0-flash")
os.environ.setdefault("S3_ENDPOINT", "http://localhost:9000")
os.environ.setdefault("S3_BUCKET", "wiki")
os.environ.setdefault("S3_ACCESS_KEY", "minioadmin")
os.environ.setdefault("VECTOR_SEARCH_ENABLED", "true")
os.environ.setdefault("MARKER_URL", "http://marker:8001")
os.environ.setdefault("VISION_MODEL", "")

import pytest
import pytest_asyncio

from app.database import Base, engine
import app.models  # noqa: F401


@pytest_asyncio.fixture(autouse=True)
async def clean_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
