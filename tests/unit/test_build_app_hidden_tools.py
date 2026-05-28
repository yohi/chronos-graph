from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def policy_file(tmp_path: Path) -> Path:
    policy = tmp_path / "intents.yaml"
    policy.write_text("version: 1\noutput_filters: {}\nintents: {}\nagents: {}\n")
    return policy


def test_selective_mode_does_not_hide_memory_save(
    monkeypatch: pytest.MonkeyPatch,
    policy_file: Path,
) -> None:
    monkeypatch.delenv("CHRONOS_INGESTION_MODE", raising=False)
    monkeypatch.setenv("MCP_GATEWAY_POLICY_PATH", str(policy_file))

    from mcp_gateway.app import build_app

    app = build_app(initial_tools=[{"name": "memory_save", "description": "x"}])
    registry = app.state.tool_registry

    names = [tool["name"] for tool in registry.all_tools]
    assert "memory_save" in names


def test_all_mode_hides_memory_save(
    monkeypatch: pytest.MonkeyPatch,
    policy_file: Path,
) -> None:
    monkeypatch.setenv("CHRONOS_INGESTION_MODE", "all")
    monkeypatch.setenv("MCP_GATEWAY_POLICY_PATH", str(policy_file))

    from mcp_gateway.app import build_app

    app = build_app(
        initial_tools=[
            {"name": "memory_save", "description": "x"},
            {"name": "memory_save_url", "description": "y"},
        ]
    )
    registry = app.state.tool_registry

    names = [tool["name"] for tool in registry.all_tools]
    assert "memory_save" not in names
    assert "memory_save_url" in names
