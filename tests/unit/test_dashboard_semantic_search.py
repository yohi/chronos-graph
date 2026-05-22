"""Tests for DashboardService.semantic_search and SemanticSearchRequest schema."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from context_store.dashboard.schemas import SemanticSearchRequest
from context_store.dashboard.services import DashboardService


@pytest.mark.asyncio
async def test_semantic_search_delegates_to_retrieval_pipeline() -> None:
    fake_memory = SimpleNamespace(
        id="m-1",
        content="hello",
        memory_type="semantic",
        importance_score=0.8,
        project="demo",
        access_count=3,
        created_at=datetime(2026, 5, 11),
    )
    response = SimpleNamespace(memories=[fake_memory])
    pipeline = MagicMock()
    pipeline.search = AsyncMock(return_value=response)

    service = DashboardService(
        storage=MagicMock(),
        graph=None,
        retrieval_pipeline=pipeline,
    )

    out = await service.semantic_search(query="tool:bash command=ls", project="demo", top_k=5)

    pipeline.search.assert_awaited_once_with(query="tool:bash command=ls", project="demo", top_k=5)
    assert out == [fake_memory]


@pytest.mark.asyncio
async def test_semantic_search_raises_when_pipeline_not_configured() -> None:
    service = DashboardService(storage=MagicMock(), graph=None)
    with pytest.raises(RuntimeError, match="retrieval_pipeline"):
        await service.semantic_search(query="anything")


@pytest.mark.asyncio
async def test_semantic_search_resolves_retrieval_results_to_memories() -> None:
    fake_memory = SimpleNamespace(id="m-1")
    storage = MagicMock()
    storage.get_memories_batch = AsyncMock(return_value=[fake_memory])
    pipeline = MagicMock()
    pipeline.search = AsyncMock(return_value={"results": [{"memory_id": "m-1"}]})
    service = DashboardService(storage=storage, graph=None, retrieval_pipeline=pipeline)

    out = await service.semantic_search(query="x")

    assert out == [fake_memory]
    storage.get_memories_batch.assert_awaited_once_with(["m-1"])


def test_semantic_search_request_defaults() -> None:
    req = SemanticSearchRequest(query="x")
    assert req.project is None
    assert req.top_k == 5


@pytest.mark.parametrize(
    "field,invalid_value",
    [
        ("top_k", 0),
        ("top_k", 51),
        ("query", ""),
    ],
)
def test_semantic_search_request_validation(field: str, invalid_value: Any) -> None:
    kwargs: dict[str, Any] = {"query": "x"}
    kwargs[field] = invalid_value
    with pytest.raises(ValueError):
        SemanticSearchRequest(**kwargs)
