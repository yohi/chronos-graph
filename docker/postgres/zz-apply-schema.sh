#!/usr/bin/env bash
set -euo pipefail

apply_schema() {
  local db_name=$1

  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$db_name" <<'SQL'
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_bigm;
SQL

  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$db_name" \
    --file /docker-entrypoint-initdb.d/schema.sql
}

apply_schema "${POSTGRES_DB:-context_store}"
apply_schema "${TEST_DB_NAME:-context_store_test}"
