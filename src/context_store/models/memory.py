from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class MemoryType(str, Enum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"


class SourceType(str, Enum):
    CONVERSATION = "conversation"
    MANUAL = "manual"
    URL = "url"


class Memory(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    content: str
    memory_type: MemoryType
    source_type: SourceType
    source_metadata: dict[str, object] = Field(default_factory=dict)
    embedding: list[float] = Field(default_factory=list)
    semantic_relevance: float = 0.5
    importance_score: float = 0.5
    access_count: int = 0
    last_accessed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    archived_at: datetime | None = None
    tags: list[str] = Field(default_factory=list)
    project: str | None = None


class ScoredMemory(BaseModel):
    memory: Memory
    score: float
    source: str = ""  # "vector" | "keyword" | "graph"
