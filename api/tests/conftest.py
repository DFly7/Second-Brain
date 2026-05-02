import os

# Hard-coded to wiki_test — never the production wiki DB.
# setdefault is intentionally NOT used: the container environment sets DATABASE_URL
# to the production DB, and we must override it here unconditionally.
os.environ["DATABASE_URL"] = "postgresql+asyncpg://wiki:wiki@db:5432/wiki_test"

# Safety net: blow up loudly if something upstream pointed us at the wrong DB.
assert "test" in os.environ["DATABASE_URL"], (
    f"Refusing to run tests against non-test DB: {os.environ['DATABASE_URL']}"
)
