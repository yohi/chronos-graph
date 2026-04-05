"""Unit tests for StorageFactory."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mock asyncpg only if not installed to avoid ModuleNotFoundError during patch resolution.
# We use find_spec to avoid importing it here if it exists.
if importlib.util.find_spec("asyncpg") is None:
    sys.modules["asyncpg"] = MagicMock()

from pydantic import SecretStr

from context_store.storage.factory import _create_graph_adapter, create_storage
from context_store.storage.inmemory import InMemoryCacheAdapter
from context_store.storage.protocols import CacheAdapter, GraphAdapter, StorageAdapter
from context_store.storage.sqlite import SQLiteStorageAdapter
from context_store.storage.sqlite_graph import SQLiteGraphAdapter
from tests.unit.conftest import make_settings

# ---------------------------------------------------------------------------
# Tests: SQLite backend
# ---------------------------------------------------------------------------


async def dispose_adapters(
    storage: StorageAdapter,
    graph_adp: GraphAdapter | None,
    cache_adp: CacheAdapter,
) -> None:
    """Dispose created adapters in a consistent order for test cleanup."""
    await storage.dispose()
    if graph_adp:
        await graph_adp.dispose()
    await cache_adp.dispose()


class TestSQLiteBackend:
    async def test_sqlite_returns_storage_adapter(self, tmp_path: Path) -> None:
        """STORAGE_BACKEND=sqlite → SQLiteStorageAdapter が返される."""
        db_path = str(tmp_path / "test.db")
        settings = make_settings(storage_backend="sqlite", sqlite_db_path=db_path)

        storage, graph_adp, cache_adp = await create_storage(settings)
        try:
            assert isinstance(storage, SQLiteStorageAdapter)
        finally:
            await dispose_adapters(storage, graph_adp, cache_adp)

    async def test_sqlite_graph_enabled(self, tmp_path: Path) -> None:
        """GRAPH_ENABLED=true, STORAGE_BACKEND=sqlite → SQLiteGraphAdapter が返される."""
        db_path = str(tmp_path / "test.db")
        settings = make_settings(
            storage_backend="sqlite",
            sqlite_db_path=db_path,
            graph_enabled=True,
        )

        storage, graph_adp, cache_adp = await create_storage(settings)
        try:
            assert isinstance(graph_adp, SQLiteGraphAdapter)
        finally:
            await dispose_adapters(storage, graph_adp, cache_adp)

    async def test_sqlite_graph_disabled(self, tmp_path: Path) -> None:
        """GRAPH_ENABLED=false → GraphAdapter が None."""
        db_path = str(tmp_path / "test.db")
        settings = make_settings(
            storage_backend="sqlite",
            sqlite_db_path=db_path,
            graph_enabled=False,
        )

        storage, graph_adp, cache_adp = await create_storage(settings)
        try:
            assert graph_adp is None
        finally:
            await dispose_adapters(storage, graph_adp, cache_adp)


# ---------------------------------------------------------------------------
# Tests: Graph backend
# ---------------------------------------------------------------------------


class TestGraphBackend:
    @pytest.mark.asyncio
    async def test_neo4j_validation_fails_with_empty_password(self) -> None:
        """Postgres モードで graph_enabled=True の場合、Neo4j 認証情報が必須."""
        # Settings をモック化して factory.py の内部バリデーションを直接テストする
        settings = MagicMock()
        settings.storage_backend = "postgres"
        settings.graph_enabled = True
        settings.neo4j_uri = "bolt://localhost"
        settings.neo4j_user = "neo4j"
        settings.neo4j_password = SecretStr("")  # 空

        with pytest.raises(ValueError, match="Neo4j uri, user, and password must be provided"):
            await _create_graph_adapter(settings)

    @pytest.mark.asyncio
    async def test_neo4j_validation_passes_with_sqlite_even_if_password_empty(
        self, tmp_path: Path
    ) -> None:
        """SQLite モードでは graph_enabled=True でも Neo4j 認証情報は不要."""
        db_path = str(tmp_path / "test.db")
        settings = make_settings(
            storage_backend="sqlite",
            sqlite_db_path=db_path,
            graph_enabled=True,
            neo4j_password="",  # 空
        )

        adapter = await _create_graph_adapter(settings)
        try:
            assert isinstance(adapter, SQLiteGraphAdapter)
        finally:
            if adapter:
                await adapter.dispose()


# ---------------------------------------------------------------------------
# Tests: Cache backend
# ---------------------------------------------------------------------------


class TestCacheBackend:
    async def test_inmemory_cache(self, tmp_path: Path) -> None:
        """CACHE_BACKEND=inmemory → InMemoryCacheAdapter が返される."""
        db_path = str(tmp_path / "test.db")
        settings = make_settings(
            storage_backend="sqlite",
            sqlite_db_path=db_path,
            cache_backend="inmemory",
        )

        storage, graph_adp, cache_adp = await create_storage(settings)
        try:
            assert isinstance(cache_adp, InMemoryCacheAdapter)
        finally:
            await dispose_adapters(storage, graph_adp, cache_adp)

    async def test_redis_cache(self, tmp_path: Path) -> None:
        """CACHE_BACKEND=redis → RedisCacheAdapter が返される."""
        db_path = str(tmp_path / "test.db")
        settings = make_settings(
            storage_backend="sqlite",
            sqlite_db_path=db_path,
            cache_backend="redis",
            redis_url="redis://localhost:6379",
        )

        from context_store.storage.redis import RedisCacheAdapter

        mock_adapter = AsyncMock(spec=RedisCacheAdapter)

        with patch(
            "context_store.storage.redis.RedisCacheAdapter.create",
            new=AsyncMock(return_value=mock_adapter),
        ):
            storage, graph_adp, cache_adp = await create_storage(settings)
            try:
                assert cache_adp is mock_adapter
            finally:
                await dispose_adapters(storage, graph_adp, cache_adp)


# ---------------------------------------------------------------------------
# Tests: PostgreSQL backend (mocked)
# ---------------------------------------------------------------------------


class TestPostgresBackend:
    async def test_postgres_returns_postgres_adapter(self, tmp_path: Path) -> None:
        """STORAGE_BACKEND=postgres → PostgresStorageAdapter が返される."""
        settings = make_settings(
            storage_backend="postgres",
            postgres_host="localhost",
            postgres_port=5432,
            postgres_db="test_db",
            postgres_user="test_user",
            postgres_password="secret",  # noqa: S106
            graph_enabled=False,
        )

        # Mock asyncpg.create_pool and postgres_dsn to avoid real DB connection
        mock_pool = MagicMock()
        mock_pool.close = AsyncMock()
        create_pool_mock = AsyncMock(return_value=mock_pool)

        with (
            patch("asyncpg.create_pool", create_pool_mock),
            patch.object(
                type(settings),
                "postgres_dsn",
                new_callable=lambda: property(
                    lambda self: "postgresql://test_user:secret@localhost:5432/test_db"
                ),
            ),
        ):
            from context_store.storage.postgres import PostgresStorageAdapter

            storage, graph_adp, cache_adp = await create_storage(settings)
            try:
                assert isinstance(storage, PostgresStorageAdapter)
                assert graph_adp is None  # postgres + graph_enabled=False
            finally:
                await dispose_adapters(storage, graph_adp, cache_adp)

    async def test_postgres_graph_disabled(self, tmp_path: Path) -> None:
        """STORAGE_BACKEND=postgres, GRAPH_ENABLED=false → GraphAdapter が None."""
        settings = make_settings(
            storage_backend="postgres",
            postgres_host="localhost",
            postgres_port=5432,
            postgres_db="test_db",
            postgres_user="test_user",
            postgres_password="secret",  # noqa: S106
            graph_enabled=False,
        )

        mock_pool = MagicMock()
        mock_pool.close = AsyncMock()
        create_pool_mock = AsyncMock(return_value=mock_pool)
        with (
            patch("asyncpg.create_pool", create_pool_mock),
            patch.object(
                type(settings),
                "postgres_dsn",
                new_callable=lambda: property(
                    lambda self: "postgresql://test_user:secret@localhost:5432/test_db"
                ),
            ),
        ):
            storage, graph_adp, cache_adp = await create_storage(settings)
            try:
                assert graph_adp is None
            finally:
                await dispose_adapters(storage, graph_adp, cache_adp)


# ---------------------------------------------------------------------------
# Tests: Return type contract
# ---------------------------------------------------------------------------


class TestReturnTypes:
    async def test_returns_three_tuple(self, tmp_path: Path) -> None:
        """create_storage は (StorageAdapter, GraphAdapter | None, CacheAdapter) を返す."""
        db_path = str(tmp_path / "test.db")
        settings = make_settings(sqlite_db_path=db_path)

        result = await create_storage(settings)
        assert len(result) == 3
        storage, graph_adp, cache_adp = result

        assert isinstance(storage, StorageAdapter)
        assert graph_adp is None or isinstance(graph_adp, GraphAdapter)
        assert isinstance(cache_adp, CacheAdapter)

        await dispose_adapters(storage, graph_adp, cache_adp)
