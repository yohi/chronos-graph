-- System metadata and lifecycle tables

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS system_metadata (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS lifecycle_state (
    id                      INT          PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    save_count              INT          NOT NULL DEFAULT 0,
    last_cleanup_at         TIMESTAMPTZ,
    last_cleanup_cursor_at  TIMESTAMPTZ,
    last_cleanup_id         TEXT,
    cleanup_lock_owner      TEXT,
    cleanup_lock_touched_at TIMESTAMPTZ,
    updated_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS lifecycle_wal_state (
    id                               INT   PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    wal_failure_count                INT   NOT NULL DEFAULT 0,
    wal_last_failure_ts              TIMESTAMPTZ,
    wal_last_checkpoint_result       TEXT,
    wal_last_observed_size_bytes     BIGINT,
    wal_consecutive_passive_failures INT   NOT NULL DEFAULT 0,
    wal_failure_window               JSONB NOT NULL DEFAULT '[]'
);
