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
from context_store.storage.protocols import ALLOWED_SORT_COLUMNS, MemoryFilters, StorageError

if TYPE_CHECKING:
    from context_store.models.memory import Memory, ScoredMemory

logger = logging.getLogger(__name__)

# Prisma does not have a strict batch size limit for ANY($1) like SQLite,
# but we use a reasonable chunk size for consistency and memory safety.
PRISMA_BATCH_FETCH_CHUNK_SIZE = 250
PRISMA_MAX_TOP_K = 200
PRISMA_PAYLOAD_TOO_LARGE_CODES = {"P2010", "P2021", "P6009"}
PRISMA_TIMEOUT_CODES = {"P2024", "P2025", "P2028", "P6004"}


# Placeholder for Prisma-specific error types that tests might expect
class PrismaError(Exception):
    """Base class for Prisma errors."""

    pass


class UniqueViolationError(PrismaError):
    """Raised when a unique constraint is violated."""

    pass


def _record_to_memory(row: dict[str, Any]) -> Memory:
    """Prisma の dict 形式のレコードを Memory モデルに変換する。"""
    from context_store.models.memory import Memory

    # content_hash は内部用なので除外。embedding は保持し、必要ならパースする。
    data = {k: v for k, v in row.items() if k != "content_hash"}

    # embedding の変換 (str "[0.1, 0.2]" -> list[float])
    emb = data.get("embedding")
    if isinstance(emb, str):
        try:
            data["embedding"] = [float(x) for x in emb.strip("[]").split(",") if x.strip()]
        except (ValueError, TypeError):
            data["embedding"] = []
    elif emb is None:
        data["embedding"] = []

    if isinstance(data.get("source_metadata"), str):
        try:
            data["source_metadata"] = json.loads(data["source_metadata"])
        except json.JSONDecodeError:
            pass
    return Memory(**data)


def _content_hash(content: str) -> str:
    """content のハッシュ値を生成する"""
    import hashlib

    return hashlib.sha256(content.encode()).hexdigest()


def _embedding_to_pg(embedding: list[float]) -> str:
    """list[float] を PostgreSQL の vector 形式文字列 '[1,2,3]' に変換する。"""
    return "[" + ",".join(map(str, embedding)) + "]"


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

        classified = self._classify_prisma_error(exc)
        if classified is not None:
            err_code, recoverable = classified
            return StorageError(message=exc_str, code=err_code, recoverable=recoverable)

        return StorageError(message=exc_str, code="STORAGE_ERROR", recoverable=False)

    @classmethod
    async def create(cls, settings: Settings) -> "PrismaStorageAdapter":
        """Create and connect the Prisma client."""
        if not prisma_available:
            raise ImportError("Prisma is not installed. Run 'prisma generate' to setup.")
        client = Prisma()
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
        except Exception as e:
            raise self._map_to_storage_error(e) from e

    async def get_memory(self, memory_id: str) -> Memory | None:
        """Retrieve a memory by ID."""
        try:
            str(UUID(str(memory_id)))
        except (TypeError, ValueError, AttributeError):
            return None

        sql = "SELECT * FROM memories WHERE id = $1"
        try:
            if hasattr(self._client, "query_first_raw"):
                row = await self._client.query_first_raw(sql, memory_id)
            else:
                rows = await self._client.query_raw(sql, memory_id)
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
            params.append(val)
            set_parts.append(f"{col} = ${len(params)}")

        if not set_parts:
            return False

        params.append(memory_id)
        # noqa: S608 (columns are whitelisted above)
        sql = f"UPDATE memories SET {', '.join(set_parts)} WHERE id = ${len(params)}"  # noqa: S608
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
            try:
                rows = await self._client.query_raw(sql, embedding_str, effective_top_k, project)
            except Exception as exc:
                classified = self._classify_prisma_error(exc)
                if classified is None:
                    raise self._map_to_storage_error(exc) from exc
                retry_top_k = max(1, effective_top_k // 2)
                try:
                    rows = await self._client.query_raw(sql, embedding_str, retry_top_k, project)
                except Exception as retry_exc:
                    raise self._map_to_storage_error(retry_exc) from retry_exc
        else:
            sql = (
                "SELECT *, 1 - (embedding <=> $1::vector) AS score "
                "FROM memories "
                "WHERE archived_at IS NULL AND embedding IS NOT NULL "
                "ORDER BY embedding <=> $1::vector "
                "LIMIT $2"
            )
            try:
                rows = await self._client.query_raw(sql, embedding_str, effective_top_k)
            except Exception as exc:
                classified = self._classify_prisma_error(exc)
                if classified is None:
                    raise self._map_to_storage_error(exc) from exc
                retry_top_k = max(1, effective_top_k // 2)
                try:
                    rows = await self._client.query_raw(sql, embedding_str, retry_top_k)
                except Exception as retry_exc:
                    raise self._map_to_storage_error(retry_exc) from retry_exc

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

        if not query or not query.strip():
            return []

        effective_top_k = self._clamp_top_k(top_k, "keyword_search")
        # SQL LIKE wildcards: escape backslashes first, then % and _
        escaped_query = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like_query = f"%{escaped_query}%"

        if project is not None:
            sql = (
                "SELECT *, bigm_similarity(content, $4) AS score FROM memories "
                "WHERE archived_at IS NULL AND content LIKE $1 ESCAPE '\\' AND project = $3 "
                "ORDER BY score DESC "
                "LIMIT $2"
            )
            try:
                rows = await self._client.query_raw(
                    sql, like_query, effective_top_k, project, query
                )
            except Exception as exc:
                classified = self._classify_prisma_error(exc)
                if classified is None:
                    raise self._map_to_storage_error(exc) from exc
                retry_top_k = max(1, effective_top_k // 2)
                try:
                    rows = await self._client.query_raw(
                        sql, like_query, retry_top_k, project, query
                    )
                except Exception as retry_exc:
                    raise self._map_to_storage_error(retry_exc) from retry_exc
        else:
            sql = (
                "SELECT *, bigm_similarity(content, $3) AS score FROM memories "
                "WHERE archived_at IS NULL AND content LIKE $1 ESCAPE '\\' "
                "ORDER BY score DESC "
                "LIMIT $2"
            )
            try:
                rows = await self._client.query_raw(sql, like_query, effective_top_k, query)
            except Exception as exc:
                classified = self._classify_prisma_error(exc)
                if classified is None:
                    raise self._map_to_storage_error(exc) from exc
                retry_top_k = max(1, effective_top_k // 2)
                try:
                    rows = await self._client.query_raw(sql, like_query, retry_top_k, query)
                except Exception as retry_exc:
                    raise self._map_to_storage_error(retry_exc) from retry_exc

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

        if filters.archived is False:
            conditions.append("archived_at IS NULL")
        elif filters.archived is True:
            conditions.append("archived_at IS NOT NULL")
        # filters.archived is None means no filter on archived status

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

        if filters.id_after is not None:
            # Shared id_after parameter for cursor-based pagination
            params.append(filters.id_after)
            id_after_idx = len(params)

            if filters.created_after is not None:
                params.append(filters.created_after)
                conditions.append(f"(created_at, id) > (${len(params)}, ${id_after_idx})")
            elif filters.archived_after is not None:
                params.append(filters.archived_after)
                conditions.append(f"(archived_at, id) > (${len(params)}, ${id_after_idx})")
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

    _PRISMA_ALLOWED_MIGRATION_PREFIXES: frozenset[str] = frozenset({"0000", "0001"})

    def __init__(self, client: Prisma) -> None:
        self._client = client

    async def run(self) -> None:
        """Apply migrations from migrations/postgres SQL files."""
        # migrations は src/context_store/storage/migrations/postgres にある
        migrations_path = Path(__file__).parent / "migrations" / "postgres"

        if not migrations_path.exists():
            logger.warning(f"Migrations directory '{migrations_path}' not found.")
            return

        sql_files = sorted(migrations_path.glob("*.sql"))
        target_files = [
            f for f in sql_files if f.name[:4] in self._PRISMA_ALLOWED_MIGRATION_PREFIXES
        ]

        await self._ensure_system_migration()
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
            content = sql_file.read_text()
            # Use sqlparse for SQL-aware splitting to avoid breaking on semicolons in strings.
            statements = [s.strip().rstrip(";") for s in sqlparse.split(content) if s.strip()]

            async with self._client.tx() as tx:
                for stmt in statements:
                    if stmt:
                        await tx.execute_raw(stmt)
                await tx.execute_raw(
                    "INSERT INTO schema_migrations (version) VALUES ($1)", sql_file.name
                )

    async def _ensure_system_migration(self) -> None:
        """Ensure the schema_migrations table exists."""
        sql = "SELECT 1 FROM pg_catalog.pg_tables WHERE tablename = 'schema_migrations'"
        try:
            res = await self._client.query_raw(sql)
            if res:
                return
        except Exception:
            logger.debug("schema_migrations table check failed, will attempt to create it.")

        logger.info("Creating schema_migrations table")
        create_sql = (
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ DEFAULT NOW())"
        )
        await self._client.execute_raw(create_sql)

    async def _get_applied_migrations(self) -> set[str]:
        """Get the set of applied migration versions."""
        sql = "SELECT version FROM schema_migrations"
        try:
            rows = await self._client.query_raw(sql)
            return {row["version"] for row in rows}
        except Exception as exc:
            exc_str = str(exc).lower()
            # P2010 is Prisma's code for "Raw query failed" (e.g. table missing).
            if "relation" in exc_str and "does not exist" in exc_str:
                return set()
            if "p2010" in exc_str:
                return set()

            logger.exception("Failed to fetch applied migrations from schema_migrations table")
            raise

    async def _tables_exist(self, tables: list[str]) -> bool:
        """Check if specified tables exist in the database."""
        sql = "SELECT tablename FROM pg_catalog.pg_tables WHERE tablename = ANY($1)"
        try:
            rows = await self._client.query_raw(sql, tables)
            return len(rows) >= len(tables)
        except Exception as exc:
            exc_str = str(exc).lower()
            code = getattr(exc, "code", "")
            # P2021: Table does not exist in current database.
            # 42P01: undefined_table (PostgreSQL error code)
            if code == "P2021" or "42p01" in exc_str or "relation" in exc_str:
                return False
            raise

    async def _mark_as_applied(self, version: str) -> None:
        """Mark a migration version as applied without executing it."""
        await self._client.execute_raw(
            "INSERT INTO schema_migrations (version) VALUES ($1) ON CONFLICT DO NOTHING", version
        )
