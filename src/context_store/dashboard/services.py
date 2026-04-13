from __future__ import annotations

import asyncio
from typing import Literal

from context_store.dashboard.schemas import (
    DashboardStats,
    GraphElementsDTO,
    GraphLayoutResponse,
    LogEntry,
    ProjectStats,
)
from context_store.models.graph import GraphResult
from context_store.models.memory import Memory
from context_store.storage.protocols import (
    GraphAdapter,
    MemoryFilters,
    StorageAdapter,
)

MAX_CONCURRENT_DASHBOARD_TASKS = 5


class DashboardService:
    """Read-Only アダプタを組み合わせた Dashboard 専用の集約サービス。"""

    def __init__(
        self,
        storage: StorageAdapter,
        graph: GraphAdapter | None,
    ) -> None:
        self._storage = storage
        self._graph = graph

    async def get_stats_summary(self) -> DashboardStats:
        active, archived, total, projects = await asyncio.gather(
            self._storage.count_by_filter(MemoryFilters(archived=None)),
            self._storage.count_by_filter(MemoryFilters(archived=True)),
            self._storage.count_by_filter(MemoryFilters(archived=False)),
            self._storage.list_projects(),
        )
        edge_count = await self._graph.count_edges() if self._graph else 0
        return DashboardStats(
            active_count=active,
            archived_count=archived,
            total_count=total,
            edge_count=edge_count,
            project_count=len(projects),
            projects=projects,
        )

    async def get_project_stats(self) -> list[ProjectStats]:
        projects = await self._storage.list_projects()
        # Limit concurrency to prevent STORAGE_BUSY (rev.10 §3.5)
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_DASHBOARD_TASKS)

        async def _fetch_project_stats(p: str) -> ProjectStats:
            async with semaphore:
                active, archived, total = await asyncio.gather(
                    self._storage.count_by_filter(MemoryFilters(project=p, archived=None)),
                    self._storage.count_by_filter(MemoryFilters(project=p, archived=True)),
                    self._storage.count_by_filter(MemoryFilters(project=p, archived=False)),
                )
                return ProjectStats(
                    project=p,
                    active_count=active,
                    archived_count=archived,
                    total_count=total,
                )

        return list(await asyncio.gather(*(_fetch_project_stats(p) for p in projects)))

    async def get_graph_layout(
        self,
        *,
        project: str | None = None,
        limit: int = 500,
        order_by: Literal["importance", "recency"] = "importance",
    ) -> GraphLayoutResponse:
        sort_column = "importance_score" if order_by == "importance" else "created_at"
        total = await self._storage.count_by_filter(MemoryFilters(project=project, archived=None))
        memories = await self._storage.list_by_filter(
            MemoryFilters(
                project=project,
                archived=None,
                limit=limit,
                order_by=sort_column,
            )
        )
        memory_ids = [str(m.id) for m in memories]
        edges = await self._graph.list_edges_for_memories(memory_ids) if self._graph else []
        nodes = [
            {
                "data": {
                    "id": str(m.id),
                    "label": (m.content or "")[:80],
                    "memoryType": m.memory_type,
                    "importance": m.importance_score,
                    "project": m.project,
                    "accessCount": m.access_count,
                    "createdAt": m.created_at.isoformat() if m.created_at else "",
                }
            }
            for m in memories
        ]
        edge_elements = [
            {
                "data": {
                    "id": f"{e.from_id}-{e.to_id}-{e.edge_type}",
                    "source": e.from_id,
                    "target": e.to_id,
                    "edgeType": e.edge_type,
                }
            }
            for e in edges
        ]
        return GraphLayoutResponse(
            elements=GraphElementsDTO(nodes=nodes, edges=edge_elements),
            total_nodes=total,
            returned_nodes=len(memories),
            total_edges=len(edges),
        )

    async def traverse_graph(
        self,
        seed_id: str,
        *,
        max_depth: int = 2,
        edge_types: list[str] | None = None,
    ) -> GraphResult:
        if self._graph is None:
            raise RuntimeError("graph backend not configured")
        return await self._graph.traverse(
            seed_ids=[seed_id],
            edge_types=edge_types or [],
            depth=max_depth,
        )

    async def get_memory(self, memory_id: str) -> Memory | None:
        """Get a memory by ID."""
        return await self._storage.get_memory(memory_id)

    async def search_memories(self, filters: MemoryFilters) -> list[Memory]:
        """Search memories by filters."""
        return await self._storage.list_by_filter(filters)

    async def get_recent_logs(self, limit: int = 100) -> list[LogEntry]:
        """Get recent system logs from the in-memory circular buffer."""
        from context_store.logger import get_recent_logs

        logs = get_recent_logs(limit=limit)
        return [
            LogEntry(
                timestamp=log["timestamp"],
                level=log["level"],
                logger=log["logger"],
                message=log["message"],
            )
            for log in logs
        ]
