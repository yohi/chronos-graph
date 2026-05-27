-- Drop content_hash UNIQUE constraint, replace with partial unique index
--
-- Background:
--   The Deduplicator's REPLACE strategy archives (sets archived_at) an existing
--   record and then INSERTs a new one with the same content_hash. The full-table
--   UNIQUE constraint blocks the INSERT even after the old record is archived.
--
-- Fix:
--   Drop the full-table UNIQUE constraint and create a partial unique index
--   that only enforces uniqueness on active (archived_at IS NULL) records.

ALTER TABLE memories DROP CONSTRAINT IF EXISTS memories_content_hash_key;
CREATE UNIQUE INDEX IF NOT EXISTS idx_memories_content_hash_active
    ON memories (content_hash)
    WHERE archived_at IS NULL;
