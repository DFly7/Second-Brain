import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ["DATABASE_URL"] = "postgresql+asyncpg://wiki:wiki@db:5432/wiki"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["SINGLE_USER_EMAIL"] = "user@example.com"
os.environ["SINGLE_USER_PASSWORD"] = "changeme"
os.environ["LITELLM_MODEL"] = "gemini/gemini-2.0-flash"
os.environ["S3_ENDPOINT"] = "http://localhost:9000"
os.environ["S3_BUCKET"] = "wiki"
os.environ["S3_ACCESS_KEY"] = "minioadmin"
os.environ["S3_SECRET_KEY"] = "minioadmin"

import pytest
import pytest_asyncio

from app.database import Base, engine


@pytest_asyncio.fixture(autouse=True)
async def clean_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
