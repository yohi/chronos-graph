from typing import Protocol
from unittest.mock import AsyncMock

import pytest
from context_store.retrieval.vector_search import VectorSearch
from context_store.models.search import ScoredMemory


class MockEmbeddingProvider(Protocol):
    """Embedding Provider のモック型"""

    async def embed(self, text: str) -> list[float]: ...
    @property
    def dimension(self) -> int: ...


@pytest.fixture
def embedding_provider() -> MockEmbeddingProvider:
    """Embedding Provider のモック"""
    provider = AsyncMock()
    provider.embed = AsyncMock(return_value=[0.1, 0.2, 0.3, 0.4, 0.5])
    return provider


@pytest.fixture
def storage_adapter():
    """Storage Adapter のモック"""
    from context_store.models.memory import Memory, MemoryType, SourceType, MemorySource
    from uuid import UUID

    adapter = AsyncMock()
    mem1 = Memory(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        content="JWT認証",
        memory_type=MemoryType.SEMANTIC,
        source_type=SourceType.MANUAL,
        importance_score=0.8,
    )
    mem2 = Memory(
        id=UUID("00000000-0000-0000-0000-000000000002"),
        content="OAuth 実装",
        memory_type=MemoryType.SEMANTIC,
        source_type=SourceType.MANUAL,
        importance_score=0.7,
    )
    scored_memories = [
        ScoredMemory(memory=mem1, score=0.95, source=MemorySource.VECTOR),
        ScoredMemory(memory=mem2, score=0.85, source=MemorySource.VECTOR),
    ]
    adapter.vector_search = AsyncMock(return_value=scored_memories)
    return adapter


@pytest.fixture
def vector_search(embedding_provider, storage_adapter):
    """VectorSearch インスタンス"""
    return VectorSearch(embedding_provider, storage_adapter)


class TestVectorSearch:
    """ベクトル検索のテスト"""

    @pytest.mark.asyncio
    async def test_search_embeds_query(self, vector_search, embedding_provider):
        """クエリがベクトル化されること"""
        query = "JWT認証の実装"
        await vector_search.search(query, top_k=10)

        # embed が呼ばれたことを確認
        embedding_provider.embed.assert_called_once_with(query)

    @pytest.mark.asyncio
    async def test_search_calls_storage_adapter(
        self, vector_search, embedding_provider, storage_adapter
    ):
        """Storage Adapter の vector_search が呼ばれること"""
        query = "JWT認証"
        top_k = 5

        await vector_search.search(query, top_k=top_k)

        # Storage Adapter の vector_search が呼ばれたことを確認
        storage_adapter.vector_search.assert_called_once()
        call_args = storage_adapter.vector_search.call_args
        assert call_args[1]["top_k"] == top_k
        # ベクトルは embed の戻り値と同じ
        assert call_args[1]["embedding"] == [0.1, 0.2, 0.3, 0.4, 0.5]

    @pytest.mark.asyncio
    async def test_search_returns_results(self, vector_search):
        """検索結果が返されること"""
        from uuid import UUID

        results = await vector_search.search("JWT認証", top_k=10)

        assert len(results) == 2
        assert results[0].memory.id == UUID("00000000-0000-0000-0000-000000000001")
        assert results[0].score == 0.95
        assert results[1].memory.id == UUID("00000000-0000-0000-0000-000000000002")
        assert results[1].score == 0.85

    @pytest.mark.asyncio
    async def test_search_with_custom_top_k(self, vector_search, storage_adapter):
        """カスタムの top_k パラメータが使用されること"""
        await vector_search.search("query", top_k=20)

        call_args = storage_adapter.vector_search.call_args
        assert call_args[1]["top_k"] == 20

    @pytest.mark.asyncio
    async def test_search_default_top_k(self, vector_search, storage_adapter):
        """デフォルトの top_k が使用されること"""
        await vector_search.search("query")

        call_args = storage_adapter.vector_search.call_args
        assert call_args[1]["top_k"] == 10

    @pytest.mark.asyncio
    async def test_search_handles_empty_results(self, vector_search, storage_adapter):
        """検索結果が空の場合に対応すること"""
        storage_adapter.vector_search.return_value = []

        results = await vector_search.search("nonexistent query", top_k=10)

        assert results == []
