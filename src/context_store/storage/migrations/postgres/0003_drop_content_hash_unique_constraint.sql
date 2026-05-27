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
--
-- Production Deployment Note:
--   This migration is applied within a transaction block (by MigrationRunner or Supabase CLI),
--   which forbids using "CREATE UNIQUE INDEX CONCURRENTLY".
--   In production environments with a large dataset, building the index synchronously
--   acquires a ShareLock on the 'memories' table and blocks all concurrent writes.
--   To avoid downtime, build the index concurrently manually prior to applying this migration:
--
--   Manual DDL (execute outside of a transaction e.g., in psql):
--     CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS idx_memories_content_hash_active ON memories (content_hash) WHERE archived_at IS NULL;
--
--   After manual execution, run this migration runner as usual. The 'IF NOT EXISTS' clause
--   will gracefully skip index creation, avoiding any locking.

ALTER TABLE memories DROP CONSTRAINT IF EXISTS memories_content_hash_key;
CREATE UNIQUE INDEX IF NOT EXISTS idx_memories_content_hash_active
    ON memories (content_hash)
    WHERE archived_at IS NULL;
