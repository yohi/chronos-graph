"""Unit tests for DashboardService (PR 5)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from context_store.dashboard.services import DashboardService
from context_store.models.graph import Edge
from context_store.models.memory import Memory


@pytest.fixture
def storage_mock():
    return AsyncMock()


@pytest.fixture
def graph_mock():
    return AsyncMock()


@pytest.mark.asyncio
async def test_get_stats_summary_aggregates_counts(storage_mock, graph_mock):
    storage_mock.count_by_filter.side_effect = [120, 30, 150]
    storage_mock.list_projects.return_value = ["p1", "p2"]
    graph_mock.count_edges.return_value = 42

    svc = DashboardService(storage=storage_mock, graph=graph_mock)
    stats = await svc.get_stats_summary()

    assert stats.active_count == 120
    assert stats.archived_count == 30
    assert stats.total_count == 150
    assert stats.edge_count == 42
    assert stats.project_count == 2
    assert stats.projects == ["p1", "p2"]

    # Verify calls

    calls = storage_mock.count_by_filter.call_args_list
    assert calls[0].args[0].archived is None  # active
    assert calls[1].args[0].archived is True  # archived
    assert calls[2].args[0].archived is False  # total


@pytest.mark.asyncio
async def test_get_stats_summary_graph_none(storage_mock):
    storage_mock.count_by_filter.side_effect = [10, 0, 10]
    storage_mock.list_projects.return_value = []
    svc = DashboardService(storage=storage_mock, graph=None)
    stats = await svc.get_stats_summary()
    assert stats.edge_count == 0


@pytest.mark.asyncio
async def test_get_graph_layout_returns_cytoscape_format(storage_mock, graph_mock):
    storage_mock.count_by_filter.return_value = 2

    m1 = MagicMock(spec=Memory)
    m1.id = UUID("550e84c0-5ec0-4b1a-b3e1-123456789abc")
    m1.content = "test 1"
    m1.memory_type = "episodic"
    m1.importance_score = 0.8
    m1.project = "p1"
    m1.access_count = 3
    m1.created_at = None

    m2 = MagicMock(spec=Memory)
    m2.id = UUID("550e84c0-5ec0-4b1a-b3e2-123456789abc")
    m2.content = "test 2"
    m2.memory_type = "semantic"
    m2.importance_score = 0.6
    m2.project = "p1"
    m2.access_count = 1
    m2.created_at = None

    storage_mock.list_by_filter.return_value = [m1, m2]

    e1 = Edge(
        from_id="550e84c0-5ec0-4b1a-b3e1-123456789abc",
        to_id="550e84c0-5ec0-4b1a-b3e2-123456789abc",
        edge_type="RELATED",
        properties={},
    )
    graph_mock.list_edges_for_memories.return_value = [e1]

    svc = DashboardService(storage=storage_mock, graph=graph_mock)
    resp = await svc.get_graph_layout(project="p1", limit=500)

    assert resp.returned_nodes == 2
    assert resp.total_edges == 1
    assert len(resp.elements.nodes) == 2
    assert len(resp.elements.edges) == 1
    first_node = resp.elements.nodes[0]
    assert "data" in first_node

    # Verify filters

    storage_mock.list_by_filter.assert_called_once()
    filters = storage_mock.list_by_filter.call_args.args[0]
    assert filters.archived is None  # Active only


@pytest.mark.asyncio
async def test_traverse_graph_raises_without_graph_backend(storage_mock):
    svc = DashboardService(storage=storage_mock, graph=None)
    with pytest.raises(RuntimeError, match="graph backend"):
        await svc.traverse_graph("m1")


@pytest.mark.asyncio
async def test_get_project_stats(storage_mock, graph_mock):
    storage_mock.list_projects.return_value = ["p1"]
    storage_mock.count_by_filter.side_effect = [10, 2, 12]
    svc = DashboardService(storage=storage_mock, graph=graph_mock)
    stats = await svc.get_project_stats()
    assert len(stats) == 1
    assert stats[0].project == "p1"
    assert stats[0].active_count == 10
    assert stats[0].archived_count == 2
    assert stats[0].total_count == 12

    calls = storage_mock.count_by_filter.call_args_list
    assert calls[0].args[0].archived is None  # active
    assert calls[1].args[0].archived is True  # archived
    assert calls[2].args[0].archived is False  # total


@pytest.mark.asyncio
async def test_get_memory_returns_memory_from_storage(storage_mock):
    m1 = MagicMock(spec=Memory)
    m1.id = UUID("550e84c0-5ec0-4b1a-b3e1-123456789abc")
    storage_mock.get_memory.return_value = m1

    svc = DashboardService(storage=storage_mock, graph=None)
    memory = await svc.get_memory(str(m1.id))

    assert memory == m1
    storage_mock.get_memory.assert_called_once_with(str(m1.id))


@pytest.mark.asyncio
async def test_get_recent_logs_returns_actual_logs(storage_mock):
    from context_store.logger import get_logger

    logger_name = f"test_logger_{uuid4().hex}"
    logger = get_logger(logger_name)
    logger.info("Test log message 1")
    logger.warning("Test log message 2")

    svc = DashboardService(storage=storage_mock, graph=None)
    logs = await svc.get_recent_logs(limit=10)

    # Filter only logs from our unique logger
    test_logs = [log for log in logs if log.logger == logger_name]
    assert len(test_logs) >= 2
    assert test_logs[-2].message == "Test log message 1"
    assert test_logs[-2].level == "INFO"
    assert test_logs[-1].message == "Test log message 2"
    assert test_logs[-1].level == "WARNING"
    assert test_logs[-1].timestamp is not None


@pytest.mark.asyncio
async def test_get_graph_layout_converts_id_to_str(storage_mock):
    """Verify that DashboardService.get_graph_layout converts UUID to string for Cytoscape."""
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
