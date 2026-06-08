"""Tests for the _sandbox_aware_sqlite fixture in conftest.py."""

from __future__ import annotations

import os

import pytest


@pytest.fixture
def sandbox_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """OPENSANDBOX=1 を設定するフィクスチャ。"""
    monkeypatch.setenv("OPENSANDBOX", "1")


@pytest.fixture
def no_sandbox_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """OPENSANDBOX が未設定の状態を保証するフィクスチャ。"""
    monkeypatch.delenv("OPENSANDBOX", raising=False)

class TestSandboxAwareSqlite:
    """_sandbox_aware_sqlite fixture の振る舞いを検証する。"""

    def test_sandbox_aware_sqlite_activates(self, tmp_path, clean_env, sandbox_env):
        """OPENSANDBOX=1 の場合、SQLITE_DB_PATH が tmp_path に設定される。"""
        assert os.environ["SQLITE_DB_PATH"] == str(tmp_path / "test.db")

    def test_sandbox_aware_sqlite_inactive_without_env(self, tmp_path, clean_env, no_sandbox_env):
        """OPENSANDBOX が未設定の場合、SQLITE パスは変更されない。"""
        assert os.environ.get("SQLITE_DB_PATH") is None
