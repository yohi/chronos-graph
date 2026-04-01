"""
Integration tests for PostgreSQL Storage Adapter.

Requires: docker compose up -d postgres
Each test runs inside a transaction that is rolled back after the test.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, AsyncMock

import pytest

from context_store.models.memory import Memory, MemoryType, SourceType
from context_store.storage.postgres import PostgresStorageAdapter
from context_store.storage.protocols import MemoryFilters, StorageError


pytestmark = pytest.mark.integration


def _make_memory(**kwargs: Any) -> Memory:
    defaults: dict[str, Any] = {
        "content": "integration test content",
        "memory_type": MemoryType.EPISODIC,
        "source_type": SourceType.MANUAL,
        "embedding": [0.1] * 768,
        "project": "test_project",
    }
    defaults.update(kwargs)
    return Memory(**defaults)


@pytest.fixture
def adapter(db_session):
    """PostgresStorageAdapter wrapping the transactional test connection."""
    # Wrap the single connection in a mock pool that yields it directly
    mock_pool = MagicMock()
    mock_pool.close = AsyncMock()

    class _FakeAcquire:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *args):
            pass

    mock_pool.acquire = MagicMock(return_value=_FakeAcquire())

    adp = PostgresStorageAdapter.__new__(PostgresStorageAdapter)
    adp._pool = mock_pool
    return adp


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

class TestCRUD:
    async def test_save_and_get(self, adapter):
        memory = _make_memory(content="save and get test")
        returned_id = await adapter.save_memory(memory)
        assert returned_id == str(memory.id)

        fetched = await adapter.get_memory(returned_id)
        assert fetched is not None
        assert fetched.content == "save and get test"
        assert fetched.memory_type == MemoryType.EPISODIC

    async def test_delete_existing(self, adapter):
        memory = _make_memory(content="to be deleted")
        memory_id = await adapter.save_memory(memory)

        result = await adapter.delete_memory(memory_id)

        assert result is True
        assert await adapter.get_memory(memory_id) is None

    async def test_delete_nonexistent_returns_false(self, adapter):
        from uuid import uuid4
        result = await adapter.delete_memory(str(uuid4()))
        assert result is False

    async def test_update_importance_score(self, adapter):
        memory = _make_memory(content="update test")
        memory_id = await adapter.save_memory(memory)

        result = await adapter.update_memory(memory_id, {"importance_score": 0.99})

        assert result is True
        updated = await adapter.get_memory(memory_id)
        assert updated is not None
        assert updated.importance_score == pytest.approx(0.99)

    async def test_duplicate_content_raises_storage_error(self, adapter):
        memory = _make_memory(content="unique content xyz")
        await adapter.save_memory(memory)

        duplicate = _make_memory(content="unique content xyz")
        with pytest.raises(StorageError) as exc_info:
            await adapter.save_memory(duplicate)
        assert exc_info.value.code == "DUPLICATE_CONTENT"


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

class TestSearch:
    async def test_vector_search_returns_results(self, adapter):
        memory = _make_memory(content="vector search target", embedding=[0.5] * 768)
        await adapter.save_memory(memory)

        results = await adapter.vector_search([0.5] * 768, top_k=5)

        assert len(results) >= 1
        contents = [r.memory.content for r in results]
        assert "vector search target" in contents

    async def test_vector_search_filters_by_project(self, adapter):
        m1 = _make_memory(content="proj a content", embedding=[0.1] * 768, project="proj_a")
        m2 = _make_memory(content="proj b content", embedding=[0.1] * 768, project="proj_b")
        await adapter.save_memory(m1)
        await adapter.save_memory(m2)

        results = await adapter.vector_search([0.1] * 768, top_k=10, project="proj_a")

        projects = {r.memory.project for r in results}
        assert "proj_b" not in projects

    async def test_keyword_search_returns_results(self, adapter):
        memory = _make_memory(content="keyword banana search test")
        await adapter.save_memory(memory)

        results = await adapter.keyword_search("banana", top_k=5)

        assert len(results) >= 1
        contents = [r.memory.content for r in results]
        assert any("banana" in c for c in contents)

    async def test_keyword_search_filters_by_project(self, adapter):
        m1 = _make_memory(content="apple in project X", project="proj_x")
        m2 = _make_memory(content="apple in project Y", project="proj_y")
        await adapter.save_memory(m1)
        await adapter.save_memory(m2)

        results = await adapter.keyword_search("apple", top_k=10, project="proj_x")

        projects = {r.memory.project for r in results}
        assert "proj_y" not in projects


# ---------------------------------------------------------------------------
# list_by_filter
# ---------------------------------------------------------------------------

class TestListByFilter:
    async def test_lists_active_memories(self, adapter):
        memory = _make_memory(content="active memory")
        await adapter.save_memory(memory)

        results = await adapter.list_by_filter(MemoryFilters())

        assert any(m.content == "active memory" for m in results)

    async def test_lists_archived_memories(self, adapter):
        from datetime import datetime, timezone
        memory = _make_memory(content="archived memory")
        memory_id = await adapter.save_memory(memory)
        await adapter.update_memory(
            memory_id, {"archived_at": datetime.now(timezone.utc)}
        )

        results = await adapter.list_by_filter(MemoryFilters(archived=True))

        assert any(m.content == "archived memory" for m in results)

    async def test_filters_by_memory_type(self, adapter):
        m_ep = _make_memory(content="episodic type", memory_type=MemoryType.EPISODIC)
        m_se = _make_memory(content="semantic type", memory_type=MemoryType.SEMANTIC)
        await adapter.save_memory(m_ep)
        await adapter.save_memory(m_se)

        results = await adapter.list_by_filter(MemoryFilters(memory_type="semantic"))

        types = {m.memory_type for m in results}
        assert MemoryType.EPISODIC not in types


# ---------------------------------------------------------------------------
# get_vector_dimension
# ---------------------------------------------------------------------------

class TestGetVectorDimension:
    async def test_returns_768_after_save(self, adapter):
        memory = _make_memory(embedding=[0.1] * 768)
        await adapter.save_memory(memory)

        dim = await adapter.get_vector_dimension()

        assert dim == 768

    async def test_returns_none_when_empty(self, adapter):
        # No memories saved in this transaction yet
        dim = await adapter.get_vector_dimension()
        assert dim is None
