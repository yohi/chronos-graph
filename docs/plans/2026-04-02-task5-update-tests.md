# Task 5: Update Tests (Assertions & Mocking) Implementation Plan

**Goal:** Update unit tests to improve assertions and mocking reliability.

**Architecture:** Surgical updates to existing test files. Adding `traversal_depth` check to SQLite graph tests, fixing mock pool disposal in Postgres storage factory tests, and cleaning up redundant imports.

**Tech Stack:** Python, pytest, unittest.mock

---

## Task 1: Update `tests/unit/test_sqlite_graph.py`

**Files:**
- Modify: `tests/unit/test_sqlite_graph.py`

**Step 1: Add `traversal_depth` assertion in `test_traverse_timeout_returns_partial_result`**
Around line 346:
Add `assert result.traversal_depth == 0` after `assert result.timeout is True`.

**Step 2: Add `traversal_depth` assertion in `test_traverse_interrupt_called_on_timeout`**
Around line 386:
Add `assert result.traversal_depth == 0` after `assert result.timeout is True`.

**Step 3: Run SQLite graph unit tests**
Run: `pytest tests/unit/test_sqlite_graph.py`
Expected: PASS

---

## Task 2: Update `tests/unit/test_storage_factory.py`

**Files:**
- Modify: `tests/unit/test_storage_factory.py`

**Step 1: Keep required imports**
Around line 128:
Keep `from unittest.mock import AsyncMock, patch` because later steps use `AsyncMock`.

**Step 2: Fix mock pool in `test_postgres_returns_postgres_adapter`**
Around line 184:
Replace `storage._pool = None` with:
```python
                mock_pool = MagicMock()
                mock_pool.close = AsyncMock()
                storage._pool = mock_pool
```
And add `await storage.dispose()` before `await cache_adp.dispose()`.

**Step 3: Fix mock pool in `test_postgres_graph_disabled`**
Around line 215:
Replace `storage._pool = None` with:
```python
                mock_pool = MagicMock()
                mock_pool.close = AsyncMock()
                storage._pool = mock_pool
```
And add `await storage.dispose()` before `await cache_adp.dispose()`.

**Step 4: Run storage factory unit tests**
Run: `pytest tests/unit/test_storage_factory.py`
Expected: PASS

---

## Task 3: Run all unit tests

**Step 1: Run all unit tests**
Run: `pytest tests/unit/`
Expected: PASS
