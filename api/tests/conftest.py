import os

# Required so importing app.* under pytest does not fail Settings validation.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test:test@127.0.0.1:5432/test",
)
