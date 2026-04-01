"""
Unit tests for Neo4j Graph Adapter.

neo4j.AsyncDriver をモックして Cypher クエリ組み立てロジックを検証する。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from context_store.models.graph import GraphResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_driver_mock():
    """Return a neo4j.AsyncDriver mock with a session context manager."""
    driver = MagicMock()
    session = AsyncMock()

    # session として使う AsyncContextManager を作る
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=None)
    driver.session = MagicMock(return_value=ctx)
    driver.close = AsyncMock()
    return driver, session


@pytest.fixture
def adapter_and_session():
    from context_store.storage.neo4j import Neo4jGraphAdapter

    driver, session = _make_driver_mock()
    adapter = Neo4jGraphAdapter.__new__(Neo4jGraphAdapter)
    adapter._driver = driver
    return adapter, session


# ---------------------------------------------------------------------------
# create_node
# ---------------------------------------------------------------------------


class TestCreateNode:
    async def test_runs_merge_cypher(self, adapter_and_session):
        adp, session = adapter_and_session
        session.run = AsyncMock()

        await adp.create_node("node-1", {"key": "val"})

        session.run.assert_called_once()
        cypher: str = session.run.call_args[0][0]
        assert "MERGE" in cypher
        assert "Memory" in cypher

    async def test_passes_memory_id(self, adapter_and_session):
        adp, session = adapter_and_session
        session.run = AsyncMock()

        await adp.create_node("abc-123", {})

        kwargs = session.run.call_args[1]
        # id が渡されていること
        assert any(v == "abc-123" for v in kwargs.values())

    async def test_does_not_raise_on_connection_failure(self, adapter_and_session):
        adp, session = adapter_and_session
        session.run = AsyncMock(side_effect=Exception("Neo4j unavailable"))

        # Graceful Degradation: 例外を外部に伝播させない
        await adp.create_node("node-1", {})


# ---------------------------------------------------------------------------
# create_edge
# ---------------------------------------------------------------------------


class TestCreateEdge:
    async def test_runs_create_edge_cypher(self, adapter_and_session):
        adp, session = adapter_and_session
        session.run = AsyncMock()

        await adp.create_edge("a", "b", "RELATES_TO", {})

        session.run.assert_called_once()
        cypher: str = session.run.call_args[0][0]
        assert "CREATE" in cypher or "MERGE" in cypher

    async def test_passes_edge_type(self, adapter_and_session):
        adp, session = adapter_and_session
        session.run = AsyncMock()

        await adp.create_edge("a", "b", "SUPERSEDES", {})

        cypher: str = session.run.call_args[0][0]
        assert "SUPERSEDES" in cypher

    async def test_does_not_raise_on_failure(self, adapter_and_session):
        adp, session = adapter_and_session
        session.run = AsyncMock(side_effect=Exception("connection error"))

        await adp.create_edge("a", "b", "RELATES_TO", {})

    async def test_rejects_invalid_edge_type(self, adapter_and_session):
        adp, session = adapter_and_session
        session.run = AsyncMock()

        await adp.create_edge("a", "b", "BAD-TYPE", {})

        session.run.assert_not_called()

    async def test_rejects_edge_type_starting_with_digit(self, adapter_and_session):
        adp, session = adapter_and_session
        session.run = AsyncMock()

        await adp.create_edge("a", "b", "1INVALID", {})

        session.run.assert_not_called()


# ---------------------------------------------------------------------------
# create_edges_batch
# ---------------------------------------------------------------------------


class TestCreateEdgesBatch:
    async def test_uses_unwind_for_batch(self, adapter_and_session):
        adp, session = adapter_and_session
        session.run = AsyncMock()
        edges = [
            {"from_id": "a", "to_id": "b", "edge_type": "RELATES_TO", "props": {}},
            {"from_id": "b", "to_id": "c", "edge_type": "CITES", "props": {}},
        ]

        await adp.create_edges_batch(edges)

        # エッジ型ごとにバッチ処理されるため、最低1回は UNWIND を含む呼び出しがある
        assert session.run.call_count >= 1
        for call_args in session.run.call_args_list:
            cypher: str = call_args[0][0]
            assert "UNWIND" in cypher

    async def test_empty_list_does_nothing(self, adapter_and_session):
        adp, session = adapter_and_session
        session.run = AsyncMock()

        await adp.create_edges_batch([])

        session.run.assert_not_called()

    async def test_does_not_raise_on_failure(self, adapter_and_session):
        adp, session = adapter_and_session
        session.run = AsyncMock(side_effect=Exception("neo4j down"))
        edges = [{"from_id": "a", "to_id": "b", "edge_type": "X", "props": {}}]

        await adp.create_edges_batch(edges)

    async def test_skips_invalid_edge_types(self, adapter_and_session):
        adp, session = adapter_and_session
        session.run = AsyncMock()
        edges = [
            {"from_id": "a", "to_id": "b", "edge_type": "RELATES_TO", "props": {}},
            {"from_id": "b", "to_id": "c", "edge_type": "BAD-TYPE", "props": {}},
        ]

        await adp.create_edges_batch(edges)

        session.run.assert_called_once()
        cypher: str = session.run.call_args[0][0]
        assert "RELATES_TO" in cypher
        assert "BAD-TYPE" not in cypher


# ---------------------------------------------------------------------------
# traverse
# ---------------------------------------------------------------------------


class TestTraverse:
    async def test_returns_graph_result(self, adapter_and_session):
        adp, session = adapter_and_session

        # neo4j result mock
        record = MagicMock()
        record.__getitem__ = MagicMock(
            side_effect=lambda k: {
                "nodes": [{"id": "a"}, {"id": "b"}],
                "rels": [{"from": "a", "to": "b", "type": "RELATES_TO", "props": {}}],
            }[k]
        )
        result_mock = AsyncMock()
        result_mock.__aiter__ = MagicMock(return_value=iter([record]))
        session.run = AsyncMock(return_value=result_mock)

        result = await adp.traverse(["a"], ["RELATES_TO"], depth=2)

        assert isinstance(result, GraphResult)

    async def test_returns_empty_result_on_failure(self, adapter_and_session):
        adp, session = adapter_and_session
        session.run = AsyncMock(side_effect=Exception("neo4j down"))

        result = await adp.traverse(["a"], [], depth=1)

        assert isinstance(result, GraphResult)
        assert result.nodes == []
        assert result.edges == []

    async def test_cypher_includes_depth(self, adapter_and_session):
        adp, session = adapter_and_session
        result_mock = AsyncMock()
        result_mock.__aiter__ = MagicMock(return_value=iter([]))
        session.run = AsyncMock(return_value=result_mock)

        await adp.traverse(["a"], [], depth=3)

        cypher: str = session.run.call_args[0][0]
        assert "3" in cypher or "depth" in cypher.lower()

    async def test_skips_invalid_edge_types_in_filter(self, adapter_and_session):
        adp, session = adapter_and_session
        result_mock = AsyncMock()
        result_mock.__aiter__ = MagicMock(return_value=iter([]))
        session.run = AsyncMock(return_value=result_mock)

        await adp.traverse(["a"], ["RELATES_TO", "BAD-TYPE"], depth=2)

        cypher: str = session.run.call_args[0][0]
        assert "RELATES_TO" in cypher
        assert "BAD-TYPE" not in cypher

    async def test_places_relationship_types_before_depth_range(self, adapter_and_session):
        adp, session = adapter_and_session
        result_mock = AsyncMock()
        result_mock.__aiter__ = MagicMock(return_value=iter([]))
        session.run = AsyncMock(return_value=result_mock)

        await adp.traverse(["a"], ["RELATES_TO", "CITES"], depth=2)

        cypher: str = session.run.call_args[0][0]
        assert "[:RELATES_TO|CITES*1..2]" in cypher

    async def test_deduplicates_returned_edges(self, adapter_and_session):
        adp, session = adapter_and_session

        class _Rel:
            def __init__(self):
                self.start_node = {"id": "a"}
                self.end_node = {"id": "b"}
                self.type = "RELATES_TO"
                self.identity = 42

            def __iter__(self):
                return iter({"weight": 1}.items())

        rel = _Rel()
        record = MagicMock()
        record.__getitem__ = MagicMock(
            side_effect=lambda k: {
                "nodes": [{"id": "a"}, {"id": "b"}],
                "rels": [rel, rel],
            }[k]
        )

        class _Result:
            def __aiter__(self):
                async def _iter():
                    yield record

                return _iter()

        session.run = AsyncMock(return_value=_Result())

        result = await adp.traverse(["a"], ["RELATES_TO"], depth=2)

        assert len(result.edges) == 1


# ---------------------------------------------------------------------------
# delete_node
# ---------------------------------------------------------------------------


class TestDeleteNode:
    async def test_runs_detach_delete(self, adapter_and_session):
        adp, session = adapter_and_session
        session.run = AsyncMock()

        await adp.delete_node("node-1")

        session.run.assert_called_once()
        cypher: str = session.run.call_args[0][0]
        assert "DELETE" in cypher

    async def test_does_not_raise_on_failure(self, adapter_and_session):
        adp, session = adapter_and_session
        session.run = AsyncMock(side_effect=Exception("neo4j down"))

        await adp.delete_node("node-1")


# ---------------------------------------------------------------------------
# dispose
# ---------------------------------------------------------------------------


class TestDispose:
    async def test_closes_driver(self, adapter_and_session):
        adp, _session = adapter_and_session
        adp._driver.close = AsyncMock()

        await adp.dispose()

        adp._driver.close.assert_called_once()
