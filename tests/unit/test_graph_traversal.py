"""Graph Traversal のテスト"""
import pytest
from unittest.mock import AsyncMock
from context_store.retrieval.graph_traversal import GraphTraversal
from context_store.models.search import ScoredMemory
from context_store.models.memory import Memory, MemoryType, SourceType, MemorySource
from uuid import UUID


@pytest.fixture
def graph_adapter():
    """Graph Adapter のモック"""
    adapter = AsyncMock()
    adapter.traverse = AsyncMock(
        return_value=[
            {
                "id": UUID("00000000-0000-0000-0000-000000000001"),
                "score": 0.85,
            },
            {
                "id": UUID("00000000-0000-0000-0000-000000000002"),
                "score": 0.75,
            },
        ]
    )
    return adapter


@pytest.fixture
def graph_traversal(graph_adapter):
    """GraphTraversal インスタンス"""
    return GraphTraversal(graph_adapter)


class TestGraphTraversal:
    """グラフトラバーサルのテスト"""

    @pytest.mark.asyncio
    async def test_traverse_with_seed_ids(self, graph_traversal, graph_adapter):
        """起点ノードIDでグラフをトラバース"""
        seed_ids = [UUID("00000000-0000-0000-0000-000000000010")]
        results = await graph_traversal.traverse(
            seed_ids=seed_ids,
            edge_types=["SEMANTICALLY_RELATED"],
            depth=2,
        )

        # グラフアダプターが呼ばれたことを確認
        graph_adapter.traverse.assert_called_once()
        call_args = graph_adapter.traverse.call_args
        assert call_args[1]['depth'] == 2

    @pytest.mark.asyncio
    async def test_traverse_with_edge_type_filter(self, graph_traversal, graph_adapter):
        """エッジタイプでフィルタリング"""
        seed_ids = [UUID("00000000-0000-0000-0000-000000000010")]
        edge_types = ["CAUSED_BY", "RESULTED_IN"]
        await graph_traversal.traverse(
            seed_ids=seed_ids,
            edge_types=edge_types,
            depth=3,
        )

        call_args = graph_adapter.traverse.call_args
        assert call_args[1]['edge_types'] == edge_types

    @pytest.mark.asyncio
    async def test_traverse_returns_results(self, graph_traversal):
        """トラバーサル結果が返されること"""
        seed_ids = [UUID("00000000-0000-0000-0000-000000000010")]
        results = await graph_traversal.traverse(
            seed_ids=seed_ids,
            edge_types=None,
            depth=2,
        )

        assert len(results) == 2
        assert results[0]["id"] == UUID("00000000-0000-0000-0000-000000000001")
        assert results[0]["score"] == 0.85

    @pytest.mark.asyncio
    async def test_traverse_handles_empty_results(self, graph_traversal, graph_adapter):
        """結果が空の場合に対応"""
        graph_adapter.traverse.return_value = []
        seed_ids = [UUID("00000000-0000-0000-0000-000000000010")]

        results = await graph_traversal.traverse(
            seed_ids=seed_ids,
            edge_types=None,
            depth=2,
        )

        assert results == []

    @pytest.mark.asyncio
    async def test_traverse_with_default_depth(self, graph_traversal, graph_adapter):
        """デフォルトのグラフ深さを使用"""
        seed_ids = [UUID("00000000-0000-0000-0000-000000000010")]
        await graph_traversal.traverse(seed_ids=seed_ids)

        call_args = graph_adapter.traverse.call_args
        # デフォルトは 2
        assert call_args[1]['depth'] == 2

    @pytest.mark.asyncio
    async def test_traverse_graceful_degradation_on_error(self, graph_traversal, graph_adapter):
        """グラフアダプター失敗時に空結果を返す（Graceful Degradation）"""
        graph_adapter.traverse.side_effect = Exception("Connection failed")
        seed_ids = [UUID("00000000-0000-0000-0000-000000000010")]

        results = await graph_traversal.traverse(
            seed_ids=seed_ids,
            edge_types=None,
            depth=2,
        )

        # 例外時は空結果を返す
        assert results == []
