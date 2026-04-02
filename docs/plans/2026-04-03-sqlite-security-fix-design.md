# Design: SQLite list_memories SQL Injection Fix

## Problem
The `list_by_filter` method in `SQLiteStorageAdapter` directly embeds `filters.order_by` and `filters.limit` into the SQL query using F-strings, which is vulnerable to SQL injection.

## Proposed Changes

### 1. `src/context_store/storage/sqlite.py`
- Modify `list_by_filter` to validate `order_by` against a whitelist of allowed columns.
- Ensure `limit` is an integer and use it safely.
- Raise `StorageError` if invalid parameters are provided.

### 2. `tests/unit/test_sqlite_storage.py`
- Add a new test case `TestSqlInjection` to verify that malicious `order_by` and `limit` strings are handled safely.

## Implementation Details

### Allowed Columns for `order_by`
- `created_at`
- `updated_at`
- `importance_score`
- `semantic_relevance`
- `access_count`
- `id`
- `content`

### Validation Logic
- For `order_by`: Split by space, check column name against whitelist, check direction (ASC/DESC).
- For `limit`: Ensure it's a positive integer.

## Verification Plan
1. Run existing tests to ensure no regressions.
2. Run new SQL injection tests to confirm failure (before fix) and success (after fix).
