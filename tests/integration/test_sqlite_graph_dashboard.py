"""Integration tests for list_edges_for_memories and count_edges (Dashboard PR 3)."""

from __future__ import annotations

import pytest

from context_store.config import Settings
from context_store.storage.sqlite_graph import SQLiteGraphAdapter


@pytest.fixture
async def graph_adapter(tmp_path):
    settings = Settings(
        storage_backend="sqlite",
        sqlite_db_path=str(tmp_path / "graph.db"),
        graph_enabled=True,
    )
    adp = SQLiteGraphAdapter(db_path=str(tmp_path / "graph.db"), settings=settings)
    await adp.initialize()
    # Seed: 3 nodes, 2 edges
    await adp.create_node("m1", {"memory_type": "episodic"})
    await adp.create_node("m2", {"memory_type": "semantic"})
    await adp.create_node("m3", {"memory_type": "procedural"})
    await adp.create_edge("m1", "m2", "RELATED", {})
    await adp.create_edge("m2", "m3", "DERIVED_FROM", {})
    yield adp
    await adp.dispose()


@pytest.mark.asyncio
async def test_list_edges_for_memories_returns_connecting_edges(graph_adapter):
    edges = await graph_adapter.list_edges_for_memories(["m1", "m2", "m3"])
    assert len(edges) == 2
    types = {e.edge_type for e in edges}
    assert types == {"RELATED", "DERIVED_FROM"}


@pytest.mark.asyncio
async def test_list_edges_for_memories_only_includes_edges_where_both_endpoints_in_set(
    graph_adapter,
):
    """m1 と m3 だけを渡した場合、m2 を経由するエッジは含まれない。"""
    edges = await graph_adapter.list_edges_for_memories(["m1", "m3"])
    assert len(edges) == 0


@pytest.mark.asyncio
async def test_list_edges_for_memories_empty_input(graph_adapter):
    edges = await graph_adapter.list_edges_for_memories([])
    assert edges == []


@pytest.mark.asyncio
async def test_count_edges_returns_total_count(graph_adapter):
    n = await graph_adapter.count_edges()
    assert n == 2


@pytest.mark.asyncio
async def test_list_edges_chunking_for_large_input(graph_adapter):
    """IN 句パラメータ上限 (999) を超えるサイズでもエラーなく動作する (rev.10 §3.5)。"""
    # 1500 件の ID (存在しないものを含む)
    ids = [f"nonexistent-{i}" for i in range(1500)]
    ids.extend(["m1", "m2"])
    edges = await graph_adapter.list_edges_for_memories(ids)
    # m1-m2 のエッジ 1 本が返る
    assert len(edges) == 1
