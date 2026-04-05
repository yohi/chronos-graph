# Traversal Timeout and Settings Helper Design

**Date:** 2026-04-02
**Topic:** Improvement of graph traversal timeout handling and centralization of test settings helper.

## 1. Graph Traversal Timeout Improvement

### Problem
Current implementation in `src/context_store/storage/sqlite_graph.py` handles `asyncio.TimeoutError` but does not explicitly handle `asyncio.CancelledError` within the `SafeSqliteInterruptCtx` context. This may lead to SQLite queries continuing after cancellation or incomplete reporting of partial results.

### Solution
Wrap `asyncio.wait_for` with a try-except block that catches both `TimeoutError` and `CancelledError`. Ensure that `ctx.interrupt()` is called while the context is still active, and populate the `partial_container` with the necessary flags.

### Data Flow
1. Enter `async with ctx:` (SafeSqliteInterruptCtx).
2. Execute `asyncio.wait_for(self._traverse_inner(...), timeout=self._timeout)`.
3. If `TimeoutError` or `CancelledError` occurs:
   - Access `partial_container[0]` if it exists.
   - Set `res.partial = True` and `res.timeout = True`.
   - Call `ctx.interrupt()`.
   - Re-raise the exception to allow standard propagation.
4. Outer `except asyncio.TimeoutError:` handles the final return of the partial result.

## 2. Centralized `make_settings` Helper

### Problem
Multiple test files define their own `make_settings` helper with similar but diverging defaults. This makes the tests harder to maintain.

### Solution
Move `make_settings` to `tests/unit/conftest.py` and make it available to all unit tests.

### Implementation Details
- Define `make_settings(**kwargs) -> Settings` in `tests/unit/conftest.py`.
- Include a comprehensive set of default values that satisfy all existing tests.
- Update `tests/unit/test_config.py`, `tests/unit/test_sqlite_graph.py`, and `tests/unit/test_storage_factory.py` to use the shared helper.

## 3. Verification Plan
- Run existing tests to ensure no regressions.
- Verify timeout behavior in `tests/unit/test_sqlite_graph.py` with the updated assertions.
- Ensure all tests pass with the centralized `make_settings`.
