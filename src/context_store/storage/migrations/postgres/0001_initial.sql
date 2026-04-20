-- Initial schema for PostgreSQL
-- Requires: vector extension (pgvector), pg_bigm extension

-- memories table
CREATE TABLE IF NOT EXISTS memories (
    id                 UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    content            TEXT         NOT NULL,
    memory_type        VARCHAR(20)  NOT NULL CHECK (
        memory_type IN ('episodic', 'semantic', 'procedural')
    ),
    source_type        VARCHAR(20)  NOT NULL CHECK (
        source_type IN ('conversation', 'manual', 'url')
    ),
    source_metadata    JSONB        DEFAULT '{}',
    embedding          vector(768),
    semantic_relevance FLOAT        NOT NULL DEFAULT 0.5 CHECK (semantic_relevance >= 0 AND semantic_relevance <= 1),
    importance_score   FLOAT        NOT NULL DEFAULT 0.5 CHECK (importance_score >= 0 AND importance_score <= 1),
    access_count       INT          NOT NULL DEFAULT 0 CHECK (access_count >= 0),
    last_accessed_at   TIMESTAMPTZ  DEFAULT NOW(),
    created_at         TIMESTAMPTZ  DEFAULT NOW(),
    updated_at         TIMESTAMPTZ  DEFAULT NOW(),
    archived_at        TIMESTAMPTZ,
    tags               TEXT[]       DEFAULT '{}',
    project            TEXT,
    content_hash       TEXT         NOT NULL UNIQUE
);

-- lifecycle_state table (Singleton)
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

-- lifecycle_wal_state table (Singleton)
-- Note: WAL state is mostly relevant for SQLite, but kept for schema parity
CREATE TABLE IF NOT EXISTS lifecycle_wal_state (
    id                               INT   PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    wal_failure_count                INT   NOT NULL DEFAULT 0,
    wal_last_failure_ts              TIMESTAMPTZ,
    wal_last_checkpoint_result       TEXT,
    wal_last_observed_size_bytes     BIGINT,
    wal_consecutive_passive_failures INT   NOT NULL DEFAULT 0,
    wal_failure_window               JSONB NOT NULL DEFAULT '[]'
);

-- Insert default rows if not exist
INSERT INTO lifecycle_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING;
INSERT INTO lifecycle_wal_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

-- B-tree indexes
CREATE INDEX IF NOT EXISTS idx_memories_memory_type  ON memories (memory_type);
CREATE INDEX IF NOT EXISTS idx_memories_source_type  ON memories (source_type);
CREATE INDEX IF NOT EXISTS idx_memories_archived_at  ON memories (archived_at);
CREATE INDEX IF NOT EXISTS idx_memories_project      ON memories (project);
CREATE INDEX IF NOT EXISTS idx_memories_created_at   ON memories (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_created_at_id ON memories (created_at ASC, id ASC);
CREATE INDEX IF NOT EXISTS idx_memories_tags_gin     ON memories USING gin (tags);

-- HNSW vector index (requires pgvector extension)
CREATE INDEX IF NOT EXISTS idx_memories_embedding_hnsw
    ON memories USING hnsw (embedding vector_cosine_ops);

-- Full-text search index with pg_bigm (requires pg_bigm extension)
CREATE INDEX IF NOT EXISTS idx_memories_content_fts
    ON memories USING gin (content gin_bigm_ops);
