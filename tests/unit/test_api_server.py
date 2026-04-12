"""Unit tests for Dashboard API Server."""

from __future__ import annotations

from fastapi.testclient import TestClient

from context_store.dashboard.api_server import create_app


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
