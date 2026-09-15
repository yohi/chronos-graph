# Migration Guide

This document describes how to migrate between ChronosGraph versions.

---

## Embedding Dimension Change (1024 → 768)

ChronosGraph changed its default/recommended embedding dimension from **1024**
to **768** when it adopted `cl-nagoya/ruri-v3-310m`. New PostgreSQL, Docker, and
Supabase schemas already use `vector(768)`. The runbook below is only for an
existing deployed PostgreSQL database whose `memories.embedding` column is
`vector(1024)`.

> [!IMPORTANT]
> Back up the database, stop ChronosGraph writes, and confirm the target
> database before changing the schema. The script below re-embeds data but does
> not perform PostgreSQL DDL.

### Existing PostgreSQL database

1. Set the migration environment to the target provider and dimension. For the
   default local model, `.env` should contain:

   ```bash
   STORAGE_BACKEND=postgres
   EMBEDDING_PROVIDER=local-model
   LOCAL_MODEL_NAME=cl-nagoya/ruri-v3-310m
   EMBEDDING_DIMENSION=768
   ```

2. Confirm the deployed column and index names. The standard schema uses
   `memories.embedding` and `idx_memories_embedding_hnsw`.

3. Back up the database, then run the following DDL in one transaction. The
   old vectors remain available in `embedding_old` until verification finishes.

   ```sql
   BEGIN;

   DROP INDEX IF EXISTS idx_memories_embedding_hnsw;
   ALTER TABLE memories RENAME COLUMN embedding TO embedding_old;
   ALTER TABLE memories ADD COLUMN embedding vector(768);

   COMMIT;
   ```

4. With the application still stopped, re-embed all memories:

   ```bash
   uv run python scripts/migrate_dimension.py
   ```

   If the process stops after partially updating the new column, keep
   `embedding_old` and rerun with `--force`.

5. Verify that every memory has a new vector before deleting the backup column:

   ```sql
   SELECT COUNT(*) AS missing_embeddings
   FROM memories
   WHERE embedding IS NULL;

   SELECT vector_dims(embedding) AS dimension, COUNT(*) AS rows
   FROM memories
   WHERE embedding IS NOT NULL
   GROUP BY vector_dims(embedding);
   ```

   Proceed only when `missing_embeddings` is `0` and every reported dimension
   is `768`. Investigate failures while `embedding_old` is still present.

6. Recreate the vector index and remove the old column:

   ```sql
   CREATE INDEX idx_memories_embedding_hnsw
       ON memories USING hnsw (embedding vector_cosine_ops);

   ALTER TABLE memories DROP COLUMN embedding_old;
   ```

### Supabase

The repository's Supabase schema and vector RPCs are fixed at `vector(768)` by
`SUPABASE_VECTOR_DIM`. A Supabase deployment must use a 768-dimensional model.
For a legacy deployment with another dimension, create and apply a new Supabase
migration rather than editing an already-applied migration. Update the
`memories.embedding` column, its HNSW index, and every vector-typed RPC
declaration together, including `vector_search`, `vector_search_brief`, and
the graph-sync outbox RPC. The application validation must remain consistent
with the deployed schema. Changing only `.env` is not sufficient.

### SQLite

SQLite does not support `ALTER COLUMN TYPE`. Follow the SQLite-specific schema
migrations for the deployment, then run the re-embedding script after the
storage accepts the target dimension. Do not drop the only copy of existing
vectors before a backup is available.

### Errors and troubleshooting

Do not resolve a dimension mismatch by changing the existing vector column type
in place. Follow the backend-specific procedure above: preserve the old column,
re-embed into a new column, validate every row, and switch only after validation.

If you see `ConfigurationError` or `StorageError` at startup, verify that
`.env` has `EMBEDDING_DIMENSION` set to the same dimension reported by the
storage schema and the active embedding provider. A model change requires both
schema migration and re-embedding; changing the environment variable alone
does not convert existing vectors.
