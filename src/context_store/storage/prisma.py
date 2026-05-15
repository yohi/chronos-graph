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
from uuid import UUID

import sqlparse

try:
    from prisma import Prisma

    prisma_available = True
except ImportError:
    Prisma = Any  # type: ignore
    prisma_available = False

from context_store.config import Settings
from context_store.storage.postgres_helpers import (
    _content_hash,
    _embedding_to_pg,
    _record_to_memory,
)
from context_store.storage.protocols import ALLOWED_SORT_COLUMNS, MemoryFilters, StorageError

if TYPE_CHECKING:
    from prisma.types import DatasourceOverride

    from context_store.models.memory import Memory, ScoredMemory

logger = logging.getLogger(__name__)

# Prisma does not have a strict batch size limit for ANY($1) like SQLite,
# but we use a reasonable chunk size for consistency and memory safety.
PRISMA_BATCH_FETCH_CHUNK_SIZE = 250
PRISMA_MAX_TOP_K = 200
PRISMA_PAYLOAD_TOO_LARGE_CODES = {"P6009"}
PRISMA_TIMEOUT_CODES = {"P2024", "P2028", "P6004"}


# Placeholder for Prisma-specific error types that tests might expect
class PrismaError(Exception):
    """Base class for Prisma errors."""

    pass


class UniqueViolationError(PrismaError):
    """Raised when a unique constraint is violated."""

    pass


class PrismaStorageAdapter:
    """StorageAdapter implementation backed by Prisma Accelerate (HTTPS)."""

    def __init__(self, client: Prisma) -> None:
        self._client = client

    def _classify_prisma_error(self, exc: Exception) -> tuple[str, bool] | None:
        """Classify Prisma-specific error codes for Accelerate fallbacks."""
        code = getattr(exc, "code", None)
        if code in PRISMA_TIMEOUT_CODES:
            return ("STORAGE_TIMEOUT", True)
        if code in PRISMA_PAYLOAD_TOO_LARGE_CODES:
            return ("STORAGE_PAYLOAD_TOO_LARGE", True)

        exc_str = str(exc).lower()
        if "408" in exc_str or "504" in exc_str or "timeout" in exc_str:
            return ("STORAGE_TIMEOUT", True)

        return None

    def _map_to_storage_error(self, exc: Exception) -> StorageError:
        """Map Prisma/Accelerate exceptions to canonical StorageError."""
        exc_str = str(exc)
        # Handle UniqueViolationError specifically
        if (
            exc.__class__.__name__ == "UniqueViolationError"
            or "unique constraint" in exc_str.lower()
        ):
            return StorageError(message=exc_str, code="DUPLICATE_CONTENT", recoverable=False)

        # Handle other codes
        code = getattr(exc, "code", "")
        if code == "P2002":
            return StorageError(message=exc_str, code="DUPLICATE_CONTENT", recoverable=False)

        # P2010 is Prisma's RawQueryError (syntax error, table not found, etc)
        if code == "P2010" or exc.__class__.__name__ == "RawQueryError":
            return StorageError(message=exc_str, code="STORAGE_ERROR", recoverable=False)

        classified = self._classify_prisma_error(exc)
        if classified is not None:
            err_code, recoverable = classified
            return StorageError(message=exc_str, code=err_code, recoverable=recoverable)

        # Unclassified network/HTTP errors default to recoverable=True
        return StorageError(message=exc_str, code="STORAGE_ERROR", recoverable=True)

    @classmethod
    async def create(cls, settings: Settings) -> "PrismaStorageAdapter":
        """Create and connect the Prisma client."""
        if not prisma_available:
            raise ImportError("Prisma is not installed. Run 'prisma generate' to setup.")

        # Settings から接続文字列を取得して Prisma クライアントに渡す
        db_url = settings.prisma_database_url.get_secret_value()
        datasource: DatasourceOverride | None = {"url": db_url} if db_url else None
        client = Prisma(datasource=datasource)

        await client.connect()
        success = False
        try:
            adapter = cls(client)
            await adapter.initialize()
            success = True
            return adapter
        except Exception:
            raise
        finally:
            if not success and client.is_connected():
                await client.disconnect()

    async def initialize(self) -> None:
        """ストレージの初期化（マイグレーション実行）。"""
        runner = _PrismaMigrationRunner(self._client)
        await runner.run()

    async def dispose(self) -> None:
        """Disconnect the Prisma client."""
        if self._client.is_connected():
            await self._client.disconnect()

    async def save_memory(self, memory: Memory) -> str:
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

        params = [
            str(memory.id),
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
        ]

        try:
            if hasattr(self._client, "query_first_raw"):
                row = await self._client.query_first_raw(sql, *params)
            else:
                rows = await self._client.query_raw(sql, *params)
                row = rows[0] if rows else None

            if row is None:
                raise StorageError(
                    message="INSERT RETURNING returned no row",
                    code="STORAGE_ERROR",
                    recoverable=False,
                )
            return str(row["id"])
        except StorageError:
            raise
        except Exception as e:
            raise self._map_to_storage_error(e) from e

    async def get_memory(self, memory_id: str) -> Memory | None:
        """Retrieve a memory by ID."""
        try:
            norm_id = str(UUID(str(memory_id)))
        except (TypeError, ValueError, AttributeError):
            return None

        sql = "SELECT * FROM memories WHERE id = $1"
        try:
            if hasattr(self._client, "query_first_raw"):
                row = await self._client.query_first_raw(sql, norm_id)
            else:
                rows = await self._client.query_raw(sql, norm_id)
                row = rows[0] if rows else None

            if row is None:
                return None
            return _record_to_memory(row)
        except Exception as exc:
            raise self._map_to_storage_error(exc) from exc

    async def get_memories_batch(self, memory_ids: list[str]) -> list[Memory]:
        """Retrieve multiple memories by ID, preserving input order.

        Accelerate の 5MB 応答上限への対策として、チャンクサイズ
        ``PRISMA_BATCH_FETCH_CHUNK_SIZE`` で分割実行し、
        エラー時はさらに半分に分割してリトライする。
        """
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
            try:
                rows = await self._client.query_raw(sql, chunk)
            except Exception as exc:
                # タイムアウトまたはサイズ上限エラーの場合、チャンクを半分にしてリトライ
                classified = self._classify_prisma_error(exc)
                if classified is None:
                    raise self._map_to_storage_error(exc) from exc

                logger.warning("Accelerate chunk error (%s); retrying with smaller chunks", exc)
                mid = max(1, len(chunk) // 2)
                rows = []
                for sub_chunk in [chunk[:mid], chunk[mid:]]:
                    if not sub_chunk:
                        continue
                    try:
                        sub_rows = await self._client.query_raw(sql, sub_chunk)
                        rows.extend(sub_rows)
                    except Exception as retry_exc:
                        raise self._map_to_storage_error(retry_exc) from retry_exc

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
        """Delete a memory by ID."""
        try:
            str(UUID(str(memory_id)))
        except (TypeError, ValueError, AttributeError) as exc:
            raise StorageError(
                message=f"invalid memory id: {memory_id}",
                code="INVALID_INPUT",
                recoverable=False,
            ) from exc

        sql = "DELETE FROM memories WHERE id = $1"
        try:
            affected = await self._client.execute_raw(sql, memory_id)
        except Exception as exc:
            raise self._map_to_storage_error(exc) from exc
        return int(affected) >= 1

    async def update_memory(self, memory_id: str, updates: dict[str, Any]) -> bool:
        """Update a memory with specific fields."""
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

            # Serialize Enums or other objects with .value
            if hasattr(val, "value"):
                val = val.value

            params.append(val)
            set_parts.append(f"{col} = ${len(params)}")

        if not set_parts:
            return False

        params.append(memory_id)
        # NOTE: Dynamic SQL is used here for UPDATE fields, but it is SAFE from SQL injection
        # because 'set_parts' only contains column names from the 'allowed_columns' whitelist.
        # Values are passed via parameters ($1, $2, etc.).
        sql = f"UPDATE memories SET {', '.join(set_parts)} WHERE id = ${len(params)}"  # noqa: S608 # nosec
        try:
            affected = await self._client.execute_raw(sql, *params)
        except Exception as exc:
            raise self._map_to_storage_error(exc) from exc
        return int(affected) >= 1

    async def increment_memory_access_count(self, memory_id: str) -> bool:
        """Increment the access count and update last_accessed_at."""
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
            raise self._map_to_storage_error(exc) from exc
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

    async def _query_raw_with_retry(
        self,
        sql: str,
        *params: Any,
        top_k_index: int = 1,
    ) -> list[Any]:
        """Execute query_raw with a single retry using halved top_k on classified errors."""
        try:
            return await self._client.query_raw(sql, *params)
        except Exception as exc:
            classified = self._classify_prisma_error(exc)
            if classified is None:
                # 分類不能なエラーはそのまま StorageError に変換して投げる
                raise self._map_to_storage_error(exc) from exc

            # Accelerate 特有のエラー (タイムアウトやペイロード過大) の場合、
            # top_k を半分にして再試行
            top_k = params[top_k_index]
            retry_top_k = max(1, top_k // 2)
            logger.warning("Accelerate error (%s); retrying with top_k=%d", exc, retry_top_k)

            retry_params = list(params)
            retry_params[top_k_index] = retry_top_k

            try:
                return await self._client.query_raw(sql, *retry_params)
            except Exception as retry_exc:
                raise self._map_to_storage_error(retry_exc) from retry_exc

    async def vector_search(
        self,
        embedding: list[float],
        top_k: int,
        project: str | None = None,
    ) -> list[ScoredMemory]:
        from context_store.models.memory import MemorySource, ScoredMemory

        if not embedding:
            return []
        embedding_str = _embedding_to_pg(embedding)

        effective_top_k = self._clamp_top_k(top_k, "vector_search")
        if project is not None:
            sql = (
                "SELECT *, 1 - (embedding <=> $1::vector) AS score "
                "FROM memories "
                "WHERE archived_at IS NULL AND embedding IS NOT NULL AND project = $3 "
                "ORDER BY embedding <=> $1::vector "
                "LIMIT $2"
            )
            rows = await self._query_raw_with_retry(sql, embedding_str, effective_top_k, project)
        else:
            sql = (
                "SELECT *, 1 - (embedding <=> $1::vector) AS score "
                "FROM memories "
                "WHERE archived_at IS NULL AND embedding IS NOT NULL "
                "ORDER BY embedding <=> $1::vector "
                "LIMIT $2"
            )
            rows = await self._query_raw_with_retry(sql, embedding_str, effective_top_k)

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
        # NOTE: We do not escape '%' or '_' in the query intentionally.
        # This allows users to use LIKE wildcards, but may lead to unexpected matches
        # if the input is not sanitized by the caller.
        # See: test_keyword_search_does_not_escape_like_wildcards
        like_query = f"%{query}%"

        if project is not None:
            sql = (
                "SELECT *, 1.0 AS score FROM memories "
                "WHERE archived_at IS NULL AND content LIKE $1 AND project = $3 "
                "LIMIT $2"
            )
            rows = await self._query_raw_with_retry(sql, like_query, effective_top_k, project)
        else:
            sql = (
                "SELECT *, 1.0 AS score FROM memories "
                "WHERE archived_at IS NULL AND content LIKE $1 "
                "LIMIT $2"
            )
            rows = await self._query_raw_with_retry(sql, like_query, effective_top_k)

        return [
            ScoredMemory(
                memory=_record_to_memory(row),
                score=float(row["score"]),
                source=MemorySource.KEYWORD,
            )
            for row in rows
        ]

    def _get_effective_sort(self, filters: MemoryFilters) -> tuple[str, bool]:
        """Determine primary sort column and direction (is_desc) for cursor pagination."""
        # Default is created_at DESC
        sort_col = "created_at"
        is_desc = True

        if filters.order_by:
            # list_by_filter parses the full clause, we just need the primary one for cursor logic
            parts = str(filters.order_by).split(",")[0].strip().split()
            if parts:
                col = parts[0].lower()
                if col in ALLOWED_SORT_COLUMNS:
                    sort_col = col
                if len(parts) > 1 and parts[1].upper() == "ASC":
                    is_desc = False
        return sort_col, is_desc

    def _build_where_clause(self, filters: MemoryFilters) -> tuple[str, list[Any]]:
        conditions: list[str] = []
        params: list[Any] = []

        if filters.archived is True:
            conditions.append("archived_at IS NOT NULL")
        elif filters.archived is None:
            conditions.append("archived_at IS NULL")
        # filters.archived is False means no filter (both active and archived)

        if filters.project is not None:
            params.append(filters.project)
            conditions.append(f"project = ${len(params)}")

        if filters.memory_type is not None:
            params.append(filters.memory_type)
            conditions.append(f"memory_type = ${len(params)}")

        if filters.tags:
            params.append(filters.tags)
            conditions.append(f"tags && ${len(params)}")

        if getattr(filters, "session_id", None) is not None:
            params.append(filters.session_id)
            conditions.append(f"source_metadata->>'session_id' = ${len(params)}")

        if filters.min_importance is not None:
            params.append(filters.min_importance)
            conditions.append(f"importance_score >= ${len(params)}")

        _sort_col, is_desc = self._get_effective_sort(filters)
        op = "<" if is_desc else ">"

        if filters.id_after is not None:
            # Shared id_after parameter for cursor-based pagination
            params.append(filters.id_after)
            id_after_idx = len(params)

            if filters.created_after is not None:
                params.append(filters.created_after)
                conditions.append(f"(created_at, id) {op} (${len(params)}, ${id_after_idx})")
            elif filters.archived_after is not None:
                params.append(filters.archived_after)
                conditions.append(f"(archived_at, id) {op} (${len(params)}, ${id_after_idx})")
            else:
                # Handle id_after alone (ID-only pagination or fallback)
                conditions.append(f"id {op} ${id_after_idx}")
        else:
            if filters.created_after is not None:
                params.append(filters.created_after)
                conditions.append(f"created_at >= ${len(params)}")

            if filters.archived_after is not None:
                params.append(filters.archived_after)
                conditions.append(f"archived_at >= ${len(params)}")

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        return where_clause, params

    async def list_by_filter(self, filters: MemoryFilters) -> list[Memory]:
        """List memories matching the given filters."""
        where_clause, params = self._build_where_clause(filters)

        # Build ORDER BY clause
        order_parts: list[str] = []
        primary_sort_col = "created_at"
        primary_is_desc = True

        if filters.order_by:
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

            # Extract primary sort for cursor consistency check
            if order_parts:
                first_parts = order_parts[0].split()
                primary_sort_col = first_parts[0]
                primary_is_desc = first_parts[1] == "DESC"
        else:
            order_parts.append("created_at DESC")

        # Ensure deterministic ordering by appending id if not present
        if not any(p.split()[0] == "id" for p in order_parts):
            # Use same direction as primary sort for consistency
            direction = "DESC" if primary_is_desc else "ASC"
            order_parts.append(f"id {direction}")

        # Validation: If id_after is used with timestamp-based sort,
        # the first order column must match the cursor type.
        if filters.id_after is not None:
            if filters.created_after is not None and primary_sort_col != "created_at":
                raise StorageError(
                    message="id_after with created_after requires ordering by created_at",
                    code="INVALID_PARAMETER",
                )
            if filters.archived_after is not None and primary_sort_col != "archived_at":
                raise StorageError(
                    message="id_after with archived_after requires ordering by archived_at",
                    code="INVALID_PARAMETER",
                )
            if (
                filters.created_after is None
                and filters.archived_after is None
                and primary_sort_col != "id"
            ):
                # ID-only pagination requires primary sort by ID
                raise StorageError(
                    message="id_after without timestamp requires primary ordering by id",
                    code="INVALID_PARAMETER",
                )

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
                limit_clause = f"LIMIT ${len(params)}"
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
                offset_clause = f"OFFSET ${len(params)}"
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
        try:
            rows = await self._client.query_raw(sql, *params)
        except Exception as exc:
            raise self._map_to_storage_error(exc) from exc
        return [_record_to_memory(row) for row in rows]

    async def count_by_filter(self, filters: MemoryFilters) -> int:
        """Count memories matching the given filters."""
        where_clause, params = self._build_where_clause(filters)
        sql = " ".join(
            part for part in ["SELECT COUNT(*) AS count", "FROM memories", where_clause] if part
        ).strip()
        try:
            if hasattr(self._client, "query_first_raw"):
                row = await self._client.query_first_raw(sql, *params)
            else:
                rows = await self._client.query_raw(sql, *params)
                row = rows[0] if rows else None
        except Exception as exc:
            raise self._map_to_storage_error(exc) from exc
        if row is None:
            return 0
        return int(row.get("count", 0) or 0)

    async def list_projects(self) -> list[str]:
        """List all unique project names present in the storage."""
        sql = "SELECT DISTINCT project FROM memories WHERE project IS NOT NULL AND project != ''"
        try:
            rows = await self._client.query_raw(sql)
        except Exception as exc:
            raise self._map_to_storage_error(exc) from exc
        return [str(row["project"]) for row in rows]

    async def get_vector_dimension(self) -> int | None:
        """Return the dimension of stored vectors."""
        sql = (
            "SELECT vector_dims(embedding) AS vector_dims "
            "FROM memories WHERE embedding IS NOT NULL LIMIT 1"
        )
        try:
            if hasattr(self._client, "query_first_raw"):
                row = await self._client.query_first_raw(sql)
            else:
                rows = await self._client.query_raw(sql)
                row = rows[0] if rows else None
        except Exception as exc:
            raise self._map_to_storage_error(exc) from exc
        if row is None or row.get("vector_dims") is None:
            return None
        return int(row["vector_dims"])


class _PrismaMigrationRunner:
    """Prisma 用の簡易マイグレーションランナー。"""

    # Prisma backend manages only the storage schema required by the memories table.
    # Graph-related tables (memory_nodes/edges) are excluded from Prisma management.
    _PRISMA_EXCLUDED_KEYWORDS: frozenset[str] = frozenset({"graph"})

    def __init__(self, client: Prisma) -> None:
        self._client = client

    async def run(self) -> None:
        """Apply migrations from migrations/postgres SQL files."""
        # migrations は src/context_store/storage/migrations/postgres にある
        migrations_path = Path(__file__).parent / "migrations" / "postgres"

        if not migrations_path.exists():
            logger.warning("Migrations directory '%s' not found.", migrations_path)
            return

        all_files = sorted(migrations_path.glob("*.sql"))
        target_files = []
        for f in all_files:
            # Check if description (after numeric prefix) starts with an excluded keyword.
            # This prevents accidental exclusion of files containing keywords elsewhere.
            name_parts = f.name.lower().split("_", 1)
            desc = name_parts[1] if len(name_parts) > 1 else name_parts[0]

            if any(desc.startswith(kw) for kw in self._PRISMA_EXCLUDED_KEYWORDS):
                logger.info("Skipping migration file '%s' (excluded by keyword prefix)", f.name)
                continue
            target_files.append(f)

        system_file = migrations_path / "0000_system.sql"
        if system_file.exists():
            await self._ensure_system_migration(system_file)
        applied = await self._get_applied_migrations()

        if "0001_initial.sql" not in applied:
            if await self._tables_exist(["memories"]):
                logger.info("Found existing 'memories' table. Baselining 0001_initial.sql")
                await self._mark_as_applied("0001_initial.sql")
                applied.add("0001_initial.sql")

        for sql_file in target_files:
            if sql_file.name in applied:
                continue

            logger.info(f"Applying migration: {sql_file.name}")
            await self._apply_migration(sql_file)

    def _is_missing_table_error(self, exc: Exception) -> bool:
        """Check if the exception indicates a missing table."""
        exc_str = str(exc).lower()
        # P2010/P2021 are Prisma's codes for "Raw query failed" / "Table does not exist".
        # 42P01: undefined_table (PostgreSQL error code)
        if "relation" in exc_str and "does not exist" in exc_str:
            return True
        if "p2010" in exc_str or "p2021" in exc_str or "42p01" in exc_str:
            return True
        return False

    async def _ensure_system_migration(self, sql_file: Path) -> None:
        """Ensure the schema_migrations table exists."""
        try:
            await self._client.query_raw("SELECT 1 FROM schema_migrations LIMIT 1")
            return
        except Exception as exc:
            if not self._is_missing_table_error(exc):
                logger.error("Unexpected error checking schema_migrations table: %s", exc)
                raise
            logger.debug("schema_migrations table missing, will apply system migration.")

        logger.info("Applying system migration: %s", sql_file.name)
        await self._apply_migration(sql_file)

    async def _get_applied_migrations(self) -> set[str]:
        """Get the set of applied migration versions."""
        sql = "SELECT version FROM schema_migrations"
        try:
            rows = await self._client.query_raw(sql)
            return {row["version"] for row in rows}
        except Exception as exc:
            if self._is_missing_table_error(exc):
                return set()

            logger.exception("Failed to fetch applied migrations from schema_migrations table")
            raise

    async def _tables_exist(self, tables: list[str]) -> bool:
        """Check if specified tables exist in the database."""
        sql = (
            "SELECT tablename FROM pg_catalog.pg_tables "
            "WHERE tablename = ANY($1) AND schemaname = ANY(current_schemas(true))"
        )
        try:
            rows = await self._client.query_raw(sql, tables)
            return len(rows) >= len(tables)
        except Exception as exc:
            if self._is_missing_table_error(exc):
                return False
            raise

    async def _mark_as_applied(self, version: str) -> None:
        """Mark a migration version as applied without executing it."""
        await self._client.execute_raw(
            "INSERT INTO schema_migrations (version) VALUES ($1) ON CONFLICT DO NOTHING", version
        )

    async def _apply_migration(self, sql_file: Path) -> None:
        """Apply one SQL migration file and record its version."""
        content = sql_file.read_text()
        statements = [s.strip().rstrip(";") for s in sqlparse.split(content) if s.strip()]

        async with self._client.tx() as tx:
            for stmt in statements:
                if stmt:
                    await tx.execute_raw(stmt)
            await tx.execute_raw(
                "INSERT INTO schema_migrations (version) VALUES ($1)", sql_file.name
            )
