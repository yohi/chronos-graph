"""Unit tests for Dashboard API Server."""

from __future__ import annotations

from pathlib import Path
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


# ---------------------------------------------------------------------------
# SPA Fallback & Security Tests
# ---------------------------------------------------------------------------


def test_spa_fallback_path_traversal(tmp_path):
    """Verify that SPA fallback prevents path traversal."""
    # Create a mock dist directory
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("index_content")
    (dist / "favicon.ico").write_text("icon_content")

    # Create a sensitive file outside dist
    secret = tmp_path / "secret.txt"
    secret.write_text("secret_content")

    app = create_app(frontend_dist_override=dist)
    client = TestClient(app, base_url="http://localhost")

    # 1. Normal file request should work
    response = client.get("/favicon.ico")
    assert response.status_code == 200
    assert response.text == "icon_content"

    # 2. Non-existent file should fallback to index.html
    response = client.get("/no-exist.html")
    assert response.status_code == 200
    assert response.text == "index_content"

    # 3. Path traversal attempt should NOT return the secret file
    # Starlette/FastAPI will decode %2e%2e/%2e%2e to ../../
    # We test if it escapes the dist root.
    response = client.get("/../secret.txt")
    # It should either return index.html (fallback) or 404/400, but NOT the secret.
    # In our implementation, if it's not relative to dist, it passes through to index_file check.
    assert response.text != "secret_content"
    assert response.text == "index_content"

    # Test with double dots encoded
    response = client.get("/%2e%2e/secret.txt")
    assert response.text != "secret_content"
    assert response.text == "index_content"
