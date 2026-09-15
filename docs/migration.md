# Migration Guide

This document describes how to migrate between ChronosGraph versions.

---

## Embedding Dimension Change (1024 → 768)

ChronosGraph changed its default/recommended embedding dimension from **1024**
to **768** when it adopted `cl-nagoya/ruri-v3-310m`. If you are upgrading from
an earlier version, a dimension mismatch will raise a `ConfigurationError` on
startup.

### 1. Re-embed existing memories (recommended)

Run the provided migration script to recalculate existing memories with the
new 768-dimension model.

```bash
uv run python scripts/migrate_dimension.py
```

### 2. Update the storage schema

> [!IMPORTANT]
> Back up your database before changing the schema, and validate
> `scripts/migrate_dimension.py` against your data if needed.

#### Supabase / PostgreSQL

```sql
-- Change the vector column to the new 768-dimension definition
ALTER TABLE memories ALTER COLUMN embedding TYPE vector(768);

-- Or drop and recreate the column (data is lost, do this before re-embedding)
ALTER TABLE memories DROP COLUMN embedding;
ALTER TABLE memories ADD COLUMN embedding vector(768);
```

#### SQLite

SQLite does not support `ALTER COLUMN TYPE`. Choose one of the following:

- **Recreate the column**: Drop the `embedding` column and add it again
  (`DROP/ADD`), or export the database, recreate the `memories` table with the
  new dimension, and reload the data.
- **Run re-embedding**: After recreating the table or adding a nullable
  `embedding` column, run `scripts/migrate_dimension.py` to repopulate the
  vectors.

### 3. Errors and troubleshooting

If you see `ConfigurationError` or `StorageError` at startup, verify that
`.env` has `EMBEDDING_DIMENSION` set to the same dimension used by the storage
schema (usually `768`).
