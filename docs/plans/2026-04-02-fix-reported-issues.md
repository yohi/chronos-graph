# Fix Reported Issues Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix various minor issues reported in code, documentation, and tests.

**Architecture:** Surgical updates to existing files to address specific nitpicks and bugs including exception handling, timeout logic, and test assertions.

**Tech Stack:** Python, Pytest, aiosqlite, asyncpg, markdownlint-cli2

---

### Task 1: Update Documentation (MD001 & AI Instructions)

**Files:**
- Modify: `docs/plans/2026-04-01-config-wal-validation-test-update.md`

**Step 1: Fix heading hierarchy and remove AI-only instruction**

Change `### Task 1` to `## Task 1` and remove the `> **For Claude:**` line.

**Step 2: Verify with markdownlint**

Run: `markdownlint-cli2 docs/plans/2026-04-01-config-wal-validation-test-update.md`
Expected: No MD001 error.

### Task 2: Fix mypy ignore in postgres.py

**Files:**
- Modify: `src/context_store/storage/postgres.py`

**Step 1: Update type ignore tag**

Change `# type: ignore[import-untyped]` to `# type: ignore[import-not-found]` for `asyncpg`.

**Step 2: Verify with mypy (optional if env allows)**

Run: `mypy src/context_store/storage/postgres.py`
Expected: No "import-not-found" for asyncpg.

### Task 3: Refactor sqlite_graph.py (Exception Handling & List Unpacking)

**Files:**
- Modify: `src/context_store/storage/sqlite_graph.py`

**Step 1: Update exception handling in query execution**

Re-raise `asyncio.CancelledError` and log other exceptions with `logger.exception`.

**Step 2: Update list concatenation to unpacking**

Use `[*seed_params, ...]` syntax for `params`.

**Step 3: Verify tests pass**

Run: `pytest tests/unit/test_sqlite_graph.py`
Expected: PASS

### Task 4: Fix Timeout Logic & Add Comments in sqlite_graph.py

**Files:**
- Modify: `src/context_store/storage/sqlite_graph.py`

**Step 1: Move asyncio.wait_for inside the interrupt context**

Ensure `asyncio.wait_for` is called within `async with ctx:`.

**Step 2: Add explanatory comments for private attribute access**

Document `conn._conn` usage and aiosqlite version dependency.

**Step 3: Verify tests pass**

Run: `pytest tests/unit/test_sqlite_graph.py`
Expected: PASS

### Task 5: Update Tests (Assertions & Mocking)

**Files:**
- Modify: `tests/unit/test_sqlite_graph.py`
- Modify: `tests/unit/test_storage_factory.py`

**Step 1: Add traversal_depth assertion in test_sqlite_graph.py**

Ensure `result.traversal_depth == 0` is checked in timeout cases.

**Step 2: Fix mock pool in test_storage_factory.py**

Replace `storage._pool = None` with a mock pool having an `AsyncMock` close method.

**Step 3: Remove redundant imports in test_storage_factory.py**

Clean up duplicated `AsyncMock` and `patch` imports.

**Step 4: Run all unit tests**

Run: `pytest tests/unit/`
Expected: ALL PASS
