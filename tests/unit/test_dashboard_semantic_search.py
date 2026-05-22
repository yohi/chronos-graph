"""Tests for DashboardService.semantic_search and SemanticSearchRequest schema."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from context_store.dashboard.api_server import create_app
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


def test_semantic_search_endpoint_returns_memories() -> None:
    fake_memory = SimpleNamespace(
        id="m-1",
        content="hello",
        memory_type="semantic",
        importance_score=0.8,
        project="demo",
        access_count=3,
        created_at=datetime(2026, 5, 11),
    )
    pipeline = MagicMock()
    pipeline.search = AsyncMock(return_value=SimpleNamespace(memories=[fake_memory]))

    service = DashboardService(storage=MagicMock(), graph=None, retrieval_pipeline=pipeline)
    app = create_app(service_override=service)

    with TestClient(app, base_url="http://localhost") as client:
        response = client.post(
            "/api/memories/semantic-search",
            json={"query": "tool:bash command=ls", "project": "demo", "top_k": 3},
        )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["content"] == "hello"
    pipeline.search.assert_awaited_once()


def test_semantic_search_endpoint_returns_503_when_pipeline_missing() -> None:
    service = DashboardService(storage=MagicMock(), graph=None)
    app = create_app(service_override=service)
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post("/api/memories/semantic-search", json={"query": "x"})
    assert response.status_code == 503
