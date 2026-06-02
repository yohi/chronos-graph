"""Storage Factory.

Creates and returns a (StorageAdapter, GraphAdapter | None, CacheAdapter) tuple
based on application Settings.

Routing logic
-------------
- STORAGE_BACKEND=sqlite   → SQLiteStorageAdapter
- STORAGE_BACKEND=postgres → PostgresStorageAdapter
- STORAGE_BACKEND=supabase → SupabaseStorageAdapter

- GRAPH_ENABLED=true + STORAGE_BACKEND=sqlite → SQLiteGraphAdapter
- GRAPH_ENABLED=true + STORAGE_BACKEND=postgres → Neo4jGraphAdapter (requires NEO4J_PASSWORD)
- GRAPH_ENABLED=true + STORAGE_BACKEND=supabase →
  Neo4jGraphAdapter when async_outbox, else ValueError
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
    from context_store.models.memory import Memory, ScoredMemory
    from context_store.storage.protocols import (
        CacheAdapter,
        GraphAdapter,
        MemoryFilters,
        StorageAdapter,
    )
    from context_store.sync.outbox_reader import OutboxReader
    from context_store.sync.outbox_worker import OutboxWorker
    from context_store.sync.outbox_writer import OutboxWriter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cache Coherence Checker (SQLite + InMemory only)
# ---------------------------------------------------------------------------


class ReadOnlyNoOpStorageAdapter:
    """A minimal StorageAdapter that returns safe defaults (None/empty).

    Used as a fallback when a specific backend does not yet support
    read_only mode (e.g., PostgreSQL in Phase 6), allowing the Dashboard
    to still run with Graph and Cache capabilities.

    NOTE: Read operations in this adapter raise NotImplementedError to signal
    that the primary storage backend is not yet accessible in read-only mode.
    """

    async def save_memory(self, memory: "Memory") -> str:
        raise NotImplementedError("ReadOnlyNoOpStorageAdapter does not support writes")

    async def get_memory(self, memory_id: str) -> "Memory | None":
        raise NotImplementedError("ReadOnlyNoOpStorageAdapter: get_memory not implemented")

    async def get_memories_batch(self, memory_ids: list[str]) -> list["Memory"]:
        raise NotImplementedError(
            "ReadOnlyNoOpStorageAdapter: get_memories_batch not implemented (Phase 6)"
        )

    async def delete_memory(self, memory_id: str) -> bool:
        raise NotImplementedError("ReadOnlyNoOpStorageAdapter does not support writes")

    async def update_memory(self, memory_id: str, updates: dict[str, Any]) -> bool:
        raise NotImplementedError("ReadOnlyNoOpStorageAdapter does not support writes")

    async def vector_search(
        self, embedding: list[float], top_k: int, project: str | None = None
    ) -> list["ScoredMemory"]:
        raise NotImplementedError(
            "ReadOnlyNoOpStorageAdapter: vector_search not implemented (Phase 6)"
        )

    async def keyword_search(
        self, query: str, top_k: int, project: str | None = None
    ) -> list["ScoredMemory"]:
        raise NotImplementedError(
            "ReadOnlyNoOpStorageAdapter: keyword_search not implemented (Phase 6)"
        )

    async def list_by_filter(self, filters: "MemoryFilters") -> list["Memory"]:
        raise NotImplementedError(
            "ReadOnlyNoOpStorageAdapter: list_by_filter not implemented (Phase 6)"
        )

    async def count_by_filter(self, filters: "MemoryFilters") -> int:
        raise NotImplementedError(
            "ReadOnlyNoOpStorageAdapter: count_by_filter not implemented (Phase 6)"
        )

    async def list_projects(self) -> list[str]:
        raise NotImplementedError(
            "ReadOnlyNoOpStorageAdapter: list_projects not implemented (Phase 6)"
        )

    async def increment_memory_access_count(self, memory_id: str) -> bool:
        return False

    async def increment_memory_access_counts(self, memory_ids: list[str]) -> int:
        return 0

    async def get_vector_dimension(self) -> int | None:
        raise NotImplementedError(
            "ReadOnlyNoOpStorageAdapter: get_vector_dimension not implemented (Phase 6)"
        )

    async def dispose(self) -> None:
        pass


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
        *,
        read_only: bool = False,
    ) -> None:
        self._db_path = db_path
        self._cache = cache
        self._poll_interval = poll_interval
        self._read_only = read_only
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
            import aiosqlite  # type: ignore[import-not-found]

            # Ensure the database file and schema are initialized (only in write mode).
            # Note: Table creation is now primarily handled by MigrationRunner (0000_system.sql),
            # but we keep a check here to ensure the storage is ready for polling.
            if not self._read_only:
                # TODO(refactor): Verify if this explicit connect/pass is still needed
                # to trigger file creation or if MigrationRunner guarantees it.
                pass

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
                    # In read_only mode, table might not exist yet if no write happened
                    if self._read_only and "no such table: system_metadata" in str(exc):
                        continue
                    logger.warning("SQLiteCacheCoherenceChecker poll failed: %s", exc)
        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# Public factory function
# ---------------------------------------------------------------------------


async def create_storage(
    settings: "Settings",
    *,
    read_only: bool = False,
) -> tuple["StorageAdapter", "GraphAdapter | None", "CacheAdapter"]:
    """Create storage, graph, and cache adapters from *settings*.

    Args:
        settings: Application settings.
        read_only: If True, open SQLite with ``mode=ro`` URI and Neo4j with READ_ACCESS.
            Cache coherence checker runs even in read_only mode to observe updates.

    Returns:
        (StorageAdapter, GraphAdapter | None, CacheAdapter)
    """
    storage = None
    graph_adp = None
    cache_adp = None
    try:
        # Create graph and cache first to allow read-only dashboard with Neo4j
        # even if Postgres read-only storage is not yet implemented.
        graph_adp = await _create_graph_adapter(settings, read_only=read_only)
        cache_adp = await _create_cache_adapter(settings)

        try:
            storage = await _create_storage_adapter(settings, read_only=read_only)
        except NotImplementedError as exc:
            # Re-raise unless we are in read-only mode (Dashboard needs to start)
            if read_only:
                logger.warning(
                    "Storage adapter not available in read-only mode: %s. "
                    "Returning ReadOnlyNoOpStorageAdapter for limited dashboard functionality.",
                    exc,
                )
                storage = ReadOnlyNoOpStorageAdapter()  # type: ignore
            else:
                raise

        # Start cache coherence checker for SQLite + InMemory combination
        checker = None
        if settings.storage_backend == "sqlite" and settings.cache_backend == "inmemory":
            import os

            from context_store.storage.inmemory import InMemoryCacheAdapter

            db_path = os.path.expanduser(settings.sqlite_db_path)
            # Only start if the database file exists (fail-fast principle)
            # In read_only mode, we still start it if the file exists.
            if os.path.exists(db_path):
                checker = SQLiteCacheCoherenceChecker(
                    db_path=db_path,
                    cache=cache_adp,  # type: ignore
                    poll_interval=settings.cache_coherence_poll_interval_seconds,
                    read_only=read_only,
                )
                checker.start()

            if checker is not None and isinstance(cache_adp, InMemoryCacheAdapter):
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


async def create_storage_with_outbox(
    settings: "Settings",
    *,
    read_only: bool = False,
    outbox_writer: "OutboxWriter | None" = None,
) -> tuple[
    "StorageAdapter",
    "GraphAdapter | None",
    "CacheAdapter",
    "OutboxWorker | None",
]:
    """async_outbox モード対応の Factory。Worker も生成して返す。"""
    from context_store.sync.graph_sync import GraphSyncService
    from context_store.sync.outbox_reader import (
        PostgresOutboxReader,
        SqliteOutboxReader,
        SupabaseOutboxReader,
    )
    from context_store.sync.outbox_worker import OutboxWorker
    from context_store.sync.outbox_writer import (
        PostgresOutboxWriter,
        SqliteOutboxWriter,
    )

    # 通常の create_storage を呼び出す
    storage, graph_adp, cache_adp = await create_storage(settings, read_only=read_only)

    if settings.graph_sync_mode != "async_outbox":
        return storage, graph_adp, cache_adp, None

    if graph_adp is None:
        raise ValueError("async_outbox requires graph_enabled=true")

    # Writer/Reader を Storage backend ごとに生成
    reader: "OutboxReader"
    if settings.storage_backend == "sqlite":
        import os

        db_path = os.path.expanduser(settings.sqlite_db_path)
        storage._outbox_writer = SqliteOutboxWriter()  # type: ignore[attr-defined]
        reader = SqliteOutboxReader(db_path=db_path)
    elif settings.storage_backend == "postgres":
        storage._outbox_writer = PostgresOutboxWriter()  # type: ignore[attr-defined]
        reader = PostgresOutboxReader(pool=storage._pool)  # type: ignore[attr-defined]
    elif settings.storage_backend == "supabase":
        storage._outbox_enabled = True  # type: ignore[attr-defined]
        # Supabase は asyncpg を直接使えないため、Task 1.3 で定義した RPC を
        # 呼び出す SupabaseOutboxReader を使用する（Python 実装は Task 4.1
        # の `outbox_reader.py` 内で SqliteOutboxReader / PostgresOutboxReader
        # と並んで提供される）。
        reader = SupabaseOutboxReader(client=storage._client)  # type: ignore[attr-defined]
    else:
        raise ValueError(f"Unsupported backend for outbox: {settings.storage_backend}")

    # GraphSyncService は Neo4jGraphAdapter を期待するためキャスト
    from typing import cast

    from context_store.storage.neo4j import Neo4jGraphAdapter

    neo4j_adp = cast(Neo4jGraphAdapter, graph_adp)

    graph_sync = GraphSyncService(graph_adapter=neo4j_adp, storage_adapter=storage)
    worker = OutboxWorker(
        reader=reader,
        storage_adapter=storage,
        graph_sync=graph_sync,
        settings=settings,
    )
    return storage, graph_adp, cache_adp, worker


async def _create_storage_adapter(
    settings: "Settings", *, read_only: bool = False
) -> "StorageAdapter":
    """Instantiate the appropriate StorageAdapter."""
    if settings.storage_backend == "sqlite":
        from context_store.storage.sqlite import SQLiteStorageAdapter

        return await SQLiteStorageAdapter.create(settings, read_only=read_only)

    if settings.storage_backend == "postgres":
        from context_store.storage.postgres import PostgresStorageAdapter

        if read_only:
            raise NotImplementedError(
                "read_only mode for postgres backend is not yet supported (Phase 6)"
            )
        return await PostgresStorageAdapter.create(settings)

    if settings.storage_backend == "supabase":
        from context_store.storage.supabase import SupabaseStorageAdapter

        if read_only:
            raise NotImplementedError("read_only mode for supabase backend is not yet supported")
        return await SupabaseStorageAdapter.create(settings)

    raise ValueError(f"Unsupported storage_backend: {settings.storage_backend!r}")


async def _create_graph_adapter(
    settings: "Settings", *, read_only: bool = False
) -> "GraphAdapter | None":
    """Instantiate the appropriate GraphAdapter, or None if disabled."""
    if not settings.graph_enabled:
        return None

    if settings.storage_backend == "sqlite":
        import os

        from context_store.storage.sqlite_graph import SQLiteGraphAdapter

        db_path = os.path.expanduser(settings.sqlite_db_path)
        adp = SQLiteGraphAdapter(db_path=db_path, settings=settings, read_only=read_only)
        await adp.initialize()
        return adp

    if settings.storage_backend == "postgres":
        # Neo4j is used as the graph backend for PostgreSQL mode
        from context_store.storage.neo4j import Neo4jGraphAdapter

        if (
            not settings.neo4j_uri
            or not settings.neo4j_user
            or not settings.neo4j_password.get_secret_value().strip()
        ):
            raise ValueError(
                "Neo4j uri, user, and password must be provided "
                "when graph is enabled with postgres backend."
            )
        return await Neo4jGraphAdapter.create(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
            read_only=read_only,
        )

    if settings.storage_backend == "supabase":
        if settings.graph_sync_mode != "async_outbox":
            raise ValueError(
                "Supabase + graph requires graph_sync_mode='async_outbox' "
                "(Neo4j Bolt cannot be tunneled over HTTPS)"
            )
        from context_store.storage.neo4j import Neo4jGraphAdapter

        return await Neo4jGraphAdapter.create(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
            read_only=read_only,
        )

    raise ValueError(f"Unsupported storage_backend for graph: {settings.storage_backend!r}")


async def _create_cache_adapter(settings: "Settings") -> "CacheAdapter":
    """Instantiate the appropriate CacheAdapter."""
    if settings.cache_backend == "inmemory":
        from context_store.storage.inmemory import InMemoryCacheAdapter

        return InMemoryCacheAdapter()

    if settings.cache_backend == "redis":
        from context_store.storage.redis import RedisCacheAdapter

        return await RedisCacheAdapter.create(
            settings.redis_url,
            ssl=settings.redis_ssl,
            socket_connect_timeout=settings.redis_socket_connect_timeout,
            socket_timeout=settings.redis_socket_timeout,
        )

    raise ValueError(f"Unsupported cache_backend: {settings.cache_backend!r}")
