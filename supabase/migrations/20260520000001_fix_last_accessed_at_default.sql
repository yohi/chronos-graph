-- Repair migration: fix last_accessed_at NULL values and enforce non-null default
UPDATE memories
   SET last_accessed_at = COALESCE(last_accessed_at, created_at, NOW())
 WHERE last_accessed_at IS NULL;

ALTER TABLE memories
  ALTER COLUMN last_accessed_at SET DEFAULT NOW(),
  ALTER COLUMN last_accessed_at SET NOT NULL;
