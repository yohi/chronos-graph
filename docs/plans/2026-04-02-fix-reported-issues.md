# Fix Reported Issues Implementation Plan

**Goal:** Fix various minor issues reported in code, documentation, and tests.

**Architecture:** Surgical updates to existing files to address specific nitpicks and bugs including exception handling, timeout logic, and test assertions.

**Tech Stack:** Python, Pytest, aiosqlite, asyncpg, markdownlint-cli2

---

## Task 1: Update Documentation (MD001 & AI Instructions)

**Files:**
- Modify: `docs/plans/2026-04-01-config-wal-validation-test-update.md`

**Step 1: Fix heading hierarchy and remove AI-only instruction**

Change task headings to use appropriate levels and remove any embedded agent-specific instructions.

**Step 2: Verify with markdownlint**

Ensure the document passes standard markdown linting checks.

## Task 2: Fix mypy ignore in postgres.py

**Files:**
- Modify: `src/context_store/storage/postgres.py`

**Step 1: Update type ignore tag**

Adjust the `type: ignore` tag for `asyncpg` to match current environment capabilities.

**Step 2: Verify with mypy**

Ensure the project passes strict typing validation.

## Task 3: Refactor sqlite_graph.py (Exception Handling & List Unpacking)

**Files:**
- Modify: `src/context_store/storage/sqlite_graph.py`

**Step 1: Update exception handling in query execution**

Improve robustness by handling cancellation and logging errors with context.

**Step 2: Update list concatenation to unpacking**

Use modern Python unpacking syntax for SQL parameters.

**Step 3: Verify tests pass**

Ensure all graph traversal unit tests remain green.

## Task 4: Fix Timeout Logic & Add Comments in sqlite_graph.py

**Files:**
- Modify: `src/context_store/storage/sqlite_graph.py`

**Step 1: Move asyncio.wait_for inside the interrupt context**

Correct the nesting of timeout logic and interrupt handling.

**Step 2: Add explanatory comments for private attribute access**

Document the rationale for using non-public API elements.

**Step 3: Verify tests pass**

Confirm that the fixes do not introduce regressions in existing graph tests.

## Task 5: Update Tests (Assertions & Mocking)

**Files:**
- Modify: `tests/unit/test_sqlite_graph.py`
- Modify: `tests/unit/test_storage_factory.py`

**Step 1: Add traversal_depth assertion in test_sqlite_graph.py**

Extend test coverage to include result depth verification in edge cases.

**Step 2: Fix mock pool in test_storage_factory.py**

Improve the accuracy of storage cleanup mocking.

**Step 3: Remove redundant imports in test_storage_factory.py**

Clean up unused or duplicate imports across test files.

**Step 4: Run all unit tests**

Execute the full unit test suite to ensure overall stability.
