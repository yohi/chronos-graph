"""Keyword Search のテスト"""

from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from context_store.models.memory import Memory, MemorySource, MemoryType, SourceType
from context_store.models.search import ScoredMemory
from context_store.retrieval.keyword_search import KeywordSearch


@pytest.fixture
def storage_adapter():
    """Storage Adapter のモック"""
    mem1 = Memory(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        content="データベース接続エラー",
        memory_type=MemoryType.SEMANTIC,
        source_type=SourceType.MANUAL,
    )
    mem2 = Memory(
        id=UUID("00000000-0000-0000-0000-000000000002"),
        content="SQL文法エラー",
        memory_type=MemoryType.SEMANTIC,
        source_type=SourceType.MANUAL,
    )
    adapter = AsyncMock()
    adapter.keyword_search = AsyncMock(
        return_value=[
            ScoredMemory(memory=mem1, score=0.9, source=MemorySource.KEYWORD),
            ScoredMemory(memory=mem2, score=0.8, source=MemorySource.KEYWORD),
        ]
    )
    return adapter


@pytest.fixture
def keyword_search(storage_adapter):
    """KeywordSearch インスタンス"""
    return KeywordSearch(storage_adapter)


class TestKeywordSearch:
    """キーワード検索のテスト"""

    @pytest.mark.asyncio
    async def test_search_calls_storage_adapter(self, keyword_search, storage_adapter):
        """Storage Adapter の keyword_search が呼ばれること"""
        query = "データベース エラー"
        await keyword_search.search(query, top_k=10)

        # Storage Adapter の keyword_search が呼ばれたことを確認
        storage_adapter.keyword_search.assert_called_once()
        call_args = storage_adapter.keyword_search.call_args
        assert call_args[1]["top_k"] == 10

    @pytest.mark.asyncio
    async def test_search_returns_results(self, keyword_search):
        """検索結果が返されること"""
        results = await keyword_search.search("エラー", top_k=10)

        assert len(results) == 2
        assert results[0].memory.id == UUID("00000000-0000-0000-0000-000000000001")
        assert results[0].score == 0.9
        assert results[1].memory.id == UUID("00000000-0000-0000-0000-000000000002")
        assert results[1].score == 0.8

    @pytest.mark.asyncio
    async def test_search_with_custom_top_k(self, keyword_search, storage_adapter):
        """カスタムの top_k が使用されること"""
        await keyword_search.search("query", top_k=20)

        call_args = storage_adapter.keyword_search.call_args
        assert call_args[1]["top_k"] == 20

    @pytest.mark.asyncio
    async def test_search_default_top_k(self, keyword_search, storage_adapter):
        """デフォルトの top_k が使用されること"""
        await keyword_search.search("query")

        call_args = storage_adapter.keyword_search.call_args
        assert call_args[1]["top_k"] == 10

    @pytest.mark.asyncio
    async def test_search_handles_empty_results(self, keyword_search, storage_adapter):
        """検索結果が空の場合に対応すること"""
        storage_adapter.keyword_search.return_value = []

        results = await keyword_search.search("nonexistent", top_k=10)

        assert results == []
