"""Storage Factory.

Creates and returns a (StorageAdapter, GraphAdapter | None, CacheAdapter) tuple
based on application Settings.

Routing logic
-------------
- STORAGE_BACKEND=sqlite  → SQLiteStorageAdapter
- STORAGE_BACKEND=postgres → PostgresStorageAdapter

- GRAPH_ENABLED=true + STORAGE_BACKEND=sqlite → SQLiteGraphAdapter
- GRAPH_ENABLED=true + STORAGE_BACKEND=postgres → Neo4jGraphAdapter (requires NEO4J_PASSWORD)
- GRAPH_ENABLED=false → None

- CACHE_BACKEND=inmemory → InMemoryCacheAdapter  (+ SQLiteCacheCoherenceChecker for sqlite)
- CACHE_BACKEND=redis    → RedisCacheAdapter

Cache Coherence (SQLite + InMemory)
------------------------------------
When using SQLite storage with an in-memory cache in a multi-process setup,
stale cache entries can accumulate.  The factory starts a background
``asyncio.Task`` (``SQLiteCacheCoherenceChecker``) that polls
``system_metadata WHERE key = 'last_cache_update'`` and calls
``CacheAdapter.clear()`` whenever a newer timestamp is detected.

The ``system_metadata`` table is created lazily if it does not exist.
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from context_store.config import Settings
    from context_store.storage.protocols import CacheAdapter, GraphAdapter, StorageAdapter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cache Coherence Checker (SQLite + InMemory only)
# ---------------------------------------------------------------------------


class SQLiteCacheCoherenceChecker:
    """Periodically polls SQLite system_metadata for cache invalidation signals.

    This is a best-effort mechanism for multi-process environments sharing the
    same SQLite file.  Stale entries that slip through are eventually evicted
    by TTL or cleaned up by the Consolidator.
    """

    def __init__(
        self,
        db_path: str,
        cache: "CacheAdapter",
        poll_interval: float,
    ) -> None:
        self._db_path = db_path
        self._cache = cache
        self._poll_interval = poll_interval
        self._last_seen: str | None = None
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        """Start the background polling task."""
        self._task = asyncio.get_event_loop().create_task(
            self._poll_loop(), name="cache-coherence-checker"
        )

    def stop(self) -> None:
        """Cancel the background task (best-effort)."""
        if self._task and not self._task.done():
            self._task.cancel()

    async def _poll_loop(self) -> None:
        """Poll until cancelled."""
        try:
            import aiosqlite

            # Ensure the table exists
            async with aiosqlite.connect(self._db_path) as conn:
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS system_metadata (
                        key        TEXT PRIMARY KEY,
                        value      TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                await conn.commit()

            while True:
                await asyncio.sleep(self._poll_interval)
                try:
                    async with aiosqlite.connect(self._db_path) as conn:
                        conn.row_factory = aiosqlite.Row
                        async with conn.execute(
                            "SELECT value, updated_at FROM system_metadata "
                            "WHERE key = 'last_cache_update'"
                        ) as cursor:
                            row = await cursor.fetchone()

                    if row is not None:
                        updated_at = row["updated_at"]
                        if self._last_seen is None or updated_at > self._last_seen:
                            self._last_seen = updated_at
                            await self._cache.clear()
                            logger.debug(
                                "Cache cleared by coherence checker (updated_at=%s)",
                                updated_at,
                            )
                except Exception as exc:
                    logger.warning(
                        "SQLiteCacheCoherenceChecker poll failed: %s", exc
                    )
        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# Public factory function
# ---------------------------------------------------------------------------


async def create_storage(
    settings: "Settings",
) -> tuple["StorageAdapter", "GraphAdapter | None", "CacheAdapter"]:
    """Create storage, graph, and cache adapters from *settings*.

    Returns:
        (StorageAdapter, GraphAdapter | None, CacheAdapter)
    """
    storage = await _create_storage_adapter(settings)
    graph_adp = await _create_graph_adapter(settings)
    cache_adp = await _create_cache_adapter(settings)

    # Start cache coherence checker for SQLite + InMemory combination
    if (
        settings.storage_backend == "sqlite"
        and settings.cache_backend == "inmemory"
    ):
        import os

        db_path = os.path.expanduser(settings.sqlite_db_path)
        checker = SQLiteCacheCoherenceChecker(
            db_path=db_path,
            cache=cache_adp,
            poll_interval=settings.cache_coherence_poll_interval_seconds,
        )
        checker.start()

    return storage, graph_adp, cache_adp


async def _create_storage_adapter(settings: "Settings") -> "StorageAdapter":
    """Instantiate the appropriate StorageAdapter."""
    if settings.storage_backend == "sqlite":
        from context_store.storage.sqlite import SQLiteStorageAdapter

        return await SQLiteStorageAdapter.create(settings)

    if settings.storage_backend == "postgres":
        from context_store.storage.postgres import PostgresStorageAdapter

        return await PostgresStorageAdapter.create(settings)

    raise ValueError(f"Unsupported storage_backend: {settings.storage_backend!r}")


async def _create_graph_adapter(settings: "Settings") -> "GraphAdapter | None":
    """Instantiate the appropriate GraphAdapter, or None if disabled."""
    if not settings.graph_enabled:
        return None

    if settings.storage_backend == "sqlite":
        import os

        from context_store.storage.sqlite_graph import SQLiteGraphAdapter

        db_path = os.path.expanduser(settings.sqlite_db_path)
        adp = SQLiteGraphAdapter(db_path=db_path, settings=settings)
        await adp.initialize()
        return adp

    if settings.storage_backend == "postgres":
        # Neo4j is used as the graph backend for PostgreSQL mode
        from context_store.storage.neo4j import Neo4jGraphAdapter

        return await Neo4jGraphAdapter.create(settings)

    raise ValueError(f"Unsupported storage_backend for graph: {settings.storage_backend!r}")


async def _create_cache_adapter(settings: "Settings") -> "CacheAdapter":
    """Instantiate the appropriate CacheAdapter."""
    if settings.cache_backend == "inmemory":
        from context_store.storage.inmemory import InMemoryCacheAdapter

        return InMemoryCacheAdapter()

    if settings.cache_backend == "redis":
        from context_store.storage.redis import RedisCacheAdapter

        return await RedisCacheAdapter.create(settings.redis_url)

    raise ValueError(f"Unsupported cache_backend: {settings.cache_backend!r}")
