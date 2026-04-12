"""Unit tests for fixes suggested by CodeRabbitAI and GreptileAI."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from context_store.dashboard.api_server import create_app
from context_store.dashboard.services import DashboardService
from context_store.models.memory import Memory, MemoryType, SourceType
from context_store.storage.protocols import MemoryFilters


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app):
    return TestClient(app, base_url="http://localhost")


# ---------------------------------------------------------------------------
# API Limit Constraints Tests
# ---------------------------------------------------------------------------


def test_get_graph_layout_limit_constraints(client):
    """Verify that /api/graph/layout limit has ge=1, le=2000 constraints."""
    response = client.get("/api/graph/layout?limit=0")
    assert response.status_code == 422

    response = client.get("/api/graph/layout?limit=2001")
    assert response.status_code == 422


def test_get_logs_limit_constraints(client):
    """Verify that /api/logs/ limit has ge=1, le=1000 constraints."""
    response = client.get("/api/logs/?limit=0")
    assert response.status_code == 422

    response = client.get("/api/logs/?limit=1001")
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Exception Handling Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_traverse_graph_503_on_runtime_error(app):
    """Verify that /api/graph/{id}/traverse returns 503 on RuntimeError (no backend)."""
    mock_service = MagicMock(spec=DashboardService)
    mock_service.traverse_graph = AsyncMock(side_effect=RuntimeError("No graph backend"))

    app.state.service = mock_service
    client = TestClient(app, base_url="http://localhost")

    response = client.post("/api/graph/test-id/traverse", json={"max_depth": 1})
    assert response.status_code == 503


# ---------------------------------------------------------------------------
# DashboardService ID String Conversion Test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_graph_layout_converts_id_to_str():
    """Verify that DashboardService.get_graph_layout converts UUID to string for Cytoscape."""
    storage_mock = AsyncMock()
    storage_mock.count_by_filter.return_value = 1

    m1 = MagicMock(spec=Memory)
    m1.id = UUID("550e84c0-5ec0-4b1a-b3e1-123456789abc")
    m1.content = "test content"
    m1.memory_type = "episodic"
    m1.importance_score = 0.8
    m1.project = "p1"
    m1.access_count = 1
    m1.created_at = None

    storage_mock.list_by_filter.return_value = [m1]

    svc = DashboardService(storage=storage_mock, graph=None)
    resp = await svc.get_graph_layout()

    node_id = resp.elements.nodes[0]["data"]["id"]
    assert isinstance(node_id, str)
    assert node_id == "550e84c0-5ec0-4b1a-b3e1-123456789abc"


# ---------------------------------------------------------------------------
# Storage Offset/MinImportance Tests
# ---------------------------------------------------------------------------


@pytest.fixture
async def sqlite_adapter(tmp_path):
    from context_store.config import Settings
    from context_store.storage.sqlite import SQLiteStorageAdapter

    db_path = str(tmp_path / "test.db")
    settings = Settings(
        sqlite_db_path=db_path,
        embedding_provider="local-model",
        local_model_name="test",
    )
    adp = await SQLiteStorageAdapter.create(settings)
    yield adp
    await adp.dispose()


@pytest.mark.asyncio
async def test_sqlite_list_by_filter_offset(sqlite_adapter):
    """Verify that offset works in SQLite list_by_filter."""
    for i in range(3):
        m = Memory(
            id=uuid4(),
            content=f"content {i}",
            memory_type=MemoryType.EPISODIC,
            source_type=SourceType.MANUAL,
            importance_score=0.5,
        )
        await sqlite_adapter.save_memory(m)

    filters = MemoryFilters(limit=1, offset=1, order_by="importance_score ASC")
    results = await sqlite_adapter.list_by_filter(filters)

    assert len(results) == 1
    assert results[0].content == "content 1"


@pytest.mark.asyncio
async def test_sqlite_list_by_filter_min_importance(sqlite_adapter):
    """Verify that min_importance filter works in SQLite list_by_filter."""
    m1 = Memory(
        id=uuid4(),
        content="low",
        importance_score=0.1,
        memory_type=MemoryType.EPISODIC,
        source_type=SourceType.MANUAL,
    )
    m2 = Memory(
        id=uuid4(),
        content="med",
        importance_score=0.5,
        memory_type=MemoryType.EPISODIC,
        source_type=SourceType.MANUAL,
    )
    m3 = Memory(
        id=uuid4(),
        content="high",
        importance_score=0.9,
        memory_type=MemoryType.EPISODIC,
        source_type=SourceType.MANUAL,
    )

    await sqlite_adapter.save_memory(m1)
    await sqlite_adapter.save_memory(m2)
    await sqlite_adapter.save_memory(m3)

    filters = MemoryFilters(min_importance=0.7)
    results = await sqlite_adapter.list_by_filter(filters)

    assert len(results) == 1
    assert results[0].content == "high"
    assert results[0].importance_score == 0.9


@pytest.mark.asyncio
async def test_postgres_list_by_filter_min_importance_offset():
    """Verify min_importance and offset logic in PostgreSQL."""
    from context_store.storage.postgres import PostgresStorageAdapter

    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = AsyncMock()

    adapter = PostgresStorageAdapter(mock_pool)
    filters = MemoryFilters(min_importance=0.7, offset=10, limit=5)

    await adapter.list_by_filter(filters)

    conn = mock_pool.acquire.return_value.__aenter__.return_value
    args, _ = conn.fetch.call_args
    sql = args[0]

    assert "importance_score >= $1" in sql
    assert "OFFSET $3" in sql or "OFFSET $2" in sql
    assert 0.7 in args
    assert 10 in args
    assert 5 in args
