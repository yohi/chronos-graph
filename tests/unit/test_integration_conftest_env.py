from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager


@contextmanager
def _reloaded_integration_conftest():
    integration_conftest = sys.modules.get("tests.integration.conftest")
    original_values = None
    if integration_conftest is not None:
        original_values = {
            name: getattr(integration_conftest, name)
            for name in ("PG_HOST", "PG_PORT", "PG_DB", "PG_USER", "PG_PASSWORD")
        }
    else:
        integration_conftest = importlib.import_module("tests.integration.conftest")
    try:
        yield importlib.reload(integration_conftest)
    finally:
        if original_values is not None:
            for name, value in original_values.items():
                setattr(integration_conftest, name, value)


def test_postgres_env_takes_precedence_over_legacy_pg_env(monkeypatch):
    monkeypatch.setenv("POSTGRES_HOST", "host.docker.internal")
    monkeypatch.setenv("POSTGRES_PORT", "5435")
    monkeypatch.setenv("POSTGRES_DB", "context_store_test")
    monkeypatch.setenv("POSTGRES_USER", "context_store")
    monkeypatch.setenv("POSTGRES_PASSWORD", "dev_password")
    monkeypatch.setenv("PG_HOST", "localhost")
    monkeypatch.setenv("PG_PORT", "15432")
    monkeypatch.setenv("PG_DB", "context_store")
    monkeypatch.setenv("PG_USER", "legacy_user")
    monkeypatch.setenv("PG_PASSWORD", "legacy_password")

    with _reloaded_integration_conftest() as integration_conftest:
        assert integration_conftest.PG_HOST == "host.docker.internal"
        assert integration_conftest.PG_PORT == 5435
        assert integration_conftest.PG_DB == "context_store_test"
        assert integration_conftest.PG_USER == "context_store"
        assert integration_conftest.PG_PASSWORD == "dev_password"


def test_legacy_pg_env_still_supported(monkeypatch):
    monkeypatch.delenv("POSTGRES_HOST", raising=False)
    monkeypatch.delenv("POSTGRES_PORT", raising=False)
    monkeypatch.delenv("POSTGRES_DB", raising=False)
    monkeypatch.delenv("POSTGRES_USER", raising=False)
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    monkeypatch.setenv("PG_HOST", "legacy-host")
    monkeypatch.setenv("PG_PORT", "15432")
    monkeypatch.setenv("PG_DB", "legacy_db")
    monkeypatch.setenv("PG_USER", "legacy_user")
    monkeypatch.setenv("PG_PASSWORD", "legacy_password")

    with _reloaded_integration_conftest() as integration_conftest:
        assert integration_conftest.PG_HOST == "legacy-host"
        assert integration_conftest.PG_PORT == 15432
        assert integration_conftest.PG_DB == "legacy_db"
        assert integration_conftest.PG_USER == "legacy_user"
        assert integration_conftest.PG_PASSWORD == "legacy_password"
