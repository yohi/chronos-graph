from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from agent_assets.bundle import build_bundle, compute_bundle_digest  # noqa: E402
from agent_assets.cli import _parse_sync_args, main  # noqa: E402
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


def test_bundle_digest_uses_nul_delimited_records(tmp_path: Path) -> None:
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    (asset_root / "a").write_bytes(b"b")
    (asset_root / "c").write_bytes(b"d")

    expected = hashlib.sha256(b"a\x00b\x00c\x00d\x00").hexdigest()

    assert compute_bundle_digest(asset_root) == expected


def test_main_redacts_plugin_registry_prerequisite_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", classmethod(lambda _: home))

    result = main(
        [
            "sync",
            "--repo-root",
            str(REPO_ROOT),
            "--mode",
            "production",
            "--ingestion-mode",
            "all",
            "--agent",
            "opencode",
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert captured.out == ""
    assert captured.err == "preflight:reject:.:registry-probe-credential\n"
    assert str(home) not in captured.err


def test_main_redacts_agent_selection_errors(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = main(["canonicalize", "--agents", "notcodex"])

    captured = capsys.readouterr()
    assert result == 2
    assert captured.out == ""
    assert captured.err == "canonicalize:reject:.:unsupported-agent\n"


def test_main_redacts_apply_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from agent_assets.transaction import ApplyError, RollbackResult

    def raise_apply_error(_request: object) -> int:
        raise ApplyError("verification-failed", RollbackResult(True))

    monkeypatch.setattr("agent_assets.cli.run_sync", raise_apply_error)

    result = main(
        [
            "sync",
            "--repo-root",
            str(REPO_ROOT),
            "--mode",
            "production",
            "--ingestion-mode",
            "selective",
            "--agent",
            "claudecode",
        ]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert captured.err == "apply:reject:.:verification-failed:rollback=None\n"


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
