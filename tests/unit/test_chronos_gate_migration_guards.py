from __future__ import annotations

import re
from pathlib import Path
from typing import ClassVar

import pytest
from pydantic import BaseModel, ConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class PackageJson(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    name: str
    main: str
    files: list[str]


def test_package_exports_only_turn_end_opencode_plugin() -> None:
    package_json = PackageJson.model_validate_json(
        (REPO_ROOT / "package.json").read_text(encoding="utf-8")
    )

    assert package_json.name == "@yohi/opencode-plugin-chronos-turn-end"
    assert package_json.main == "./.opencode/plugins/chronos-turn-end.js"
    assert package_json.files == [
        ".opencode/plugins/chronos-turn-end.js",
        "README.md",
        "LICENSE",
    ]


def test_legacy_security_evaluator_entrypoints_are_absent() -> None:
    assert not (REPO_ROOT / "src" / "mcp_gateway").exists()
    assert not (REPO_ROOT / ".opencode" / "plugins" / "chronos-gate.js").exists()
    assert not (REPO_ROOT / "scripts" / "chronos-evaluator-hook.sh").exists()
    assert not (REPO_ROOT / "scripts" / "check_evaluator.sh").exists()


def test_no_runtime_references_to_legacy_security_evaluator() -> None:
    scanned_suffixes = {".py", ".js", ".json", ".toml"}
    runtime_roots = [
        REPO_ROOT / "src",
        REPO_ROOT / "scripts",
        REPO_ROOT / ".opencode" / "plugins",
        REPO_ROOT / "package.json",
        REPO_ROOT / "pyproject.toml",
    ]
    legacy_pattern = re.compile(r"mcp_gateway|permission\.ask|chronos-mcp-gateway")

    matches: list[str] = []
    for root in runtime_roots:
        paths = [root] if root.is_file() else root.rglob("*")
        for path in paths:
            if not path.is_file() or path.suffix not in scanned_suffixes:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if legacy_pattern.search(text):
                matches.append(str(path.relative_to(REPO_ROOT)))

    assert matches == []


def test_turn_end_plugin_ingestion_mode_constants_match_chronos_shared() -> None:
    chronos_shared_ingestion_mode = pytest.importorskip(
        "chronos_shared.ingestion_mode",
        reason="chronos_shared is not installed; skipping SSOT consistency check",
    )
    CHRONOS_INGESTION_MODE_ENV = chronos_shared_ingestion_mode.CHRONOS_INGESTION_MODE_ENV
    DEFAULT_INGESTION_MODE = chronos_shared_ingestion_mode.DEFAULT_INGESTION_MODE

    plugin_text = (REPO_ROOT / ".opencode" / "plugins" / "chronos-turn-end.js").read_text(
        encoding="utf-8"
    )
    assert "CHRONOS_SHARED_SSOT_GUARD" in plugin_text
    env_pattern = rf"\bINGESTION_MODE_ENV\s*=\s*'{CHRONOS_INGESTION_MODE_ENV}'"
    default_pattern = rf"\bDEFAULT_INGESTION_MODE\s*=\s*'{DEFAULT_INGESTION_MODE}'"
    assert re.search(env_pattern, plugin_text) is not None
    assert re.search(default_pattern, plugin_text) is not None
