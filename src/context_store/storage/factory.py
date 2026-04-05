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
from typing import TYPE_CHECKING, Any

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
        self._task: asyncio.Task[Any] | None = None

    def start(self) -> None:
        """Start the background polling task."""
        self._task = asyncio.get_running_loop().create_task(
            self._poll_loop(), name="cache-coherence-checker"
        )

    async def stop(self) -> None:
        """Cancel the background task (best-effort) and await completion."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

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
                    logger.warning("SQLiteCacheCoherenceChecker poll failed: %s", exc)
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
    storage = None
    graph_adp = None
    cache_adp = None
    try:
        storage = await _create_storage_adapter(settings)
        graph_adp = await _create_graph_adapter(settings)
        cache_adp = await _create_cache_adapter(settings)

        # Start cache coherence checker for SQLite + InMemory combination
        if settings.storage_backend == "sqlite" and settings.cache_backend == "inmemory":
            import os

            from context_store.storage.inmemory import InMemoryCacheAdapter

            db_path = os.path.expanduser(settings.sqlite_db_path)
            checker = SQLiteCacheCoherenceChecker(
                db_path=db_path,
                cache=cache_adp,
                poll_interval=settings.cache_coherence_poll_interval_seconds,
            )
            checker.start()
            if isinstance(cache_adp, InMemoryCacheAdapter):
                cache_adp.set_coherence_checker(checker)

        return storage, graph_adp, cache_adp
    except Exception:
        # 各リソースの dispose() を個別に try/except で囲むことで、
        # 途中で例外が発生しても全リソースの解放を試みる。
        if cache_adp:
            try:
                await cache_adp.dispose()
            except Exception:
                logger.exception("Failed to dispose cache_adp")
        if graph_adp:
            try:
                await graph_adp.dispose()
            except Exception:
                logger.exception("Failed to dispose graph_adp")
        if storage:
            try:
                await storage.dispose()
            except Exception:
                logger.exception("Failed to dispose storage")
        raise


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

        if not settings.neo4j_uri or not settings.neo4j_user or not settings.neo4j_password:
            raise ValueError(
                "Neo4j uri, user, and password must be provided when graph is enabled with postgres backend."
            )
        return await Neo4jGraphAdapter.create(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password.get_secret_value(),
        )

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
