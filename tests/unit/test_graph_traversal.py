"""Graph Traversal のテスト"""

from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from context_store.retrieval.graph_traversal import GraphTraversal
from context_store.models.graph import GraphResult, Edge


@pytest.fixture
def graph_adapter():
    """Graph Adapter のモック"""
    adapter = AsyncMock()
    adapter.traverse = AsyncMock(
        return_value=GraphResult(
            nodes=[
                {"id": str(UUID("00000000-0000-0000-0000-000000000001")), "score": 0.85},
                {"id": str(UUID("00000000-0000-0000-0000-000000000002")), "score": 0.75},
            ],
            edges=[
                Edge(
                    from_id=str(UUID("00000000-0000-0000-0000-000000000001")),
                    to_id=str(UUID("00000000-0000-0000-0000-000000000002")),
                    edge_type="SEMANTICALLY_RELATED",
                )
            ],
            traversal_depth=2,
        )
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
        result = await graph_traversal.traverse(
            seed_ids=seed_ids,
            edge_types=["SEMANTICALLY_RELATED"],
            depth=2,
        )

        graph_adapter.traverse.assert_called_once()
        call_args = graph_adapter.traverse.call_args
        assert call_args[1]["depth"] == 2
        assert isinstance(result, GraphResult)

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
        assert call_args[1]["edge_types"] == edge_types

    @pytest.mark.asyncio
    async def test_traverse_returns_graph_result(self, graph_traversal):
        """GraphResult が返されること"""
        seed_ids = [UUID("00000000-0000-0000-0000-000000000010")]
        result = await graph_traversal.traverse(seed_ids=seed_ids, edge_types=None, depth=2)

        assert isinstance(result, GraphResult)
        assert len(result.nodes) == 2
        assert result.nodes[0]["score"] == 0.85
        graph_traversal.graph_adapter.traverse.assert_called_once_with(
            seed_ids=[str(seed_ids[0])],
            edge_types=[],
            depth=2,
        )

    @pytest.mark.asyncio
    async def test_traverse_handles_empty_results(self, graph_traversal, graph_adapter):
        """結果が空の場合に対応"""
        graph_adapter.traverse.return_value = GraphResult(nodes=[], edges=[], traversal_depth=2)
        seed_ids = [UUID("00000000-0000-0000-0000-000000000010")]

        result = await graph_traversal.traverse(seed_ids=seed_ids, edge_types=None, depth=2)

        assert isinstance(result, GraphResult)
        assert result.nodes == []

    @pytest.mark.asyncio
    async def test_traverse_with_default_depth(self, graph_traversal, graph_adapter):
        """デフォルトのグラフ深さを使用"""
        seed_ids = [UUID("00000000-0000-0000-0000-000000000010")]
        await graph_traversal.traverse(seed_ids=seed_ids)

        call_args = graph_adapter.traverse.call_args
        assert call_args[1]["depth"] == 2  # デフォルト

    @pytest.mark.asyncio
    async def test_traverse_graceful_degradation_on_error(self, graph_traversal, graph_adapter):
        """グラフアダプター失敗時に空の GraphResult を返す（Graceful Degradation）"""
        graph_adapter.traverse.side_effect = ConnectionError("Connection failed")
        seed_ids = [UUID("00000000-0000-0000-0000-000000000010")]

        result = await graph_traversal.traverse(seed_ids=seed_ids, edge_types=None, depth=2)

        assert isinstance(result, GraphResult)
        assert result.nodes == []
        assert result.edges == []
        assert result.partial is True
        assert result.timeout is False

    @pytest.mark.asyncio
    async def test_traverse_seed_ids_converted_to_str(self, graph_traversal, graph_adapter):
        """UUID が文字列に変換されてアダプターに渡されること"""
        seed_ids = [UUID("00000000-0000-0000-0000-000000000010")]
        await graph_traversal.traverse(seed_ids=seed_ids)

        call_args = graph_adapter.traverse.call_args
        passed_ids = call_args[1]["seed_ids"]
        assert all(isinstance(sid, str) for sid in passed_ids)
