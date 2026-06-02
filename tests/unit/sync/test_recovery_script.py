"""sync_storage_to_neo4j.py のスモークテスト。"""

from __future__ import annotations

import pathlib
import sys
from typing import Any

import pytest


@pytest.fixture
def script_path() -> pathlib.Path:
    root = pathlib.Path(__file__).resolve().parents[3]
    return root / "scripts" / "sync_storage_to_neo4j.py"


@pytest.fixture
def recovery_module(script_path: pathlib.Path) -> object:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "sync_storage_to_neo4j",
        str(script_path.resolve()),
    )
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_main_requires_mode_flag(
    recovery_module: Any, script_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """引数なしで実行すると SystemExit が発生する。"""
    monkeypatch.setattr(sys, "argv", [str(script_path)])
    with pytest.raises(SystemExit):
        recovery_module.main()


def test_confirm_full_returns_true_with_yes_flag(recovery_module: Any) -> None:
    result = recovery_module._confirm_full(assume_yes=True)
    assert result is True
