-- Initial schema for SQLite

CREATE TABLE memories (
    id              TEXT PRIMARY KEY,
    content         TEXT NOT NULL,
    memory_type     TEXT NOT NULL,
    source_type     TEXT NOT NULL,
    source_metadata TEXT NOT NULL DEFAULT '{}',
    semantic_relevance REAL NOT NULL DEFAULT 0.5,
    importance_score   REAL NOT NULL DEFAULT 0.5,
    access_count       INTEGER NOT NULL DEFAULT 0,
    last_accessed_at   TEXT NOT NULL,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    archived_at        TEXT,
    tags               TEXT NOT NULL DEFAULT '[]',
    project            TEXT
);

CREATE INDEX idx_memories_created_id ON memories(created_at, id);

CREATE TABLE vectors_metadata (
    dimension INTEGER NOT NULL UNIQUE
);

CREATE VIRTUAL TABLE memories_fts USING fts5(
    content,
    content=memories,
    content_rowid=rowid
);

-- Triggers to keep FTS in sync
CREATE TRIGGER memories_ai
AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, content) VALUES (new.rowid, new.content);
END;

CREATE TRIGGER memories_ad
AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content)
        VALUES ('delete', old.rowid, old.content);
END;

CREATE TRIGGER memories_au
AFTER UPDATE OF content ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content)
        VALUES ('delete', old.rowid, old.content);
    INSERT INTO memories_fts(rowid, content) VALUES (new.rowid, new.content);
END;

CREATE TABLE memory_embeddings (
    memory_id TEXT PRIMARY KEY REFERENCES memories(id) ON DELETE CASCADE,
    embedding BLOB NOT NULL
);
