# Design: SQLite Storage Security Fix (SQL Injection in ORDER BY and LIMIT)

## Overview
This design addresses a potential SQL injection vulnerability in the SQLite storage adapter's `list_memories` (or equivalent) method, where `ORDER BY` and `LIMIT` clauses are constructed using raw string interpolation.

## 1. Safe ORDER BY Construction
- **Problem**: `filters.order_by` is interpolated directly into the SQL string.
- **Solution**: Use a whitelist-based approach to validate and construct the `ORDER BY` clause.
- **Components**: `src/context_store/storage/sqlite.py`
- **Logic**:
    - Define a whitelist of allowed columns (e.g., `id`, `created_at`, `memory_type`, `project`).
    - Define a whitelist of allowed directions (`ASC`, `DESC`).
    - Parse `filters.order_by` (e.g., split by space).
    - If valid, construct the clause using tokens from the whitelist.
    - If invalid or empty, fall back to a safe default: `ORDER BY m.created_at DESC`.

## 2. Safe LIMIT Clause
- **Problem**: `filters.limit` is interpolated directly.
- **Solution**:
    - Ensure `filters.limit` is an integer.
    - Use a parameterized query (`LIMIT ?`) and add the value to the `params` list.
- **Components**: `src/context_store/storage/sqlite.py`

## 3. Testing and Validation
- **Regression Tests**:
    - Add test cases to `tests/unit/test_sqlite_storage.py` that attempt SQL injection via `order_by` (e.g., `id; DROP TABLE memories;`) and `limit`.
    - Verify that the injected SQL is ignored or handled safely.
- **Static Analysis**:
    - Ensure no regressions in `mypy` or `ruff`.
