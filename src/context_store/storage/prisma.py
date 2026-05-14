"""Prisma Accelerate-backed Storage Adapter.

社内ネットワークでの PostgreSQL 直接接続遮断を回避するため、HTTPS (443) 経由で
Prisma Accelerate を介して PostgreSQL にアクセスする実装。

設計仕様: docs/superpowers/specs/2026-05-12-prisma-adapter-design.md
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from prisma.errors import PrismaError, RawQueryError  # type: ignore[import-not-found]

from context_store.config import Settings
from prisma import Prisma  # type: ignore[attr-defined, import-not-found]

if TYPE_CHECKING:
    from context_store.models.memory import Memory, ScoredMemory
    from context_store.storage.protocols import MemoryFilters

logger = logging.getLogger(__name__)

# --- Accelerate 制約に対する定数 (設計書 4.3) ---
PRISMA_MAX_TOP_K: int = 200
PRISMA_BATCH_FETCH_CHUNK_SIZE: int = 250
PRISMA_TIMEOUT_CODES: frozenset[str] = frozenset({"P2024", "P2028", "P6004"})
PRISMA_PAYLOAD_TOO_LARGE_CODES: frozenset[str] = frozenset({"P6009"})


# ヘルパー関数は既存 PostgresStorageAdapter のものを物理的に再利用する。
# DRY の観点から本ファイルで再定義するのではなく、postgres.py から import する。

__all__ = [
    "PRISMA_BATCH_FETCH_CHUNK_SIZE",
    "PRISMA_MAX_TOP_K",
    "PRISMA_PAYLOAD_TOO_LARGE_CODES",
    "PRISMA_TIMEOUT_CODES",
    "PrismaStorageAdapter",
]
# 注: _content_hash / _embedding_to_pg / _parse_embedding / _record_to_memory は
# プライベートヘルパーであり再エクスポート対象としない (`from prisma import *` に
# 含めない)。本ファイル内部でのみ参照する。


class PrismaStorageAdapter:
    """StorageAdapter implementation backed by Prisma Accelerate (HTTPS)."""

    is_implemented: bool = False

    def __init__(self, client: Prisma) -> None:
        self._client = client

    @classmethod
    async def create(cls, settings: Settings) -> "PrismaStorageAdapter":
        """Connect to Prisma Accelerate and apply migrations."""
        url = settings.prisma_database_url.get_secret_value().strip()
        client = Prisma(
            datasource={"url": url},
        )
        await client.connect()
        adapter = cls(client=client)
        try:
            await adapter.initialize()
        except Exception:
            await client.disconnect()
            raise

        if not cls.is_implemented:
            await client.disconnect()
            raise NotImplementedError("Prisma backend not implemented")

        return adapter

    async def initialize(self) -> None:
        """Apply schema migrations (既存 postgres/ ディレクトリの SQL を順次実行)."""
        runner = _PrismaMigrationRunner(self._client)
        await runner.run()

    async def dispose(self) -> None:
        """Disconnect the Prisma client."""
        await self._client.disconnect()

    async def save_memory(self, memory: "Memory") -> str:
        raise NotImplementedError("Not supported by Prisma stub")

    async def get_memory(self, memory_id: str) -> "Memory | None":
        raise NotImplementedError("Not supported by Prisma stub")

    async def get_memories_batch(self, memory_ids: list[str]) -> list["Memory"]:
        raise NotImplementedError("Not supported by Prisma stub")

    async def delete_memory(self, memory_id: str) -> bool:
        raise NotImplementedError("Not supported by Prisma stub")

    async def update_memory(self, memory_id: str, updates: dict[str, Any]) -> bool:
        raise NotImplementedError("Not supported by Prisma stub")

    async def vector_search(
        self, embedding: list[float], top_k: int, project: str | None = None
    ) -> list["ScoredMemory"]:
        raise NotImplementedError("Not supported by Prisma stub")

    async def keyword_search(
        self, query: str, top_k: int, project: str | None = None
    ) -> list["ScoredMemory"]:
        raise NotImplementedError("Not supported by Prisma stub")

    async def list_by_filter(self, filters: "MemoryFilters") -> list["Memory"]:
        raise NotImplementedError("Not supported by Prisma stub")

    async def count_by_filter(self, filters: "MemoryFilters") -> int:
        raise NotImplementedError("Not supported by Prisma stub")

    async def list_projects(self) -> list[str]:
        raise NotImplementedError("Not supported by Prisma stub")

    async def increment_memory_access_count(self, memory_id: str) -> bool:
        raise NotImplementedError("Not supported by Prisma stub")

    async def get_vector_dimension(self) -> int | None:
        raise NotImplementedError("Not supported by Prisma stub")


class _PrismaMigrationRunner:
    """Apply existing postgres/*.sql migrations via prisma.execute_raw."""

    def __init__(self, client: Prisma) -> None:
        self._client = client

    # Prisma バックエンドが処理対象とするマイグレーションのみを許可するファイル名 prefix。
    # 設計書 §2 で graph 機能は Prisma の対象外とされているため、0002_graph.sql 以降の
    # graph 関連マイグレーションは Prisma 経由では適用しない。
    _PRISMA_ALLOWED_MIGRATION_PREFIXES: frozenset[str] = frozenset({"0000", "0001"})

    async def run(self) -> None:
        """Apply pending migrations in order.

        実装方針:
        - postgres/ ディレクトリの SQL ファイルを `pathlib.Path` で列挙
        - `_PRISMA_ALLOWED_MIGRATION_PREFIXES` に含まれる prefix のもののみを対象とする
          (graph 関連の 0002* 等は Prisma バックエンドの対象外、設計書 §2)
        - `schema_migrations` テーブル存在チェックは `query_raw`
        - 適用済みバージョン取得は `query_raw`
        - 未適用ファイルを sequential に `execute_raw` で適用
        - `pg_catalog.pg_tables` を用いた baseline 検出は既存 MigrationRunner と同等
        """
        migrations_dir = Path(__file__).parent / "migrations" / "postgres"
        all_files = sorted(migrations_dir.glob("*.sql"))
        files = [
            f for f in all_files if f.name.split("_")[0] in self._PRISMA_ALLOWED_MIGRATION_PREFIXES
        ]

        # 0000_system.sql を必ず最初に確保
        system_file = migrations_dir / "0000_system.sql"
        if system_file.exists():
            await self._ensure_system_migration(system_file)

        applied = await self._get_applied_migrations()

        # Baseline: 既存テーブルが存在する場合は対応マイグレーションを applied として記録
        if not applied or applied == {"0000_system.sql"}:
            await self._handle_baseline(files, applied)
            applied = await self._get_applied_migrations()

        for file_path in files:
            version = file_path.name
            if version not in applied:
                await self._apply_migration(file_path)
                logger.info("Applied migration via Prisma: %s", version)

    async def _ensure_system_migration(self, file_path: Path) -> None:
        try:
            await self._client.query_raw("SELECT 1 FROM schema_migrations LIMIT 1")
            return
        except RawQueryError as e:
            error_str = str(e).lower()
            if "does not exist" in error_str or "42p01" in error_str:
                logger.debug("Table schema_migrations not found, applying system migration")
                await self._apply_migration(file_path)
                return
            raise
        except PrismaError:
            raise

    async def _get_applied_migrations(self) -> set[str]:
        try:
            rows = await self._client.query_raw("SELECT version FROM schema_migrations")
        except RawQueryError as e:
            error_str = str(e).lower()
            if "does not exist" in error_str or "42p01" in error_str:
                return set()
            raise
        return {row["version"] for row in rows}

    async def _handle_baseline(self, files: list[Path], applied: set[str]) -> None:
        # graph (memory_nodes / memory_edges) は Prisma バックエンド対象外のため
        # baseline 検出対象に含めない (設計書 §2)。
        requirements = {"0001": ["memories"]}
        to_baseline: list[str] = []
        for file_path in files:
            prefix = file_path.name.split("_")[0]
            req_tables = requirements.get(prefix)
            if req_tables and await self._tables_exist(req_tables):
                to_baseline.append(file_path.name)
        for version in to_baseline:
            await self._client.execute_raw(
                "INSERT INTO schema_migrations (version) VALUES ($1) ON CONFLICT DO NOTHING",
                version,
            )

    async def _tables_exist(self, table_names: list[str]) -> bool:
        rows = await self._client.query_raw(
            "SELECT tablename FROM pg_catalog.pg_tables WHERE tablename = ANY($1::text[])",
            table_names,
        )
        return len(rows) == len(table_names)

    async def _apply_migration(self, file_path: Path) -> None:
        sql = file_path.read_text()
        version = file_path.name

        statements = [stmt.strip() for stmt in sql.split(";")]
        for stmt in statements:
            lines = [line.strip() for line in stmt.splitlines() if line.strip()]
            if not lines or all(line.startswith("--") for line in lines):
                continue
            await self._client.execute_raw(stmt)

        await self._client.execute_raw(
            "INSERT INTO schema_migrations (version) VALUES ($1)",
            version,
        )
