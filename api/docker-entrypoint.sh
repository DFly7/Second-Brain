#!/bin/sh
set -e

# Apply DB migrations before booting the API. Idempotent when already at head.
# Set SKIP_DB_MIGRATE=1 to disable (one-off debugging).
if [ "${SKIP_DB_MIGRATE:-}" != "1" ]; then
  alembic upgrade head
fi

exec "$@"
