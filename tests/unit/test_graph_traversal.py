import pytest
from uuid import UUID
from unittest.mock import AsyncMock, MagicMock

from context_store.models.graph import GraphResult
from context_store.retrieval.graph_traversal import GraphTraversal


@pytest.fixture
def graph_adapter():
    mock = MagicMock()
    mock.traverse = AsyncMock()
    return mock


@pytest.fixture
def graph_traversal(graph_adapter):
    return GraphTraversal(graph_adapter=graph_adapter)


@pytest.mark.asyncio
async def test_traverse_calls_adapter(graph_traversal, graph_adapter):
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
async def test_traverse_handles_empty_results(graph_traversal, graph_adapter):
    """結果が空の場合に対応"""
    graph_adapter.traverse.return_value = GraphResult(nodes=[], edges=[], traversal_depth=2)
    seed_ids = [UUID("00000000-0000-0000-0000-000000000010")]

    result = await graph_traversal.traverse(seed_ids=seed_ids, edge_types=None, depth=2)

    assert isinstance(result, GraphResult)
    assert result.nodes == []
    assert result.edges == []


@pytest.mark.asyncio
async def test_traverse_with_default_depth(graph_traversal, graph_adapter):
    """デフォルトのグラフ深さを使用"""
    seed_ids = [UUID("00000000-0000-0000-0000-000000000010")]
    await graph_traversal.traverse(seed_ids=seed_ids)

    call_args = graph_adapter.traverse.call_args
    assert call_args[1]["depth"] == 2  # デフォルト


@pytest.mark.asyncio
async def test_traverse_graceful_degradation_on_error(graph_traversal, graph_adapter):
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
async def test_traverse_graceful_degradation_on_timeout(graph_traversal, graph_adapter):
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
async def test_traverse_graceful_degradation_on_oserror(graph_traversal, graph_adapter):
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
async def test_traverse_seed_ids_converted_to_str(graph_traversal, graph_adapter):
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
