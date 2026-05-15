from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

from context_store.config import Settings
from context_store.storage.postgres import (
    _content_hash,
    _embedding_to_pg,
    _record_to_memory,
)
from context_store.storage.protocols import StorageError

try:
    from prisma import Prisma  # type: ignore[import-not-found, attr-defined]

    prisma_available = True
except ImportError:
    Prisma = Any  # type: ignore
    prisma_available = False

if TYPE_CHECKING:
    from context_store.models.memory import Memory

try:
    from prisma.errors import PrismaError
except ImportError:

    class PrismaError(Exception):  # type: ignore[no-redef]
        pass


try:
    from prisma.errors import DataError, UniqueViolationError  # type: ignore
except ImportError:

    class DataError(PrismaError):  # type: ignore[no-redef]
        pass

    class UniqueViolationError(DataError):  # type: ignore[no-redef]
        pass


try:
    from prisma.errors import PrismaClientKnownRequestError  # type: ignore
except ImportError:

    class PrismaClientKnownRequestError(PrismaError):  # type: ignore[no-redef]
        pass


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
        if not prisma_available:
            raise ImportError(
                "Prisma is not installed. Please install 'prisma' package "
                "to use PrismaStorageAdapter."
            )
        url = settings.prisma_database_url.get_secret_value().strip()
        client = Prisma(
            datasource={"url": url},
        )
        adapter = cls(client)
        await client.connect()
        await adapter.initialize()
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
        try:
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
        except PrismaError as e:
            # P2002: Unique constraint failed.
            # We check both the specific UniqueViolationError and the error code "P2002"
            # (common in PrismaClientKnownRequestError) for robust mapping.
            is_unique_violation = getattr(e, "code", None) == "P2002" or isinstance(
                e, (UniqueViolationError, PrismaClientKnownRequestError)
            )
            if is_unique_violation:
                raise StorageError(
                    message=str(e),
                    code="DUPLICATE_CONTENT",
                    recoverable=False,
                ) from e
            # Other Prisma related errors
            raise StorageError(
                message=str(e),
                code="STORAGE_ERROR",
                recoverable=False,
            ) from e
        except Exception as e:
            if isinstance(e, StorageError):
                raise
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

    async def get_memory(self, memory_id: str) -> "Memory | None":  # type: ignore[name-defined]
        """Retrieve a memory by ID."""
        try:
            UUID(str(memory_id))
        except (TypeError, ValueError, AttributeError):
            return None

        sql = "SELECT * FROM memories WHERE id = $1"
        try:
            row = await self._client.query_first_raw(sql, memory_id)  # type: ignore[attr-defined]
        except Exception as exc:
            raise StorageError(message=str(exc), code="STORAGE_ERROR", recoverable=False) from exc
        if row is None:
            return None
        return _record_to_memory(row)

    async def get_memories_batch(self, memory_ids: list[str]) -> "list[Memory]":  # type: ignore[name-defined]
        """Retrieve multiple memories by ID, preserving input order.

        Accelerate の 5MB 応答上限への対策として、チャンクサイズ
        ``PRISMA_BATCH_FETCH_CHUNK_SIZE`` で分割実行する。
        """

        if not memory_ids:
            return []

        # 重複を除去しつつ、有効な UUID のみを抽出
        unique_cleaned: dict[str, None] = {}
        for memory_id in memory_ids:
            try:
                norm_id = str(UUID(str(memory_id)))
                unique_cleaned[norm_id] = None
            except (TypeError, ValueError, AttributeError):
                continue

        if not unique_cleaned:
            return []

        cleaned = list(unique_cleaned.keys())
        sql = "SELECT * FROM memories WHERE id = ANY($1::uuid[])"
        memory_map: dict[str, Any] = {}
        for offset in range(0, len(cleaned), PRISMA_BATCH_FETCH_CHUNK_SIZE):
            chunk = cleaned[offset : offset + PRISMA_BATCH_FETCH_CHUNK_SIZE]
            try:
                rows = await self._client.query_raw(sql, chunk)
            except Exception as exc:
                raise StorageError(
                    message=str(exc), code="STORAGE_ERROR", recoverable=False
                ) from exc
            for row in rows:
                memory_map[str(row["id"])] = _record_to_memory(row)

        results = []
        for memory_id in memory_ids:
            try:
                norm_id = str(UUID(str(memory_id)))
            except (TypeError, ValueError, AttributeError):
                continue
            memory = memory_map.get(norm_id)
            if memory is not None:
                results.append(memory)
        return results

    async def delete_memory(self, memory_id: str) -> bool:
        sql = "DELETE FROM memories WHERE id = $1"
        try:
            affected = await self._client.execute_raw(sql, memory_id)
        except Exception as exc:
            raise StorageError(message=str(exc), code="STORAGE_ERROR", recoverable=False) from exc
        return int(affected) >= 1

    async def update_memory(self, memory_id: str, updates: dict[str, Any]) -> bool:
        if not updates:
            return False

        allowed_columns = {
            "content",
            "memory_type",
            "source_type",
            "source_metadata",
            "embedding",
            "semantic_relevance",
            "importance_score",
            "access_count",
            "last_accessed_at",
            "updated_at",
            "archived_at",
            "tags",
            "project",
        }
        set_parts: list[str] = []
        params: list[Any] = []
        for col, val in updates.items():
            if col not in allowed_columns:
                continue
            if col == "content":
                params.append(val)
                set_parts.append(f"{col} = ${len(params)}")
                params.append(_content_hash(str(val)))
                set_parts.append(f"content_hash = ${len(params)}")
                continue
            if col == "embedding":
                val = _embedding_to_pg(val) if isinstance(val, list) else val
                params.append(val)
                set_parts.append(f"{col} = ${len(params)}::vector")
                continue
            if col == "source_metadata" and isinstance(val, dict):
                val = json.dumps(val)
                params.append(val)
                set_parts.append(f"{col} = ${len(params)}::jsonb")
                continue
            params.append(val)
            set_parts.append(f"{col} = ${len(params)}")

        if not set_parts:
            return False

        params.append(memory_id)
        sql = " ".join(
            [
                "UPDATE memories",
                f"SET {', '.join(set_parts)}",
                f"WHERE id = ${len(params)}",
            ]
        )
        try:
            affected = await self._client.execute_raw(sql, *params)
        except Exception as exc:
            raise StorageError(message=str(exc), code="STORAGE_ERROR", recoverable=False) from exc
        return int(affected) >= 1

    async def increment_memory_access_count(self, memory_id: str) -> bool:
        sql = (
            "UPDATE memories "
            "SET access_count = access_count + 1, "
            "    last_accessed_at = NOW(), "
            "    updated_at = NOW() "
            "WHERE id = $1"
        )
        try:
            affected = await self._client.execute_raw(sql, memory_id)
        except Exception as exc:
            raise StorageError(message=str(exc), code="STORAGE_ERROR", recoverable=False) from exc
        return int(affected) >= 1

    async def list_memories(
        self,
        filter_dict: dict[str, Any] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Memory]:
        """List memories with basic filtering and pagination."""
        params: list[Any] = []
        where_clauses: list[str] = []

        if filter_dict:
            for col, val in filter_dict.items():
                params.append(val)
                where_clauses.append(f"{col} = ${len(params)}")

        where_sql = ""
        if where_clauses:
            where_sql = f"WHERE {' AND '.join(where_clauses)}"

        params.append(limit)
        limit_idx = len(params)
        params.append(offset)
        offset_idx = len(params)

        sql = f"SELECT * FROM memories {where_sql} LIMIT ${limit_idx} OFFSET ${offset_idx}"

        try:
            rows = await self._client.query_raw(sql, *params)
        except Exception as exc:
            raise StorageError(message=str(exc), code="STORAGE_ERROR", recoverable=False) from exc

        return [_record_to_memory(row) for row in rows]


class _PrismaMigrationRunner:
    """Prisma 用の簡易マイグレーションランナー。

    Prisma 自身には execute_raw で複数ステートメントを一括実行する機能がないため、
    ステートメントを分割して逐次実行する。
    """

    # Prisma バックエンドが処理対象とするマイグレーションのみを許可するファイル名 prefix。
    # 設計書 §2 で graph 機能は Prisma の対象外とされているため、0002_graph.sql 以降の
    # graph 関連マイグレーションは Prisma 経由では適用しない。
    _PRISMA_ALLOWED_MIGRATION_PREFIXES: frozenset[str] = frozenset({"0000", "0001"})

    def __init__(self, client: Prisma) -> None:
        self._client = client

    async def run(self) -> None:
        """SQL ファイルを順次実行し、schema_migrations テーブルで状態を管理する。

        実装方針:
        - postgres/ ディレクトリ의 SQL ファイルを `pathlib.Path` で列挙
        - `_PRISMA_ALLOWED_MIGRATION_PREFIXES` に含まれる prefix のもののみを対象とする
          (graph 関連の 0002* 等は Prisma バックエンドの対象外、設計書 §2)
        - `schema_migrations` テーブル存在チェックは `query_raw`
        - 適用済みバージョン取得は `query_raw`
        - 未適用ファイルを sequential に `execute_raw` で適用
        - `pg_catalog.pg_tables` を用いた baseline 検出は既存 MigrationRunner と同等
        """
        # docker/postgres ディレクトリを現在のファイルから遡って探索する
        curr = Path(__file__).resolve().parent
        migrations_path = None
        for _ in range(5):
            candidate = curr / "docker" / "postgres"
            if candidate.exists():
                migrations_path = candidate
                break
            curr = curr.parent

        if not migrations_path:
            logger.warning("Migrations directory 'docker/postgres' not found in parent hierarchy.")
            return

        sql_files = sorted(migrations_path.glob("*.sql"))
        target_files = [
            f
            for f in sql_files
            if f.name[:4] in self._PRISMA_ALLOWED_MIGRATION_PREFIXES
        ]

        await self._ensure_system_migration()
        applied = await self._get_applied_migrations()

        # baseline 検出 (memories テーブルが既に存在する場合、0001 を適用済みとみなす)
        if "0001_initial.sql" not in applied:
            if await self._tables_exist(["memories"]):
                logger.info("Found existing 'memories' table. Baselining 0001_initial.sql")
                await self._mark_as_applied("0001_initial.sql")
                applied.add("0001_initial.sql")

        for sql_file in target_files:
            if sql_file.name in applied:
                continue

            logger.info(f"Applying migration: {sql_file.name}")
            content = sql_file.read_text()
            # Prisma does not support multiple statements in one execute_raw.
            # We split by ';' and execute each, but this is naive and might fail for complex SQL.
            # Migration files are expected to be simple.
            statements = [s.strip() for s in content.split(";") if s.strip()]

            async with self._client.tx() as tx:
                for stmt in statements:
                    await tx.execute_raw(stmt)
                # 適用済みとして記録
                await tx.execute_raw(
                    "INSERT INTO schema_migrations (version) VALUES ($1)", sql_file.name
                )

    async def _ensure_system_migration(self) -> None:
        """schema_migrations テーブルの存在を保証する。"""
        sql = (
            "SELECT 1 FROM pg_catalog.pg_tables "
            "WHERE tablename = 'schema_migrations'"
        )
        try:
            res = await self._client.query_raw(sql)
            if res:
                return
        except Exception:
            pass

        logger.info("Creating schema_migrations table")
        await self._client.execute_raw(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ DEFAULT NOW())"
        )

    async def _get_applied_migrations(self) -> set[str]:
        sql = "SELECT version FROM schema_migrations"
        try:
            rows = await self._client.query_raw(sql)
            return {row["version"] for row in rows}
        except Exception:
            return set()

    async def _tables_exist(self, tables: list[str]) -> bool:
        sql = "SELECT tablename FROM pg_catalog.pg_tables WHERE tablename = ANY($1)"
        rows = await self._client.query_raw(sql, tables)
        return len(rows) >= len(tables)

    async def _mark_as_applied(self, version: str) -> None:
        await self._client.execute_raw(
            "INSERT INTO schema_migrations (version) VALUES ($1)", version
        )
