"""Unit tests for Dashboard Logs API."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from context_store.dashboard.api_server import create_app
from context_store.dashboard.log_collector import LogCollectorHandler


def test_get_recent_logs_format():
    """Verify that GET /api/logs/recent returns { "entries": [...] }."""
    app = create_app()
    client = TestClient(app, base_url="http://localhost")

    # Mock the LogCollectorHandler to return predictable logs
    mock_handler = MagicMock(spec=LogCollectorHandler)
    mock_handler.get_recent.return_value = [
        {
            "timestamp": "2026-04-14T10:00:00Z",
            "level": "INFO",
            "logger": "test",
            "message": "test message",
        }
    ]

    # Patch the global get_log_handler to return our mock
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("context_store.dashboard.routes.logs.get_log_handler", lambda: mock_handler)

        response = client.get("/api/logs/recent?limit=10")
        assert response.status_code == 200
        data = response.json()

        # Verify the shape: must have "entries" key and be a list
        assert "entries" in data
        assert isinstance(data["entries"], list)
        assert len(data["entries"]) == 1
        assert data["entries"][0]["message"] == "test message"
        # Verify camelCase conversion (DashboardBaseModel uses to_camel)
        assert data["entries"][0]["timestamp"] == "2026-04-14T10:00:00Z"


def test_get_recent_logs_limit_constraints():
    """Verify limit constraints for /api/logs/recent."""
    app = create_app()
    client = TestClient(app, base_url="http://localhost")

    # ge=1 constraint
    response = client.get("/api/logs/recent?limit=0")
    assert response.status_code == 422

    # le=1000 constraint
    response = client.get("/api/logs/recent?limit=1001")
    assert response.status_code == 422
