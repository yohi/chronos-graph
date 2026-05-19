"""Supabase Data API (PostgREST)-backed Storage Adapter.

設計仕様: docs/superpowers/specs/2026-05-18-supabase-storage-adapter-design.md
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Iterator, cast

try:  # noqa: I001
    from postgrest.exceptions import (  # type: ignore[import-not-found]
        APIError as PostgrestAPIError,  # type: ignore[import-not-found]  # noqa: F401
    )

    from supabase import (  # type: ignore[attr-defined]  # noqa: F401
        AsyncClient,
        create_async_client,
    )

    _supabase_available = True
except ImportError:
    AsyncClient = Any  # type: ignore[misc,assignment]
    PostgrestAPIError = Exception  # type: ignore[misc,assignment]
    _supabase_available = False

from context_store.models.memory import MemorySource, ScoredMemory
from context_store.storage.postgres_helpers import (
    _content_hash,
    _embedding_to_pg,
    _parse_embedding,
    _record_to_memory,
)
from context_store.storage.protocols import ALLOWED_SORT_COLUMNS, MemoryFilters, StorageError

if TYPE_CHECKING:
    from context_store.config import Settings
    from context_store.models.memory import Memory

logger = logging.getLogger(__name__)

SUPABASE_BATCH_FETCH_CHUNK_SIZE = 200
SUPABASE_MAX_TOP_K = 200

ALLOWED_UPDATE_COLUMNS: frozenset[str] = frozenset(
    {
        "content",
        "memory_type",
        "source_type",
        "source_metadata",
        "embedding",
        "semantic_relevance",
        "importance_score",
        "tags",
        "project",
        "archived_at",
    }
)


class SupabaseStorageAdapter:
    """StorageAdapter implementation backed by Supabase Data API (HTTPS only)."""

    def __init__(self, client: "AsyncClient") -> None:
        self._client = client

    @classmethod
    async def create(cls, settings: "Settings") -> "SupabaseStorageAdapter":
        if not _supabase_available:
            raise ImportError(
                "supabase is not installed. Install with: uv sync --extra storage-supabase"
            )
        client = await create_async_client(
            settings.supabase_url,
            settings.supabase_key.get_secret_value(),
        )
        adapter = cls(client)
        try:
            actual_dim = await adapter.get_vector_dimension()
        except Exception as exc:
            await adapter.dispose()
            raise adapter._map_to_storage_error(exc) from exc

        if actual_dim is not None and actual_dim != settings.embedding_dimension:
            await adapter.dispose()
            raise StorageError(
                f"Supabase memories.embedding dimension ({actual_dim}) does not match "
                f"settings.embedding_dimension ({settings.embedding_dimension}). "
                "Apply the matching supabase/migrations SQL or reconcile EMBEDDING_DIMENSION.",
                code="INVALID_STATE",
                recoverable=False,
            )
        return adapter

    async def get_vector_dimension(self) -> int | None:
        chain = (
            self._client.table("memories")
            .select("embedding")
            .not_.is_("embedding", "null")
            .limit(1)
        )
        response = await chain.execute()
        rows = response.data or []
        if rows:
            embedding = _parse_embedding(rows[0].get("embedding"))
            if embedding:
                return len(embedding)
        # Empty table: query schema dimension via RPC
        try:
            rpc_response = await self._client.rpc("get_embedding_dimension", {}).execute()
        except Exception as exc:
            raise self._map_to_storage_error(exc) from exc
        data = rpc_response.data
        if isinstance(data, list) and data:
            dim = data[0]
        elif isinstance(data, int):
            dim = data
        else:
            dim = None
        if isinstance(dim, int) and dim > 0:
            return dim
        raise StorageError(
            "Could not determine memories.embedding dimension from schema. "
            "Ensure pgvector extension is installed and the memories table exists.",
            code="INVALID_STATE",
            recoverable=False,
        )

    async def dispose(self) -> None:
        client = self._client
        postgrest = getattr(client, "postgrest", None)
        if postgrest is not None and hasattr(postgrest, "aclose"):
            await postgrest.aclose()

    def _map_to_storage_error(self, exc: Exception) -> StorageError:
        code = getattr(exc, "code", None) or ""
        message = getattr(exc, "message", "") or str(exc)

        if code == "23505":
            return StorageError(message, code="DUPLICATE_CONTENT", recoverable=False)
        if code in ("22P02", "22023"):
            return StorageError(message, code="INVALID_INPUT", recoverable=False)
        if code == "PGRST116":
            return StorageError(message, code="NOT_FOUND", recoverable=False)

        exc_str = str(exc).lower()
        if any(kw in exc_str for kw in ("timeout", "408", "504", "503", "connecterror")):
            return StorageError(message, code="STORAGE_TIMEOUT", recoverable=True)
        if "413" in exc_str or "payload too large" in exc_str:
            return StorageError(message, code="STORAGE_PAYLOAD_TOO_LARGE", recoverable=False)

        return StorageError(message, code="STORAGE_ERROR", recoverable=True)

    async def save_memory(self, memory: "Memory") -> str:
        row = {
            "content": memory.content,
            "memory_type": memory.memory_type.value,
            "source_type": memory.source_type.value,
            "source_metadata": memory.source_metadata or {},
            "embedding": _embedding_to_pg(memory.embedding or []),
            "semantic_relevance": memory.semantic_relevance,
            "importance_score": memory.importance_score,
            "tags": list(memory.tags or []),
            "project": memory.project,
            "content_hash": _content_hash(memory.content),
        }
        try:
            response = await self._client.table("memories").insert(row).execute()  # type: ignore[arg-type]
        except Exception as exc:
            raise self._map_to_storage_error(exc) from exc
        rows = response.data or []
        if not rows:
            raise StorageError(
                "Insert returned no rows",
                code="STORAGE_ERROR",
                recoverable=True,
            )
        return cast(str, rows[0]["id"])  # type: ignore[call-overload,index]

    async def update_memory(self, memory_id: str, updates: dict[str, Any]) -> bool:
        if not _is_valid_uuid(memory_id):
            return False
        filtered = {k: v for k, v in updates.items() if k in ALLOWED_UPDATE_COLUMNS}
        if "content" in filtered:
            filtered["content_hash"] = _content_hash(filtered["content"])
        if "embedding" in filtered and not isinstance(filtered["embedding"], str):
            filtered["embedding"] = _embedding_to_pg(filtered["embedding"] or [])
        if not filtered:
            return False
        try:
            response = (
                await self._client.table("memories").update(filtered).eq("id", memory_id).execute()
            )
        except Exception as exc:
            raise self._map_to_storage_error(exc) from exc
        return bool(response.data)

    @staticmethod
    def _chunked(items: list[str], size: int) -> Iterator[list[str]]:
        for i in range(0, len(items), size):
            yield items[i : i + size]

    async def get_memory(self, memory_id: str) -> Memory | None:
        if not _is_valid_uuid(memory_id):
            return None
        try:
            chain = self._client.table("memories").select("*").eq("id", memory_id)
            response = await chain.execute()
        except Exception as exc:
            raise self._map_to_storage_error(exc) from exc
        rows = response.data or []
        if not rows:
            return None
        return _record_to_memory(rows[0])  # type: ignore[arg-type]

    async def get_memories_batch(self, memory_ids: list[str]) -> list[Memory]:
        results: list[Memory] = []
        for chunk in self._chunked(memory_ids, SUPABASE_BATCH_FETCH_CHUNK_SIZE):
            valid_ids = [mid for mid in chunk if _is_valid_uuid(mid)]
            if not valid_ids:
                continue
            try:
                response = await (
                    self._client.table("memories").select("*").in_("id", valid_ids).execute()
                )
            except Exception as exc:
                raise self._map_to_storage_error(exc) from exc
            rows = response.data or []
            row_map: dict[str, Any] = {row["id"]: row for row in rows}  # type: ignore[index,call-overload,misc]
            for mid in chunk:
                if mid in row_map:
                    results.append(_record_to_memory(row_map[mid]))  # type: ignore[arg-type]
        return results

    async def delete_memory(self, memory_id: str) -> bool:
        if not _is_valid_uuid(memory_id):
            return False
        try:
            response = await self._client.table("memories").delete().eq("id", memory_id).execute()
        except Exception as exc:
            raise self._map_to_storage_error(exc) from exc
        return bool(response.data)

    async def vector_search(
        self,
        embedding: list[float],
        top_k: int,
        project: str | None = None,
    ) -> list[ScoredMemory]:
        effective_top_k = top_k
        if top_k > SUPABASE_MAX_TOP_K:
            logger.warning(
                "top_k=%d exceeds SUPABASE_MAX_TOP_K=%d; clamping",
                top_k,
                SUPABASE_MAX_TOP_K,
            )
            effective_top_k = SUPABASE_MAX_TOP_K
        if effective_top_k < 1:
            effective_top_k = 1

        params = {
            "query_embedding": embedding,
            "match_count": effective_top_k,
            "p_project": project,
        }
        try:
            response = await self._client.rpc("vector_search", params).execute()
        except Exception as exc:
            raise self._map_to_storage_error(exc) from exc

        results: list[ScoredMemory] = []
        for row in response.data or []:
            score = float(row.pop("score", 0.0))
            memory = _record_to_memory(row)
            results.append(ScoredMemory(memory=memory, score=score, source=MemorySource.VECTOR))
        return results

    async def keyword_search(
        self, query: str, top_k: int, project: str | None = None
    ) -> list[ScoredMemory]:
        effective_top_k = max(1, min(top_k, SUPABASE_MAX_TOP_K))
        builder = (
            self._client.table("memories")
            .select("*")
            .ilike("content", f"%{query}%")
            .is_("archived_at", "null")
            .limit(effective_top_k)
        )
        if project is not None:
            builder = builder.eq("project", project)
        try:
            response = await builder.execute()
        except Exception as exc:
            raise self._map_to_storage_error(exc) from exc

        results: list[ScoredMemory] = []
        for row in response.data or []:
            memory = _record_to_memory(row)
            results.append(ScoredMemory(memory=memory, score=1.0, source=MemorySource.KEYWORD))
        return results

    async def list_by_filter(self, filters: MemoryFilters) -> list[Memory]:
        builder = self._client.table("memories").select("*")
        builder = _apply_common_filters(builder, filters)

        if filters.created_after is not None and filters.id_after is not None:
            if not _is_valid_uuid(filters.id_after):
                return []
            ts = _format_pg_datetime(filters.created_after)
            builder = builder.or_(
                f"created_at.lt.{ts},and(created_at.eq.{ts},id.lt.{filters.id_after})"
            )
        elif filters.created_after is not None:
            builder = builder.lt("created_at", _format_pg_datetime(filters.created_after))

        if filters.order_by:
            column, _, direction = filters.order_by.partition(" ")
            if column in ALLOWED_SORT_COLUMNS:
                desc = direction.upper() == "DESC"
                builder = builder.order(column, desc=desc)
        if filters.limit is not None:
            builder = builder.limit(filters.limit)
        if filters.offset is not None:
            builder = builder.offset(filters.offset)

        try:
            response = await builder.execute()
        except Exception as exc:
            raise self._map_to_storage_error(exc) from exc
        return [_record_to_memory(row) for row in response.data or []]

    async def count_by_filter(self, filters: MemoryFilters) -> int:
        builder = self._client.table("memories").select("*", count="exact", head=True)
        builder = _apply_common_filters(builder, filters)
        try:
            response = await builder.execute()
        except Exception as exc:
            raise self._map_to_storage_error(exc) from exc
        return int(response.count or 0)

    async def list_projects(self) -> list[str]:
        try:
            response = await self._client.rpc("list_projects", {}).execute()
        except Exception as exc:
            raise self._map_to_storage_error(exc) from exc
        data = cast(list[dict[str, Any]], response.data or [])
        return [str(row["project"]) for row in data]

    async def increment_memory_access_count(self, memory_id: str) -> bool:
        if not _is_valid_uuid(memory_id):
            return False
        try:
            response = await self._client.rpc(
                "increment_memory_access_count", {"p_memory_id": memory_id}
            ).execute()
        except Exception as exc:
            raise self._map_to_storage_error(exc) from exc
        return bool(response.data)


def _format_pg_datetime(dt: "datetime") -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _apply_common_filters(builder: Any, filters: MemoryFilters) -> Any:
    if filters.project is not None:
        builder = builder.eq("project", filters.project)
    if filters.memory_type is not None:
        builder = builder.eq("memory_type", filters.memory_type)
    if filters.session_id is not None:
        builder = builder.eq("source_metadata->>session_id", filters.session_id)
    if filters.min_importance is not None:
        builder = builder.gte("importance_score", filters.min_importance)
    if filters.tags:
        builder = builder.contains("tags", filters.tags)

    effective_archived = filters.archived
    if filters.archived_after is not None and effective_archived is None:
        effective_archived = True

    if effective_archived is None:
        builder = builder.is_("archived_at", "null")
    elif effective_archived is True:
        builder = builder.not_.is_("archived_at", "null")

    if filters.archived_after is not None:
        builder = builder.gte("archived_at", _format_pg_datetime(filters.archived_after))
    return builder


def _is_valid_uuid(value: str) -> bool:
    """Validate a UUID string (accepts both standard and hex formats)."""
    if not value:
        return False
    try:
        uuid.UUID(str(value))
        return True
    except (TypeError, ValueError, AttributeError):
        return False
