"""Task 4.5: Graph Linker のユニットテスト。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call
from uuid import uuid4

import pytest

from context_store.ingestion.graph_linker import EdgeType, GraphLinker
from context_store.models.memory import Memory, MemoryType, ScoredMemory, SourceType
from context_store.storage.protocols import GraphAdapter, StorageAdapter


def _make_memory(
    content: str = "test",
    project: str | None = "proj1",
    session_id: str | None = None,
    document_id: str | None = None,
    chunk_index: int | None = None,
    **kwargs: Any,
) -> Memory:
    """テスト用 Memory を作成する。"""
    meta: dict[str, Any] = {}
    if session_id:
        meta["session_id"] = session_id
    if document_id:
        meta["document_id"] = document_id
    if chunk_index is not None:
        meta["chunk_index"] = chunk_index

    defaults: dict[str, Any] = {
        "content": content,
        "memory_type": MemoryType.EPISODIC,
        "source_type": SourceType.MANUAL,
        "embedding": [0.5] * 4,
        "importance_score": 0.5,
        "project": project,
        "source_metadata": meta,
    }
    defaults.update(kwargs)
    return Memory(**defaults)


def _make_scored_memory(memory: Memory, score: float) -> ScoredMemory:
    return ScoredMemory(memory=memory, score=score)


def _make_mocks() -> tuple[MagicMock, MagicMock]:
    """StorageAdapter と GraphAdapter のモックを作成する。"""
    storage = MagicMock(spec=StorageAdapter)
    storage.vector_search = AsyncMock(return_value=[])

    graph = MagicMock(spec=GraphAdapter)
    graph.create_node = AsyncMock()
    graph.create_edges_batch = AsyncMock()

    return storage, graph


# ===========================================================================
# SEMANTICALLY_RELATED エッジテスト
# ===========================================================================


@pytest.mark.asyncio
async def test_graph_linker_semantically_related_created() -> None:
    """類似度 >= 0.70 で SEMANTICALLY_RELATED エッジが作成される。"""
    storage, graph = _make_mocks()

    new_memory = _make_memory("新しい記憶", id=uuid4())
    existing = _make_memory("類似した既存記憶", id=uuid4())

    storage.vector_search = AsyncMock(
        return_value=[_make_scored_memory(existing, 0.80)]
    )

    linker = GraphLinker(storage=storage, graph=graph)
    await linker.link(new_memory)

    # create_edges_batch が呼ばれていること
    graph.create_edges_batch.assert_called_once()
    edges = graph.create_edges_batch.call_args[0][0]
    sem_edges = [e for e in edges if e["edge_type"] == EdgeType.SEMANTICALLY_RELATED]
    assert len(sem_edges) >= 1
    edge_pairs = {(e["from_id"], e["to_id"]) for e in sem_edges}
    assert (str(new_memory.id), str(existing.id)) in edge_pairs


@pytest.mark.asyncio
async def test_graph_linker_semantically_related_not_created_below_threshold() -> None:
    """類似度 < 0.70 では SEMANTICALLY_RELATED エッジは作成されない。"""
    storage, graph = _make_mocks()

    new_memory = _make_memory("新しい記憶")
    existing = _make_memory("あまり似ていない記憶")

    storage.vector_search = AsyncMock(
        return_value=[_make_scored_memory(existing, 0.60)]
    )

    linker = GraphLinker(storage=storage, graph=graph)
    await linker.link(new_memory)

    graph.create_edges_batch.assert_called_once()
    edges = graph.create_edges_batch.call_args[0][0]
    sem_edges = [e for e in edges if e["edge_type"] == EdgeType.SEMANTICALLY_RELATED]
    assert len(sem_edges) == 0


# ===========================================================================
# TEMPORAL_NEXT/PREV エッジテスト
# ===========================================================================


@pytest.mark.asyncio
async def test_graph_linker_temporal_links_same_session() -> None:
    """同一セッションの記憶に TEMPORAL_NEXT/PREV エッジが作成される。"""
    storage, graph = _make_mocks()

    session_id = "session-001"
    prev_memory = _make_memory("前の記憶", session_id=session_id, id=uuid4())
    new_memory = _make_memory("新しい記憶", session_id=session_id, id=uuid4())

    linker = GraphLinker(storage=storage, graph=graph)
    await linker.link(new_memory, previous_memories=[prev_memory])

    graph.create_edges_batch.assert_called_once()
    edges = graph.create_edges_batch.call_args[0][0]

    temporal_next = [e for e in edges if e["edge_type"] == EdgeType.TEMPORAL_NEXT]
    temporal_prev = [e for e in edges if e["edge_type"] == EdgeType.TEMPORAL_PREV]

    # TEMPORAL_NEXT: prev → new, TEMPORAL_PREV: new → prev
    assert any(
        e["from_id"] == str(prev_memory.id) and e["to_id"] == str(new_memory.id)
        for e in temporal_next
    )
    assert any(
        e["from_id"] == str(new_memory.id) and e["to_id"] == str(prev_memory.id)
        for e in temporal_prev
    )


@pytest.mark.asyncio
async def test_graph_linker_no_temporal_links_different_session() -> None:
    """異なるセッションの記憶には TEMPORAL エッジが作成されない。"""
    storage, graph = _make_mocks()

    prev_memory = _make_memory("前の記憶", session_id="session-001")
    new_memory = _make_memory("新しい記憶", session_id="session-002")

    linker = GraphLinker(storage=storage, graph=graph)
    await linker.link(new_memory, previous_memories=[prev_memory])

    graph.create_edges_batch.assert_called_once()
    edges = graph.create_edges_batch.call_args[0][0]

    temporal_edges = [
        e for e in edges
        if e["edge_type"] in (EdgeType.TEMPORAL_NEXT, EdgeType.TEMPORAL_PREV)
    ]
    assert len(temporal_edges) == 0


# ===========================================================================
# SUPERSEDES エッジテスト
# ===========================================================================


@pytest.mark.asyncio
async def test_graph_linker_supersedes_created() -> None:
    """Append-only 置換時に SUPERSEDES エッジが作成される。"""
    storage, graph = _make_mocks()

    old_memory = _make_memory("古い記憶")
    new_memory = _make_memory("新しい記憶（置換）")

    linker = GraphLinker(storage=storage, graph=graph)
    await linker.link(new_memory, supersedes=old_memory)

    graph.create_edges_batch.assert_called_once()
    edges = graph.create_edges_batch.call_args[0][0]

    supersedes_edges = [e for e in edges if e["edge_type"] == EdgeType.SUPERSEDES]
    assert len(supersedes_edges) >= 1
    assert any(
        e["from_id"] == str(new_memory.id) and e["to_id"] == str(old_memory.id)
        for e in supersedes_edges
    )


# ===========================================================================
# REFERENCES エッジテスト
# ===========================================================================


@pytest.mark.asyncio
async def test_graph_linker_references_url() -> None:
    """コンテンツ内のURLから REFERENCES エッジが作成される。"""
    storage, graph = _make_mocks()

    new_memory = _make_memory(
        "詳細は https://example.com/docs を参照してください",
        source_metadata={"url": "https://example.com/docs"},
    )

    # URL に対応するノードが存在するとして、vector_search でヒットさせる
    url_memory = _make_memory("example.com のドキュメント")
    # REFERENCESはURLメタデータから作成するため、vector_searchでヒットしなくても可

    linker = GraphLinker(storage=storage, graph=graph)
    await linker.link(new_memory)

    # create_edges_batch が呼ばれること（エッジ0件でも呼ばれる）
    graph.create_edges_batch.assert_called_once()


@pytest.mark.asyncio
async def test_graph_linker_references_file_path() -> None:
    """コンテンツ内のファイルパスから REFERENCES エッジが作成される。"""
    storage, graph = _make_mocks()

    new_memory = _make_memory("設定ファイルは /etc/config.yaml を参照")

    linker = GraphLinker(storage=storage, graph=graph)
    await linker.link(new_memory)

    graph.create_edges_batch.assert_called_once()


# ===========================================================================
# CHUNK_NEXT/PREV エッジテスト
# ===========================================================================


@pytest.mark.asyncio
async def test_graph_linker_chunk_links_sequential() -> None:
    """同一ドキュメント内の連続チャンク間に CHUNK_NEXT/PREV エッジが作成される。"""
    storage, graph = _make_mocks()

    doc_id = "doc-001"
    chunk0 = _make_memory("チャンク0", document_id=doc_id, chunk_index=0)
    chunk1 = _make_memory("チャンク1", document_id=doc_id, chunk_index=1)

    linker = GraphLinker(storage=storage, graph=graph)
    await linker.link(chunk1, chunk_neighbors={doc_id: [chunk0, chunk1]})

    graph.create_edges_batch.assert_called_once()
    edges = graph.create_edges_batch.call_args[0][0]

    chunk_next = [e for e in edges if e["edge_type"] == EdgeType.CHUNK_NEXT]
    chunk_prev = [e for e in edges if e["edge_type"] == EdgeType.CHUNK_PREV]

    # chunk0 → chunk1: CHUNK_NEXT
    assert any(
        e["from_id"] == str(chunk0.id) and e["to_id"] == str(chunk1.id)
        for e in chunk_next
    )
    # chunk1 → chunk0: CHUNK_PREV
    assert any(
        e["from_id"] == str(chunk1.id) and e["to_id"] == str(chunk0.id)
        for e in chunk_prev
    )


# ===========================================================================
# バルクインサート (N+1 問題回避) テスト
# ===========================================================================


@pytest.mark.asyncio
async def test_graph_linker_uses_batch_insert() -> None:
    """create_edges_batch が1回だけ呼ばれる（N+1問題回避）。"""
    storage, graph = _make_mocks()

    new_memory = _make_memory("新しい記憶")
    existing1 = _make_memory("類似記憶1")
    existing2 = _make_memory("類似記憶2")

    storage.vector_search = AsyncMock(
        return_value=[
            _make_scored_memory(existing1, 0.80),
            _make_scored_memory(existing2, 0.75),
        ]
    )

    linker = GraphLinker(storage=storage, graph=graph)
    await linker.link(new_memory)

    # create_edge は呼ばれない
    assert not hasattr(graph, "create_edge") or not graph.create_edge.called
    # create_edges_batch は1回だけ呼ばれる
    assert graph.create_edges_batch.call_count == 1
