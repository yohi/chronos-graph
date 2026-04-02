# Fix Reported Issues Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix ingestion pipeline cache collisions and PostgreSQL storage formatting/typing issues.

**Architecture:** Update `memo_key` in the pipeline to include `document_id` for uniqueness. Refactor `delete_memory` in the PostgreSQL adapter for type safety and apply standard formatting.

**Tech Stack:** Python, asyncpg, ruff, mypy, pytest

---

### Task 1: Update Ingestion Pipeline Cache Key

**Files:**
- Modify: `src/context_store/ingestion/pipeline.py:227-237`
- Test: `tests/unit/test_ingestion_pipeline.py`

**Step 1: Write the failing test**

Modify `tests/unit/test_ingestion_pipeline.py` to add a test case that verifies `memo_key` uniqueness across different `document_id`s.

```python
async def test_process_chunk_memo_key_uniqueness(pipeline, sample_chunk):
    # Same content, different document_id
    chunk1 = sample_chunk
    chunk1.metadata["document_id"] = "doc1"
    
    chunk2 = copy.deepcopy(sample_chunk)
    chunk2.metadata["document_id"] = "doc2"
    
    # Manually check the logic that would be in _process_chunk
    # This might require making _compute_hash or the key generation logic accessible or testing via side effects
    # Better: test that two separate tasks are created for different document_ids even with same content
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_ingestion_pipeline.py -v`
Expected: Collision (if we can observe it) or fail to distinguish.

**Step 3: Write minimal implementation**

```python
<<<<
        url = chunk.metadata.get("url") or chunk.metadata.get("source_id", "")
        chunk_index = chunk.metadata.get("chunk_index", 0)
        memo_key = (
            content_hash,
            project_id,
            session_id,
            source_type,
            url,
            chunk_index,
        )
====
        url = chunk.metadata.get("url") or chunk.metadata.get("source_id", "")
        chunk_index = chunk.metadata.get("chunk_index", 0)
        document_id = chunk.metadata.get("document_id", "")
        memo_key = (
            content_hash,
            project_id,
            session_id,
            source_type,
            url,
            chunk_index,
            document_id,
        )
>>>>
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_ingestion_pipeline.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/context_store/ingestion/pipeline.py
git commit -m "fix(ingestion): memo_keyにdocument_idを追加しキャッシュ衝突を防止"
```

---

### Task 2: Fix PostgreSQL Storage `delete_memory` and Formatting

**Files:**
- Modify: `src/context_store/storage/postgres.py`
- Test: `tests/unit/test_postgres_storage.py`

**Step 1: Verify existing tests and run mypy**

Run: `pytest tests/unit/test_postgres_storage.py -v`
Run: `mypy src/context_store/storage/postgres.py`
Expected: `pytest` passes, `mypy` might show warnings if `type: ignore` is removed.

**Step 2: Refactor `delete_memory`**

```python
<<<<
    async def delete_memory(self, memory_id: str) -> bool:
        """Delete a memory. Returns True if deleted."""
        sql = "DELETE FROM memories WHERE id = $1"
        async with self._pool.acquire() as conn:
            status = await conn.execute(sql, memory_id)
        return status == "DELETE 1"  # type: ignore[no-any-return]
====
    async def delete_memory(self, memory_id: str) -> bool:
        """Delete a memory. Returns True if deleted."""
        sql = "DELETE FROM memories WHERE id = $1"
        async with self._pool.acquire() as conn:
            status = await conn.execute(sql, memory_id)
        return str(status) == "DELETE 1"
>>>>
```

**Step 3: Apply ruff formatting**

Run: `ruff format src/context_store/storage/postgres.py`

**Step 4: Verify with mypy and ruff check**

Run: `mypy src/context_store/storage/postgres.py`
Run: `ruff format --check src/context_store/storage/postgres.py`
Expected: No errors/warnings.

**Step 5: Run unit tests**

Run: `pytest tests/unit/test_postgres_storage.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add src/context_store/storage/postgres.py
git commit -m "fix(storage.postgres): delete_memoryの型安全性を向上し、フォーマットを修正"
```
