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
    semantic_relevance FLOAT        DEFAULT 0.5,
    importance_score   FLOAT        DEFAULT 0.5,
    access_count       INT          DEFAULT 0,
    last_accessed_at   TIMESTAMPTZ  DEFAULT NOW(),
    created_at         TIMESTAMPTZ  DEFAULT NOW(),
    updated_at         TIMESTAMPTZ  DEFAULT NOW(),
    archived_at        TIMESTAMPTZ,
    tags               TEXT[]       DEFAULT '{}',
    project            TEXT,
    content_hash       TEXT         NOT NULL UNIQUE
);

-- lifecycle_state table
CREATE TABLE IF NOT EXISTS lifecycle_state (
    id               SERIAL      PRIMARY KEY,
    last_cleanup_at  TIMESTAMPTZ,
    save_count       INT         DEFAULT 0,
    cleanup_running  BOOLEAN     DEFAULT FALSE,
    updated_at       TIMESTAMPTZ DEFAULT NOW()
);

-- Insert default row if not exists
INSERT INTO lifecycle_state (id)
VALUES (1)
ON CONFLICT (id) DO NOTHING;

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
