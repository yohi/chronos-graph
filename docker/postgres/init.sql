CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_bigm;

-- Test database for sandbox integration tests
CREATE DATABASE context_store_test;
GRANT ALL PRIVILEGES ON DATABASE context_store_test TO context_store;
