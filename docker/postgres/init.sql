CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_bigm;

\i /docker-entrypoint-initdb.d/schema.sql
-- Test database for sandbox integration tests
CREATE DATABASE context_store_test;
GRANT ALL PRIVILEGES ON DATABASE context_store_test TO context_store;

-- Switch to test database and apply the same schema
\c context_store_test
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_bigm;
\i /docker-entrypoint-initdb.d/schema.sql
