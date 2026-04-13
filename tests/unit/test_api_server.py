"""Unit tests for Dashboard API Server."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from context_store.dashboard.api_server import create_app
from context_store.dashboard.services import DashboardService


def test_cors_origins_from_settings(monkeypatch):
    """Verify that CORSMiddleware uses origins from Settings."""
    monkeypatch.setenv("DASHBOARD_CORS_ORIGINS", "http://custom-origin.com,http://another.com")

    app = create_app()
    # Check middleware via its presence in the app's user_middleware list
    cors_mw = None
    for mw in app.user_middleware:
        if "CORSMiddleware" in str(mw.cls):
            cors_mw = mw
            break

    assert cors_mw is not None
    # Middleware configuration is in .kwargs
    assert cors_mw.kwargs["allow_origins"] == ["http://custom-origin.com", "http://another.com"]


def test_delete_endpoint_removed():
    """Verify that DELETE /api/memories/{id} is no longer available."""
    app = create_app()
    client = TestClient(app, base_url="http://localhost")

    # We removed the DELETE route. Since GET still exists on this path,
    # FastAPI returns 405 Method Not Allowed.
    response = client.delete("/api/memories/test-id")
    assert response.status_code == 405


# ---------------------------------------------------------------------------
# API Limit Constraints Tests
# ---------------------------------------------------------------------------


def test_get_graph_layout_limit_constraints():
    """Verify that /api/graph/layout limit has ge=1, le=2000 constraints."""
    app = create_app()
    client = TestClient(app, base_url="http://localhost")

    response = client.get("/api/graph/layout?limit=0")
    assert response.status_code == 422

    response = client.get("/api/graph/layout?limit=2001")
    assert response.status_code == 422


def test_get_logs_limit_constraints():
    """Verify that /api/logs/ limit has ge=1, le=1000 constraints."""
    app = create_app()
    client = TestClient(app, base_url="http://localhost")

    response = client.get("/api/logs/?limit=0")
    assert response.status_code == 422

    response = client.get("/api/logs/?limit=1001")
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Exception Handling Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_traverse_graph_503_on_runtime_error():
    """Verify that /api/graph/{id}/traverse returns 503 on RuntimeError (no backend)."""
    app = create_app()
    mock_service = MagicMock(spec=DashboardService)
    mock_service.traverse_graph = AsyncMock(side_effect=RuntimeError("No graph backend"))

    app.state.service = mock_service
    client = TestClient(app, base_url="http://localhost")

    response = client.post("/api/graph/test-id/traverse", json={"max_depth": 1})
    assert response.status_code == 503
