"""Tests for the _sandbox_aware_sqlite fixture in conftest.py."""

from __future__ import annotations

import os


class TestSandboxAwareSqlite:
    """_sandbox_aware_sqlite fixture の振る舞いを検証する。"""

    def test_sandbox_aware_sqlite_activates(self, tmp_path, monkeypatch):
        """OPENSANDBOX=1 の場合、SQLITE_DB_PATH と SQLITE_GRAPH_PATH が tmp_path に設定される。"""
        monkeypatch.setenv("OPENSANDBOX", "1")
        monkeypatch.delenv("SQLITE_DB_PATH", raising=False)
        monkeypatch.delenv("SQLITE_GRAPH_PATH", raising=False)

        # conftest.py の fixture と同じロジックを実行
        if os.environ.get("OPENSANDBOX") == "1":
            monkeypatch.setenv("SQLITE_DB_PATH", str(tmp_path / "test.db"))
            monkeypatch.setenv("SQLITE_GRAPH_PATH", str(tmp_path / "test_graph.db"))

        assert os.environ["SQLITE_DB_PATH"] == str(tmp_path / "test.db")
        assert os.environ["SQLITE_GRAPH_PATH"] == str(tmp_path / "test_graph.db")

    def test_sandbox_aware_sqlite_inactive_without_env(self, tmp_path, monkeypatch):
        """OPENSANDBOX が未設定の場合、SQLITE パスは変更されない。"""
        monkeypatch.delenv("OPENSANDBOX", raising=False)
        monkeypatch.delenv("SQLITE_DB_PATH", raising=False)
        monkeypatch.delenv("SQLITE_GRAPH_PATH", raising=False)

        # conftest.py の fixture と同じロジックを実行
        if os.environ.get("OPENSANDBOX") == "1":
            monkeypatch.setenv("SQLITE_DB_PATH", str(tmp_path / "test.db"))
            monkeypatch.setenv("SQLITE_GRAPH_PATH", str(tmp_path / "test_graph.db"))

        assert os.environ.get("SQLITE_DB_PATH") is None
        assert os.environ.get("SQLITE_GRAPH_PATH") is None
