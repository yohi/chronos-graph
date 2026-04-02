# SQLite list_memories SQL Injection Fix Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix SQL injection vulnerability in `SQLiteStorageAdapter.list_by_filter` by validating `order_by` and `limit` parameters.

**Architecture:** Use a whitelist-based validation for `order_by` columns and ensure `limit` is a safe integer before embedding in SQL.

**Tech Stack:** Python, aiosqlite, pytest

---

### Task 1: Reproduce Vulnerability with Failing Tests

**Files:**
- Modify: `tests/unit/test_sqlite_storage.py`

**Step 1: Write the failing tests**

Add `TestSqlInjection` class to `tests/unit/test_sqlite_storage.py`:

```python
class TestSqlInjection:
    async def test_list_by_filter_order_by_injection(self, adapter):
        # Malicious order_by to drop a table (SQLite allows multiple statements with executescript, 
        # but aiosqlite.execute might just fail or execute the first one. 
        # However, we can test for unexpected behavior or syntax errors.)
        malicious_order = "id; DROP TABLE memories;"
        filters = MemoryFilters(order_by=malicious_order)
        
        # Current implementation will likely raise a database error because the SQL becomes invalid:
        # SELECT ... ORDER BY id; DROP TABLE memories;
        # We want our fix to either:
        # 1. Raise a StorageError (INVALID_PARAMETER) before reaching the DB.
        # 2. Or safely ignore/sanitize it.
        # Given it's a security issue, raising StorageError is better.
        with pytest.raises(StorageError) as exc_info:
            await adapter.list_by_filter(filters)
        assert exc_info.value.code == "INVALID_PARAMETER"

    async def test_list_by_filter_limit_injection(self, adapter):
        malicious_limit = "1; DROP TABLE memories;"
        filters = MemoryFilters()
        filters.limit = malicious_limit
        
        with pytest.raises(StorageError) as exc_info:
            await adapter.list_by_filter(filters)
        assert exc_info.value.code == "INVALID_PARAMETER"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_sqlite_storage.py -k TestSqlInjection -v`
Expected: FAIL (either `AssertionError` if it doesn't raise, or `aiosqlite.OperationalError` instead of `StorageError`)

---

### Task 2: Implement Validation in `list_by_filter`

**Files:**
- Modify: `src/context_store/storage/sqlite.py`

**Step 1: Implement the fix**

Update `list_by_filter` in `src/context_store/storage/sqlite.py`:

```python
    async def list_by_filter(self, filters: MemoryFilters) -> list[Memory]:
        """List memories matching filters."""
        # ... (conditions setup) ...

        # Validation for order_by
        allowed_sort_columns = {
            "id", "content", "memory_type", "source_type", "semantic_relevance",
            "importance_score", "access_count", "last_accessed_at", "created_at",
            "updated_at", "archived_at", "project"
        }
        
        raw_order = filters.order_by or "m.created_at DESC"
        # Basic parsing: split by spaces and check column
        parts = raw_order.strip().split()
        if not parts:
            order_clause = "ORDER BY m.created_at DESC"
        else:
            col = parts[0].replace("m.", "")
            if col not in allowed_sort_columns:
                raise StorageError(f"Invalid sort column: {col}", code="INVALID_PARAMETER")
            
            direction = ""
            if len(parts) > 1:
                dir_part = parts[1].upper()
                if dir_part not in ("ASC", "DESC"):
                    raise StorageError(f"Invalid sort direction: {dir_part}", code="INVALID_PARAMETER")
                direction = dir_part
            
            order_clause = f"ORDER BY m.{col} {direction}"

        # Validation for limit
        limit_clause = ""
        if getattr(filters, "limit", None) is not None:
            try:
                limit_val = int(filters.limit)
                if limit_val < 0:
                    raise ValueError()
                limit_clause = f"LIMIT {limit_val}"
            except (ValueError, TypeError):
                raise StorageError(f"Invalid limit: {filters.limit}", code="INVALID_PARAMETER")

        # ... (rest of the method) ...
```

**Step 2: Run tests to verify it passes**

Run: `pytest tests/unit/test_sqlite_storage.py -k TestSqlInjection -v`
Expected: PASS

**Step 3: Run all unit tests to ensure no regressions**

Run: `pytest tests/unit/test_sqlite_storage.py -v`
Expected: PASS

---

### Task 3: Finalize and Commit

**Step 1: Commit the changes**

Run: `git add src/context_store/storage/sqlite.py tests/unit/test_sqlite_storage.py docs/plans/2026-04-03-sqlite-security-fix-plan.md`
Run: `git commit -m "fix(storage.sqlite): ORDER BYとLIMITのSQLインジェクション脆弱性を修正"`
