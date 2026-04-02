# Design: Fix Reported Issues (Pipeline Cache and Postgres Formatting)

## Overview
This design addresses reported issues in the ingestion pipeline's caching mechanism and formatting/type-hinting issues in the PostgreSQL storage adapter.

## 1. Ingestion Pipeline Cache Key Update
- **Problem**: `memo_key` used for in-flight ingestion tasks omits `document_id`, causing collisions when the same content is ingested from different documents.
- **Solution**: Include `document_id` in the `memo_key` tuple.
- **Components**: `src/context_store/ingestion/pipeline.py`
- **Data Flow**:
    - Extract `document_id` from `chunk.metadata`.
    - Update `memo_key` to include `document_id`.

## 2. PostgreSQL Storage Formatting and Type-Hinting
- **Problem**:
    - `src/context_store/storage/postgres.py` has formatting errors reported by CI.
    - `delete_memory` has a bogus `# type: ignore[no-any-return]` and potentially incorrect type handling for the return value.
- **Solution**:
    - Run `ruff format` on `src/context_store/storage/postgres.py`.
    - Fix `delete_memory` return type handling by ensuring `status` is treated correctly (cast or explicit type check) and remove the `type: ignore`.
- **Components**: `src/context_store/storage/postgres.py`

## 3. Testing and Validation
- **Unit Tests**:
    - Run `tests/unit/test_ingestion_pipeline.py`.
    - Run `tests/unit/test_postgres_storage.py`.
- **Static Analysis**:
    - Run `ruff format --check src/context_store/storage/postgres.py`.
    - Run `mypy src/context_store/storage/postgres.py`.
