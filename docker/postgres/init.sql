CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_bigm;

\i /docker-entrypoint-initdb.d/schema.sql
