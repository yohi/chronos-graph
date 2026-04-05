# Traversal Timeout and Settings Helper Implementation Plan

Execute this plan task-by-task using the project's standard plan-execution workflow.

**Goal:** Refine timeout handling in `sqlite_graph.py` and centralize `make_settings` helper.

**Architecture:** 
- Use a try-except block within `async with ctx:` to catch `CancelledError` and `TimeoutError`.
- Centralize `make_settings` in `tests/unit/conftest.py`.

**Tech Stack:** Python, Pytest, aiosqlite

---

## Task 1: Refactor sqlite_graph.py Timeout Logic

**Files:**
- Modify: `src/context_store/storage/sqlite_graph.py:216-245`

**Step 1: Update the traversal wrapper**

```python
                async with ctx:
                    try:
                        result = await asyncio.wait_for(
                            self._traverse_inner(
                                conn, ctx, seed_ids, edge_types, effective_depth, partial_container
                            ),
                            timeout=self._timeout,
                        )
                        return result
                    except (asyncio.TimeoutError, asyncio.CancelledError):
                        if partial_container:
                            res = partial_container[0]
                            res.partial = True
                            res.timeout = True
                        ctx.interrupt()
                        raise
```

**Step 2: Clean up the outer `except asyncio.TimeoutError:` block**

Remove the logic that sets `partial` and `timeout` since it's now handled inside the interrupt context.

```python
        except asyncio.TimeoutError:
            logger.warning(
                "graph_traversal_timeout: traversal from seeds=%s "
                "exceeded %.2fs; returning partial result.",
                seed_ids,
                self._timeout,
            )
            if partial_container:
                return partial_container[0]
            return GraphResult(nodes=[], edges=[], traversal_depth=0, partial=True, timeout=True)
```

**Step 3: Run existing tests**

Run: `pytest tests/unit/test_sqlite_graph.py`
Expected: PASS

## Task 2: Centralize `make_settings` in `tests/unit/conftest.py`

**Files:**
- Modify: `tests/unit/conftest.py`

**Step 1: Add `make_settings` helper**

```python
from context_store.config import Settings

def make_settings(**kwargs) -> Settings:
    """Settings オブジェクトを作成するヘルパー。"""
    defaults: dict = {
        "storage_backend": "sqlite",
        "graph_enabled": True,
        "cache_backend": "inmemory",
        "sqlite_db_path": ":memory:",
        "sqlite_max_concurrent_connections": 5,
        "sqlite_max_queued_requests": 20,
        "sqlite_acquire_timeout": 2.0,
        "stale_lock_timeout_seconds": 600,
        "graph_max_logical_depth": 5,
        "graph_max_physical_hops": 50,
        "graph_traversal_timeout_seconds": 2.0,
        "cache_coherence_poll_interval_seconds": 5.0,
        "postgres_host": "localhost",
        "postgres_password": "test",
        "neo4j_password": "test",
        "openai_api_key": "sk-test",
    }
    defaults.update(kwargs)
    return Settings.model_construct(**defaults)
```

## Task 3: Update Test Files to Use Shared `make_settings`

**Files:**
- Modify: `tests/unit/test_config.py`
- Modify: `tests/unit/test_sqlite_graph.py`
- Modify: `tests/unit/test_storage_factory.py`

**Step 1: Update `tests/unit/test_config.py`**

- Remove existing `make_settings`.
- Import `make_settings` from `.conftest` or rely on fixture if converted to one. (Prefer simple import if possible or use fixture).

**Step 2: Update `tests/unit/test_sqlite_graph.py`**

- Remove local `make_settings`.
- Import `make_settings` from `.conftest`.

**Step 3: Update `tests/unit/test_storage_factory.py`**

- Remove local `make_settings`.
- Import `make_settings` from `.conftest`.

## Task 4: Final Verification

**Step 1: Run all unit tests**

Run: `pytest tests/unit/`
Expected: ALL PASS

**Step 2: Verify `sqlite_graph.py` timeout test**

Run: `pytest tests/unit/test_sqlite_graph.py::TestTimeout -v`
Expected: ALL PASS (confirming the new flags logic)
the new flags logic)
