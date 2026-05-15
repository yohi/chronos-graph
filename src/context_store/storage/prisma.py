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

from context_store.storage.protocols import StorageError

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
    """Prisma Client を直接使用した PostgreSQL ストレージ実装 (HTTPS)。"""

    def __init__(self, client: Prisma) -> None:
        self._client = client

    @classmethod
    async def create(cls, settings: Any) -> "PrismaStorageAdapter":
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
            await client.disconnect()
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
        except UniqueViolationError as exc:
            raise StorageError(
                message=f"duplicate content detected: {exc}",
                code="DUPLICATE_CONTENT",
                recoverable=False,
            ) from exc
        except Exception as exc:
            exc_str = str(exc)
            # Handle simulated KnownRequestError with .code or str match
            code = getattr(exc, "code", "")
            if code == "P2002" or "unique constraint" in exc_str.lower():
                raise StorageError(
                    message=f"duplicate content detected: {exc_str}",
                    code="DUPLICATE_CONTENT",
                    recoverable=False,
                ) from exc
            raise StorageError(message=str(exc), code="STORAGE_ERROR", recoverable=False) from exc

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
            raise StorageError(message=str(exc), code="STORAGE_ERROR", recoverable=False) from exc

    async def get_memories_batch(self, memory_ids: list[str]) -> list[Memory]:
        """Retrieve multiple memories by ID, preserving input order.

        Accelerate の 5MB 応答上限への対策として、チャンクサイズ
        ``PRISMA_BATCH_FETCH_CHUNK_SIZE`` で分割実行する。
        """
        if not memory_ids:
            return []

        unique_ids = list(set(memory_ids))
        valid_ids = []
        for mid in unique_ids:
            try:
                valid_ids.append(str(UUID(str(mid))))
            except (TypeError, ValueError, AttributeError):
                continue

        if not valid_ids:
            return []

        results_map = {}
        # Process in chunks
        for i in range(0, len(valid_ids), PRISMA_BATCH_FETCH_CHUNK_SIZE):
            chunk = valid_ids[i : i + PRISMA_BATCH_FETCH_CHUNK_SIZE]
            sql = "SELECT * FROM memories WHERE id = ANY($1::uuid[])"
            try:
                rows = await self._client.query_raw(sql, chunk)
                for row in rows:
                    results_map[str(row["id"])] = _record_to_memory(row)
            except Exception as exc:
                raise StorageError(
                    message=str(exc), code="STORAGE_ERROR", recoverable=False
                ) from exc

        # Maintain original order and handle missing
        final_results = []
        for mid in memory_ids:
            try:
                norm_id = str(UUID(str(mid)))
                if norm_id in results_map:
                    final_results.append(results_map[norm_id])
            except (TypeError, ValueError, AttributeError):
                continue
        return final_results

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
            raise StorageError(message=str(exc), code="STORAGE_ERROR", recoverable=False) from exc
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
            raise StorageError(message=str(exc), code="STORAGE_ERROR", recoverable=False) from exc
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

        allowed_columns = {
            "memory_type",
            "source_type",
            "project",
            "archived_at",
            "importance_score",
        }

        if filter_dict:
            for col, val in filter_dict.items():
                if col not in allowed_columns:
                    raise StorageError(
                        message=f"Invalid filter column: {col}",
                        code="INVALID_INPUT",
                        recoverable=False,
                    )
                if val is None:
                    where_clauses.append(f'"{col}" IS NULL')
                else:
                    params.append(val)
                    where_clauses.append(f'"{col}" = ${len(params)}')

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        params.append(limit)
        limit_idx = len(params)
        params.append(offset)
        offset_idx = len(params)

        # noqa: S608 (where_clauses use whitelisted keys)
        sql = f"SELECT * FROM memories {where_sql} LIMIT ${limit_idx} OFFSET ${offset_idx}"  # noqa: S608

        try:
            rows = await self._client.query_raw(sql, *params)
        except Exception as exc:
            raise StorageError(message=str(exc), code="STORAGE_ERROR", recoverable=False) from exc

        return [_record_to_memory(row) for row in rows]

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
            try:
                rows = await self._client.query_raw(sql, embedding_str, effective_top_k, project)
            except Exception as exc:
                raise StorageError(
                    message=str(exc), code="STORAGE_ERROR", recoverable=False
                ) from exc
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
                raise StorageError(
                    message=str(exc), code="STORAGE_ERROR", recoverable=False
                ) from exc

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
            try:
                rows = await self._client.query_raw(sql, like_query, effective_top_k, project)
            except Exception as exc:
                raise StorageError(
                    message=str(exc), code="STORAGE_ERROR", recoverable=False
                ) from exc
        else:
            sql = (
                "SELECT *, 1.0 AS score FROM memories "
                "WHERE archived_at IS NULL AND content LIKE $1 "
                "LIMIT $2"
            )
            try:
                rows = await self._client.query_raw(sql, like_query, effective_top_k)
            except Exception as exc:
                raise StorageError(
                    message=str(exc), code="STORAGE_ERROR", recoverable=False
                ) from exc

        return [
            ScoredMemory(
                memory=_record_to_memory(row),
                score=float(row["score"]),
                source=MemorySource.KEYWORD,
            )
            for row in rows
        ]


class _PrismaMigrationRunner:
    """Prisma 用の簡易マイグレーションランナー。"""

    _PRISMA_ALLOWED_MIGRATION_PREFIXES: frozenset[str] = frozenset({"0000", "0001"})

    def __init__(self, client: Prisma) -> None:
        self._client = client

    async def run(self) -> None:
        """Apply migrations from docker/postgres SQL files."""
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
            statements = [
                s.strip().rstrip(";") for s in sqlparse.split(content) if s.strip()
            ]

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
            pass

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
            return set()

    async def _tables_exist(self, tables: list[str]) -> bool:
        """Check if specified tables exist in the database."""
        sql = "SELECT tablename FROM pg_catalog.pg_tables WHERE tablename = ANY($1)"
        try:
            rows = await self._client.query_raw(sql, tables)
            return len(rows) >= len(tables)
        except Exception:
            return False

    async def _mark_as_applied(self, version: str) -> None:
        """Mark a migration version as applied without executing it."""
        await self._client.execute_raw(
            "INSERT INTO schema_migrations (version) VALUES ($1) ON CONFLICT DO NOTHING", version
        )
