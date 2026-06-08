CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_bigm;

-- NOTE: The test database (TEST_DB_NAME, default context_store_test) is created
-- by zz-apply-schema.sh. Static SQL here cannot read the TEST_DB_NAME env var,
-- so the database-name contract lives in that script to stay consistent.
