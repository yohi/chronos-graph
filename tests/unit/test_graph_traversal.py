"""Graph Traversal のテスト"""
import pytest
from typing import Protocol
from uuid import UUID
from unittest.mock import AsyncMock, MagicMock

from context_store.models.graph import GraphResult, Edge
from context_store.retrieval.graph_traversal import GraphTraversal


@pytest.fixture
def graph_adapter():
    """Graph Adapter のモック"""
    mock = MagicMock()
    mock.traverse = AsyncMock(
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
    return mock


@pytest.fixture
def graph_traversal(graph_adapter):
    """GraphTraversal インスタンス"""
    return GraphTraversal(graph_adapter=graph_adapter)


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
    async def test_traverse_calls_adapter(self, graph_traversal, graph_adapter):
        """アダプターを正しく呼び出すこと"""
        graph_adapter.traverse.return_value = GraphResult(
            nodes=[{"id": "node1", "score": 0.85}, {"id": "node2", "score": 0.75}],
            edges=[{"from_id": "node1", "to_id": "node2", "edge_type": "links"}],
            traversal_depth=2,
        )
        seed_ids = [UUID("00000000-0000-0000-0000-000000000010")]

        result = await graph_traversal.traverse(
            seed_ids=seed_ids,
            edge_types=["links"],
            depth=3,
        )

        assert isinstance(result, GraphResult)
        assert len(result.nodes) == 2
        assert result.nodes[0]["score"] == 0.85
        graph_traversal.graph_adapter.traverse.assert_called_once_with(
            seed_ids=[str(seed_ids[0])],
            edge_types=["links"],
            depth=3,
        )

    @pytest.mark.asyncio
    async def test_traverse_returns_graph_result(self, graph_traversal):
        """GraphResult が返されること"""
        seed_ids = [UUID("00000000-0000-0000-0000-000000000010")]
        result = await graph_traversal.traverse(seed_ids=seed_ids, edge_types=None, depth=2)

        assert isinstance(result, GraphResult)
        assert len(result.nodes) == 2
        assert result.nodes[0]["score"] == 0.85

    @pytest.mark.asyncio
    async def test_traverse_handles_empty_results(self, graph_traversal, graph_adapter):
        """結果が空の場合に対応"""
        graph_adapter.traverse.return_value = GraphResult(nodes=[], edges=[], traversal_depth=2)
        seed_ids = [UUID("00000000-0000-0000-0000-000000000010")]

        result = await graph_traversal.traverse(seed_ids=seed_ids, edge_types=None, depth=2)

        assert isinstance(result, GraphResult)
        assert result.nodes == []
        assert result.edges == []

    @pytest.mark.asyncio
    async def test_traverse_with_default_depth(self, graph_traversal, graph_adapter):
        """デフォルトのグラフ深さを使用"""
        seed_ids = [UUID("00000000-0000-0000-0000-000000000010")]
        await graph_traversal.traverse(seed_ids=seed_ids)

        call_args = graph_adapter.traverse.call_args
        assert call_args[1]["depth"] == 2  # デフォルト
        assert call_args[1]["edge_types"] == []

    @pytest.mark.asyncio
    async def test_traverse_graceful_degradation_on_error(self, graph_traversal, graph_adapter):
        """グラフアダプター失敗時に空の GraphResult を返す（Graceful Degradation）"""
        graph_adapter.traverse.side_effect = ConnectionError("Connection failed")
        seed_ids = [UUID("00000000-0000-0000-0000-000000000010")]

        result = await graph_traversal.traverse(seed_ids=seed_ids, edge_types=None, depth=2)

        assert isinstance(result, GraphResult)
        assert result.nodes == []
        assert result.edges == []
        assert result.traversal_depth == 0
        assert result.partial is True
        assert result.timeout is False

    @pytest.mark.asyncio
    async def test_traverse_graceful_degradation_on_timeout(self, graph_traversal, graph_adapter):
        """タイムアウト時に partial と timeout が立った GraphResult を返す。"""
        graph_adapter.traverse.side_effect = TimeoutError("Timeout")
        seed_ids = [UUID("00000000-0000-0000-0000-000000000010")]

        result = await graph_traversal.traverse(seed_ids=seed_ids, edge_types=None, depth=2)

        assert isinstance(result, GraphResult)
        assert result.nodes == []
        assert result.edges == []
        assert result.traversal_depth == 0
        assert result.partial is True
        assert result.timeout is True

    @pytest.mark.asyncio
    async def test_traverse_graceful_degradation_on_oserror(self, graph_traversal, graph_adapter):
        """OSError 時も graceful degradation で空結果を返す。"""
        graph_adapter.traverse.side_effect = OSError("Connection reset")
        seed_ids = [UUID("00000000-0000-0000-0000-000000000010")]

        result = await graph_traversal.traverse(seed_ids=seed_ids, edge_types=None, depth=2)

        assert isinstance(result, GraphResult)
        assert result.nodes == []
        assert result.edges == []
        assert result.traversal_depth == 0
        assert result.partial is True
        assert result.timeout is False

    @pytest.mark.asyncio
    async def test_traverse_seed_ids_converted_to_str(self, graph_traversal, graph_adapter):
        """UUID が文字列に変換されてアダプターに渡されること"""
        seed_ids = [
            UUID("00000000-0000-0000-0000-000000000010"),
            UUID("00000000-0000-0000-0000-000000000020"),
        ]
        await graph_traversal.traverse(seed_ids=seed_ids)

        call_args = graph_adapter.traverse.call_args
        passed_ids = call_args[1]["seed_ids"]
        expected_ids = [str(uid) for uid in seed_ids]
        assert passed_ids == expected_ids
