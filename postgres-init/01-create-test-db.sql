-- Creates the test database used by pytest so tests never touch the production wiki DB.
-- This script only runs on a fresh data volume (docker entrypoint convention).
-- For existing deployments run manually:
--   docker compose exec db psql -U wiki -c "CREATE DATABASE wiki_test;"
SELECT 'CREATE DATABASE wiki_test'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'wiki_test')\gexec
