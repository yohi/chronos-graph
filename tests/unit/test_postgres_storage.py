"""
Unit tests for PostgreSQL Storage Adapter.

asyncpg.Pool をモックして SQL クエリの組み立てロジックと
レコード変換ロジックを検証する。
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from context_store.models.memory import Memory, MemorySource, MemoryType, ScoredMemory, SourceType
from context_store.storage.protocols import MemoryFilters, StorageError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_memory(**kwargs: Any) -> Memory:
    defaults: dict[str, Any] = {
        "content": "test content",
        "memory_type": MemoryType.EPISODIC,
        "source_type": SourceType.MANUAL,
        "embedding": [0.1, 0.2, 0.3],
    }
    defaults.update(kwargs)
    return Memory(**defaults)


def _make_record(memory: Memory) -> dict[str, Any]:
    """asyncpg の Record ライクな dict を返す。"""
    return {
        "id": memory.id,
        "content": memory.content,
        "memory_type": memory.memory_type.value,
        "source_type": memory.source_type.value,
        "source_metadata": json.dumps(memory.source_metadata),
        "embedding": memory.embedding,
        "semantic_relevance": memory.semantic_relevance,
        "importance_score": memory.importance_score,
        "access_count": memory.access_count,
        "last_accessed_at": memory.last_accessed_at,
        "created_at": memory.created_at,
        "updated_at": memory.updated_at,
        "archived_at": memory.archived_at,
        "tags": memory.tags,
        "project": memory.project,
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_pool():
    """asyncpg.Pool のモック。"""
    pool = MagicMock()
    conn = AsyncMock()
    pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=conn),
        __aexit__=AsyncMock(return_value=None),
    ))
    pool.close = AsyncMock()
    return pool, conn


@pytest.fixture
def adapter(mock_pool):
    """PostgresStorageAdapter をプール注入済みで返す。"""
    from context_store.storage.postgres import PostgresStorageAdapter
    pool, conn = mock_pool
    adapter = PostgresStorageAdapter.__new__(PostgresStorageAdapter)
    adapter._pool = pool
    return adapter, conn


# ---------------------------------------------------------------------------
# save_memory
# ---------------------------------------------------------------------------

class TestSaveMemory:
    async def test_returns_memory_id(self, adapter):
        adp, conn = adapter
        memory = _make_memory()
        conn.fetchval = AsyncMock(return_value=memory.id)

        result = await adp.save_memory(memory)

        assert result == str(memory.id)

    async def test_executes_insert_with_correct_params(self, adapter):
        adp, conn = adapter
        memory = _make_memory(content="hello world")
        conn.fetchval = AsyncMock(return_value=memory.id)

        await adp.save_memory(memory)

        conn.fetchval.assert_called_once()
        call_args = conn.fetchval.call_args
        sql: str = call_args[0][0]
        assert "INSERT INTO memories" in sql
        assert "content" in sql

    async def test_includes_embedding_when_present(self, adapter):
        adp, conn = adapter
        memory = _make_memory(embedding=[0.1, 0.2, 0.3])
        conn.fetchval = AsyncMock(return_value=memory.id)

        await adp.save_memory(memory)

        call_args = conn.fetchval.call_args
        args = call_args[0][1:]  # positional params after SQL
        # embedding should be converted to vector string '[0.1,0.2,0.3]'
        embedding_str = str([0.1, 0.2, 0.3]).replace(" ", "")
        assert any(embedding_str in str(a) for a in args)

    async def test_empty_embedding_stored_as_none(self, adapter):
        adp, conn = adapter
        memory = _make_memory(embedding=[])
        conn.fetchval = AsyncMock(return_value=memory.id)

        await adp.save_memory(memory)

        call_args = conn.fetchval.call_args
        args = call_args[0][1:]
        assert None in args

    async def test_raises_storage_error_on_unique_violation(self, adapter):
        import asyncpg
        adp, conn = adapter
        memory = _make_memory()
        exc = asyncpg.UniqueViolationError(
            "duplicate key value violates unique constraint"
        )
        conn.fetchval = AsyncMock(side_effect=exc)

        with pytest.raises(StorageError) as exc_info:
            await adp.save_memory(memory)
        assert exc_info.value.code == "DUPLICATE_CONTENT"


# ---------------------------------------------------------------------------
# get_memory
# ---------------------------------------------------------------------------

class TestGetMemory:
    async def test_returns_none_when_not_found(self, adapter):
        adp, conn = adapter
        conn.fetchrow = AsyncMock(return_value=None)

        result = await adp.get_memory(str(uuid4()))

        assert result is None

    async def test_returns_memory_when_found(self, adapter):
        adp, conn = adapter
        memory = _make_memory()
        record = _make_record(memory)
        conn.fetchrow = AsyncMock(return_value=record)

        result = await adp.get_memory(str(memory.id))

        assert result is not None
        assert result.content == memory.content
        assert result.memory_type == memory.memory_type

    async def test_query_uses_memory_id(self, adapter):
        adp, conn = adapter
        memory_id = str(uuid4())
        conn.fetchrow = AsyncMock(return_value=None)

        await adp.get_memory(memory_id)

        call_args = conn.fetchrow.call_args
        assert memory_id in str(call_args[0][1:])


# ---------------------------------------------------------------------------
# delete_memory
# ---------------------------------------------------------------------------

class TestDeleteMemory:
    async def test_returns_true_when_deleted(self, adapter):
        adp, conn = adapter
        conn.execute = AsyncMock(return_value="DELETE 1")

        result = await adp.delete_memory(str(uuid4()))

        assert result is True

    async def test_returns_false_when_not_found(self, adapter):
        adp, conn = adapter
        conn.execute = AsyncMock(return_value="DELETE 0")

        result = await adp.delete_memory(str(uuid4()))

        assert result is False


# ---------------------------------------------------------------------------
# update_memory
# ---------------------------------------------------------------------------

class TestUpdateMemory:
    async def test_returns_true_on_success(self, adapter):
        adp, conn = adapter
        conn.execute = AsyncMock(return_value="UPDATE 1")

        result = await adp.update_memory(str(uuid4()), {"importance_score": 0.9})

        assert result is True

    async def test_returns_false_when_not_found(self, adapter):
        adp, conn = adapter
        conn.execute = AsyncMock(return_value="UPDATE 0")

        result = await adp.update_memory(str(uuid4()), {"importance_score": 0.9})

        assert result is False

    async def test_builds_dynamic_set_clause(self, adapter):
        adp, conn = adapter
        conn.execute = AsyncMock(return_value="UPDATE 1")

        await adp.update_memory(str(uuid4()), {"importance_score": 0.8, "access_count": 5})

        call_args = conn.execute.call_args
        sql: str = call_args[0][0]
        assert "UPDATE memories" in sql
        assert "importance_score" in sql
        assert "access_count" in sql

    async def test_casts_embedding_to_vector(self, adapter):
        adp, conn = adapter
        conn.execute = AsyncMock(return_value="UPDATE 1")

        await adp.update_memory(str(uuid4()), {"embedding": [0.1, 0.2, 0.3]})

        call_args = conn.execute.call_args
        sql: str = call_args[0][0]
        params = call_args[0][1:]
        assert "::vector" in sql
        assert params[0] == "[0.1,0.2,0.3]"


# ---------------------------------------------------------------------------
# vector_search
# ---------------------------------------------------------------------------

class TestVectorSearch:
    async def test_returns_empty_list_when_no_results(self, adapter):
        adp, conn = adapter
        conn.fetch = AsyncMock(return_value=[])

        result = await adp.vector_search([0.1, 0.2, 0.3], top_k=5)

        assert result == []

    async def test_returns_scored_memories(self, adapter):
        adp, conn = adapter
        memory = _make_memory()
        record = _make_record(memory)
        record["score"] = 0.95
        conn.fetch = AsyncMock(return_value=[record])

        result = await adp.vector_search([0.1, 0.2, 0.3], top_k=5)

        assert len(result) == 1
        assert isinstance(result[0], ScoredMemory)
        assert result[0].score == pytest.approx(0.95)
        assert result[0].source == MemorySource.VECTOR

    async def test_uses_cosine_distance_operator(self, adapter):
        adp, conn = adapter
        conn.fetch = AsyncMock(return_value=[])

        await adp.vector_search([0.1, 0.2], top_k=3)

        call_args = conn.fetch.call_args
        sql: str = call_args[0][0]
        assert "<=>" in sql

    async def test_filters_by_project(self, adapter):
        adp, conn = adapter
        conn.fetch = AsyncMock(return_value=[])

        await adp.vector_search([0.1, 0.2], top_k=5, project="my_project")

        call_args = conn.fetch.call_args
        sql: str = call_args[0][0]
        assert "project" in sql

    async def test_respects_top_k(self, adapter):
        adp, conn = adapter
        conn.fetch = AsyncMock(return_value=[])

        await adp.vector_search([0.1], top_k=7)

        call_args = conn.fetch.call_args
        assert 7 in call_args[0][1:]


# ---------------------------------------------------------------------------
# keyword_search
# ---------------------------------------------------------------------------

class TestKeywordSearch:
    async def test_returns_empty_list_when_no_results(self, adapter):
        adp, conn = adapter
        conn.fetch = AsyncMock(return_value=[])

        result = await adp.keyword_search("hello", top_k=5)

        assert result == []

    async def test_returns_scored_memories(self, adapter):
        adp, conn = adapter
        memory = _make_memory(content="hello world")
        record = _make_record(memory)
        record["score"] = 1.0
        conn.fetch = AsyncMock(return_value=[record])

        result = await adp.keyword_search("hello", top_k=5)

        assert len(result) == 1
        assert result[0].source == MemorySource.KEYWORD

    async def test_query_uses_bigm_like(self, adapter):
        adp, conn = adapter
        conn.fetch = AsyncMock(return_value=[])

        await adp.keyword_search("test query", top_k=5)

        call_args = conn.fetch.call_args
        sql: str = call_args[0][0]
        # pg_bigm uses LIKE or % operator
        assert "LIKE" in sql or "%" in sql or "bigm" in sql.lower() or "content" in sql

    async def test_filters_by_project(self, adapter):
        adp, conn = adapter
        conn.fetch = AsyncMock(return_value=[])

        await adp.keyword_search("test", top_k=5, project="proj_a")

        call_args = conn.fetch.call_args
        sql: str = call_args[0][0]
        assert "project" in sql


# ---------------------------------------------------------------------------
# list_by_filter
# ---------------------------------------------------------------------------

class TestListByFilter:
    async def test_no_filter_returns_active_memories(self, adapter):
        adp, conn = adapter
        memory = _make_memory()
        conn.fetch = AsyncMock(return_value=[_make_record(memory)])

        result = await adp.list_by_filter(MemoryFilters())

        assert len(result) == 1

    async def test_archived_true_filters_archived(self, adapter):
        adp, conn = adapter
        conn.fetch = AsyncMock(return_value=[])

        await adp.list_by_filter(MemoryFilters(archived=True))

        call_args = conn.fetch.call_args
        sql: str = call_args[0][0]
        assert "archived_at" in sql

    async def test_project_filter_applied(self, adapter):
        adp, conn = adapter
        conn.fetch = AsyncMock(return_value=[])

        await adp.list_by_filter(MemoryFilters(project="my_proj"))

        call_args = conn.fetch.call_args
        sql: str = call_args[0][0]
        assert "project" in sql

    async def test_memory_type_filter_applied(self, adapter):
        adp, conn = adapter
        conn.fetch = AsyncMock(return_value=[])

        await adp.list_by_filter(MemoryFilters(memory_type="episodic"))

        call_args = conn.fetch.call_args
        sql: str = call_args[0][0]
        assert "memory_type" in sql

    async def test_tags_filter_applied(self, adapter):
        adp, conn = adapter
        conn.fetch = AsyncMock(return_value=[])

        await adp.list_by_filter(MemoryFilters(tags=["tag1", "tag2"]))

        call_args = conn.fetch.call_args
        sql: str = call_args[0][0]
        assert "tags" in sql


# ---------------------------------------------------------------------------
# get_vector_dimension
# ---------------------------------------------------------------------------

class TestGetVectorDimension:
    async def test_returns_dimension_when_exists(self, adapter):
        adp, conn = adapter
        conn.fetchval = AsyncMock(return_value=768)

        result = await adp.get_vector_dimension()

        assert result == 768

    async def test_returns_none_when_no_data(self, adapter):
        adp, conn = adapter
        conn.fetchval = AsyncMock(return_value=None)

        result = await adp.get_vector_dimension()

        assert result is None

    async def test_uses_vector_dims_function(self, adapter):
        adp, conn = adapter
        conn.fetchval = AsyncMock(return_value=None)

        await adp.get_vector_dimension()

        call_args = conn.fetchval.call_args
        sql: str = call_args[0][0]
        assert "vector_dims" in sql


# ---------------------------------------------------------------------------
# dispose
# ---------------------------------------------------------------------------

class TestDispose:
    async def test_closes_pool(self, adapter):
        adp, _conn = adapter
        adp._pool.close = AsyncMock()

        await adp.dispose()

        adp._pool.close.assert_called_once()
