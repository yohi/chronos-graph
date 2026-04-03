"""PostgreSQL Storage Adapter using asyncpg."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

import asyncpg  # type: ignore[import-not-found]

from context_store.config import Settings
from context_store.models.memory import Memory, MemorySource, MemoryType, ScoredMemory, SourceType
from context_store.storage.protocols import ALLOWED_SORT_COLUMNS, MemoryFilters, StorageError


def _content_hash(content: str) -> str:
    """Create the canonical content hash stored in PostgreSQL."""
    return hashlib.sha256(content.encode()).hexdigest()


def _parse_embedding(raw: object) -> list[float]:
    """Parse embedding value returned from asyncpg into list[float].

    asyncpg may return the pgvector column as a string like '[0.1,0.2,...]'
    or as a list, depending on the installed asyncpg codec.
    """
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        return [float(v) for v in raw]
    # str form: '[0.1,0.2,...]'
    s = str(raw).strip()
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]
    if not s:
        return []
    return [float(v) for v in s.split(",")]


def _embedding_to_pg(embedding: list[float]) -> str | None:
    """Convert Python float list to pgvector string '[x,y,z]'."""
    if not embedding:
        return None
    return "[" + ",".join(str(v) for v in embedding) + "]"


def _record_to_memory(record: dict[str, Any]) -> Memory:
    """Convert an asyncpg Record (or dict) to a Memory model."""
    source_metadata = record.get("source_metadata") or {}
    if isinstance(source_metadata, str):
        source_metadata = json.loads(source_metadata)

    return Memory(
        id=record["id"],
        content=record["content"],
        memory_type=MemoryType(record["memory_type"]),
        source_type=SourceType(record["source_type"]),
        source_metadata=source_metadata,
        embedding=_parse_embedding(record.get("embedding")),
        semantic_relevance=float(record.get("semantic_relevance") or 0.5),
        importance_score=float(record.get("importance_score") or 0.5),
        access_count=int(record.get("access_count") or 0),
        last_accessed_at=record["last_accessed_at"],
        created_at=record["created_at"],
        updated_at=record["updated_at"],
        archived_at=record.get("archived_at"),
        tags=list(record.get("tags") or []),
        project=record.get("project"),
    )


class PostgresStorageAdapter:
    """StorageAdapter implementation backed by PostgreSQL + pgvector + pg_bigm."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    async def create(cls, settings: Settings) -> "PostgresStorageAdapter":
        """Create a new adapter by connecting to PostgreSQL."""
        pool = await asyncpg.create_pool(
            dsn=settings.postgres_dsn,
            min_size=1,
            max_size=10,
        )
        return cls(pool)

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

        try:
            async with self._pool.acquire() as conn:
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
            status = await conn.execute(sql, memory_id)
        return str(status) == "DELETE 1"

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
        sql = f"UPDATE memories SET {', '.join(set_parts)} WHERE id = ${len(params)}"

        async with self._pool.acquire() as conn:
            status = await conn.execute(sql, *params)
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

    async def list_by_filter(self, filters: MemoryFilters) -> list[Memory]:
        """List memories matching the given filters."""
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

        if filters.created_after is not None:
            if filters.id_after is not None:
                params.append(filters.created_after)
                params.append(filters.id_after)
                conditions.append(f"(created_at, id) > (${len(params)-1}, ${len(params)})")
            else:
                params.append(filters.created_after)
                conditions.append(f"created_at >= ${len(params)}")

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
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

        sql = f"SELECT * FROM memories {where_clause} {order_clause} {limit_clause}".strip()

        async with self._pool.acquire() as conn:
            records = await conn.fetch(sql, *params)

        return [_record_to_memory(dict(r)) for r in records]

    async def get_vector_dimension(self) -> int | None:
        """Return the dimension of stored vectors."""
        sql = "SELECT vector_dims(embedding) FROM memories WHERE embedding IS NOT NULL LIMIT 1"
        async with self._pool.acquire() as conn:
            result = await conn.fetchval(sql)
        return None if result is None else int(result)

    async def dispose(self) -> None:
        """Release the connection pool."""
        await self._pool.close()
