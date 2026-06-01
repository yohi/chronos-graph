"""PostgreSQL Storage Adapter using asyncpg."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import asyncpg  # type: ignore[import-not-found]

from context_store.config import Settings
from context_store.models.memory import Memory, MemorySource, ScoredMemory
from context_store.storage.migrations.runner import MigrationRunner
from context_store.storage.postgres_helpers import (
    _content_hash,
    _embedding_to_pg,
    _record_to_memory,
)
from context_store.storage.protocols import ALLOWED_SORT_COLUMNS, MemoryFilters, StorageError
from context_store.sync.outbox_writer import OutboxWriter


class PostgresStorageAdapter:
    """StorageAdapter implementation backed by PostgreSQL + pgvector + pg_bigm."""

    def __init__(self, pool: asyncpg.Pool, outbox_writer: OutboxWriter | None = None) -> None:
        self._pool = pool
        self._outbox_writer: OutboxWriter | None = outbox_writer

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    async def create(
        cls,
        settings: Settings,
        outbox_writer: OutboxWriter | None = None,
    ) -> "PostgresStorageAdapter":
        """Create a new adapter by connecting to PostgreSQL."""
        import ssl

        # asyncpg creates a default SSL context when ssl=True.
        # Use None explicitly when SSL is disabled to avoid any ambiguous behavior.
        ssl_opt: bool | ssl.SSLContext | None = None
        if settings.postgres_ssl:
            # For some cloud providers like Supabase, default verification might fail
            # depending on the environment. We try to use a default context.
            ssl_opt = ssl.create_default_context()
            # Only disable verification when explicitly requested via settings,
            # e.g. for self-signed certs in dev/staging environments.
            if settings.postgres_ssl_no_verify:
                ssl_opt.check_hostname = False
                ssl_opt.verify_mode = ssl.CERT_NONE

        pool = await asyncpg.create_pool(
            dsn=settings.postgres_dsn,
            min_size=1,
            max_size=10,
            ssl=ssl_opt,
            statement_cache_size=settings.postgres_statement_cache_size,
        )
        adapter = cls(pool, outbox_writer=outbox_writer)
        try:
            await adapter.initialize()
        except Exception:
            await pool.close()
            raise
        return adapter

    async def initialize(self) -> None:
        """Apply schema migrations."""
        runner = MigrationRunner("postgres", self._pool)
        await runner.run()

    # ------------------------------------------------------------------
    # StorageAdapter Protocol
    # ------------------------------------------------------------------

    async def save_memory(self, memory: Memory) -> str:
        """Persist a memory and return its string ID."""
        embedding_str = _embedding_to_pg(memory.embedding)

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

        content_hash = _content_hash(memory.content)

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                try:
                    row_id = await conn.fetchval(
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
                except asyncpg.UniqueViolationError as e:
                    raise StorageError(
                        message=str(e),
                        code="DUPLICATE_CONTENT",
                        recoverable=False,
                    ) from e
                if self._outbox_writer is not None:
                    await self._outbox_writer.enqueue_sync(
                        conn=conn,
                        memory_id=str(row_id),
                        event_type="SYNC_MEMORY",
                    )

        return str(row_id)

    async def get_memory(self, memory_id: str) -> Memory | None:
        """Retrieve a memory by ID."""
        sql = "SELECT * FROM memories WHERE id = $1"
        async with self._pool.acquire() as conn:
            record = await conn.fetchrow(sql, memory_id)
        if record is None:
            return None
        return _record_to_memory(dict(record))

    async def get_memories_batch(self, memory_ids: list[str]) -> list[Memory]:
        """Retrieve multiple memories by ID."""
        if not memory_ids:
            return []
        cleaned_ids: list[str] = []
        for memory_id in memory_ids:
            try:
                cleaned_ids.append(str(UUID(str(memory_id))))
            except (TypeError, ValueError, AttributeError):
                continue
        if not cleaned_ids:
            return []
        sql = "SELECT * FROM memories WHERE id = ANY($1::uuid[])"
        async with self._pool.acquire() as conn:
            records = await conn.fetch(sql, cleaned_ids)
        memory_map = {str(record["id"]): _record_to_memory(dict(record)) for record in records}
        results: list[Memory] = []
        for memory_id in memory_ids:
            try:
                norm_id = str(UUID(str(memory_id)))
                if norm_id in memory_map:
                    results.append(memory_map[norm_id])
            except (TypeError, ValueError, AttributeError):
                continue
        return results

    async def delete_memory(self, memory_id: str) -> bool:
        """Delete a memory. Returns True if deleted."""
        sql = "DELETE FROM memories WHERE id = $1"
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                if self._outbox_writer is not None:
                    meta_row = await conn.fetchrow(
                        "SELECT memory_type, tags, project FROM memories WHERE id = $1::uuid",
                        memory_id,
                    )
                else:
                    meta_row = None
                status = await conn.execute(sql, memory_id)
                deleted = str(status) == "DELETE 1"
                if deleted and self._outbox_writer is not None:
                    await self._outbox_writer.enqueue_sync(
                        conn=conn,
                        memory_id=memory_id,
                        event_type="DELETE_MEMORY",
                        payload=dict(meta_row) if meta_row else {},
                    )
        return deleted

    async def update_memory(self, memory_id: str, updates: dict[str, Any]) -> bool:
        """Apply partial updates to a memory."""
        if not updates:
            return False

        # Build dynamic SET clause: $1=val1, $2=val2, ...
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
        set_parts = []
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
        # Final SQL assembly
        query_parts = [
            "UPDATE memories",
            f"SET {', '.join(set_parts)}",
            f"WHERE id = ${len(params)}",
        ]
        sql = " ".join(query_parts)

        async with self._pool.acquire() as conn:
            status = await conn.execute(sql, *params)  # noqa: S608
        return str(status) == "UPDATE 1"

    async def vector_search(
        self, embedding: list[float], top_k: int, project: str | None = None
    ) -> list[ScoredMemory]:
        """Search by cosine similarity using pgvector <=> operator."""
        embedding_str = _embedding_to_pg(embedding)
        if embedding_str is None:
            return []

        if project is not None:
            sql = """
                SELECT *, 1 - (embedding <=> $1::vector) AS score
                FROM memories
                WHERE archived_at IS NULL AND embedding IS NOT NULL AND project = $3
                ORDER BY embedding <=> $1::vector
                LIMIT $2
            """
            params = (embedding_str, top_k, project)
        else:
            sql = """
                SELECT *, 1 - (embedding <=> $1::vector) AS score
                FROM memories
                WHERE archived_at IS NULL AND embedding IS NOT NULL
                ORDER BY embedding <=> $1::vector
                LIMIT $2
            """
            params = (embedding_str, top_k)  # type: ignore[assignment]

        async with self._pool.acquire() as conn:
            records = await conn.fetch(sql, *params)

        return [
            ScoredMemory(
                memory=_record_to_memory(dict(r)),
                score=float(r["score"]),
                source=MemorySource.VECTOR,
            )
            for r in records
        ]

    async def keyword_search(
        self, query: str, top_k: int, project: str | None = None
    ) -> list[ScoredMemory]:
        """Full-text keyword search using pg_bigm LIKE."""
        like_query = f"%{query}%"

        if project is not None:
            sql = """
                SELECT *, 1.0 AS score
                FROM memories
                WHERE archived_at IS NULL
                  AND content LIKE $1
                  AND project = $3
                LIMIT $2
            """
            params = (like_query, top_k, project)
        else:
            sql = """
                SELECT *, 1.0 AS score
                FROM memories
                WHERE archived_at IS NULL
                  AND content LIKE $1
                LIMIT $2
            """
            params = (like_query, top_k)  # type: ignore[assignment]

        async with self._pool.acquire() as conn:
            records = await conn.fetch(sql, *params)

        return [
            ScoredMemory(
                memory=_record_to_memory(dict(r)),
                score=float(r["score"]),
                source=MemorySource.KEYWORD,
            )
            for r in records
        ]

    def _build_where_clause(self, filters: MemoryFilters) -> tuple[str, list[Any]]:
        """共通の WHERE 句とパラメータを生成する。"""
        conditions: list[str] = []
        params: list[Any] = []

        if filters.archived is None:
            conditions.append("archived_at IS NULL")
        elif filters.archived is True:
            conditions.append("archived_at IS NOT NULL")
        # archived=False → both active and archived, no condition

        if filters.project is not None:
            params.append(filters.project)
            conditions.append(f"project = ${len(params)}")

        if filters.memory_type is not None:
            params.append(filters.memory_type)
            conditions.append(f"memory_type = ${len(params)}")

        if filters.tags:
            params.append(filters.tags)
            conditions.append(f"tags && ${len(params)}")  # array overlap

        if getattr(filters, "session_id", None) is not None:
            params.append(filters.session_id)
            conditions.append(f"source_metadata->>'session_id' = ${len(params)}")

        if filters.min_importance is not None:
            params.append(filters.min_importance)
            conditions.append(f"importance_score >= ${len(params)}")

        if filters.created_after is not None:
            if filters.id_after is not None:
                params.append(filters.created_after)
                params.append(filters.id_after)
                conditions.append(f"(created_at, id) > (${len(params) - 1}, ${len(params)})")
            else:
                params.append(filters.created_after)
                conditions.append(f"created_at >= ${len(params)}")

        if filters.archived_after is not None:
            if filters.id_after is not None:
                params.append(filters.archived_after)
                params.append(filters.id_after)
                conditions.append(f"(archived_at, id) > (${len(params) - 1}, ${len(params)})")
            else:
                params.append(filters.archived_after)
                conditions.append(f"archived_at >= ${len(params)}")

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        return where_clause, params

    async def list_by_filter(self, filters: MemoryFilters) -> list[Memory]:
        """List memories matching the given filters."""
        where_clause, params = self._build_where_clause(filters)

        # Validate and whitelist ORDER BY columns
        allowed_order_cols = ALLOWED_SORT_COLUMNS
        order_clause = "ORDER BY created_at DESC"
        if filters.order_by:
            order_parts = []
            for part in str(filters.order_by).split(","):
                tokens = part.strip().split()
                if tokens:
                    col = tokens[0].lower()
                    if col not in allowed_order_cols:
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

        # Parameterize LIMIT
        limit_clause = ""
        limit_val = getattr(filters, "limit", None)
        if limit_val is not None:
            try:
                limit_int = int(limit_val)
                if limit_int < 0:
                    raise StorageError(
                        message=f"Invalid limit value: {limit_int}",
                        code="INVALID_PARAMETER",
                    )
                params.append(limit_int)
                limit_clause = f"LIMIT ${len(params)}"
            except (ValueError, TypeError) as e:
                raise StorageError(
                    message=f"Invalid limit type: {type(limit_val)}",
                    code="INVALID_PARAMETER",
                ) from e

        # Parameterize OFFSET
        offset_clause = ""
        offset_val = getattr(filters, "offset", None)
        if offset_val is not None:
            try:
                offset_int = int(offset_val)
                if offset_int < 0:
                    raise StorageError(
                        message=f"Invalid offset value: {offset_int}",
                        code="INVALID_PARAMETER",
                    )
                params.append(offset_int)
                offset_clause = f"OFFSET ${len(params)}"
            except (ValueError, TypeError) as e:
                raise StorageError(
                    message=f"Invalid offset type: {type(offset_val)}",
                    code="INVALID_PARAMETER",
                ) from e

        # Final SQL assembly
        query_parts = [
            "SELECT * FROM memories",
            where_clause,
            order_clause,
            limit_clause,
            offset_clause,
        ]
        sql = " ".join(part for part in query_parts if part).strip()

        async with self._pool.acquire() as conn:
            records = await conn.fetch(sql, *params)  # noqa: S608

        return [_record_to_memory(dict(r)) for r in records]

    async def count_by_filter(self, filters: MemoryFilters) -> int:
        """Count memories matching the given filters."""
        where_clause, params = self._build_where_clause(filters)

        # Final SQL assembly
        query_parts = ["SELECT COUNT(*)", "FROM memories", where_clause]
        sql = " ".join(part for part in query_parts if part).strip()

        async with self._pool.acquire() as conn:
            count = await conn.fetchval(sql, *params)  # noqa: S608
            return int(count) if count is not None else 0

    async def list_projects(self) -> list[str]:
        """List all unique project names present in the storage."""
        sql = "SELECT DISTINCT project FROM memories WHERE project IS NOT NULL AND project != ''"
        async with self._pool.acquire() as conn:
            records = await conn.fetch(sql)
            return [str(r["project"]) for r in records]

    async def increment_memory_access_count(self, memory_id: str) -> bool:
        """Atomically increment the access count and update last_accessed_at."""
        sql = """
            UPDATE memories
            SET access_count = access_count + 1,
                last_accessed_at = NOW(),
                updated_at = NOW()
            WHERE id = $1
        """
        async with self._pool.acquire() as conn:
            status = await conn.execute(sql, memory_id)
        return str(status) == "UPDATE 1"

    async def increment_memory_access_counts(self, memory_ids: list[str]) -> int:
        """Bulk variant: atomically increment access counts for many memories."""
        if not memory_ids:
            return 0
        cleaned: list[str] = []
        for mid in memory_ids:
            try:
                cleaned.append(str(UUID(str(mid))))
            except (TypeError, ValueError, AttributeError):
                continue
        if not cleaned:
            return 0
        sql = (
            "UPDATE memories "
            "SET access_count = access_count + 1, "
            "    last_accessed_at = NOW(), "
            "    updated_at = NOW() "
            "WHERE id = ANY($1::uuid[])"
        )
        async with self._pool.acquire() as conn:
            status = await conn.execute(sql, cleaned)
        parts = str(status).split()
        try:
            return int(parts[-1])
        except (ValueError, IndexError):
            return 0

    async def get_vector_dimension(self) -> int | None:
        """Return the dimension of stored vectors."""
        sql = "SELECT vector_dims(embedding) FROM memories WHERE embedding IS NOT NULL LIMIT 1"
        async with self._pool.acquire() as conn:
            result = await conn.fetchval(sql)
        return None if result is None else int(result)

    async def dispose(self) -> None:
        """Release the connection pool."""
        await self._pool.close()
