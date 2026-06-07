#!/usr/bin/env bash
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname context_store_test <<'SQL'
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_bigm;
SQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname context_store_test \
  --file /docker-entrypoint-initdb.d/schema.sql
