from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from context_store.models.memory import MemoryType, ScoredMemory

__all__ = ["SearchStrategy", "SearchFilters", "SearchResult", "ScoredMemory"]


class SearchStrategy(BaseModel):
    vector_weight: float = Field(default=0.5, ge=0.0, le=1.0)
    keyword_weight: float = Field(default=0.2, ge=0.0, le=1.0)
    graph_weight: float = Field(default=0.3, ge=0.0, le=1.0)
    graph_depth: int = Field(default=2, gt=0)
    time_decay_enabled: bool = True

    @model_validator(mode="after")
    def validate_weights(self) -> "SearchStrategy":
        total_weight = self.vector_weight + self.keyword_weight + self.graph_weight
        if abs(total_weight - 1.0) > 1e-6:
            raise ValueError(
                f"検索ウェイトの合計は 1.0 である必要があります。現在値: {total_weight}"
            )
        return self


class SearchFilters(BaseModel):
    project: str | None = None
    memory_type: MemoryType | None = None
    top_k: int = Field(default=10, gt=0)
    max_tokens: int | None = Field(default=None, gt=0, le=100000)


class SearchResult(BaseModel):
    results: list[ScoredMemory]
    total_count: int
    strategy_used: SearchStrategy
