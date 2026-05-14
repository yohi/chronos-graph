"""Prisma Accelerate-backed Storage Adapter.

社内ネットワークでの PostgreSQL 直接接続遮断を回避するため、HTTPS (443) 経由で
Prisma Accelerate を介して PostgreSQL にアクセスする実装。

設計仕様: docs/superpowers/specs/2026-05-12-prisma-adapter-design.md
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from context_store.config import Settings
from context_store.storage.postgres import (
    _content_hash,
    _embedding_to_pg,
    _record_to_memory,
)
from context_store.storage.protocols import ALLOWED_SORT_COLUMNS, MemoryFilters, StorageError
from prisma import Prisma  # type: ignore[import-not-found]

if TYPE_CHECKING:
    from context_store.models.memory import Memory, ScoredMemory

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
            row = await self._client.query_first_raw(
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
            # Handle UniqueViolationError without the mapper yet
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

    async def get_memory(self, memory_id: str) -> Memory | None:
        """Retrieve a memory by ID."""
        sql = "SELECT * FROM memories WHERE id = $1"
        row = await self._client.query_first_raw(sql, memory_id)
        if row is None:
            return None
        return _record_to_memory(row)

    async def get_memories_batch(self, memory_ids: list[str]) -> list[Memory]:
        """Retrieve multiple memories by ID, preserving input order.

        Accelerate の 5MB 応答上限への対策として、チャンクサイズ
        ``PRISMA_BATCH_FETCH_CHUNK_SIZE`` で分割実行する。
        """
        from uuid import UUID

        if not memory_ids:
            return []

        cleaned: list[str] = []
        for memory_id in memory_ids:
            try:
                cleaned.append(str(UUID(str(memory_id))))
            except (TypeError, ValueError, AttributeError):
                continue
        if not cleaned:
            return []

        sql = "SELECT * FROM memories WHERE id = ANY($1::uuid[])"
        memory_map: dict[str, Any] = {}
        for offset in range(0, len(cleaned), PRISMA_BATCH_FETCH_CHUNK_SIZE):
            chunk = cleaned[offset : offset + PRISMA_BATCH_FETCH_CHUNK_SIZE]
            rows = await self._client.query_raw(sql, chunk)
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
        affected = await self._client.execute_raw(sql, memory_id)
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
        affected = await self._client.execute_raw(sql, *params)
        return int(affected) >= 1

    async def increment_memory_access_count(self, memory_id: str) -> bool:
        sql = (
            "UPDATE memories "
            "SET access_count = access_count + 1, "
            "    last_accessed_at = NOW(), "
            "    updated_at = NOW() "
            "WHERE id = $1"
        )
        affected = await self._client.execute_raw(sql, memory_id)
        return int(affected) >= 1

    def _clamp_top_k(self, top_k: int, method_name: str) -> int:
        if top_k <= 0:
            raise StorageError(
                message=f"top_k must be >= 1 (got {top_k})",
                code="INVALID_PARAMETER",
                recoverable=False,
            )
        if top_k > PRISMA_MAX_TOP_K:
            logger.warning(
                "%s: top_k clamped %d -> %d (PRISMA_MAX_TOP_K)",
                method_name,
                top_k,
                PRISMA_MAX_TOP_K,
            )
            return PRISMA_MAX_TOP_K
        return top_k

    async def vector_search(
        self,
        embedding: list[float],
        top_k: int,
        project: str | None = None,
    ) -> list[ScoredMemory]:
        from context_store.models.memory import MemorySource, ScoredMemory

        embedding_str = _embedding_to_pg(embedding)
        if embedding_str is None:
            return []

        effective_top_k = self._clamp_top_k(top_k, "vector_search")
        if project is not None:
            sql = (
                "SELECT *, 1 - (embedding <=> $1::vector) AS score "
                "FROM memories "
                "WHERE archived_at IS NULL AND embedding IS NOT NULL AND project = $3 "
                "ORDER BY embedding <=> $1::vector "
                "LIMIT $2"
            )
            rows = await self._client.query_raw(sql, embedding_str, effective_top_k, project)
        else:
            sql = (
                "SELECT *, 1 - (embedding <=> $1::vector) AS score "
                "FROM memories "
                "WHERE archived_at IS NULL AND embedding IS NOT NULL "
                "ORDER BY embedding <=> $1::vector "
                "LIMIT $2"
            )
            rows = await self._client.query_raw(sql, embedding_str, effective_top_k)

        return [
            ScoredMemory(
                memory=_record_to_memory(row),
                score=float(row["score"]),
                source=MemorySource.VECTOR,
            )
            for row in rows
        ]

    async def keyword_search(
        self,
        query: str,
        top_k: int,
        project: str | None = None,
    ) -> list[ScoredMemory]:
        from context_store.models.memory import MemorySource, ScoredMemory

        effective_top_k = self._clamp_top_k(top_k, "keyword_search")
        like_query = f"%{query}%"

        if project is not None:
            sql = (
                "SELECT *, 1.0 AS score FROM memories "
                "WHERE archived_at IS NULL AND content LIKE $1 AND project = $3 "
                "LIMIT $2"
            )
            rows = await self._client.query_raw(sql, like_query, effective_top_k, project)
        else:
            sql = (
                "SELECT *, 1.0 AS score FROM memories "
                "WHERE archived_at IS NULL AND content LIKE $1 "
                "LIMIT $2"
            )
            rows = await self._client.query_raw(sql, like_query, effective_top_k)

        return [
            ScoredMemory(
                memory=_record_to_memory(row),
                score=float(row["score"]),
                source=MemorySource.KEYWORD,
            )
            for row in rows
        ]

    def _build_where_clause(self, filters: MemoryFilters) -> tuple[str, list[Any]]:
        conditions: list[str] = []
        params: list[Any] = []

        if filters.archived is None:
            conditions.append("archived_at IS NULL")
        elif filters.archived is True:
            conditions.append("archived_at IS NOT NULL")

        if filters.project is not None:
            params.append(filters.project)
            conditions.append(f"project = \${len(params)}")

        if filters.memory_type is not None:
            params.append(filters.memory_type)
            conditions.append(f"memory_type = \${len(params)}")

        if filters.tags:
            params.append(filters.tags)
            conditions.append(f"tags && \${len(params)}")

        if getattr(filters, "session_id", None) is not None:
            params.append(filters.session_id)
            conditions.append(f"source_metadata->>'session_id' = \${len(params)}")

        if filters.min_importance is not None:
            params.append(filters.min_importance)
            conditions.append(f"importance_score >= \${len(params)}")

        if filters.created_after is not None:
            if filters.id_after is not None:
                params.append(filters.created_after)
                params.append(filters.id_after)
                conditions.append(f"(created_at, id) > (\${len(params) - 1}, \${len(params)})")
            else:
                params.append(filters.created_after)
                conditions.append(f"created_at >= \${len(params)}")

        if filters.archived_after is not None:
            if filters.id_after is not None:
                params.append(filters.archived_after)
                params.append(filters.id_after)
                conditions.append(f"(archived_at, id) > (\${len(params) - 1}, \${len(params)})")
            else:
                params.append(filters.archived_after)
                conditions.append(f"archived_at >= \${len(params)}")

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        return where_clause, params

    async def list_by_filter(self, filters: MemoryFilters) -> list[Memory]:
        where_clause, params = self._build_where_clause(filters)

        order_clause = "ORDER BY created_at DESC"
        if filters.order_by:
            order_parts: list[str] = []
            for part in str(filters.order_by).split(","):
                tokens = part.strip().split()
                if not tokens:
                    continue
                col = tokens[0].lower()
                if col not in ALLOWED_SORT_COLUMNS:
                    raise StorageError(
                        message=f"Invalid sort column: {col}",
                        code="INVALID_PARAMETER",
                    )
                direction = "DESC"
                if len(tokens) > 1:
                    dir_token = tokens[1].upper()
                    if dir_token not in ("ASC", "DESC"):
                        raise StorageError(
                            message=f"Invalid sort direction: {dir_token}",
                            code="INVALID_PARAMETER",
                        )
                    direction = dir_token
                order_parts.append(f"{col} {direction}")
            if order_parts:
                order_clause = f"ORDER BY {', '.join(order_parts)}"

        limit_clause = ""
        if filters.limit is not None:
            try:
                limit_int = int(filters.limit)
                if limit_int < 0:
                    raise StorageError(
                        message=f"Invalid limit value: {limit_int}",
                        code="INVALID_PARAMETER",
                    )
                params.append(limit_int)
                limit_clause = f"LIMIT \${len(params)}"
            except (ValueError, TypeError) as e:
                raise StorageError(
                    message=f"Invalid limit type: {type(filters.limit)}",
                    code="INVALID_PARAMETER",
                ) from e

        offset_clause = ""
        if filters.offset is not None:
            try:
                offset_int = int(filters.offset)
                if offset_int < 0:
                    raise StorageError(
                        message=f"Invalid offset value: {offset_int}",
                        code="INVALID_PARAMETER",
                    )
                params.append(offset_int)
                offset_clause = f"OFFSET \${len(params)}"
            except (ValueError, TypeError) as e:
                raise StorageError(
                    message=f"Invalid offset type: {type(filters.offset)}",
                    code="INVALID_PARAMETER",
                ) from e

        sql = " ".join(
            part
            for part in [
                "SELECT * FROM memories",
                where_clause,
                order_clause,
                limit_clause,
                offset_clause,
            ]
            if part
        ).strip()
        rows = await self._client.query_raw(sql, *params)
        return [_record_to_memory(row) for row in rows]

    async def count_by_filter(self, filters: MemoryFilters) -> int:
        where_clause, params = self._build_where_clause(filters)
        sql = " ".join(
            part for part in ["SELECT COUNT(*) AS count", "FROM memories", where_clause] if part
        ).strip()
        row = await self._client.query_first_raw(sql, *params)
        if row is None:
            return 0
        return int(row.get("count", 0) or 0)

    async def list_projects(self) -> list[str]:
        sql = "SELECT DISTINCT project FROM memories WHERE project IS NOT NULL AND project != ''"
        rows = await self._client.query_raw(sql)
        return [str(row["project"]) for row in rows]

    async def get_vector_dimension(self) -> int | None:
        sql = (
            "SELECT vector_dims(embedding) AS vector_dims "
            "FROM memories WHERE embedding IS NOT NULL LIMIT 1"
        )
        row = await self._client.query_first_raw(sql)
        if row is None or row.get("vector_dims") is None:
            return None
        return int(row["vector_dims"])


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
        from pathlib import Path

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

    async def _ensure_system_migration(self, file_path: "Path") -> None:  # type: ignore[name-defined]
        try:
            await self._client.query_raw("SELECT 1 FROM schema_migrations LIMIT 1")
            return
        except Exception:
            logger.debug("schema_migrations table not found, applying system migration")
            pass
        await self._apply_migration(file_path)

    async def _get_applied_migrations(self) -> set[str]:
        try:
            rows = await self._client.query_raw("SELECT version FROM schema_migrations")
        except Exception:
            return set()
        return {row["version"] for row in rows}

    async def _handle_baseline(
        self,
        files: list["Path"],
        applied: set[str],  # type: ignore[name-defined]
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

    async def _apply_migration(self, file_path: "Path") -> None:  # type: ignore[name-defined]
        sql = file_path.read_text()
        version = file_path.name
        async with self._client.tx() as tx:
            await tx.execute_raw(sql)
            await tx.execute_raw("INSERT INTO schema_migrations (version) VALUES ($1)", version)
