"""GraphSyncService: Storage → Neo4j のバルク同期ロジック検証。"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from context_store.models.memory import Memory, MemoryType, SourceType


def _make_memory(**overrides) -> Memory:
    base = dict(
        content="hello",
        memory_type=MemoryType.SEMANTIC,
        source_type=SourceType.MANUAL,
        source_metadata={},
        embedding=[0.1] * 768,
        semantic_relevance=0.5,
        importance_score=0.5,
        tags=["t1"],
        project="p1",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    base.update(overrides)
    return Memory(**base)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_bulk_merge_memories_issues_unwind_merge_cypher() -> None:
    from context_store.sync.graph_sync import GraphSyncService

    graph = MagicMock()
    graph.execute_write = AsyncMock()
    storage = MagicMock()
    storage.list_edges_for_memories = AsyncMock(return_value=[])

    svc = GraphSyncService(graph_adapter=graph, storage_adapter=storage)
    n = await svc.bulk_merge_memories([_make_memory(), _make_memory()])

    assert n == 2
    cypher_calls = [c.args[0] for c in graph.execute_write.await_args_list]
    assert any("UNWIND $batch" in c and "MERGE (m:Memory" in c for c in cypher_calls)


@pytest.mark.asyncio
async def test_bulk_merge_memories_only_writes_minimal_props() -> None:
    """Neo4j に格納するプロパティは id / memory_type / created_at / project / tags のみ。"""
    from context_store.sync.graph_sync import GraphSyncService

    graph = MagicMock()
    graph.execute_write = AsyncMock()
    storage = MagicMock()
    storage.list_edges_for_memories = AsyncMock(return_value=[])

    svc = GraphSyncService(graph_adapter=graph, storage_adapter=storage)
    await svc.bulk_merge_memories([_make_memory()])

    first_call = graph.execute_write.await_args_list[0]
    batch = first_call.args[1]["batch"]
    keys = set(batch[0].keys())
    assert keys == {"id", "memory_type", "created_at", "project", "tags"}


@pytest.mark.asyncio
async def test_bulk_delete_nodes_uses_detach_delete() -> None:
    from context_store.sync.graph_sync import GraphSyncService

    graph = MagicMock()
    graph.execute_write = AsyncMock()
    storage = MagicMock()

    ids_to_delete = ["mem-id-a", "mem-id-b"]
    svc = GraphSyncService(graph_adapter=graph, storage_adapter=storage)
    await svc.bulk_delete_nodes(ids_to_delete)

    graph.execute_write.assert_awaited_once()
    cypher = graph.execute_write.await_args.args[0]
    assert "DETACH DELETE" in cypher
    params = graph.execute_write.await_args.args[1]
    assert params["ids"] == ids_to_delete


@pytest.mark.asyncio
async def test_bulk_merge_memories_empty_list_is_noop() -> None:
    from context_store.sync.graph_sync import GraphSyncService

    graph = MagicMock()
    graph.execute_write = AsyncMock()
    storage = MagicMock()

    svc = GraphSyncService(graph_adapter=graph, storage_adapter=storage)
    result = await svc.bulk_merge_memories([])
    assert result == 0
    graph.execute_write.assert_not_called()
