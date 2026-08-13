from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from context_store.dashboard.api_server import create_app
from context_store.dashboard.services import DashboardService


def test_memory_search_normalizes_project_before_storage() -> None:
    storage = MagicMock()
    storage.list_by_filter = AsyncMock(return_value=[])
    service = DashboardService(storage=storage, graph=None)
    app = create_app(service_override=service)

    with TestClient(app, base_url="http://localhost") as client:
        response = client.post(
            "/api/memories/search",
            json={"project": "/workspace/Acme-Repo"},
        )

    assert response.status_code == 200
    filters = storage.list_by_filter.await_args.args[0]
    assert filters.project == "acme-repo"


def test_semantic_search_normalizes_project_before_retrieval() -> None:
    pipeline = MagicMock()
    pipeline.search = AsyncMock(return_value=MagicMock(memories=[]))
    service = DashboardService(
        storage=MagicMock(),
        graph=None,
        retrieval_pipeline=pipeline,
    )
    app = create_app(service_override=service)

    with TestClient(app, base_url="http://localhost") as client:
        response = client.post(
            "/api/memories/semantic-search",
            json={"query": "hello", "project": "/workspace/Acme-Repo"},
        )

    assert response.status_code == 200
    pipeline.search.assert_awaited_once_with(
        query="hello",
        project="acme-repo",
        top_k=5,
    )


def test_graph_layout_normalizes_project_before_storage() -> None:
    storage = MagicMock()
    storage.count_by_filter = AsyncMock(return_value=0)
    storage.list_by_filter = AsyncMock(return_value=[])
    service = DashboardService(storage=storage, graph=None)
    app = create_app(service_override=service)

    with TestClient(app, base_url="http://localhost") as client:
        response = client.get(
            "/api/graph/layout",
            params={"project": "/workspace/Graph-Repo"},
        )

    assert response.status_code == 200
    count_filters = storage.count_by_filter.await_args.args[0]
    list_filters = storage.list_by_filter.await_args.args[0]
    assert count_filters.project == "graph-repo"
    assert list_filters.project == "graph-repo"
