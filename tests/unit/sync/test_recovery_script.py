"""sync_storage_to_neo4j.py のスモークテスト。"""

from __future__ import annotations

import pathlib
import pytest


def test_main_requires_mode_flag() -> None:
    """引数なしで実行すると SystemExit が発生する。"""
    import importlib
    import importlib.util

    script_path = pathlib.Path(__file__).parent.parent.parent.parent / "scripts" / "sync_storage_to_neo4j.py"
    spec = importlib.util.spec_from_file_location(
        "sync_storage_to_neo4j",
        str(script_path.resolve()),
    )
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    with pytest.raises(SystemExit):
        mod.main()


def test_confirm_full_returns_true_with_yes_flag() -> None:
    import importlib.util

    script_path = pathlib.Path(__file__).parent.parent.parent.parent / "scripts" / "sync_storage_to_neo4j.py"
    spec = importlib.util.spec_from_file_location(
        "sync_storage_to_neo4j",
        str(script_path.resolve()),
    )
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    result = mod._confirm_full(assume_yes=True)
    assert result is True
