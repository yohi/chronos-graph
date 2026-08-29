from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from agent_assets.bundle import (  # noqa: E402
    AssetValidationError,
    build_bundle,
    render_managed_block,
)
from agent_assets.cli import main  # noqa: E402
from agent_assets.models import (  # noqa: E402
    AgentId,
    AgentSelectionError,
    ExecutionMode,
    IngestionMode,
    SyncRequest,
    adapter_for,
    parse_agent_csv,
)


def test_parse_agent_csv_normalizes_order_and_removes_duplicates() -> None:
    result = parse_agent_csv(" opencode , claudecode , codex , opencode ")

    assert result == (
        AgentId.CLAUDECODE,
        AgentId.CODEX,
        AgentId.OPENCODE,
    )


@pytest.mark.parametrize("raw", ["", "claudecode,", ",codex", "notcodex", "cursorcli"])
def test_parse_agent_csv_rejects_invalid_values(raw: str) -> None:
    with pytest.raises(AgentSelectionError):
        parse_agent_csv(raw)


def test_adapter_for_resolves_the_documented_global_paths(tmp_path: Path) -> None:
    adapter = adapter_for(AgentId.OPENCODE, tmp_path)

    assert adapter.skills_root == tmp_path / ".config" / "opencode" / "skills"
    assert adapter.instructions_path == tmp_path / ".config" / "opencode" / "AGENTS.md"
    assert adapter.instructions_root == tmp_path / ".config" / "opencode"


def test_bundle_digest_changes_when_a_regular_asset_changes(tmp_path: Path) -> None:
    asset_root = tmp_path / "agent-assets"
    shutil.copytree(REPO_ROOT / "agent-assets", asset_root)
    before = build_bundle(asset_root).digest

    skill = asset_root / "skills" / "chronos-memory-save" / "SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    assert build_bundle(asset_root).digest != before


def test_bundle_rejects_a_symlink(tmp_path: Path) -> None:
    asset_root = tmp_path / "agent-assets"
    shutil.copytree(REPO_ROOT / "agent-assets", asset_root)
    (asset_root / "symlinked-asset.md").symlink_to("minimal-instructions.md")

    with pytest.raises(AssetValidationError):
        build_bundle(asset_root)


def test_rendered_all_block_has_no_unresolved_token() -> None:
    bundle = build_bundle(REPO_ROOT / "agent-assets")
    rendered = render_managed_block(bundle, IngestionMode.ALL)

    assert b"{{" not in rendered
    assert bundle.digest.encode("ascii") in rendered
    assert b"ingestion-mode=all" in rendered


def test_main_canonicalize_uses_raw_args(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["canonicalize", "--agents", "codex,opencode"])
    captured = capsys.readouterr()

    assert code == 0
    assert captured.out == "codex\nopencode\n"


def test_main_canonicalize_ignores_sys_argv(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "argv", ["unexpected", "sync"])
    code = main(["canonicalize", "--agents", "claudecode"])
    captured = capsys.readouterr()

    assert code == 0
    assert captured.out == "claudecode\n"


def test_main_canonicalize_works_with_global_help_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["unexpected", "sync"])
    with pytest.raises(SystemExit) as exc_info:
        main(["-h"])
    assert exc_info.value.code == 0


def test_main_sync_runs_when_repo_root_is_cwd_in_dry_run_selective(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["unexpected", "sync"])
    calls: list[object] = []
    monkeypatch.setattr(
        "agent_assets.cli.run_sync",
        lambda request: calls.append(request) or 0,
    )
    code = main(
        [
            "sync",
            "--repo-root",
            str(Path.cwd()),
            "--mode",
            "dry-run",
            "--ingestion-mode",
            "selective",
            "--agent",
            "claudecode",
        ]
    )

    assert code == 0
    assert len(calls) == 1
    request = calls[0]
    assert isinstance(request, SyncRequest)
    assert request.command == "sync"
    assert request.repo_root == Path.cwd()
    assert request.mode is ExecutionMode.DRY_RUN
    assert request.ingestion_mode is IngestionMode.SELECTIVE
    assert request.agent_ids == (AgentId.CLAUDECODE,)


def test_main_canonicalize_still_runs_when_args_match_sync_default_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["unexpected", "sync"])
    calls: list[object] = []
    monkeypatch.setattr(
        "agent_assets.cli.run_sync",
        lambda request: calls.append(request) or 0,
    )
    printed: list[str] = []
    monkeypatch.setattr(
        "agent_assets.cli._print_canonical_agents",
        lambda request: printed.extend(agent_id.value for agent_id in request.agent_ids) or 0,
    )
    code = main(["canonicalize", "--agents", "codex"])

    assert code == 0
    assert not calls
    assert printed == ["codex"]
