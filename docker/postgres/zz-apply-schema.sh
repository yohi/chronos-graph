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

# Create the database (and grant privileges) when it does not yet exist so that
# apply_schema can connect. This honors TEST_DB_NAME overrides, which init.sql
# cannot (it is static SQL executed by psql and cannot read shell env vars).
ensure_database() {
  local db_name=$1
  local admin_db="${POSTGRES_DB:-context_store}"
  local exists

  exists=$(psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$admin_db" \
    -tAc "SELECT 1 FROM pg_database WHERE datname = '${db_name}'")

  if [ "$exists" != "1" ]; then
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$admin_db" \
      -c "CREATE DATABASE \"${db_name}\""
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$admin_db" \
      -c "GRANT ALL PRIVILEGES ON DATABASE \"${db_name}\" TO \"${POSTGRES_USER}\""
  fi
}

apply_schema "${POSTGRES_DB:-context_store}"
ensure_database "${TEST_DB_NAME:-context_store_test}"
apply_schema "${TEST_DB_NAME:-context_store_test}"
