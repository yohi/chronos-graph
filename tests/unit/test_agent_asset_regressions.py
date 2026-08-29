from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from agent_assets.bundle import build_bundle, compute_bundle_digest  # noqa: E402
from agent_assets.cli import _parse_sync_args  # noqa: E402
from agent_assets.models import (  # noqa: E402
    AgentId,
    ExecutionMode,
    IngestionMode,
    SyncRequest,
    adapter_for,
)


def test_adapter_for_uses_codex_home_for_instructions(tmp_path: Path) -> None:
    adapter = adapter_for(AgentId.CODEX, tmp_path)

    assert adapter.skills_root == tmp_path / ".agents" / "skills"
    assert adapter.instructions_path == tmp_path / ".codex" / "AGENTS.md"
    assert adapter.instructions_root == tmp_path / ".codex"


def test_parse_sync_args_uses_home_based_codex_home_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", classmethod(lambda _: home))
    monkeypatch.delenv("CODEX_HOME", raising=False)

    request = _parse_sync_args(
        [
            "sync",
            "--repo-root",
            str(tmp_path),
            "--mode",
            "dry-run",
            "--ingestion-mode",
            "selective",
            "--agent",
            "codex",
        ]
    )

    assert request.home == home
    assert request.codex_home == home / ".codex"


def test_parse_sync_args_preserves_custom_codex_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    codex_home = tmp_path / "custom-codex"
    monkeypatch.setattr(Path, "home", classmethod(lambda _: home))
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    request = _parse_sync_args(
        [
            "sync",
            "--repo-root",
            str(tmp_path),
            "--mode",
            "dry-run",
            "--ingestion-mode",
            "selective",
            "--agent",
            "codex",
        ]
    )

    assert request.home == home
    assert request.codex_home == codex_home
    adapter = adapter_for(AgentId.CODEX, request.home, request.codex_home)
    assert adapter.instructions_path == codex_home / "AGENTS.md"

    from agent_assets.preflight import preflight

    plan = preflight(request, build_bundle(REPO_ROOT / "agent-assets"))
    assert plan.targets[0].path == codex_home / "AGENTS.md"


def test_bundle_digest_distinguishes_ambiguous_nul_separated_records(
    tmp_path: Path,
) -> None:
    first_root = tmp_path / "first"
    first_root.mkdir()
    (first_root / "a").write_bytes(b"b")
    (first_root / "c").write_bytes(b"d")

    second_root = tmp_path / "second"
    second_root.mkdir()
    (second_root / "a").write_bytes(b"b\x00c\x00d")

    assert compute_bundle_digest(first_root) != compute_bundle_digest(second_root)


def test_apply_sync_stages_each_target_locally_and_cleans_staging_roots(
    tmp_path: Path,
) -> None:
    from agent_assets.preflight import preflight
    from agent_assets.transaction import SystemFileOperations, apply_sync

    home = tmp_path / "home"
    request = SyncRequest(
        command="sync",
        repo_root=REPO_ROOT,
        home=home,
        mode=ExecutionMode.PRODUCTION,
        ingestion_mode=IngestionMode.SELECTIVE,
        agent_ids=(AgentId.CLAUDECODE,),
    )
    plan = preflight(request, build_bundle(REPO_ROOT / "agent-assets"))
    operations = SystemFileOperations()
    replacements: list[tuple[Path, Path]] = []
    original_replace = operations.replace

    def record_replace(source: Path, destination: Path) -> None:
        replacements.append((source, destination))
        original_replace(source, destination)

    operations.replace = record_replace
    apply_sync(plan, operations)

    assert replacements
    for source, destination in replacements:
        assert source.parent.parent == destination.parent
        assert not source.parent.exists()
