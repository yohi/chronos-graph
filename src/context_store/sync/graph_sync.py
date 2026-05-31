"""GraphSyncService: Storage → Neo4j のバルク同期ロジック。

Worker / リカバリスクリプト両方から使用。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from context_store.models.memory import Memory
    from context_store.storage.neo4j import Neo4jGraphAdapter
    from context_store.storage.protocols import StorageAdapter

logger = logging.getLogger(__name__)


_NODE_MERGE_CYPHER = """
UNWIND $batch AS row
MERGE (m:Memory {id: row.id})
SET m.memory_type = row.memory_type,
    m.created_at  = row.created_at,
    m.project     = row.project,
    m.tags        = row.tags
"""

_EDGE_MERGE_CYPHER_TEMPLATE = """
UNWIND $batch AS row
MATCH (a:Memory {{id: row.from_id}})
MATCH (b:Memory {{id: row.to_id}})
MERGE (a)-[r:{edge_type}]->(b)
SET r += row.props
"""

_DELETE_CYPHER = """
UNWIND $ids AS mid
MATCH (m:Memory {id: mid})
DETACH DELETE m
"""


class GraphSyncService:
    """Storage Layer → Neo4j のバルク同期サービス。"""

    def __init__(
        self,
        *,
        graph_adapter: "Neo4jGraphAdapter",
        storage_adapter: "StorageAdapter",
    ) -> None:
        self._graph = graph_adapter
        self._storage = storage_adapter

    async def bulk_merge_memories(self, memories: list["Memory"]) -> int:
        """ノード + 関連エッジを Neo4j に MERGE する。

        戻り値: MERGE したメモリ件数。
        """
        if not memories:
            return 0

        batch = [
            {
                "id": str(m.id),
                "memory_type": m.memory_type.value
                if hasattr(m.memory_type, "value")
                else m.memory_type,
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "project": m.project,
                "tags": list(m.tags or []),
            }
            for m in memories
        ]
        await self._graph.execute_write(_NODE_MERGE_CYPHER, {"batch": batch})

        memory_ids = [str(m.id) for m in memories]
        edges = await self._storage.list_edges_for_memories(memory_ids)  # type: ignore[attr-defined]

        if not edges:
            return len(memories)

        grouped: dict[str, list[dict[str, Any]]] = {}
        for e in edges:
            grouped.setdefault(e.edge_type, []).append(
                {
                    "from_id": e.from_id,
                    "to_id": e.to_id,
                    "props": dict(e.properties or {}),
                }
            )
        for edge_type, payload in grouped.items():
            cypher = _EDGE_MERGE_CYPHER_TEMPLATE.format(edge_type=_sanitize_edge_type(edge_type))
            await self._graph.execute_write(cypher, {"batch": payload})

        return len(memories)

    async def bulk_delete_nodes(self, memory_ids: list[str]) -> int:
        """ノード + 関連エッジを DETACH DELETE する。"""
        if not memory_ids:
            return 0
        await self._graph.execute_write(_DELETE_CYPHER, {"ids": list(memory_ids)})
        return len(memory_ids)

    async def full_sync_from_storage(self, *, chunk_size: int = 1000) -> int:
        """Storage 全体から Neo4j を再構築。chunk_size でページネーション。"""
        from context_store.storage.protocols import MemoryFilters

        total = 0
        offset = 0
        while True:
            filters = MemoryFilters(limit=chunk_size, offset=offset, order_by="id")
            page = await self._storage.list_by_filter(filters)
            if not page:
                break
            n = await self.bulk_merge_memories(page)
            total += n
            offset += chunk_size
            logger.info("GraphSyncService.full_sync_from_storage: synced %d so far", total)
        return total


def _sanitize_edge_type(edge_type: str) -> str:
    """Cypher 注入を防ぐためエッジ種別を英数字+アンダースコアに限定。"""
    if not edge_type.replace("_", "").isalnum():
        raise ValueError(f"Invalid edge_type for Cypher: {edge_type!r}")
    return edge_type
