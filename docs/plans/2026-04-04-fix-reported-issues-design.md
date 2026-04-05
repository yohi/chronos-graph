# Fix Reported Issues Design

**Goal:** Resolve reported issues relating to lock semantics, coroutine leaks, project boundary logic in vector search, and FK errors in SQLite updates.

**Architecture:**
This design implements 4 targeted fixes across the context_store:
1.  **LifecycleState Lock Semantics (`manager.py`, `sqlite.py`)**: Split general state update timestamp (`updated_at`) from the cleanup lock logic. Introduce `cleanup_lock_owner` and `cleanup_lock_touched_at`. Use Compare-And-Swap (CAS) updates for acquiring, releasing, and heartbeating the lock, ensuring operations only succeed if the expected owner token matches.
2.  **Coroutine Leaks (`manager.py`)**: Update `LifecycleManager._spawn_background_task` to accept a factory `Callable[[], Coroutine]` instead of a `Coroutine` object. If `self._shutting_down` is True, the factory is not invoked, preventing coroutine objects from leaking un-awaited. This applies to calls like `self._spawn_background_task(self._check_time_based_cleanup)`.
3.  **Project Boundaries (`consolidator.py`)**: Inside `Consolidator.run()`, add an explicit guard condition when evaluating `scored_neighbors`. If `scored.memory.project != memory.project` (treating `None == None` as allowed), `continue` the loop before applying threshold checks.
4.  **SQLite FK Errors (`sqlite.py`)**: In `SQLiteStorageAdapter.update_memory`, unconditionally execute a `SELECT 1 FROM memories WHERE id = ?` check using the current connection before performing an `INSERT OR REPLACE` into `memory_embeddings`, regardless of whether `set_parts` is truthy. Ensure `updated = 1` is set when only the embedding is updated.

**Tech Stack:** Python 3.12, asyncio, aiosqlite, sqlite-vec

---

### Component 1: Lifecycle Lock Semantics
*   **Target Files:** `src/context_store/lifecycle/manager.py`, `src/context_store/storage/sqlite.py`, and test files.
*   **Changes:**
    *   `LifecycleState`: Replace `cleanup_running` with `cleanup_lock_owner: str | None` and `cleanup_lock_touched_at: datetime | None`.
    *   `LifecycleStateStore`:
        *   Update signature of `acquire_cleanup_lock` to take a `token: str`.
        *   Update signature of `release_cleanup_lock` to take a `token: str`.
        *   Add `heartbeat_cleanup_lock(token: str) -> None`.
        *   Ensure `increment_save_count` no longer updates any lock timestamp.
    *   `SQLiteLifecycleStateStore`: Implement CAS logic. `release` and `heartbeat` must include `WHERE cleanup_lock_owner = ?` using the provided token. `acquire` logic checks for `cleanup_lock_owner IS NULL` OR stale lock based on `cleanup_lock_touched_at`.
    *   `LifecycleManager`: Generate a UUID in `run_cleanup()` as the token. Pass this token to `acquire`, `release`. Update any tests mocking these methods.

### Component 2: Coroutine Leaks
*   **Target Files:** `src/context_store/lifecycle/manager.py`.
*   **Changes:**
    *   In `LifecycleManager`, redefine `_spawn_background_task(self, factory: Callable[[], Coroutine[Any, Any, None]]) -> None`.
    *   In `_spawn_background_task`, check `if getattr(self, "_shutting_down", False): return`. Only then call `factory()` to get the coroutine and pass it to `asyncio.create_task()`.
    *   In `start()`, change the call to `self._spawn_background_task(self._check_time_based_cleanup)`. (No parentheses on `_check_time_based_cleanup`).
    *   In `on_memory_saved()`, change the call to `self._spawn_background_task(self.run_cleanup)`. (No parentheses).
    *   In `run_cleanup()`, change the follow-up call to `self._spawn_background_task(self.run_cleanup)`. (No parentheses).

### Component 3: Consolidator Project Boundaries
*   **Target Files:** `src/context_store/lifecycle/consolidator.py`.
*   **Changes:**
    *   In `run()`, within the `for scored in scored_neighbors:` loop, add:
        ```python
        if scored.memory.project != memory.project:
            continue
        ```
        before the existing threshold checks (`scored.score >= self._dedup_threshold`).

### Component 4: SQLite FK Errors
*   **Target Files:** `src/context_store/storage/sqlite.py`.
*   **Changes:**
    *   In `update_memory()`, before validating and inserting the embedding, add:
        ```python
        async with conn.execute(
            "SELECT 1 FROM memories WHERE id = ?", (memory_id,)
        ) as cursor:
            if not await cursor.fetchone():
                return False
        ```
    *   This must happen unconditionally if `embedding` is provided, even if `set_parts` has values. Remove the old `if not set_parts:` condition around this check.
    *   Keep the dimension validation and `INSERT OR REPLACE`. Ensure `updated = 1` is set if the embedding update succeeds and `set_parts` was empty.