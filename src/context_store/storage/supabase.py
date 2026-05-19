"""Supabase Data API (PostgREST)-backed Storage Adapter.

設計仕様: docs/superpowers/specs/2026-05-18-supabase-storage-adapter-design.md
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

try:
    from supabase import AsyncClient, create_async_client  # type: ignore[attr-defined]  # noqa: F401
    from postgrest.exceptions import APIError as PostgrestAPIError  # type: ignore[import-not-found]  # noqa: F401

    _supabase_available = True
except ImportError:
    AsyncClient = Any  # type: ignore[misc,assignment]
    PostgrestAPIError = Exception  # type: ignore[misc,assignment]
    _supabase_available = False
    from supabase import AsyncClient, create_async_client  # noqa: F401
    from postgrest.exceptions import APIError as PostgrestAPIError  # noqa: F401

    _supabase_available = True
except ImportError:
    AsyncClient = Any  # type: ignore[misc,assignment]
    PostgrestAPIError = Exception  # type: ignore[misc,assignment]
    _supabase_available = False

from context_store.storage.protocols import StorageError

if TYPE_CHECKING:
    from context_store.config import Settings

logger = logging.getLogger(__name__)

SUPABASE_BATCH_FETCH_CHUNK_SIZE = 200
SUPABASE_MAX_TOP_K = 200


class SupabaseStorageAdapter:
    """StorageAdapter implementation backed by Supabase Data API (HTTPS only)."""

    def __init__(self, client: "AsyncClient") -> None:
        self._client = client

    @classmethod
    async def create(cls, settings: "Settings") -> "SupabaseStorageAdapter":
        # 詳細実装は Task 3.2 で追加
        raise NotImplementedError

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
