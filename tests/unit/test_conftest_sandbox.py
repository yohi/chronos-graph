"""Tests for the _sandbox_aware_sqlite fixture in conftest.py."""

from __future__ import annotations

import os

import pytest


@pytest.fixture
def sandbox_aware_sqlite_env(
    clean_env,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    if request.node.name == "test_sandbox_aware_sqlite_activates":
        monkeypatch.setenv("OPENSANDBOX", "1")
    else:
        monkeypatch.delenv("OPENSANDBOX", raising=False)


class TestSandboxAwareSqlite:
    """_sandbox_aware_sqlite fixture の振る舞いを検証する。"""

    def test_sandbox_aware_sqlite_activates(self, tmp_path):
        """OPENSANDBOX=1 の場合、SQLITE_DB_PATH が tmp_path に設定される。"""
        assert os.environ["SQLITE_DB_PATH"] == str(tmp_path / "test.db")

    def test_sandbox_aware_sqlite_inactive_without_env(self, tmp_path):
        """OPENSANDBOX が未設定の場合、SQLITE パスは変更されない。"""
        assert os.environ.get("SQLITE_DB_PATH") is None
