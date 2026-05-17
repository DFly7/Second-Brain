import os
from unittest.mock import AsyncMock, patch

import pytest

# Hard-coded to wiki_test — never the production wiki DB.
# setdefault is intentionally NOT used: the container environment sets DATABASE_URL
# to the production DB, and we must override it here unconditionally.
os.environ["DATABASE_URL"] = "postgresql+asyncpg://wiki:wiki@db:5432/wiki_test"

# Hard-coded to wiki-test — never the production wiki bucket.
os.environ["S3_BUCKET"] = "wiki-test"

os.environ["AUTHENTIK_ISSUER"] = (
    "https://auth.example.com/application/o/second-brain/"
)
os.environ["AUTHENTIK_JWKS_URI"] = (
    "https://auth.example.com/application/o/second-brain/jwks/"
)
os.environ["AUTHENTIK_CLIENT_ID"] = "second-brain"
os.environ["AUTHENTIK_TOKEN_URL"] = "https://auth.example.com/application/o/token/"
os.environ["AUTHENTIK_REDIRECT_URI"] = "https://smoothstudy.ai/callback"

# Disable vector search so tests never trigger embedding API calls.
os.environ.setdefault("VECTOR_SEARCH_ENABLED", "false")

# Safety nets: blow up loudly if something upstream pointed us at the wrong resources.
assert "test" in os.environ["DATABASE_URL"], (
    f"Refusing to run tests against non-test DB: {os.environ['DATABASE_URL']}"
)
assert "test" in os.environ["S3_BUCKET"], (
    f"Refusing to run tests against non-test S3 bucket: {os.environ['S3_BUCKET']}"
)


@pytest.fixture(autouse=True)
def _mock_broadcaster():
    """Block Redis connections so tests run without a Redis instance."""
    with patch("app.sse.broadcaster.connect", new_callable=AsyncMock), patch(
        "app.sse.broadcaster.disconnect", new_callable=AsyncMock
    ):
        yield


@pytest.fixture(autouse=True)
def _mock_s3():
    """Block all real S3 calls in every test. Tests that need storage should mock explicitly."""
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
                yield
