"""Unit tests for SQLiteGraphAdapter."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import AsyncGenerator

import pytest

from context_store.models.graph import GraphResult
from context_store.storage.sqlite_graph import SQLiteGraphAdapter
from tests.unit.conftest import make_settings

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def tmp_db_path(tmp_path: Path) -> str:
    return str(tmp_path / "test_graph.db")


@pytest.fixture
async def adapter(tmp_db_path: str) -> AsyncGenerator[SQLiteGraphAdapter, None]:
    """Create and initialize a SQLiteGraphAdapter with a fresh DB."""
    settings = make_settings(sqlite_db_path=tmp_db_path)
    adp = SQLiteGraphAdapter(db_path=tmp_db_path, settings=settings)
    await adp.initialize()
    yield adp
    await adp.dispose()


# ---------------------------------------------------------------------------
# Tests: create_node
# ---------------------------------------------------------------------------


class TestCreateNode:
    async def test_create_node_basic(self, adapter: SQLiteGraphAdapter) -> None:
        """ノードが正常に作成される."""
        await adapter.create_node("node-1", {"label": "test"})
        # verify by traversal seed
        result = await adapter.traverse(["node-1"], [], depth=0)
        node_ids = [n["id"] for n in result.nodes]
        assert "node-1" in node_ids

    async def test_create_node_idempotent(self, adapter: SQLiteGraphAdapter) -> None:
        """同じノードIDで2回呼び出しても例外が発生しない（upsert）."""
        await adapter.create_node("node-1", {"label": "first"})
        await adapter.create_node("node-1", {"label": "updated"})
        result = await adapter.traverse(["node-1"], [], depth=0)
        assert len(result.nodes) == 1

    async def test_create_node_with_metadata(self, adapter: SQLiteGraphAdapter) -> None:
        """メタデータが保持される."""
        metadata = {"label": "Memory", "project": "proj-a", "memory_type": "SEMANTIC"}
        await adapter.create_node("node-meta", metadata)
        result = await adapter.traverse(["node-meta"], [], depth=0)
        node = next(n for n in result.nodes if n["id"] == "node-meta")
        assert node["label"] == "Memory"


# ---------------------------------------------------------------------------
# Tests: create_edge
# ---------------------------------------------------------------------------


class TestCreateEdge:
    async def test_create_edge_basic(self, adapter: SQLiteGraphAdapter) -> None:
        """エッジが正常に作成される."""
        await adapter.create_node("a", {})
        await adapter.create_node("b", {})
        await adapter.create_edge("a", "b", "SEMANTICALLY_RELATED", {"weight": 0.9})

        result = await adapter.traverse(["a"], ["SEMANTICALLY_RELATED"], depth=1)
        edge_pairs = [(e.from_id, e.to_id, e.edge_type) for e in result.edges]
        assert ("a", "b", "SEMANTICALLY_RELATED") in edge_pairs

    async def test_create_edge_duplicate_ignored(self, adapter: SQLiteGraphAdapter) -> None:
        """同じエッジを2回追加しても重複しない."""
        await adapter.create_node("x", {})
        await adapter.create_node("y", {})
        await adapter.create_edge("x", "y", "SUPERSEDES", {})
        await adapter.create_edge("x", "y", "SUPERSEDES", {})

        result = await adapter.traverse(["x"], ["SUPERSEDES"], depth=1)
        supersedes = [e for e in result.edges if e.edge_type == "SUPERSEDES"]
        assert len(supersedes) == 1


# ---------------------------------------------------------------------------
# Tests: create_edges_batch
# ---------------------------------------------------------------------------


class TestCreateEdgesBatch:
    async def test_batch_insert(self, adapter: SQLiteGraphAdapter) -> None:
        """複数エッジを一括登録できる."""
        for nid in ["n1", "n2", "n3", "n4"]:
            await adapter.create_node(nid, {})

        edges = [
            {"from_id": "n1", "to_id": "n2", "edge_type": "CHUNK_NEXT", "props": {}},
            {"from_id": "n2", "to_id": "n3", "edge_type": "CHUNK_NEXT", "props": {}},
            {"from_id": "n3", "to_id": "n4", "edge_type": "CHUNK_NEXT", "props": {}},
        ]
        await adapter.create_edges_batch(edges)

        result = await adapter.traverse(["n1"], ["CHUNK_NEXT"], depth=3)
        edge_types = {e.edge_type for e in result.edges}
        assert "CHUNK_NEXT" in edge_types
        node_ids = {n["id"] for n in result.nodes}
        # n2, n3, n4 should be reachable
        assert {"n2", "n3", "n4"}.issubset(node_ids)

    async def test_batch_empty(self, adapter: SQLiteGraphAdapter) -> None:
        """空リストでも例外が発生しない."""
        await adapter.create_edges_batch([])  # no exception


# ---------------------------------------------------------------------------
# Tests: traverse
# ---------------------------------------------------------------------------


class TestTraverse:
    async def test_traverse_depth_1(self, adapter: SQLiteGraphAdapter) -> None:
        """depth=1 で直接隣接ノードのみ返される."""
        for nid in ["root", "child1", "child2", "grandchild"]:
            await adapter.create_node(nid, {})
        await adapter.create_edge("root", "child1", "TEMPORAL_NEXT", {})
        await adapter.create_edge("root", "child2", "TEMPORAL_NEXT", {})
        await adapter.create_edge("child1", "grandchild", "TEMPORAL_NEXT", {})

        result = await adapter.traverse(["root"], ["TEMPORAL_NEXT"], depth=1)
        node_ids = {n["id"] for n in result.nodes}
        assert "child1" in node_ids
        assert "child2" in node_ids
        assert "grandchild" not in node_ids
        assert result.traversal_depth == 1

    async def test_traverse_depth_2(self, adapter: SQLiteGraphAdapter) -> None:
        """depth=2 で孫ノードまで返される."""
        for nid in ["root", "child", "grandchild"]:
            await adapter.create_node(nid, {})
        await adapter.create_edge("root", "child", "REFERENCES", {})
        await adapter.create_edge("child", "grandchild", "REFERENCES", {})

        result = await adapter.traverse(["root"], ["REFERENCES"], depth=2)
        node_ids = {n["id"] for n in result.nodes}
        assert "grandchild" in node_ids
        assert result.traversal_depth == 2

    async def test_traverse_depth_3(self, adapter: SQLiteGraphAdapter) -> None:
        """depth=3 でさらに深いノードまで返される."""
        nodes = ["a", "b", "c", "d"]
        for nid in nodes:
            await adapter.create_node(nid, {})
        await adapter.create_edge("a", "b", "TEMPORAL_NEXT", {})
        await adapter.create_edge("b", "c", "TEMPORAL_NEXT", {})
        await adapter.create_edge("c", "d", "TEMPORAL_NEXT", {})

        result = await adapter.traverse(["a"], ["TEMPORAL_NEXT"], depth=3)
        node_ids = {n["id"] for n in result.nodes}
        assert "d" in node_ids
        assert result.traversal_depth == 3

    async def test_traverse_empty_seed(self, adapter: SQLiteGraphAdapter) -> None:
        """空のシードリストは空結果を返す."""
        result = await adapter.traverse([], [], depth=5)
        assert result.nodes == []
        assert result.edges == []

    async def test_traverse_edge_type_filter(self, adapter: SQLiteGraphAdapter) -> None:
        """edge_types フィルタが機能する."""
        for nid in ["src", "a", "b"]:
            await adapter.create_node(nid, {})
        await adapter.create_edge("src", "a", "SEMANTICALLY_RELATED", {})
        await adapter.create_edge("src", "b", "REFERENCES", {})

        result = await adapter.traverse(["src"], ["SEMANTICALLY_RELATED"], depth=1)
        node_ids = {n["id"] for n in result.nodes}
        assert "a" in node_ids
        assert "b" not in node_ids

    async def test_traverse_no_edge_type_filter(self, adapter: SQLiteGraphAdapter) -> None:
        """edge_types が空リストのとき全エッジタイプを辿る."""
        for nid in ["src", "a", "b"]:
            await adapter.create_node(nid, {})
        await adapter.create_edge("src", "a", "SEMANTICALLY_RELATED", {})
        await adapter.create_edge("src", "b", "REFERENCES", {})

        result = await adapter.traverse(["src"], [], depth=1)
        node_ids = {n["id"] for n in result.nodes}
        assert "a" in node_ids
        assert "b" in node_ids

    async def test_traverse_depth_hard_limit(self, adapter: SQLiteGraphAdapter) -> None:
        """graph_max_logical_depth を超える depth は強制制限される."""
        # Settings: graph_max_logical_depth=3
        settings = make_settings(
            sqlite_db_path=adapter._db_path,
            graph_max_logical_depth=3,
        )
        adp = SQLiteGraphAdapter(db_path=adapter._db_path, settings=settings)
        await adp.initialize()

        nodes = [f"n{i}" for i in range(7)]
        for nid in nodes:
            await adp.create_node(nid, {})
        for i in range(6):
            await adp.create_edge(nodes[i], nodes[i + 1], "TEMPORAL_NEXT", {})

        # request depth=10, should be clamped to max_logical_depth=3
        result = await adp.traverse(["n0"], ["TEMPORAL_NEXT"], depth=10)
        node_ids = {n["id"] for n in result.nodes}
        # n4+ is beyond depth 3 from n0
        assert "n4" not in node_ids
        assert result.traversal_depth <= 3

        await adp.dispose()

    async def test_traverse_supersedes_no_logical_depth(self, adapter: SQLiteGraphAdapter) -> None:
        """SUPERSEDES エッジは論理深さをカウントしない."""
        # a -SUPERSEDES-> b -SUPERSEDES-> c -TEMPORAL_NEXT-> d
        for nid in ["a", "b", "c", "d"]:
            await adapter.create_node(nid, {})
        await adapter.create_edge("a", "b", "SUPERSEDES", {})
        await adapter.create_edge("b", "c", "SUPERSEDES", {})
        await adapter.create_edge("c", "d", "TEMPORAL_NEXT", {})

        # With depth=1, SUPERSEDES should not consume logical depth
        # so we should still reach d via the TEMPORAL_NEXT at the end
        result = await adapter.traverse(["a"], [], depth=1)
        node_ids = {n["id"] for n in result.nodes}
        # b and c reached via SUPERSEDES (no depth consumed)
        assert "b" in node_ids
        assert "c" in node_ids
        # d is at logical depth 1 from c → should be included
        assert "d" in node_ids


# ---------------------------------------------------------------------------
# Tests: delete_node
# ---------------------------------------------------------------------------


class TestDeleteNode:
    async def test_delete_existing_node(self, adapter: SQLiteGraphAdapter) -> None:
        """存在するノードを削除できる."""
        await adapter.create_node("to-delete", {})
        await adapter.delete_node("to-delete")
        result = await adapter.traverse(["to-delete"], [], depth=0)
        assert "to-delete" not in {n["id"] for n in result.nodes}

    async def test_delete_cascades_edges(self, adapter: SQLiteGraphAdapter) -> None:
        """ノード削除時に関連エッジも削除される."""
        for nid in ["p", "q"]:
            await adapter.create_node(nid, {})
        await adapter.create_edge("p", "q", "TEMPORAL_NEXT", {})
        await adapter.delete_node("p")

        async with adapter._connect() as conn:
            async with conn.execute(
                "SELECT COUNT(*) FROM memory_edges WHERE from_id = ? OR to_id = ?", ("p", "p")
            ) as cursor:
                count = (await cursor.fetchone())[0]
        assert count == 0

    async def test_delete_nonexistent_node(self, adapter: SQLiteGraphAdapter) -> None:
        """存在しないノードの削除でも例外が発生しない."""
        await adapter.delete_node("does-not-exist")  # no exception


# ---------------------------------------------------------------------------
# Tests: GraphAdapter Protocol compliance
# ---------------------------------------------------------------------------


class TestProtocolCompliance:
    async def test_implements_graph_adapter_protocol(self, adapter: SQLiteGraphAdapter) -> None:
        """GraphAdapter Protocol を実装しているか確認."""
        from context_store.storage.protocols import GraphAdapter

        assert isinstance(adapter, GraphAdapter)

    async def test_traverse_returns_graph_result(self, adapter: SQLiteGraphAdapter) -> None:
        """traverse の戻り値は GraphResult."""
        result = await adapter.traverse([], [], depth=1)
        assert isinstance(result, GraphResult)
        assert isinstance(result.nodes, list)
        assert isinstance(result.edges, list)


# ---------------------------------------------------------------------------
# Tests: Timeout / Graceful Degradation
# ---------------------------------------------------------------------------


class TestTimeout:
    async def test_traverse_timeout_returns_partial_result(self, tmp_db_path: str) -> None:
        """タイムアウト発生時に例外を送出せず部分/空結果を返す."""
        settings = make_settings(
            sqlite_db_path=tmp_db_path,
            graph_traversal_timeout_seconds=0.001,  # extremely short
        )
        adp = SQLiteGraphAdapter(db_path=tmp_db_path, settings=settings)
        await adp.initialize()

        # Create a small graph
        for nid in ["t1", "t2", "t3"]:
            await adp.create_node(nid, {})
        await adp.create_edge("t1", "t2", "TEMPORAL_NEXT", {})
        await adp.create_edge("t2", "t3", "TEMPORAL_NEXT", {})

        # Monkeypatch to force timeout
        original_inner = adp._traverse_inner

        async def slow_inner(*args, **kwargs):
            await asyncio.sleep(0.01)
            return await original_inner(*args, **kwargs)

        adp._traverse_inner = slow_inner

        # Should not raise even if timeout hits
        result = await adp.traverse(["t1"], [], depth=5)
        assert isinstance(result, GraphResult)
        assert result.partial is True
        assert result.timeout is True
        assert result.traversal_depth == 0
        # In this specific test, because we sleep BEFORE calling the actual traversal,
        # the result will be empty.
        assert len(result.nodes) == 0
        assert len(result.edges) == 0

        await adp.dispose()

    async def test_traverse_interrupt_called_on_timeout(
        self, tmp_db_path: str, monkeypatch
    ) -> None:
        """タイムアウト時に SafeSqliteInterruptCtx.interrupt() が呼ばれることを確認."""
        from context_store.storage.sqlite_graph import SafeSqliteInterruptCtx

        settings = make_settings(
            sqlite_db_path=tmp_db_path,
            graph_traversal_timeout_seconds=0.01,
        )
        adp = SQLiteGraphAdapter(db_path=tmp_db_path, settings=settings)
        await adp.initialize()

        interrupt_called = False

        def mock_interrupt(self):
            nonlocal interrupt_called
            interrupt_called = True

        monkeypatch.setattr(SafeSqliteInterruptCtx, "interrupt", mock_interrupt)

        # Mock _traverse_inner to sleep longer than timeout
        async def slow_inner(*args, **kwargs):
            await asyncio.sleep(0.1)
            return GraphResult(nodes=[], edges=[], traversal_depth=0)

        monkeypatch.setattr(adp, "_traverse_inner", slow_inner)

        # Run traverse
        result = await adp.traverse(["seed"], [], depth=1)

        # Verify interrupt was called
        assert interrupt_called is True
        assert result.timeout is True
        assert result.traversal_depth == 0

        await adp.dispose()
