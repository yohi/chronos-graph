# Storage Validation and Connection Optimization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** ストレージアダプターのバリデーション強化と SQLite 接続の最適化。

**Architecture:** Postgres と SQLite の両アダプターにおいて、無効な入力に対するバリデーションを強化し、`StorageError` を送出するようにします。また、SQLite のバッチ取得処理において、ループ外で接続を管理するようにリファクタリングします。

**Tech Stack:** Python, asyncpg (Postgres), aiosqlite (SQLite), pytest.

---

### Task 1: Postgres Validation Improvement

**Files:**
- Modify: `src/context_store/storage/postgres.py`
- Test: `tests/unit/test_postgres_storage.py`

**Step 1: Write the failing tests**

```python
# tests/unit/test_postgres_storage.py に追加
class TestGetMemoriesValidation:
    @pytest.mark.asyncio
    async def test_get_memories_invalid_order_by(self, adapter):
        adp, _ = adapter
        filters = MemoryFilters(order_by="invalid_col ASC")
        with pytest.raises(StorageError) as exc:
            await adp.get_memories(filters)
        assert exc.value.code == "INVALID_PARAMETER"

    @pytest.mark.asyncio
    async def test_get_memories_invalid_direction(self, adapter):
        adp, _ = adapter
        filters = MemoryFilters(order_by="created_at NOT_A_DIRECTION")
        with pytest.raises(StorageError) as exc:
            await adp.get_memories(filters)
        assert exc.value.code == "INVALID_PARAMETER"

    @pytest.mark.asyncio
    async def test_get_memories_invalid_limit_type(self, adapter):
        adp, _ = adapter
        filters = MemoryFilters()
        filters.limit = "not-an-int"
        with pytest.raises(StorageError) as exc:
            await adp.get_memories(filters)
        assert exc.value.code == "INVALID_PARAMETER"

    @pytest.mark.asyncio
    async def test_get_memories_negative_limit(self, adapter):
        adp, _ = adapter
        filters = MemoryFilters(limit=-1)
        with pytest.raises(StorageError) as exc:
            await adp.get_memories(filters)
        assert exc.value.code == "INVALID_PARAMETER"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_postgres_storage.py -k TestGetMemoriesValidation -v`
Expected: FAIL

**Step 3: Write implementation**

`src/context_store/storage/postgres.py` の `get_memories` 内の `order_by` と `limit` 処理を修正。

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_postgres_storage.py -k TestGetMemoriesValidation -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/context_store/storage/postgres.py tests/unit/test_postgres_storage.py
git commit -m "feat(postgres): add strict validation for order_by and limit"
```

---

### Task 2: SQLite update_memory Validation

**Files:**
- Modify: `src/context_store/storage/sqlite.py`
- Test: `tests/unit/test_sqlite_storage.py`

**Step 1: Write the failing tests**

```python
# tests/unit/test_sqlite_storage.py に追加
class TestUpdateMemoryValidation:
    @pytest.mark.asyncio
    async def test_update_memory_invalid_json(self, adapter):
        memory = _make_memory()
        mid = await adapter.save_memory(memory)
        with pytest.raises(StorageError) as exc:
            await adapter.update_memory(mid, {"tags": "invalid-json["})
        assert exc.value.code == "INVALID_PARAMETER"

    @pytest.mark.asyncio
    async def test_update_memory_invalid_tags_type(self, adapter):
        memory = _make_memory()
        mid = await adapter.save_memory(memory)
        with pytest.raises(StorageError) as exc:
            await adapter.update_memory(mid, {"tags": '{"not": "a list"}'})
        assert exc.value.code == "INVALID_PARAMETER"

    @pytest.mark.asyncio
    async def test_update_memory_invalid_metadata_type(self, adapter):
        memory = _make_memory()
        mid = await adapter.save_memory(memory)
        with pytest.raises(StorageError) as exc:
            await adapter.update_memory(mid, {"source_metadata": "[not, an, object]"})
        assert exc.value.code == "INVALID_PARAMETER"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_sqlite_storage.py -k TestUpdateMemoryValidation -v`
Expected: FAIL

**Step 3: Write implementation**

`src/context_store/storage/sqlite.py` の `update_memory` 内のループを修正。

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_sqlite_storage.py -k TestUpdateMemoryValidation -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/context_store/storage/sqlite.py tests/unit/test_sqlite_storage.py
git commit -m "feat(sqlite): add strict validation for tags and source_metadata in update_memory"
```

---

### Task 3: SQLite Connection Optimization

**Files:**
- Modify: `src/context_store/storage/sqlite.py`

**Step 1: Refactor get_memories_batch**

`src/context_store/storage/sqlite.py` の `get_memories_batch` を修正して接続を再利用するようにする。

**Step 2: Run existing tests to verify correctness**

Run: `pytest tests/unit/test_sqlite_storage.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add src/context_store/storage/sqlite.py
git commit -m "perf(sqlite): reuse database connection in get_memories_batch"
```
