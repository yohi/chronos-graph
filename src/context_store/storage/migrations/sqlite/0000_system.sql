-- System metadata and lifecycle tables

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS system_metadata (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lifecycle_state (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    save_count INTEGER NOT NULL DEFAULT 0,
    last_cleanup_at TIMESTAMP,
    last_cleanup_cursor_at TIMESTAMP,
    last_cleanup_id TEXT,
    cleanup_lock_owner TEXT,
    cleanup_lock_touched_at TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS lifecycle_wal_state (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    wal_failure_count INTEGER NOT NULL DEFAULT 0,
    wal_last_failure_ts TIMESTAMP,
    wal_last_checkpoint_result TEXT,
    wal_last_observed_size_bytes INTEGER,
    wal_consecutive_passive_failures INTEGER NOT NULL DEFAULT 0,
    wal_failure_window TEXT NOT NULL DEFAULT '[]'
);
