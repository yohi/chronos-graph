from __future__ import annotations

from pydantic import BaseModel

from context_store.models.memory import ScoredMemory


class SearchStrategy(BaseModel):
    vector_weight: float = 0.5
    keyword_weight: float = 0.2
    graph_weight: float = 0.3
    graph_depth: int = 2
    time_decay_enabled: bool = True


class SearchFilters(BaseModel):
    project: str | None = None
    memory_type: str | None = None
    top_k: int = 10
    max_tokens: int | None = None


class SearchResult(BaseModel):
    results: list[ScoredMemory]
    total_count: int
    strategy_used: SearchStrategy
