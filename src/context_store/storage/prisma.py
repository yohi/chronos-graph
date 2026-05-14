"""Prisma Accelerate-backed Storage Adapter.

社内ネットワークでの PostgreSQL 直接接続遮断を回避するため、HTTPS (443) 経由で
Prisma Accelerate を介して PostgreSQL にアクセスする実装。

設計仕様: docs/superpowers/specs/2026-05-12-prisma-adapter-design.md
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from context_store.config import Settings
from context_store.storage.postgres import _content_hash, _embedding_to_pg
from context_store.storage.protocols import StorageError
from prisma import Prisma  # type: ignore[import-not-found]

if TYPE_CHECKING:
    from context_store.models.memory import Memory

try:
    from prisma.errors import PrismaError
except ImportError:
    PrismaError = Exception  # type: ignore

try:
    from prisma.errors import PrismaClientKnownRequestError  # type: ignore[attr-defined]
except ImportError:
    PrismaClientKnownRequestError = PrismaError  # type: ignore

try:
    from prisma.errors import PrismaClientUnknownRequestError  # type: ignore[attr-defined]
except ImportError:
    PrismaClientUnknownRequestError = PrismaError  # type: ignore

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


class PrismaStorageAdapter:
    """StorageAdapter implementation backed by Prisma Accelerate (HTTPS)."""

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
        return adapter

    async def initialize(self) -> None:
        """Apply schema migrations (既存 postgres/ ディレクトリの SQL を順次実行)."""
        runner = _PrismaMigrationRunner(self._client)
        await runner.run()

    async def dispose(self) -> None:
        """Disconnect the Prisma client."""
        await self._client.disconnect()

    async def save_memory(self, memory: "Memory") -> str:  # type: ignore[name-defined]
        """Persist a memory and return its string ID."""
        embedding_str = _embedding_to_pg(memory.embedding)
        content_hash = _content_hash(memory.content)

        sql = """
            INSERT INTO memories (
                id, content, memory_type, source_type, source_metadata,
                embedding, semantic_relevance, importance_score, access_count,
                last_accessed_at, created_at, updated_at, archived_at,
                tags, project, content_hash
            ) VALUES (
                $1, $2, $3, $4, $5::jsonb,
                $6::vector, $7, $8, $9,
                $10, $11, $12, $13,
                $14, $15, $16
            )
            RETURNING id
        """

        try:
            row = await self._client.query_first_raw(  # type: ignore[attr-defined]
                sql,
                memory.id,
                memory.content,
                memory.memory_type.value,
                memory.source_type.value,
                json.dumps(memory.source_metadata),
                embedding_str,
                memory.semantic_relevance,
                memory.importance_score,
                memory.access_count,
                memory.last_accessed_at,
                memory.created_at,
                memory.updated_at,
                memory.archived_at,
                memory.tags,
                memory.project,
                content_hash,
            )
        except Exception as e:
            if e.__class__.__name__ == "UniqueViolationError":
                raise StorageError(
                    message=str(e),
                    code="DUPLICATE_CONTENT",
                    recoverable=False,
                ) from e
            raise StorageError(
                message=str(e),
                code="STORAGE_ERROR",
                recoverable=False,
            ) from e

        if row is None:
            raise StorageError(
                message="INSERT RETURNING returned no row",
                code="STORAGE_ERROR",
                recoverable=False,
            )
        return str(row["id"])


class _PrismaMigrationRunner:
    """Apply existing postgres/*.sql migrations via prisma.execute_raw."""

    def __init__(self, client: Prisma) -> None:
        self._client = client

    # Prisma バックエンドが処理対象とするマイグレーションのみを許可するファイル名 prefix。
    # 設計書 §2 で graph 機能は Prisma の対象外とされているため、0002_graph.sql 以降の
    # graph 関連マイグレーションは Prisma 経由では適用しない。
    _PRISMA_ALLOWED_MIGRATION_PREFIXES: frozenset[str] = frozenset({"0000", "0001"})

    async def run(self) -> None:
        """Apply pending migrations in order."""
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
        except (
            PrismaClientKnownRequestError,
            PrismaClientUnknownRequestError,
            PrismaError,
        ) as e:
            # We catch specific Prisma errors and check the message to ensure
            # "table not found" errors are handled correctly even in
            # mock-heavy test environments or different client versions.
            msg = str(e).lower()
            if "relation" in msg and "does not exist" in msg:
                logger.info("schema_migrations table not found, applying system migration")
                await self._apply_migration(file_path)
                return
            raise

    async def _get_applied_migrations(self) -> set[str]:
        try:
            rows = await self._client.query_raw("SELECT version FROM schema_migrations")
        except (
            PrismaClientKnownRequestError,
            PrismaClientUnknownRequestError,
            PrismaError,
        ) as e:
            msg = str(e).lower()
            if "relation" in msg and "does not exist" in msg:
                logger.info("schema_migrations table not found, returning empty applied set")
                return set()
            raise
        return {row["version"] for row in rows}

    async def _handle_baseline(
        self,
        files: list[Path],
        applied: set[str],
    ) -> None:
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

        # Prisma Accelerate does not support multiple statements in a single execute_raw call.
        # Split by semicolon and filter out empty or comment-only statements.
        statements = [s.strip() for s in sql.split(";") if s.strip()]

        async with self._client.tx() as tx:
            for stmt in statements:
                # Skip if the statement consists only of comments and whitespace
                if all(
                    line.strip().startswith("--") or not line.strip() for line in stmt.splitlines()
                ):
                    continue
                await tx.execute_raw(stmt)
            await tx.execute_raw("INSERT INTO schema_migrations (version) VALUES ($1)", version)
