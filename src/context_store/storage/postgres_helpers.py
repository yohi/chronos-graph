"""Shared PostgreSQL row/value conversion helpers for storage adapters."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from context_store.models.memory import Memory, MemoryType, SourceType


def _content_hash(content: str) -> str:
    """Create the canonical content hash stored in PostgreSQL."""
    return hashlib.sha256(content.encode()).hexdigest()


def _parse_embedding(raw: object) -> list[float]:
    """Parse a pgvector value returned by a PostgreSQL client into list[float]."""
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        return [float(v) for v in raw]
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
    """Convert a PostgreSQL record dict to a Memory model."""
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
