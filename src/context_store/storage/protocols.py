from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from context_store.models.graph import GraphResult
from context_store.models.memory import Memory, ScoredMemory


class StorageError(Exception):
    """Base exception for all storage adapter errors."""

    def __init__(
        self, message: str, code: str = "STORAGE_ERROR", recoverable: bool = False
    ) -> None:
        super().__init__(message)
        self.code = code
        self.recoverable = recoverable


@dataclass
class MemoryFilters:
    """Filters for listing memories."""

    project: str | None = None
    memory_type: str | None = None
    # None = active only, True = archived only, False = both
    archived: bool | None = None
    tags: list[str] = field(default_factory=list)
    limit: int | None = None
    order_by: str | None = None
    session_id: str | None = None
    created_after: datetime | None = None
    id_after: str | None = None


ALLOWED_SORT_COLUMNS: set[str] = {
    "id",
    "memory_type",
    "source_type",
    "semantic_relevance",
    "importance_score",
    "access_count",
    "last_accessed_at",
    "created_at",
    "updated_at",
    "archived_at",
    "project",
}


@runtime_checkable
class StorageAdapter(Protocol):
    """Protocol for vector/document storage backends (SQLite, PostgreSQL, etc.)."""

    async def save_memory(self, memory: Memory) -> str:
        """Persist a memory and return its ID."""
        ...

    async def get_memory(self, memory_id: str) -> Memory | None:
        """Retrieve a memory by ID. Returns None if not found."""
        ...

    async def get_memories_batch(self, memory_ids: list[str]) -> list[Memory]:
        """Retrieve multiple memories by ID.

        Returns a list of `Memory` objects containing only found memories.
        Non-existent memory IDs are omitted from the returned list (i.e., no
        placeholders or None entries). Callers must handle missing IDs client-side.
        """
        ...

    async def delete_memory(self, memory_id: str) -> bool:
        """Delete a memory. Returns True if deleted, False if not found."""
        ...

    async def update_memory(self, memory_id: str, updates: dict[str, Any]) -> bool:
        """Apply partial updates to a memory. Returns True on success."""
        ...

    async def vector_search(
        self, embedding: list[float], top_k: int, project: str | None = None
    ) -> list[ScoredMemory]:
        """Search by embedding similarity. Returns top_k results sorted by score."""
        ...

    async def keyword_search(
        self, query: str, top_k: int, project: str | None = None
    ) -> list[ScoredMemory]:
        """Full-text keyword search. Returns top_k results sorted by score."""
        ...

    async def list_by_filter(self, filters: MemoryFilters) -> list[Memory]:
        """List memories matching the given filters."""
        ...

    async def count_by_filter(self, filters: MemoryFilters) -> int:
        """Count memories matching the given filters."""
        ...

    async def increment_memory_access_count(self, memory_id: str) -> bool:
        """Atomically increment the access count and update last_accessed_at.

        Returns True on success, False if not found.
        """
        ...

    async def get_vector_dimension(self) -> int | None:
        """Return the dimension of stored vectors.

        Returns None if no memories with embeddings exist yet.
        The orchestrator uses this at startup to detect dimension mismatch
        with the configured embedding provider.
        """
        ...

    async def dispose(self) -> None:
        """Release all resources held by this adapter."""
        ...


@runtime_checkable
class GraphAdapter(Protocol):
    """Protocol for graph storage backends (SQLite adjacency, Neo4j, etc.)."""

    async def create_node(self, memory_id: str, metadata: dict[str, Any]) -> None:
        """Create or upsert a graph node for the given memory ID."""
        ...

    async def create_edge(
        self, from_id: str, to_id: str, edge_type: str, props: dict[str, Any]
    ) -> None:
        """Create a directed edge between two nodes."""
        ...

    async def create_edges_batch(self, edges: list[dict[str, Any]]) -> None:
        """Create multiple edges in a single operation for efficiency."""
        ...

    async def traverse(self, seed_ids: list[str], edge_types: list[str], depth: int) -> GraphResult:
        """Traverse the graph from seed nodes up to the given depth.

        Args:
            seed_ids: Starting node IDs.
            edge_types: Edge type filters; empty list means all types.
            depth: Maximum traversal depth.

        Returns:
            GraphResult containing discovered nodes and edges.
        """
        ...

    async def delete_node(self, memory_id: str) -> None:
        """Delete a node and all its incident edges."""
        ...

    async def dispose(self) -> None:
        """Release all resources held by this adapter."""
        ...


@runtime_checkable
class CacheAdapter(Protocol):
    """Protocol for caching backends (in-memory, Redis, etc.).

    Implementation notes:
    - ``invalidate_prefix`` MUST NOT use Redis KEYS command; use SCAN + batch DELETE.
    - For in-memory implementations, use prefix matching with asyncio.Lock.
    """

    async def get(self, key: str) -> Any | None:
        """Retrieve a cached value. Returns None on cache miss."""
        ...

    async def set(self, key: str, value: Any, ttl: int) -> None:
        """Store a value with a TTL (seconds)."""
        ...

    async def invalidate(self, key: str) -> None:
        """Remove a single cache entry."""
        ...

    async def invalidate_prefix(self, prefix: str) -> None:
        """Remove all cache entries whose keys start with ``prefix``.

        Must NOT use Redis KEYS command; use SCAN + batch DELETE instead.
        For in-memory backends, use prefix matching with asyncio.Lock.
        """
        ...

    async def clear(self) -> None:
        """Remove all cache entries."""
        ...

    async def dispose(self) -> None:
        """Release all resources held by this adapter."""
        ...
