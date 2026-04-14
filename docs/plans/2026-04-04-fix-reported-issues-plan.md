# Fix Reported Issues Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix issues with LifecycleState lock semantics, manager coroutine leaks, Consolidator project boundaries, and SQLite update FK constraints.

**Architecture:** We will implement 4 targeted fixes: 1) Update `LifecycleState` with CAS logic for locking via tokens. 2) Use a callable factory to prevent coroutine leaks in `_spawn_background_task`. 3) Add a project guard to `Consolidator`'s vector search loop. 4) Run a `SELECT` check before inserting embeddings in `SQLiteStorageAdapter` updates.

**Tech Stack:** Python 3.12, asyncio, pytest, aiosqlite

---

## Task 1: Fix Consolidator Project Boundaries

**Files:**
- Modify: `src/context_store/lifecycle/consolidator.py`
- Modify: `tests/unit/test_consolidator.py`

**Step 1: Write the failing test**

Add to `tests/unit/test_consolidator.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from context_store.models.memory import Memory, MemoryType, SourceType, ScoredMemory, MemorySource
from context_store.lifecycle.consolidator import Consolidator
import uuid
from datetime import datetime, timezone

@pytest.mark.asyncio
async def test_consolidator_skips_different_projects():
    # Setup storage mock
    mock_storage = AsyncMock()
    
    # Base memory (project 'A')
    memory_a = Memory(
        id=uuid.uuid4(),
        content="test",
        memory_type=MemoryType.OBSERVATION,
        source_type=SourceType.USER,
        source_metadata={},
        embedding=[0.1],
        semantic_relevance=0.5,
        importance_score=0.5,
        access_count=0,
        last_accessed_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        archived_at=None,
        tags=[],
        project="A"
    )
    
    # Neighbor memory (project 'B')
    memory_b = Memory(
        id=uuid.uuid4(),
        content="test 2",
        memory_type=MemoryType.OBSERVATION,
        source_type=SourceType.USER,
        source_metadata={},
        embedding=[0.1],
        semantic_relevance=0.5,
        importance_score=0.5,
        access_count=0,
        last_accessed_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        archived_at=None,
        tags=[],
        project="B"
    )
    
    scored_b = ScoredMemory(memory=memory_b, score=0.99, source=MemorySource.VECTOR)
    
    mock_storage.list_by_filter.return_value = [memory_a]
    mock_storage.vector_search.return_value = [scored_b]
    
    consolidator = Consolidator(storage=mock_storage)
    result = await consolidator.run()
    
    # Since neighbor is from project B and base is from A, it should be skipped
    assert result.consolidated_count == 0
    mock_storage.update_memory.assert_not_called()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_consolidator.py::test_consolidator_skips_different_projects -v`
Expected: FAIL because `update_memory` will be called due to high similarity.

**Step 3: Write minimal implementation**

In `src/context_store/lifecycle/consolidator.py`, inside `run()`:

```python
            for scored in scored_neighbors:
                neighbor_id = str(scored.memory.id)
                if neighbor_id == memory_id:
                    continue
                if neighbor_id in archived_in_this_run:
                    continue
                # NEW: Skip memories from different projects
                if scored.memory.project != memory.project:
                    continue
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_consolidator.py::test_consolidator_skips_different_projects -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/context_store/lifecycle/consolidator.py tests/unit/test_consolidator.py
git commit -m "fix(consolidator): skip cross-project neighbors in vector search"
```

## Task 2: Fix SQLiteStorageAdapter update_memory FK Errors

**Files:**
- Modify: `src/context_store/storage/sqlite.py`
- Modify: `tests/unit/test_sqlite_storage.py`

**Step 1: Write the failing test**

Add to `tests/unit/test_sqlite_storage.py`:

```python
import pytest
from context_store.storage.sqlite import SQLiteStorageAdapter
import uuid

@pytest.mark.asyncio
async def test_update_memory_non_existent_with_embedding(settings):
    adapter = await SQLiteStorageAdapter.create(settings)
    
    # Try to update a non-existent memory with an embedding AND other fields
    bad_id = str(uuid.uuid4())
    result = await adapter.update_memory(
        bad_id, 
        {"content": "new", "embedding": [1.0, 0.0]}
    )
    
    # Should safely return False, not raise SQLite FK error
    assert result is False
    
    # Try to update ONLY embedding
    result_only_emb = await adapter.update_memory(
        bad_id,
        {"embedding": [1.0, 0.0]}
    )
    assert result_only_emb is False
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_sqlite_storage.py::test_update_memory_non_existent_with_embedding -v`
Expected: FAIL with `StorageError` or SQLite FK constraint error.

**Step 3: Write minimal implementation**

In `src/context_store/storage/sqlite.py`, inside `update_memory()`:

Replace:
```python
                if embedding is not None:
                    if not set_parts:
                        # Check if memory exists before inserting embedding to avoid FK violations
                        async with conn.execute(
                            "SELECT 1 FROM memories WHERE id = ?", (memory_id,)
                        ) as cursor:
                            if not await cursor.fetchone():
                                return False
```

With:
```python
                if embedding is not None:
                    # Unconditionally check if memory exists before inserting embedding to avoid FK violations
                    async with conn.execute(
                        "SELECT 1 FROM memories WHERE id = ?", (memory_id,)
                    ) as cursor:
                        if not await cursor.fetchone():
                            return False
```

And update the success check for embedding-only updates:

Replace:
```python
                    # If only embedding was updated, we still want to return True
                    if not set_parts:
                        updated = 1
```

With:
```python
                    # If only embedding was updated, we still want to return True
                    if not set_parts:
                        updated = 1
```
(Keep it as is, it's correct)

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_sqlite_storage.py::test_update_memory_non_existent_with_embedding -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/context_store/storage/sqlite.py tests/unit/test_sqlite_storage.py
git commit -m "fix(storage): check memory existence unconditionally when updating embedding"
```

## Task 3: Fix LifecycleManager Coroutine Leaks

**Files:**
- Modify: `src/context_store/lifecycle/manager.py`

**Step 1: Write the failing test**

Add to `tests/unit/test_lifecycle_manager.py` (or similar file testing LifecycleManager):

```python
import pytest
import asyncio
from unittest.mock import MagicMock
from context_store.lifecycle.manager import LifecycleManager

@pytest.mark.asyncio
async def test_spawn_background_task_no_leak():
    # Setup mocks
    mock_store = MagicMock()
    mock_archiver = MagicMock()
    mock_purger = MagicMock()
    mock_consolidator = MagicMock()
    mock_decay = MagicMock()
    mock_storage = MagicMock()
    
    manager = LifecycleManager(
        mock_store, mock_archiver, mock_purger, mock_consolidator, mock_decay, mock_storage
    )
    
    # Simulate shutdown
    manager._shutting_down = True
    
    called = False
    async def dummy_task():
        nonlocal called
        called = True
        
    def task_factory():
        return dummy_task()
        
    manager._spawn_background_task(task_factory)
    
    # Wait a bit just in case
    await asyncio.sleep(0.01)
    
    # The factory shouldn't be called, so the coroutine is never created, hence no leak.
    assert called is False
    assert len(manager._active_tasks) == 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_lifecycle_manager.py::test_spawn_background_task_no_leak -v`
Expected: FAIL because `_spawn_background_task` takes a Coroutine, so passing a factory function will crash with `TypeError: a coroutine was expected, got <function ...>`.

**Step 3: Write minimal implementation**

In `src/context_store/lifecycle/manager.py`:

Change signature of `_spawn_background_task`:
```python
    def _spawn_background_task(self, factory: Callable[[], Coroutine[Any, Any, None]]) -> None:
        """例外ハンドリング付きでバックグラウンドタスクを開始する。"""
        if getattr(self, "_shutting_down", False):
            return

        task: asyncio.Task[None] = asyncio.create_task(factory())
```

Update calls in `LifecycleManager`:
```python
    async def start(self) -> None:
        self._spawn_background_task(self._check_time_based_cleanup)

    async def on_memory_saved(self) -> None:
        # ...
        if threshold_just_reached:
            logger.info("Save count threshold reached, triggering cleanup.")
            self._spawn_background_task(self.run_cleanup)

    async def run_cleanup(self) -> None:
        # ...
        if should_schedule_followup:
            logger.info("Scheduling follow-up cleanup.")
            self._spawn_background_task(self.run_cleanup)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_lifecycle_manager.py::test_spawn_background_task_no_leak -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/context_store/lifecycle/manager.py tests/unit/test_lifecycle_manager.py
git commit -m "fix(lifecycle): prevent coroutine leaks during shutdown"
```

## Task 4: Fix LifecycleState Lock Semantics - Interfaces and Types

**Files:**
- Modify: `src/context_store/lifecycle/manager.py`
- Modify: `tests/unit/test_lifecycle_manager.py`

**Step 1: Write the failing test**

In `tests/unit/test_lifecycle_manager.py`, add a test to check the new lock interface and types.

```python
from context_store.lifecycle.manager import LifecycleState

def test_lifecycle_state_fields():
    state = LifecycleState()
    assert hasattr(state, "cleanup_lock_owner")
    assert hasattr(state, "cleanup_lock_touched_at")
    assert not hasattr(state, "cleanup_running")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_lifecycle_manager.py::test_lifecycle_state_fields -v`
Expected: FAIL

**Step 3: Write minimal implementation**

In `src/context_store/lifecycle/manager.py`:

Update `LifecycleState`:
```python
@dataclass
class LifecycleState:
    save_count: int = 0
    last_cleanup_at: datetime | None = None
    last_cleanup_cursor_at: datetime | None = None
    last_cleanup_id: str | None = None
    cleanup_lock_owner: str | None = None
    cleanup_lock_touched_at: datetime | None = None
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
```

Update `LifecycleStateStore` protocol:
```python
    async def acquire_cleanup_lock(self, token: str) -> bool:
        ...

    async def release_cleanup_lock(self, token: str) -> None:
        ...

    async def heartbeat_cleanup_lock(self, token: str) -> None:
        ...
```

Update `InMemoryLifecycleStateStore` (used for tests):
```python
    async def increment_save_count(self, threshold: int) -> bool:
        async with self._lock:
            state = self._state
            new_count = state.save_count + 1
            threshold_just_reached = new_count == threshold

            self._state = LifecycleState(
                save_count=new_count,
                last_cleanup_at=state.last_cleanup_at,
                last_cleanup_cursor_at=state.last_cleanup_cursor_at,
                last_cleanup_id=state.last_cleanup_id,
                cleanup_lock_owner=state.cleanup_lock_owner,
                cleanup_lock_touched_at=state.cleanup_lock_touched_at,
                updated_at=datetime.now(timezone.utc),
            )
            return threshold_just_reached

    async def acquire_cleanup_lock(self, token: str) -> bool:
        async with self._lock:
            state = self._state
            if state.cleanup_lock_owner is not None:
                now = datetime.now(timezone.utc)
                if state.cleanup_lock_touched_at:
                    elapsed = (now - state.cleanup_lock_touched_at).total_seconds()
                    if elapsed < self._stale_lock_timeout_seconds:
                        return False
                    logger.warning("Stale cleanup lock detected, force releasing.")

            self._state = LifecycleState(
                save_count=state.save_count,
                last_cleanup_at=state.last_cleanup_at,
                last_cleanup_cursor_at=state.last_cleanup_cursor_at,
                last_cleanup_id=state.last_cleanup_id,
                cleanup_lock_owner=token,
                cleanup_lock_touched_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            return True

    async def release_cleanup_lock(self, token: str) -> None:
        async with self._lock:
            state = self._state
            if state.cleanup_lock_owner == token:
                self._state = LifecycleState(
                    save_count=state.save_count,
                    last_cleanup_at=state.last_cleanup_at,
                    last_cleanup_cursor_at=state.last_cleanup_cursor_at,
                    last_cleanup_id=state.last_cleanup_id,
                    cleanup_lock_owner=None,
                    cleanup_lock_touched_at=None,
                    updated_at=datetime.now(timezone.utc),
                )

    async def heartbeat_cleanup_lock(self, token: str) -> None:
        async with self._lock:
            state = self._state
            if state.cleanup_lock_owner == token:
                self._state = LifecycleState(
                    save_count=state.save_count,
                    last_cleanup_at=state.last_cleanup_at,
                    last_cleanup_cursor_at=state.last_cleanup_cursor_at,
                    last_cleanup_id=state.last_cleanup_id,
                    cleanup_lock_owner=token,
                    cleanup_lock_touched_at=datetime.now(timezone.utc),
                    updated_at=state.updated_at,
                )
```

Update `LifecycleManager._run_cleanup_inner` to generate and pass a token, and use a heartbeat. Also fix the `run_cleanup` state updates:
```python
    import uuid

    async def _run_cleanup_inner(self) -> bool:
        token = str(uuid.uuid4())
        acquired = await self._state_store.acquire_cleanup_lock(token)
        if not acquired:
            return False

        try:
            # ... existing code ...
            
            # 5. Stats Collector
            await self._collect_stats()
            
            await self._state_store.heartbeat_cleanup_lock(token)

            # ... existing code ...

            new_state = LifecycleState(
                save_count=remaining_count,
                last_cleanup_at=now,
                last_cleanup_cursor_at=next_cursor_at,
                last_cleanup_id=next_cursor_id,
                cleanup_lock_owner=token, # Keep holding lock until finally
                cleanup_lock_touched_at=current_state.cleanup_lock_touched_at,
                updated_at=now,
            )
            await self._state_store.save_state(new_state)
            
            # ...
        except Exception:
            # ...
            try:
                state = await self._state_store.load_state()
                await self._state_store.save_state(
                    LifecycleState(
                        save_count=min(state.save_count, self._save_count_threshold - 1),
                        last_cleanup_at=state.last_cleanup_at,
                        last_cleanup_cursor_at=state.last_cleanup_cursor_at,
                        last_cleanup_id=state.last_cleanup_id,
                        cleanup_lock_owner=token,
                        cleanup_lock_touched_at=state.cleanup_lock_touched_at,
                        updated_at=datetime.now(timezone.utc),
                    )
                )
            # ...
        finally:
            await self._state_store.release_cleanup_lock(token)
```

You'll also need to update any tests in `tests/unit/test_lifecycle_manager.py` that mock `acquire_cleanup_lock` or `release_cleanup_lock` to expect the `token` argument, or that construct `LifecycleState` objects to use the new fields.

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_lifecycle_manager.py -v`
Expected: PASS (all tests in that file)

**Step 5: Commit**

```bash
git add src/context_store/lifecycle/manager.py tests/unit/test_lifecycle_manager.py
git commit -m "feat(lifecycle): update lock semantics interfaces to use tokens"
```

## Task 5: Fix SQLiteLifecycleStateStore Lock Implementation

**Files:**
- Modify: `src/context_store/lifecycle/manager.py` (The `SQLiteLifecycleStateStore` class)

**Step 1: Write the failing test**

Add to `tests/unit/test_lifecycle_manager.py` (or wherever `SQLiteLifecycleStateStore` is tested, maybe `test_sqlite_storage.py`):

```python
@pytest.mark.asyncio
async def test_sqlite_state_store_cas_locking(tmp_path):
    from context_store.lifecycle.manager import SQLiteLifecycleStateStore
    import aiosqlite
    db_path = str(tmp_path / "test.db")
    store = SQLiteLifecycleStateStore(db_path, stale_lock_timeout_seconds=600)
    
    # Test acquire
    token1 = "token1"
    assert await store.acquire_cleanup_lock(token1) is True
    
    # Test acquire fail
    token2 = "token2"
    assert await store.acquire_cleanup_lock(token2) is False
    
    # Test heartbeat failure (wrong token)
    await store.heartbeat_cleanup_lock(token2)
    
    # Test release failure (wrong token)
    await store.release_cleanup_lock(token2)
    
    # Verify still locked by token1
    state = await store.load_state()
    assert state.cleanup_lock_owner == token1
    
    # Real release
    await store.release_cleanup_lock(token1)
    state = await store.load_state()
    assert state.cleanup_lock_owner is None
```

**Step 2: Run test to verify it fails**

Run the test. It will fail because `SQLiteLifecycleStateStore` methods don't take `token`.

**Step 3: Write minimal implementation**

In `src/context_store/lifecycle/manager.py` inside `SQLiteLifecycleStateStore`:

1. Update `_ensure_tables` to match the new schema:
Replace `cleanup_running INTEGER NOT NULL DEFAULT 0` with `cleanup_lock_owner TEXT` and `cleanup_lock_touched_at TIMESTAMP`. Remove `cleanup_running` via schema update logic (or just drop the table since it's transient/internal state, but safer to `ALTER TABLE` to add the columns if missing). Since `sqlite` doesn't drop columns easily, add new ones and ignore `cleanup_running`.

```python
        if "cleanup_lock_owner" not in column_names:
            await conn.execute("ALTER TABLE lifecycle_state ADD COLUMN cleanup_lock_owner TEXT")
        if "cleanup_lock_touched_at" not in column_names:
            await conn.execute("ALTER TABLE lifecycle_state ADD COLUMN cleanup_lock_touched_at TIMESTAMP")
```

2. Update `load_state`:
```python
            cursor = await conn.execute(
                "SELECT save_count, last_cleanup_at, last_cleanup_cursor_at, last_cleanup_id, "
                "cleanup_lock_owner, cleanup_lock_touched_at, updated_at "
                "FROM lifecycle_state WHERE id = 1"
            )
            # ...
            return LifecycleState(
                # ...
                cleanup_lock_owner=row["cleanup_lock_owner"],
                cleanup_lock_touched_at=_parse_ts(row["cleanup_lock_touched_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]).replace(tzinfo=timezone.utc),
            )
```

3. Update `save_state`:
```python
            await conn.execute(
                """
                UPDATE lifecycle_state
                SET save_count = ?, last_cleanup_at = ?, last_cleanup_cursor_at = ?,
                    last_cleanup_id = ?, cleanup_lock_owner = ?, cleanup_lock_touched_at = ?, updated_at = ?
                WHERE id = 1
                """,
                (
                    state.save_count,
                    _fmt_ts(state.last_cleanup_at),
                    _fmt_ts(state.last_cleanup_cursor_at),
                    state.last_cleanup_id,
                    state.cleanup_lock_owner,
                    _fmt_ts(state.cleanup_lock_touched_at),
                    state.updated_at.isoformat(),
                ),
            )
```

4. Update `acquire_cleanup_lock`:
```python
    async def acquire_cleanup_lock(self, token: str) -> bool:
        import aiosqlite

        async with aiosqlite.connect(self._db_path) as conn:
            await self._ensure_tables(conn)
            now = datetime.now(timezone.utc)

            # 1. Normal acquire (only if owner is NULL)
            cursor = await conn.execute(
                "UPDATE lifecycle_state SET cleanup_lock_owner = ?, cleanup_lock_touched_at = ?, updated_at = ? "
                "WHERE id = 1 AND cleanup_lock_owner IS NULL",
                (token, now.isoformat(), now.isoformat()),
            )
            await conn.commit()
            if cursor.rowcount > 0:
                return True

            # 2. Stale lock check
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT cleanup_lock_owner, cleanup_lock_touched_at FROM lifecycle_state WHERE id = 1"
            )
            row = await cursor.fetchone()
            if row is None or row["cleanup_lock_owner"] is None:
                return False

            touched_at_str = row["cleanup_lock_touched_at"]
            if not touched_at_str:
                return False
            touched_at = datetime.fromisoformat(touched_at_str).replace(tzinfo=timezone.utc)
            elapsed = (now - touched_at).total_seconds()

            if elapsed >= self._stale_lock_timeout_seconds:
                logger.warning("Stale lock detected, forcing release.")
                # CAS override
                cursor = await conn.execute(
                    "UPDATE lifecycle_state SET cleanup_lock_owner = ?, cleanup_lock_touched_at = ?, updated_at = ? "
                    "WHERE id = 1 AND cleanup_lock_touched_at = ?",
                    (token, now.isoformat(), now.isoformat(), touched_at_str),
                )
                await conn.commit()
                if cursor.rowcount > 0:
                    return True

        return False
```

5. Update `release_cleanup_lock`:
```python
    async def release_cleanup_lock(self, token: str) -> None:
        import aiosqlite

        async with aiosqlite.connect(self._db_path) as conn:
            await self._ensure_tables(conn)
            now = datetime.now(timezone.utc)
            await conn.execute(
                "UPDATE lifecycle_state SET cleanup_lock_owner = NULL, cleanup_lock_touched_at = NULL, updated_at = ? "
                "WHERE id = 1 AND cleanup_lock_owner = ?",
                (now.isoformat(), token),
            )
            await conn.commit()
```

6. Add `heartbeat_cleanup_lock`:
```python
    async def heartbeat_cleanup_lock(self, token: str) -> None:
        import aiosqlite

        async with aiosqlite.connect(self._db_path) as conn:
            await self._ensure_tables(conn)
            now = datetime.now(timezone.utc)
            await conn.execute(
                "UPDATE lifecycle_state SET cleanup_lock_touched_at = ? "
                "WHERE id = 1 AND cleanup_lock_owner = ?",
                (now.isoformat(), token),
            )
            await conn.commit()
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_lifecycle_manager.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/context_store/lifecycle/manager.py tests/unit/test_lifecycle_manager.py
git commit -m "feat(lifecycle): implement sqlite CAS lock with tokens"
```
