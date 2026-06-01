"""Settings / GatewaySettings ingestion_mode and env passthrough tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from chronos_shared.ingestion_mode import (
    CHRONOS_INGESTION_MODE_ENV,
    DEFAULT_INGESTION_MODE,
    IngestionMode,
)
from mcp_gateway.config import GatewaySettings
from mcp_gateway.upstream.context_store_client import build_upstream_env


@pytest.fixture
def policy_file(tmp_path: Path) -> Path:
    """GatewaySettings.policy_path requires an existing file."""
    path = tmp_path / "policy.yaml"
    path.write_text("version: 1\nallow: []\n", encoding="utf-8")
    return path


def test_context_store_settings_defaults_to_selective(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When env is unset, context_store uses the shared selective default."""
    monkeypatch.delenv(CHRONOS_INGESTION_MODE_ENV, raising=False)
    from context_store.config import Settings

    settings = Settings(_env_file=None)
    assert settings.ingestion_mode == "selective"
    assert settings.ingestion_mode == DEFAULT_INGESTION_MODE


def test_context_store_settings_reads_all_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CHRONOS_INGESTION_MODE_ENV, "all")
    from context_store.config import Settings

    settings = Settings(_env_file=None)
    assert settings.ingestion_mode == "all"


def test_context_store_settings_rejects_invalid_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CHRONOS_INGESTION_MODE_ENV, "invalid_value")
    from context_store.config import Settings

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_gateway_settings_defaults_to_selective(
    monkeypatch: pytest.MonkeyPatch, policy_file: Path
) -> None:
    monkeypatch.delenv(CHRONOS_INGESTION_MODE_ENV, raising=False)
    settings = GatewaySettings(policy_path=policy_file, _env_file=None)
    assert settings.ingestion_mode == "selective"
    assert settings.ingestion_mode == DEFAULT_INGESTION_MODE


def test_gateway_settings_reads_all_from_env(
    monkeypatch: pytest.MonkeyPatch, policy_file: Path
) -> None:
    monkeypatch.setenv(CHRONOS_INGESTION_MODE_ENV, "all")
    settings = GatewaySettings(policy_path=policy_file, _env_file=None)
    assert settings.ingestion_mode == "all"


def test_gateway_settings_rejects_invalid_value(
    monkeypatch: pytest.MonkeyPatch, policy_file: Path
) -> None:
    monkeypatch.setenv(CHRONOS_INGESTION_MODE_ENV, "invalid_value")
    with pytest.raises(ValidationError):
        GatewaySettings(policy_path=policy_file, _env_file=None)


def test_gateway_upstream_passthrough_includes_ingestion_mode(policy_file: Path) -> None:
    """AC-10: default passthrough includes CHRONOS_INGESTION_MODE."""
    settings = GatewaySettings(policy_path=policy_file, _env_file=None)
    assert CHRONOS_INGESTION_MODE_ENV in settings.upstream_env_passthrough


def test_build_upstream_env_propagates_ingestion_mode(policy_file: Path) -> None:
    """AC-10: build_upstream_env passes CHRONOS_INGESTION_MODE downstream."""
    settings = GatewaySettings(policy_path=policy_file, _env_file=None)
    base = {
        "PATH": "dummy-path",
        "OPENAI_API_KEY": "dummy",
        CHRONOS_INGESTION_MODE_ENV: "all",
        "UNRELATED": "should-be-filtered",
    }

    env = build_upstream_env(passthrough=settings.upstream_env_passthrough, base_env=base)

    assert env[CHRONOS_INGESTION_MODE_ENV] == "all"
    assert "UNRELATED" not in env


def test_both_settings_use_same_ssot_type(
    monkeypatch: pytest.MonkeyPatch, policy_file: Path
) -> None:
    """AC-9: both settings expose values compatible with the shared IngestionMode."""
    monkeypatch.setenv(CHRONOS_INGESTION_MODE_ENV, "all")
    from context_store.config import Settings

    context_settings = Settings(_env_file=None)
    gateway_settings = GatewaySettings(policy_path=policy_file, _env_file=None)
    value_context: IngestionMode = context_settings.ingestion_mode
    value_gateway: IngestionMode = gateway_settings.ingestion_mode
    assert value_context == value_gateway == "all"
