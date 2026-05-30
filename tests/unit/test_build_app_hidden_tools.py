from __future__ import annotations

import sys
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def reload_gateway_modules() -> None:
    # キャッシュを削除して、テストごとに環境変数の変更が反映されるようにする
    for mod in list(sys.modules.keys()):
        if mod.startswith("mcp_gateway"):
            sys.modules.pop(mod, None)


@pytest.fixture
def policy_file(tmp_path: Path) -> Path:
    policy = tmp_path / "intents.yaml"
    policy.write_text("version: 1\noutput_filters: {}\nintents: {}\nagents: {}\n")
    return policy


def test_selective_mode_does_not_hide_memory_save(
    monkeypatch: pytest.MonkeyPatch,
    policy_file: Path,
) -> None:
    # ローカル .env が CHRONOS_INGESTION_MODE=all を持っていても確実に上書きするため、
    # delenv ではなく明示的に "selective" を setenv する。
    monkeypatch.setenv("CHRONOS_INGESTION_MODE", "selective")
    monkeypatch.setenv("MCP_GATEWAY_POLICY_PATH", str(policy_file))

    from mcp_gateway.app import build_app

    app = build_app(
        initial_tools=[{"name": "memory_save", "description": "x"}],
        upstream_override=object(),
    )
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
        ],
        upstream_override=object(),
    )
    registry = app.state.tool_registry

    names = [tool["name"] for tool in registry.all_tools]
    assert "memory_save" not in names
    assert "memory_save_url" in names


def test_hidden_tools_persists_after_replace(
    monkeypatch: pytest.MonkeyPatch,
    policy_file: Path,
) -> None:
    monkeypatch.setenv("CHRONOS_INGESTION_MODE", "all")
    monkeypatch.setenv("MCP_GATEWAY_POLICY_PATH", str(policy_file))

    from mcp_gateway.app import build_app

    app = build_app(
        initial_tools=[{"name": "memory_save", "description": "x"}],
        upstream_override=object(),
    )
    registry = app.state.tool_registry

    # 初期状態のチェック
    assert "memory_save" not in [t["name"] for t in registry.all_tools]

    # アップストリームが隠蔽対象を含む新しいツール一覧を提供したとシミュレート
    new_tools = [
        {"name": "memory_save", "description": "updated"},
        {"name": "other_tool", "description": "new"},
    ]
    registry.replace_tools(new_tools)

    # 置き換え後も memory_save は隠蔽されている必要がある
    names = [tool["name"] for tool in registry.all_tools]
    assert "memory_save" not in names
    assert "other_tool" in names


def test_all_mode_emits_setup_warning(
    monkeypatch: pytest.MonkeyPatch,
    policy_file: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AC-6: all モード起動時に WARNING が stderr 相当に出る。"""
    import logging

    monkeypatch.setenv("CHRONOS_INGESTION_MODE", "all")
    monkeypatch.setenv("MCP_GATEWAY_POLICY_PATH", str(policy_file))

    with caplog.at_level(logging.WARNING, logger="mcp_gateway.app"):
        from mcp_gateway.app import build_app

        build_app(
            initial_tools=[{"name": "memory_save", "description": "x"}],
            upstream_override=object(),
        )

    msgs = [r.message for r in caplog.records if r.name == "mcp_gateway.app"]
    assert any("ingestion mode: all" in m for m in msgs)
    assert any("memory_save" in m and "HIDDEN" in m for m in msgs)
    assert any("Client-side hook" in m for m in msgs)


def test_selective_mode_does_not_emit_setup_warning(
    monkeypatch: pytest.MonkeyPatch,
    policy_file: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """selective モードでは setup 警告が出ないことを検証する。"""
    import logging

    # ローカル .env が CHRONOS_INGESTION_MODE=all を持っていても上書きするため
    # delenv ではなく明示的に "selective" を setenv する。
    monkeypatch.setenv("CHRONOS_INGESTION_MODE", "selective")
    monkeypatch.setenv("MCP_GATEWAY_POLICY_PATH", str(policy_file))

    with caplog.at_level(logging.WARNING, logger="mcp_gateway.app"):
        from mcp_gateway.app import build_app

        build_app(
            initial_tools=[{"name": "memory_save", "description": "x"}],
            upstream_override=object(),
        )

    msgs = [r.message for r in caplog.records if r.name == "mcp_gateway.app"]
    assert not any("ingestion mode: all" in m for m in msgs)
