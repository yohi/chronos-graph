"""Tests for MCP client configuration generation script."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType


def load_generate_config(script: Path) -> ModuleType:
    """Load generate_config.py as an isolated module for testing."""
    spec = importlib.util.spec_from_file_location("generate_config_under_test", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generate_config_supports_supabase_uvx_backend(monkeypatch, capsys) -> None:
    """Supabase backend emits uvx config with Supabase env and explicit Redis cache."""
    # Pydantic Settings が .env を読み込むのを抑制
    monkeypatch.setenv("ENV_FILE", "/dev/null")
    supabase_url = "https://example.supabase.co"
    supabase_key = "test-service-role-key"
    monkeypatch.setenv("SUPABASE_URL", supabase_url)
    monkeypatch.setenv("SUPABASE_KEY", supabase_key)

    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "scripts" / "generate_config.py"
    module = load_generate_config(script)

    monkeypatch.setattr(
        "sys.argv",
        [
            "generate_config.py",
            "--backend",
            "supabase",
            "--method",
            "uvx",
            "--uv-from",
            "git+https://github.com/yohi/chronos-graph.git",
            "--ssl",
        ],
    )

    module.main()
    config = json.loads(capsys.readouterr().out)
    server = config["mcpServers"]["chronos-graph"]

    assert server["command"] == "uvx"
    assert server["args"] == [
        "--quiet",
        "--from",
        "context-store-mcp[all] @ git+https://github.com/yohi/chronos-graph.git",
        "context-store",
    ]
    env = server["env"]
    assert env["STORAGE_BACKEND"] == "supabase"
    assert env["SUPABASE_URL"] == supabase_url
    assert env["SUPABASE_KEY"] == supabase_key
    assert env["GRAPH_ENABLED"] == "false"
    assert env["CACHE_BACKEND"] == "redis"
    assert env["REDIS_SSL"] == "true"
    assert env["REDIS_URL"].startswith("rediss://")


def test_generate_config_supports_explicit_supabase_inmemory_cache(monkeypatch, capsys) -> None:
    """Supabase backend allows InMemory cache only when explicitly selected."""
    # Pydantic Settings が .env を読み込むのを抑制
    monkeypatch.setenv("ENV_FILE", "/dev/null")
    supabase_url = "https://example.supabase.co"
    supabase_key = "test-service-role-key"
    monkeypatch.setenv("SUPABASE_URL", supabase_url)
    monkeypatch.setenv("SUPABASE_KEY", supabase_key)

    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "scripts" / "generate_config.py"
    module = load_generate_config(script)

    monkeypatch.setattr(
        "sys.argv",
        [
            "generate_config.py",
            "--backend",
            "supabase",
            "--cache",
            "inmemory",
        ],
    )

    module.main()

    config = json.loads(capsys.readouterr().out)
    env = config["mcpServers"]["chronos-graph"]["env"]

    assert env["STORAGE_BACKEND"] == "supabase"
    assert env["CACHE_BACKEND"] == "inmemory"
    assert "REDIS_URL" not in env
    assert "REDIS_SSL" not in env
