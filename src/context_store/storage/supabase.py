"""Supabase Data API (PostgREST)-backed Storage Adapter.

設計仕様: docs/superpowers/specs/2026-05-18-supabase-storage-adapter-design.md
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

try:
    from postgrest.exceptions import (
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

from context_store.models.memory import ScoredMemory
from context_store.storage.postgres_helpers import (
    _content_hash,
    _embedding_to_pg,
    _parse_embedding,
    _record_to_memory,
)
from context_store.storage.protocols import MemoryFilters, StorageError

if TYPE_CHECKING:
    from context_store.config import Settings
    from context_store.models.memory import Memory, ScoredMemory

logger = logging.getLogger(__name__)

SUPABASE_BATCH_FETCH_CHUNK_SIZE = 200
SUPABASE_MAX_TOP_K = 200
UUID_HEX_LEN = 36

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
        if not rows:
            return None
        embedding = _parse_embedding(rows[0].get("embedding"))
        return len(embedding) if embedding else None

    async def dispose(self) -> None:
        client = self._client
        postgrest = getattr(client, "postgrest", None)
        if postgrest is not None and hasattr(postgrest, "aclose"):
            await postgrest.aclose()

    @staticmethod
    def _chunked(items: list[str], size: int):
        for i in range(0, len(items), size):
            yield items[i : i + size]

    async def get_memory(self, memory_id: str) -> Memory | None:
        if len(memory_id) != UUID_HEX_LEN:
            return None
        try:
            response = await (
                self._client.table("memories").select("*").eq("id", memory_id).execute()
            )
        except Exception as exc:
            raise self._map_to_storage_error(exc) from exc
        rows = response.data or []
        if not rows:
            return None
        return _record_to_memory(rows[0])

    async def get_memories_batch(self, memory_ids: list[str]) -> list[Memory]:
        results: list[Memory] = []
        for chunk in self._chunked(memory_ids, SUPABASE_BATCH_FETCH_CHUNK_SIZE):
            valid_ids = [mid for mid in chunk if len(mid) == UUID_HEX_LEN]
            if not valid_ids:
                continue
            try:
                response = await (
                    self._client.table("memories").select("*").in_("id", valid_ids).execute()
                )
            except Exception as exc:
                raise self._map_to_storage_error(exc) from exc
            rows = response.data or []
            row_map = {row["id"]: row for row in rows}
            for mid in chunk:
                if mid in row_map:
                    results.append(_record_to_memory(row_map[mid]))
        return results

    async def delete_memory(self, memory_id: str) -> bool:
        try:
            response = await self._client.table("memories").delete().eq("id", memory_id).execute()
        except Exception as exc:
            raise self._map_to_storage_error(exc) from exc
        return bool(response.data)

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
            raise StorageError("Insert returned no rows", code="STORAGE_ERROR", recoverable=True)
        return cast(str, rows[0]["id"])  # type: ignore[call-overload,index]

    async def update_memory(self, memory_id: str, updates: dict[str, Any]) -> bool:
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

    async def vector_search(
        self, embedding: list[float], top_k: int, project: str | None = None
    ) -> list[ScoredMemory]:
        if not embedding:
            return []
        top_k = min(top_k, SUPABASE_MAX_TOP_K)
        pg_vec = _embedding_to_pg(embedding)
        try:
            response = await self._client.rpc(
                "vector_search",
                {
                    "query_embedding": pg_vec,
                    "match_count": top_k,
                    "p_project": project,
                },
            ).execute()
        except Exception as exc:
            raise self._map_to_storage_error(exc) from exc

        results: list[ScoredMemory] = []
        for row in response.data or []:
            mem = _record_to_memory(row)
            score = float(row.get("score") or 0.0)
            results.append(ScoredMemory(memory=mem, score=score))
        return results

    async def keyword_search(
        self, query: str, top_k: int, project: str | None = None
    ) -> list[ScoredMemory]:
        if not query.strip():
            return []
        top_k = min(top_k, SUPABASE_MAX_TOP_K)
        cleaned = query.strip()
        try:
            chain = (
                self._client.table("memories")
                .select("*, similarity:1.0")
                .ilike("content", f"%{cleaned}%")
                .is_("archived_at", "null")
                .limit(top_k)
            )
            if project is not None:
                chain = chain.eq("project", project)
            response = await chain.execute()
        except Exception as exc:
            raise self._map_to_storage_error(exc) from exc

        results: list[ScoredMemory] = []
        for row in response.data or []:
            mem = _record_to_memory(row)
            results.append(ScoredMemory(memory=mem, score=1.0))
        return results

    async def list_by_filter(self, filters: MemoryFilters) -> list[Memory]:
        try:
            chain = self._client.table("memories").select("*")
            if filters.project is not None:
                chain = chain.eq("project", filters.project)
            if filters.memory_type is not None:
                chain = chain.eq("memory_type", filters.memory_type)
            if filters.archived is False:
                chain = chain.is_("archived_at", "null")
            elif filters.archived is True:
                chain = chain.not_.is_("archived_at", "null")
            if filters.tags:
                chain = chain.contains("tags", filters.tags)
            if filters.limit is not None:
                chain = chain.limit(filters.limit)
            if filters.offset is not None:
                chain = chain.offset(filters.offset)
            if filters.order_by is not None:
                chain = chain.order(filters.order_by)
            if filters.min_importance is not None:
                chain = chain.gte("importance_score", filters.min_importance)

            response = await chain.execute()
        except Exception as exc:
            raise self._map_to_storage_error(exc) from exc
        return [_record_to_memory(row) for row in (response.data or [])]

    async def count_by_filter(self, filters: MemoryFilters) -> int:
        try:
            chain = self._client.table("memories").select("*", count="exact", head=True)
            if filters.project is not None:
                chain = chain.eq("project", filters.project)
            if filters.memory_type is not None:
                chain = chain.eq("memory_type", filters.memory_type)
            if filters.archived is False:
                chain = chain.is_("archived_at", "null")
            elif filters.archived is True:
                chain = chain.not_.is_("archived_at", "null")
            if filters.tags:
                chain = chain.contains("tags", filters.tags)

            response = await chain.execute()
        except Exception as exc:
            raise self._map_to_storage_error(exc) from exc
        return response.count or 0

    async def list_projects(self) -> list[str]:
        try:
            response = await self._client.rpc("list_projects").execute()
        except Exception as exc:
            raise self._map_to_storage_error(exc) from exc
        rows = response.data or []
        return [row["project"] for row in rows if row.get("project")]

    async def increment_memory_access_count(self, memory_id: str) -> bool:
        try:
            response = await self._client.rpc(
                "increment_memory_access_count",
                {"p_memory_id": memory_id},
            ).execute()
        except Exception as exc:
            raise self._map_to_storage_error(exc) from exc
        data = response.data
        if isinstance(data, list) and data:
            return bool(data[0])
        return bool(data)
