-- pgvector + pg_trgm 拡張
CREATE EXTENSION IF NOT EXISTS "vector";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- memories テーブル
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
    semantic_relevance FLOAT        NOT NULL DEFAULT 0.5
                       CHECK (semantic_relevance >= 0 AND semantic_relevance <= 1),
    importance_score   FLOAT        NOT NULL DEFAULT 0.5
                       CHECK (importance_score >= 0 AND importance_score <= 1),
    access_count       INT          NOT NULL DEFAULT 0 CHECK (access_count >= 0),
    last_accessed_at   TIMESTAMPTZ  DEFAULT NOW(),
    created_at         TIMESTAMPTZ  DEFAULT NOW(),
    updated_at         TIMESTAMPTZ  DEFAULT NOW(),
    archived_at        TIMESTAMPTZ,
    tags               TEXT[]       DEFAULT '{}',
    project            TEXT,
    content_hash       TEXT         NOT NULL UNIQUE
);

-- B-tree indexes
CREATE INDEX IF NOT EXISTS idx_memories_memory_type    ON memories (memory_type);
CREATE INDEX IF NOT EXISTS idx_memories_source_type    ON memories (source_type);
CREATE INDEX IF NOT EXISTS idx_memories_archived_at    ON memories (archived_at);
CREATE INDEX IF NOT EXISTS idx_memories_project        ON memories (project);
CREATE INDEX IF NOT EXISTS idx_memories_created_at     ON memories (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_created_at_id  ON memories (created_at ASC, id ASC);
CREATE INDEX IF NOT EXISTS idx_memories_tags_gin       ON memories USING gin (tags);

-- HNSW vector index
CREATE INDEX IF NOT EXISTS idx_memories_embedding_hnsw
    ON memories USING hnsw (embedding vector_cosine_ops);

-- Full-text search (pg_trgm)
CREATE INDEX IF NOT EXISTS idx_memories_content_fts
    ON memories USING gin (content gin_trgm_ops);
