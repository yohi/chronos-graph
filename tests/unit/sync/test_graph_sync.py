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


@pytest.mark.asyncio
async def test_bulk_merge_memories_with_edges() -> None:
    import uuid

    from context_store.models.graph import Edge
    from context_store.storage.protocols import GraphAdapter
    from context_store.sync.graph_sync import GraphSyncService

    graph = MagicMock()
    graph.execute_write = AsyncMock()

    class MockStorageGraphAdapter(GraphAdapter):
        async def list_edges_for_memories(self, memory_ids: list[str]) -> list[Edge]:
            pass

    storage = MagicMock(spec=MockStorageGraphAdapter)

    mem_a_id = str(uuid.uuid4())
    mem_b_id = str(uuid.uuid4())
    edge = Edge(
        from_id=mem_a_id,
        to_id=mem_b_id,
        edge_type="RELATED_TO",
        properties={"weight": 1.0},
    )
    storage.list_edges_for_memories = AsyncMock(return_value=[edge])

    svc = GraphSyncService(graph_adapter=graph, storage_adapter=storage)
    memories = [_make_memory(id=mem_a_id), _make_memory(id=mem_b_id)]
    n = await svc.bulk_merge_memories(memories)

    assert n == 2
    assert graph.execute_write.call_count == 2
    cypher_calls = [c.args[0] for c in graph.execute_write.await_args_list]
    assert any("MERGE (a)-[r:RELATED_TO]->(b)" in c for c in cypher_calls)


@pytest.mark.asyncio
async def test_full_sync_pagination_and_safeguard() -> None:
    import uuid

    from context_store.sync.graph_sync import GraphSyncService

    graph = MagicMock()
    graph.execute_write = AsyncMock()
    storage = MagicMock()

    mem_1_id = str(uuid.uuid4())
    mem_2_id = str(uuid.uuid4())
    page1 = [_make_memory(id=mem_1_id)]
    page2 = [_make_memory(id=mem_2_id)]
    storage.list_by_filter = AsyncMock(side_effect=[page1, page2, []])

    svc = GraphSyncService(graph_adapter=graph, storage_adapter=storage)
    total = await svc.full_sync_from_storage(chunk_size=1)

    assert total == 2
    assert graph.execute_write.call_count == 2

    # Safeguard check
    storage.list_by_filter = AsyncMock(return_value=[_make_memory(id=str(uuid.uuid4()))])
    total_safeguard = await svc.full_sync_from_storage(chunk_size=1, max_pages=3)
    assert total_safeguard == 3


def test_sanitize_edge_type_validation() -> None:
    from context_store.sync.graph_sync import _sanitize_edge_type

    assert _sanitize_edge_type("RELATED_TO") == "RELATED_TO"
    assert _sanitize_edge_type("has_property") == "has_property"
    assert _sanitize_edge_type("_private") == "_private"

    with pytest.raises(ValueError):
        _sanitize_edge_type("1abc")

    with pytest.raises(ValueError):
        _sanitize_edge_type("")

    with pytest.raises(ValueError):
        _sanitize_edge_type("a-b")

    with pytest.raises(ValueError):
        _sanitize_edge_type("a; DROP TABLE nodes;")


@pytest.mark.asyncio
async def test_bulk_merge_invalid_edge_type_raises() -> None:
    import uuid

    from context_store.models.graph import Edge
    from context_store.storage.protocols import GraphAdapter
    from context_store.sync.graph_sync import GraphSyncService

    graph = MagicMock()
    graph.execute_write = AsyncMock()

    class MockStorageGraphAdapter(GraphAdapter):
        async def list_edges_for_memories(self, memory_ids: list[str]) -> list[Edge]:
            pass

    storage = MagicMock(spec=MockStorageGraphAdapter)
    mem_a_id = str(uuid.uuid4())
    mem_b_id = str(uuid.uuid4())
    edge = Edge(
        from_id=mem_a_id,
        to_id=mem_b_id,
        edge_type="1invalid",
        properties={},
    )
    storage.list_edges_for_memories = AsyncMock(return_value=[edge])

    svc = GraphSyncService(graph_adapter=graph, storage_adapter=storage)
    memories = [_make_memory(id=mem_a_id), _make_memory(id=mem_b_id)]

    with pytest.raises(ValueError) as excinfo:
        await svc.bulk_merge_memories(memories)
    assert "Invalid edge_type for Cypher" in str(excinfo.value)
