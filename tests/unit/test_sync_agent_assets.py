from __future__ import annotations

import errno
import hashlib
import io
import json
import os
import shutil
import stat
import sys
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

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
    PlannedTarget,
    SyncPlan,
    SyncRequest,
    adapter_for,
    parse_agent_csv,
)
from agent_assets.preflight import (  # noqa: E402
    LEGACY_RECALL_BYTE_LENGTH,
    LEGACY_RECALL_HEADING,
    LEGACY_RECALL_SHA256,
    LEGACY_SAVE_BYTE_LENGTH,
    LEGACY_SAVE_SHA256,
    InstructionCollisionError,
    LegacyKind,
    LegacySaveAllModeCollision,
    LegacySignature,
    MarkerError,
    SkillCollisionError,
    detect_legacy_prompts,
    parse_instruction_sections,
    preflight,
    safe_diagnostic,
)
from agent_assets.transaction import (  # noqa: E402
    ApplyError,
    FileOperations,
    HookSetupError,
    PostWriteVerificationError,
    SystemFileOperations,
    apply_sync,
)


def _instruction_target(plan: SyncPlan) -> PlannedTarget:
    return next(target for target in plan.targets if target.path.name == "CLAUDE.md")


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


def test_bundle_rejects_missing_skill_sentinel(tmp_path: Path) -> None:
    asset_root = tmp_path / "agent-assets"
    shutil.copytree(REPO_ROOT / "agent-assets", asset_root)
    sentinel = asset_root / "skills" / "chronos-memory-save" / ".chronosgraph-managed"
    sentinel.unlink()

    with pytest.raises(AssetValidationError) as error_info:
        build_bundle(asset_root)

    assert error_info.value.code == "asset-skill-sentinel-missing"


def test_bundle_rejects_template_with_invalid_render_tokens(tmp_path: Path) -> None:
    asset_root = tmp_path / "agent-assets"
    shutil.copytree(REPO_ROOT / "agent-assets", asset_root)
    template = asset_root / "minimal-instructions.md"
    template.write_bytes(template.read_bytes().replace(b"{{INGESTION_MODE}}", b"all"))

    with pytest.raises(AssetValidationError) as error_info:
        build_bundle(asset_root)

    assert error_info.value.code == "asset-template-render-token"


def test_bundle_rejects_skill_with_invalid_frontmatter(tmp_path: Path) -> None:
    asset_root = tmp_path / "agent-assets"
    shutil.copytree(REPO_ROOT / "agent-assets", asset_root)
    document = asset_root / "skills" / "chronos-memory-save" / "SKILL.md"
    document.write_bytes(
        document.read_bytes().replace(b"name: chronos-memory-save", b"name: unexpected")
    )

    with pytest.raises(AssetValidationError) as error_info:
        build_bundle(asset_root)

    assert error_info.value.code == "asset-skill-frontmatter"


def test_bundle_rejects_skill_with_malformed_yaml_frontmatter(tmp_path: Path) -> None:
    asset_root = tmp_path / "agent-assets"
    shutil.copytree(REPO_ROOT / "agent-assets", asset_root)
    document = asset_root / "skills" / "chronos-memory-save" / "SKILL.md"
    document.write_bytes(b"---\nname: chronos-memory-save\ndescription: [\n---\n<role>\n</role>\n")

    with pytest.raises(AssetValidationError) as error_info:
        build_bundle(asset_root)

    assert error_info.value.code == "asset-skill-frontmatter"


def test_bundle_rejects_skill_with_nonstring_description(tmp_path: Path) -> None:
    asset_root = tmp_path / "agent-assets"
    shutil.copytree(REPO_ROOT / "agent-assets", asset_root)
    document = asset_root / "skills" / "chronos-memory-save" / "SKILL.md"
    document.write_bytes(
        b"---\nname: chronos-memory-save\ndescription: [save]\n---\n<role>\n</role>\n"
    )

    with pytest.raises(AssetValidationError) as error_info:
        build_bundle(asset_root)

    assert error_info.value.code == "asset-skill-frontmatter"


def test_bundle_rejects_skill_with_duplicate_frontmatter_keys(tmp_path: Path) -> None:
    asset_root = tmp_path / "agent-assets"
    shutil.copytree(REPO_ROOT / "agent-assets", asset_root)
    document = asset_root / "skills" / "chronos-memory-save" / "SKILL.md"
    document.write_bytes(
        b"---\nname: chronos-memory-save\nname: replacement\ndescription: Save memory.\n"
        b"---\n<role>\n</role>\n"
    )

    with pytest.raises(AssetValidationError) as error_info:
        build_bundle(asset_root)

    assert error_info.value.code == "asset-skill-frontmatter"


def test_bundle_rejects_semantically_duplicate_frontmatter_keys(
    tmp_path: Path,
) -> None:
    asset_root = tmp_path / "agent-assets"
    shutil.copytree(REPO_ROOT / "agent-assets", asset_root)
    document = asset_root / "skills" / "chronos-memory-save" / "SKILL.md"
    document.write_bytes(
        b"---\nname: chronos-memory-save\n1: first\n01: second\n"
        b"description: Save memory.\n---\n<role>\n</role>\n"
    )

    with pytest.raises(AssetValidationError) as error_info:
        build_bundle(asset_root)

    assert error_info.value.code == "asset-skill-frontmatter"


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


def test_main_sync_dry_run_loads_sync_modules(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda _: tmp_path))

    code = main(
        [
            "sync",
            "--repo-root",
            str(REPO_ROOT),
            "--mode",
            "dry-run",
            "--ingestion-mode",
            "selective",
            "--agent",
            "claudecode",
        ]
    )

    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.startswith("bundle-digest:")
    assert f"{tmp_path / '.claude' / 'CLAUDE.md'}:create" in captured.out


def test_main_maps_invalid_asset_bundle_to_preflight_rejection(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    asset_root = repo_root / "agent-assets"
    shutil.copytree(REPO_ROOT / "agent-assets", asset_root)
    template = asset_root / "minimal-instructions.md"
    template.write_bytes(template.read_bytes().replace(b"{{INGESTION_MODE}}", b"all"))
    monkeypatch.setattr(Path, "home", classmethod(lambda _: tmp_path / "home"))

    code = main(
        [
            "sync",
            "--repo-root",
            str(repo_root),
            "--mode",
            "dry-run",
            "--ingestion-mode",
            "selective",
            "--agent",
            "claudecode",
        ]
    )
    captured = capsys.readouterr()

    assert code == 2
    assert captured.err == f"preflight:reject:{template}:asset-template-render-token\n"


def test_main_sync_production_installs_selected_agent_assets(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", classmethod(lambda _: home))

    code = main(
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
    assert code == 0
    assert captured.out.startswith("bundle-digest:")
    assert ":create:sha256=" in captured.out
    assert (home / ".claude" / "CLAUDE.md").is_file()
    assert (home / ".claude" / "skills" / "chronos-memory-recall" / "SKILL.md").is_file()
    assert (home / ".claude" / "skills" / "chronos-memory-save" / "SKILL.md").is_file()


def test_apply_sync_rejects_unmanaged_skill_change_after_preflight(tmp_path: Path) -> None:
    from agent_assets.preflight import preflight
    from agent_assets.transaction import ApplyError, SystemFileOperations, apply_sync

    home = tmp_path / "home"
    unmanaged = home / ".claude" / "skills" / "user-skill" / "README.md"
    unmanaged.parent.mkdir(parents=True)
    unmanaged.write_bytes(b"before\n")
    request = SyncRequest(
        command="sync",
        repo_root=REPO_ROOT,
        home=home,
        mode=ExecutionMode.PRODUCTION,
        ingestion_mode=IngestionMode.SELECTIVE,
        agent_ids=(AgentId.CLAUDECODE,),
    )
    plan = preflight(request, build_bundle(REPO_ROOT / "agent-assets"))
    unmanaged.write_bytes(b"after\n")

    with pytest.raises(ApplyError):
        apply_sync(plan, SystemFileOperations())

    assert not (home / ".claude" / "CLAUDE.md").exists()


def preflight_request_for(agent: AgentId, home: Path) -> SyncRequest:
    return SyncRequest(
        command="sync",
        repo_root=REPO_ROOT,
        home=home,
        mode=ExecutionMode.PRODUCTION,
        ingestion_mode=IngestionMode.SELECTIVE,
        agent_ids=(agent,),
    )


def test_parse_instruction_sections_preserves_bytes_outside_one_marker_block() -> None:
    original = (
        b"before\n"
        b"<!-- BEGIN CHRONOSGRAPH MANAGED: agent-memory -->\n"
        b"old\n"
        b"<!-- END CHRONOSGRAPH MANAGED: agent-memory -->\n"
        b"after\n"
    )

    sections = parse_instruction_sections(original)

    assert sections.prefix == b"before\n"
    assert sections.suffix == b"\nafter\n"


@pytest.mark.parametrize(
    "malformed",
    [
        b"<!-- BEGIN CHRONOSGRAPH MANAGED: agent-memory -->\n",
        b"<!-- END CHRONOSGRAPH MANAGED: agent-memory -->\n",
        (
            b"<!-- BEGIN CHRONOSGRAPH MANAGED: agent-memory -->"
            b"<!-- BEGIN CHRONOSGRAPH MANAGED: agent-memory -->"
        ),
    ],
)
def test_parse_instruction_sections_rejects_malformed_markers(malformed: bytes) -> None:
    with pytest.raises(MarkerError):
        parse_instruction_sections(malformed)


def test_preflight_rejects_same_name_skill_without_valid_sentinel(tmp_path: Path) -> None:
    skill_root = tmp_path / ".claude" / "skills" / "chronos-memory-save"
    skill_root.mkdir(parents=True)
    (skill_root / "SKILL.md").write_text("user managed", encoding="utf-8")

    with pytest.raises(SkillCollisionError):
        preflight(
            preflight_request_for(AgentId.CLAUDECODE, tmp_path),
            build_bundle(REPO_ROOT / "agent-assets"),
        )


def test_preflight_rejects_instruction_symlink_outside_approved_root(tmp_path: Path) -> None:
    home = tmp_path / "home"
    external = tmp_path / "external.md"
    external.write_text("private instructions", encoding="utf-8")
    instruction = home / ".claude" / "CLAUDE.md"
    instruction.parent.mkdir(parents=True)
    instruction.symlink_to(external)

    with pytest.raises(InstructionCollisionError):
        preflight(
            preflight_request_for(AgentId.CLAUDECODE, home),
            build_bundle(REPO_ROOT / "agent-assets"),
        )


def test_preflight_rejects_shared_resolved_instruction_target(tmp_path: Path) -> None:
    home = tmp_path / "home"
    shared_root = home / ".claude"
    shared_instruction = shared_root / "CLAUDE.md"
    shared_root.mkdir(parents=True)
    shared_instruction.write_bytes(b"shared instructions\n")
    (shared_root / "AGENTS.md").symlink_to(shared_instruction)
    request = SyncRequest(
        command="sync",
        repo_root=REPO_ROOT,
        home=home,
        mode=ExecutionMode.PRODUCTION,
        ingestion_mode=IngestionMode.SELECTIVE,
        agent_ids=(AgentId.CLAUDECODE, AgentId.CODEX),
        codex_home=shared_root,
    )

    with pytest.raises(InstructionCollisionError) as error_info:
        preflight(request, build_bundle(REPO_ROOT / "agent-assets"))

    assert error_info.value.code == "instruction-symlink-shared"


def test_preflight_replaces_only_the_managed_instruction_section(tmp_path: Path) -> None:
    instruction = tmp_path / ".claude" / "CLAUDE.md"
    instruction.parent.mkdir(parents=True)
    original = (
        b"before\n"
        b"<!-- BEGIN CHRONOSGRAPH MANAGED: agent-memory -->\nold\n"
        b"<!-- END CHRONOSGRAPH MANAGED: agent-memory -->\nafter\n"
    )
    instruction.write_bytes(original)
    bundle = build_bundle(REPO_ROOT / "agent-assets")

    plan = preflight(preflight_request_for(AgentId.CLAUDECODE, tmp_path), bundle)
    target = _instruction_target(plan)

    assert target.action.value == "update"
    assert target.content == (
        b"before\n"
        + render_managed_block(bundle, IngestionMode.SELECTIVE).removesuffix(b"\n")
        + b"\nafter\n"
    )


def test_preflight_keeps_rendered_instruction_unchanged(tmp_path: Path) -> None:
    instruction = tmp_path / ".claude" / "CLAUDE.md"
    instruction.parent.mkdir(parents=True)
    bundle = build_bundle(REPO_ROOT / "agent-assets")
    instruction.write_bytes(
        render_managed_block(bundle, IngestionMode.SELECTIVE).removesuffix(b"\n")
    )

    plan = preflight(preflight_request_for(AgentId.CLAUDECODE, tmp_path), bundle)

    assert _instruction_target(plan).action.value == "unchanged"


def test_preflight_accepts_owned_same_name_skill_as_an_update(tmp_path: Path) -> None:
    skill_root = tmp_path / ".claude" / "skills" / "chronos-memory-save"
    skill_root.mkdir(parents=True)
    (skill_root / ".chronosgraph-managed").write_bytes(b"owner=chronosgraph\nformat=1\n")

    plan = preflight(
        preflight_request_for(AgentId.CLAUDECODE, tmp_path),
        build_bundle(REPO_ROOT / "agent-assets"),
    )

    assert any(
        target.path == skill_root and target.action.value == "update" for target in plan.targets
    )


def test_apply_sync_does_not_follow_existing_skill_symlink(tmp_path: Path) -> None:
    home = tmp_path / "home"
    skill_root = home / ".claude" / "skills" / "chronos-memory-save"
    skill_root.mkdir(parents=True)
    external = tmp_path / "external.md"
    external.write_bytes(b"outside-before")
    (skill_root / "SKILL.md").symlink_to(external)
    (skill_root / ".chronosgraph-managed").write_bytes(b"owner=chronosgraph\nformat=1\n")
    plan = preflight(
        preflight_request_for(AgentId.CLAUDECODE, home),
        build_bundle(REPO_ROOT / "agent-assets"),
    )

    apply_sync(plan, SystemFileOperations())

    assert external.read_bytes() == b"outside-before"
    assert not (skill_root / "SKILL.md").is_symlink()
    assert (skill_root / "SKILL.md").read_bytes() == (
        REPO_ROOT / "agent-assets" / "skills" / "chronos-memory-save" / "SKILL.md"
    ).read_bytes()


@pytest.mark.parametrize("target_kind", ["broken", "cycle", "directory"])
def test_preflight_rejects_unsafe_instruction_symlink_targets(
    tmp_path: Path, target_kind: str
) -> None:
    home = tmp_path / "home"
    instruction = home / ".claude" / "CLAUDE.md"
    instruction.parent.mkdir(parents=True)
    match target_kind:
        case "broken":
            instruction.symlink_to(home / ".claude" / "missing.md")
        case "cycle":
            instruction.symlink_to(instruction)
        case "directory":
            directory = home / ".claude" / "instructions"
            directory.mkdir()
            instruction.symlink_to(directory)
        case _:
            pytest.fail("unexpected target kind")

    with pytest.raises(InstructionCollisionError):
        preflight(
            preflight_request_for(AgentId.CLAUDECODE, home),
            build_bundle(REPO_ROOT / "agent-assets"),
        )


def test_preflight_rejects_instruction_symlink_cycle_from_eloop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_assets.preflight_files import safe_instruction_target

    home = tmp_path / "home"
    instruction = home / ".claude" / "CLAUDE.md"
    instruction.parent.mkdir(parents=True)
    instruction.symlink_to(instruction)

    def raise_eloop(_path: Path, strict: bool = False) -> Path:
        raise OSError(errno.ELOOP, "too many levels of symbolic links")

    monkeypatch.setattr(Path, "resolve", raise_eloop)

    with pytest.raises(InstructionCollisionError):
        safe_instruction_target(instruction, instruction.parent)


def test_preflight_rejects_instruction_parent_symlink(tmp_path: Path) -> None:
    home = tmp_path / "home"
    actual_root = home / "actual-claude"
    actual_root.mkdir(parents=True)
    (home / ".claude").symlink_to(actual_root, target_is_directory=True)

    with pytest.raises(InstructionCollisionError):
        preflight(
            preflight_request_for(AgentId.CLAUDECODE, home),
            build_bundle(REPO_ROOT / "agent-assets"),
        )


def test_legacy_warning_does_not_echo_existing_instruction_or_secret() -> None:
    legacy_template = (
        REPO_ROOT / "tests" / "fixtures" / "agent_assets" / "legacy-recall-v1.md"
    ).read_bytes()
    signature = LegacySignature(
        kind=LegacyKind.RECALL,
        heading=LEGACY_RECALL_HEADING,
        digest=LEGACY_RECALL_SHA256,
        byte_length=LEGACY_RECALL_BYTE_LENGTH,
    )
    instruction = b"credential=do-not-print\n" + legacy_template

    assert LEGACY_SAVE_SHA256 == "e7641028c918c614d42cf548f67e4a810e02fa204f641e2cd0b8fd3a3c7ebfb1"
    assert LEGACY_SAVE_BYTE_LENGTH == 5273
    assert hashlib.sha256(legacy_template).hexdigest() == LEGACY_RECALL_SHA256
    assert len(legacy_template) == LEGACY_RECALL_BYTE_LENGTH
    detected = detect_legacy_prompts(instruction, (signature,))
    rendered = safe_diagnostic(detected[0], Path("AGENTS.md")).render()

    assert "do-not-print" not in rendered
    assert "Memory Recall" not in rendered


def test_preflight_rejects_legacy_save_prompt_in_all_mode(tmp_path: Path) -> None:
    instruction = tmp_path / ".claude" / "CLAUDE.md"
    instruction.parent.mkdir(parents=True)
    instruction.write_bytes(
        (REPO_ROOT / "tests" / "fixtures" / "agent_assets" / "legacy-save-v1.md").read_bytes()
    )
    request = SyncRequest(
        command="sync",
        repo_root=REPO_ROOT,
        home=tmp_path,
        mode=ExecutionMode.PRODUCTION,
        ingestion_mode=IngestionMode.ALL,
        agent_ids=(AgentId.CLAUDECODE,),
    )

    with pytest.raises(LegacySaveAllModeCollision):
        preflight(request, build_bundle(REPO_ROOT / "agent-assets"))


class ReplaceFailingFileOperations:
    """Test-only structural FileOperations fake."""

    def __init__(self, fail_on_replace: int) -> None:
        self._delegate = SystemFileOperations()
        self._fail_on_replace = fail_on_replace
        self._replace_count = 0

    def replace(self, source: Path, destination: Path) -> None:
        self._replace_count += 1
        if self._replace_count == self._fail_on_replace:
            raise OSError("injected replace failure")
        self._delegate.replace(source, destination)

    def move(self, source: Path, destination: Path) -> None:
        self._delegate.move(source, destination)

    def remove(self, path: Path) -> None:
        self._delegate.remove(path)


class RecoveryStageFailingFileOperations:
    def __init__(self) -> None:
        self._delegate = SystemFileOperations()
        self.backup_path: Path | None = None

    def replace(self, source: Path, destination: Path) -> None:
        self._delegate.replace(source, destination)

    def move(self, source: Path, destination: Path) -> None:
        if source.name.startswith("backup-"):
            self.backup_path = source
            raise OSError("injected-recovery-stage-move-failure")
        self._delegate.move(source, destination)

    def remove(self, path: Path) -> None:
        self._delegate.remove(path)


class ExternalChangeOnReplaceFailureOperations:
    def __init__(self, target: Path) -> None:
        self._delegate = SystemFileOperations()
        self._target = target
        self.backup_path: Path | None = None

    def replace(self, source: Path, destination: Path) -> None:
        if destination == self._target:
            self._target.write_bytes(b"external-change\n")
            raise OSError("injected-replace-failure")
        self._delegate.replace(source, destination)

    def move(self, source: Path, destination: Path) -> None:
        if source == self._target:
            self.backup_path = destination
        self._delegate.move(source, destination)

    def remove(self, path: Path) -> None:
        self._delegate.remove(path)


def prepared_plan_for(
    agent: AgentId,
    home: Path,
    ingestion_mode: IngestionMode,
    repo_root: Path = REPO_ROOT,
) -> SyncPlan:
    request = SyncRequest(
        command="sync",
        repo_root=repo_root,
        home=home,
        mode=ExecutionMode.PRODUCTION,
        ingestion_mode=ingestion_mode,
        agent_ids=(agent,),
    )
    return preflight(request, build_bundle(repo_root / "agent-assets"))


def test_apply_sync_keeps_target_when_recovery_stage_move_fails(tmp_path: Path) -> None:
    home = tmp_path / "home"
    instruction = home / ".claude" / "CLAUDE.md"
    instruction.parent.mkdir(parents=True)
    instruction.write_bytes(b"user-before\n")
    plan = prepared_plan_for(AgentId.CLAUDECODE, home, IngestionMode.SELECTIVE)
    operations = RecoveryStageFailingFileOperations()

    with pytest.raises(ApplyError) as error:
        apply_sync(plan, operations, verify=lambda _: False)

    target = _instruction_target(plan)
    assert target.content is not None
    assert instruction.read_bytes() == target.content
    assert operations.backup_path is not None
    assert operations.backup_path.exists()
    assert error.value.rollback.recovery_paths == (operations.backup_path,)


def test_apply_sync_reports_external_change_when_uninstalled_target_reappears(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    instruction = home / ".claude" / "CLAUDE.md"
    instruction.parent.mkdir(parents=True)
    instruction.write_bytes(b"user-before\n")
    plan = prepared_plan_for(AgentId.CLAUDECODE, home, IngestionMode.SELECTIVE)
    operations = ExternalChangeOnReplaceFailureOperations(instruction)

    with pytest.raises(ApplyError) as error:
        apply_sync(plan, operations)

    assert instruction.read_bytes() == b"external-change\n"
    assert operations.backup_path is not None
    assert operations.backup_path.exists()
    assert not error.value.rollback.succeeded
    assert error.value.rollback.category == "rollback-external-change"
    assert error.value.rollback.recovery_paths == (operations.backup_path,)


def test_apply_sync_restores_owned_instruction_after_verification_failure(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    instruction = home / ".claude" / "CLAUDE.md"
    instruction.parent.mkdir(parents=True)
    instruction.write_bytes(b"user-before\n")
    plan = prepared_plan_for(AgentId.CLAUDECODE, home, IngestionMode.SELECTIVE)

    with pytest.raises(ApplyError):
        apply_sync(plan, SystemFileOperations(), verify=lambda _: False)

    assert instruction.read_bytes() == b"user-before\n"


def test_apply_sync_restores_owned_artifacts_after_verifier_exception(tmp_path: Path) -> None:
    home = tmp_path / "home"
    instruction = home / ".claude" / "CLAUDE.md"
    instruction.parent.mkdir(parents=True)
    instruction.write_bytes(b"user-before\n")
    plan = prepared_plan_for(AgentId.CLAUDECODE, home, IngestionMode.SELECTIVE)

    def raise_from_verifier(_: SyncPlan) -> bool:
        raise RuntimeError("injected verifier failure")

    with pytest.raises(ApplyError) as error:
        apply_sync(plan, SystemFileOperations(), verify=raise_from_verifier)

    assert isinstance(error.value.__cause__, PostWriteVerificationError)
    assert instruction.read_bytes() == b"user-before\n"


def test_apply_sync_removes_only_new_transaction_artifacts_on_failure(tmp_path: Path) -> None:
    home = tmp_path / "home"
    plan = prepared_plan_for(AgentId.CODEX, home, IngestionMode.SELECTIVE)
    operations: FileOperations = ReplaceFailingFileOperations(fail_on_replace=2)

    with pytest.raises(ApplyError):
        apply_sync(plan, operations)

    assert not (home / ".agents" / "skills" / "chronos-memory-save").exists()
    assert not (home / ".agents" / "skills" / "chronos-memory-recall").exists()


def configure_opencode_plugin_registry(home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    registry = home / ".npmrc"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(
        "@yohi:registry=https://npm.pkg.github.com\n"
        "//npm.pkg.github.com/:_authToken=${CHRONOS_OPENCODE_PACKAGES_TOKEN}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CHRONOS_OPENCODE_PACKAGES_TOKEN", "test-only-token")
    return registry


def test_all_mode_registers_opencode_plugin_without_replacing_other_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import agent_assets.hooks as hooks

    monkeypatch.setattr(hooks, "probe_package_metadata", lambda _: None)
    home = tmp_path / "home"
    registry = configure_opencode_plugin_registry(home, monkeypatch)
    registry_before = registry.read_bytes()
    config = home / ".config" / "opencode" / "opencode.json"
    config.parent.mkdir(parents=True)
    config.write_text('{"theme":"dark","plugin":["other-plugin"]}', encoding="utf-8")
    plan = prepared_plan_for(AgentId.OPENCODE, home, IngestionMode.ALL)

    apply_sync(plan, SystemFileOperations())
    apply_sync(
        prepared_plan_for(AgentId.OPENCODE, home, IngestionMode.ALL),
        SystemFileOperations(),
    )

    registered = json.loads(config.read_text(encoding="utf-8"))
    assert registered["theme"] == "dark"
    assert registered["plugin"] == ["other-plugin", "@yohi/opencode-plugin-chronos-turn-end"]
    assert registry.read_bytes() == registry_before


def test_all_mode_creates_wrapper_and_selective_mode_does_not(tmp_path: Path) -> None:
    all_repo = tmp_path / "all-repo"
    shutil.copytree(REPO_ROOT / "agent-assets", all_repo / "agent-assets")
    (all_repo / "scripts").mkdir()
    shutil.copy2(REPO_ROOT / "scripts" / "agent_turn_hook.py", all_repo / "scripts")
    all_home = tmp_path / "all-home"
    apply_sync(
        prepared_plan_for(AgentId.CLAUDECODE, all_home, IngestionMode.ALL, all_repo),
        SystemFileOperations(),
    )
    wrapper_name = "chronos-turn-hook.cmd" if os.name == "nt" else "chronos-turn-hook.sh"
    assert (all_repo / "scripts" / wrapper_name).is_file()
    if os.name != "nt":
        assert all_repo.joinpath("scripts", wrapper_name).stat().st_mode & stat.S_IXUSR

    selective_repo = tmp_path / "selective-repo"
    shutil.copytree(all_repo / "agent-assets", selective_repo / "agent-assets")
    (selective_repo / "scripts").mkdir()
    shutil.copy2(REPO_ROOT / "scripts" / "agent_turn_hook.py", selective_repo / "scripts")
    apply_sync(
        prepared_plan_for(
            AgentId.CLAUDECODE,
            tmp_path / "selective-home",
            IngestionMode.SELECTIVE,
            selective_repo,
        ),
        SystemFileOperations(),
    )
    assert not (selective_repo / "scripts" / wrapper_name).exists()


def test_all_mode_rejects_existing_hook_changed_after_preflight(tmp_path: Path) -> None:
    import agent_assets.hooks as hooks

    repo_root = tmp_path / "repo"
    shutil.copytree(REPO_ROOT / "agent-assets", repo_root / "agent-assets")
    (repo_root / "scripts").mkdir()
    shutil.copy2(
        REPO_ROOT / "scripts" / "agent_turn_hook.py",
        repo_root / "scripts" / "agent_turn_hook.py",
    )
    wrapper_name = "chronos-turn-hook.cmd" if os.name == "nt" else "chronos-turn-hook.sh"
    wrapper = repo_root / "scripts" / wrapper_name
    wrapper.write_bytes(hooks._wrapper_content() + b"\n")
    request = SyncRequest(
        command="sync",
        repo_root=repo_root,
        home=tmp_path / "home",
        mode=ExecutionMode.PRODUCTION,
        ingestion_mode=IngestionMode.ALL,
        agent_ids=(AgentId.CLAUDECODE,),
    )

    plan = preflight(request, build_bundle(repo_root / "agent-assets"))
    hook_target = next(target for target in plan.targets if target.path == wrapper)
    assert hook_target.snapshots
    assert hook_target.snapshots[0] in plan.snapshots
    wrapper.write_bytes(b"external-change\n")

    with pytest.raises(ApplyError):
        apply_sync(plan, SystemFileOperations())

    assert wrapper.read_bytes() == b"external-change\n"


@pytest.mark.skipif(os.name == "nt", reason="POSIX wrapper permissions are not available")
def test_all_mode_makes_existing_posix_wrapper_executable(tmp_path: Path) -> None:
    import agent_assets.hooks as hooks

    repo_root = tmp_path / "repo"
    shutil.copytree(REPO_ROOT / "agent-assets", repo_root / "agent-assets")
    (repo_root / "scripts").mkdir()
    shutil.copy2(
        REPO_ROOT / "scripts" / "agent_turn_hook.py",
        repo_root / "scripts" / "agent_turn_hook.py",
    )
    wrapper = repo_root / "scripts" / "chronos-turn-hook.sh"
    wrapper.write_bytes(hooks._wrapper_content() + b"\n")
    wrapper.chmod(0o640)
    request = SyncRequest(
        command="sync",
        repo_root=repo_root,
        home=tmp_path / "home",
        mode=ExecutionMode.PRODUCTION,
        ingestion_mode=IngestionMode.ALL,
        agent_ids=(AgentId.CLAUDECODE,),
    )

    apply_sync(preflight(request, build_bundle(repo_root / "agent-assets")), SystemFileOperations())

    mode = stat.S_IMODE(wrapper.stat().st_mode)
    assert mode & stat.S_IXUSR
    assert mode & stat.S_IRUSR
    assert mode & stat.S_IWUSR
    assert not mode & stat.S_IXGRP
    assert not mode & stat.S_IXOTH


def test_all_mode_rejects_existing_opencode_config_changed_after_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import agent_assets.hooks as hooks

    monkeypatch.setattr(hooks, "probe_package_metadata", lambda _: None)
    home = tmp_path / "home"
    configure_opencode_plugin_registry(home, monkeypatch)
    config = home / ".config" / "opencode" / "opencode.json"
    config.parent.mkdir(parents=True)
    config.write_text('{"theme":"dark"}', encoding="utf-8")

    plan = prepared_plan_for(AgentId.OPENCODE, home, IngestionMode.ALL)
    config.write_text('{"theme":"external"}', encoding="utf-8")

    with pytest.raises(ApplyError):
        apply_sync(plan, SystemFileOperations())

    assert json.loads(config.read_text(encoding="utf-8"))["theme"] == "external"


def test_registry_token_accepts_spaced_entries_and_comments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import agent_assets.hooks as hooks

    registry = tmp_path / ".npmrc"
    registry.write_text(
        "  # comment = ignored\n"
        "; other = ignored\n"
        " @yohi:registry = https://npm.pkg.github.com/ \n"
        " //npm.pkg.github.com/:_authToken = ${TEST_TOKEN} \n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TEST_TOKEN", "test-token")

    assert hooks._registry_token(registry) == "test-token"


def test_registry_token_maps_invalid_utf8_to_credential_prerequisite(
    tmp_path: Path,
) -> None:
    import agent_assets.hooks as hooks
    from agent_assets.hooks import PluginRegistryPrerequisiteError

    registry = tmp_path / ".npmrc"
    registry.write_bytes(
        b"@yohi:registry=https://npm.pkg.github.com\n//npm.pkg.github.com/:_authToken=\xff\n"
    )

    with pytest.raises(PluginRegistryPrerequisiteError) as error:
        hooks._registry_token(registry)

    assert error.value.category == "registry-probe-credential"


def test_updated_plugin_config_reports_actual_path(tmp_path: Path) -> None:
    import agent_assets.hooks as hooks
    from agent_assets.hooks import HookConfigCollision

    config_path = tmp_path / ".config" / "opencode" / "opencode.json"

    with pytest.raises(HookConfigCollision) as error:
        hooks.updated_plugin_config(b"[]", config_path)

    assert error.value.path == config_path


def test_all_mode_rejects_missing_opencode_plugin_registry_before_any_apply(
    tmp_path: Path,
) -> None:
    from agent_assets.hooks import PluginRegistryPrerequisiteError

    with pytest.raises(PluginRegistryPrerequisiteError):
        prepared_plan_for(AgentId.OPENCODE, tmp_path / "home", IngestionMode.ALL)

    assert not (tmp_path / "home" / ".config" / "opencode" / "opencode.json").exists()


def test_dry_run_all_mode_plans_opencode_without_registry_prerequisite(
    tmp_path: Path,
) -> None:
    from agent_assets.hooks import plan_hook_targets

    request = SyncRequest(
        command="sync",
        repo_root=REPO_ROOT,
        home=tmp_path / "home",
        mode=ExecutionMode.DRY_RUN,
        ingestion_mode=IngestionMode.ALL,
        agent_ids=(AgentId.OPENCODE,),
    )

    targets = plan_hook_targets(request)

    assert [target.path for target in targets] == [
        request.home / ".config" / "opencode" / "opencode.json"
    ]


@pytest.mark.parametrize("filename", ["opencode.jsonc", "oh-my-opencode.jsonc"])
def test_all_mode_rejects_locally_managed_opencode_config_before_any_apply(
    tmp_path: Path, filename: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import agent_assets.hooks as hooks
    from agent_assets.hooks import HookConfigCollision

    monkeypatch.setattr(hooks, "probe_package_metadata", lambda _: None)
    home = tmp_path / "home"
    configure_opencode_plugin_registry(home, monkeypatch)
    jsonc = home / ".config" / "opencode" / filename
    jsonc.parent.mkdir(parents=True)
    jsonc.write_text("// managed elsewhere\n{}", encoding="utf-8")

    with pytest.raises(HookConfigCollision):
        prepared_plan_for(AgentId.OPENCODE, home, IngestionMode.ALL)


def test_opencode_package_probe_is_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import agent_assets.hooks as hooks

    home = tmp_path / "home"
    configure_opencode_plugin_registry(home, monkeypatch)
    monkeypatch.setattr(hooks, "probe_package_metadata", lambda _: None)
    prepared_plan_for(AgentId.OPENCODE, home, IngestionMode.ALL)
    assert not (home / ".config" / "opencode" / "opencode.json").exists()


def test_opencode_package_probe_redacts_http_failures() -> None:
    import agent_assets.hooks as hooks
    from agent_assets.hooks import PluginRegistryPrerequisiteError

    token = "sensitive-test-token"
    response_body = b"response-body-secret"

    def fail_urlopen(_request: urllib.request.Request, _timeout: float) -> None:
        raise urllib.error.HTTPError(
            hooks._METADATA_URL,
            401,
            f"token={token};body={response_body.decode()}",
            None,
            io.BytesIO(response_body),
        )

    with patch.object(hooks.urllib.request, "urlopen", fail_urlopen):
        with pytest.raises(PluginRegistryPrerequisiteError) as error:
            hooks.probe_package_metadata(token)

    assert token not in str(error.value)
    assert response_body.decode() not in str(error.value)


def test_all_mode_hook_failure_restores_skills_instructions_and_wrapper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import agent_assets.transaction as transaction

    home = tmp_path / "home"
    repo_root = tmp_path / "repo"
    shutil.copytree(REPO_ROOT / "agent-assets", repo_root / "agent-assets")
    (repo_root / "scripts").mkdir()
    shutil.copy2(REPO_ROOT / "scripts" / "agent_turn_hook.py", repo_root / "scripts")
    plan = prepared_plan_for(AgentId.CLAUDECODE, home, IngestionMode.ALL, repo_root)

    def fail_hooks(*_: object) -> None:
        raise HookSetupError("injected-hook-failure")

    monkeypatch.setattr(transaction, "install_selected_hooks", fail_hooks)

    with pytest.raises(ApplyError):
        apply_sync(plan, SystemFileOperations())

    assert not (home / ".claude" / "skills" / "chronos-memory-save").exists()
    wrapper_name = "chronos-turn-hook.cmd" if os.name == "nt" else "chronos-turn-hook.sh"
    assert not (plan.request.repo_root / "scripts" / wrapper_name).exists()


def test_apply_sync_preserves_unchanged_unmanaged_skill_entries(tmp_path: Path) -> None:
    from agent_assets.preflight import preflight
    from agent_assets.transaction import SystemFileOperations, apply_sync

    home = tmp_path / "home"
    unmanaged = home / ".claude" / "skills" / "user-skill" / "README.md"
    unmanaged.parent.mkdir(parents=True)
    unmanaged.write_bytes(b"before\n")
    request = SyncRequest(
        command="sync",
        repo_root=REPO_ROOT,
        home=home,
        mode=ExecutionMode.PRODUCTION,
        ingestion_mode=IngestionMode.SELECTIVE,
        agent_ids=(AgentId.CLAUDECODE,),
    )
    plan = preflight(request, build_bundle(REPO_ROOT / "agent-assets"))

    apply_sync(plan, SystemFileOperations())

    assert unmanaged.read_bytes() == b"before\n"
    assert (home / ".claude" / "skills" / "chronos-memory-recall" / "SKILL.md").is_file()


def test_apply_sync_rejects_unmanaged_skill_added_after_preflight(tmp_path: Path) -> None:
    from agent_assets.preflight import preflight
    from agent_assets.transaction import ApplyError, SystemFileOperations, apply_sync

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
    added = home / ".claude" / "skills" / "external-skill" / "README.md"
    added.parent.mkdir(parents=True)
    added.write_bytes(b"added-after-preflight\n")

    with pytest.raises(ApplyError):
        apply_sync(plan, SystemFileOperations())

    assert added.read_bytes() == b"added-after-preflight\n"
    assert not (home / ".claude" / "skills" / "chronos-memory-recall").exists()


def test_safe_instruction_target_rejects_root_that_is_not_an_ancestor(
    tmp_path: Path,
) -> None:
    from agent_assets.preflight_errors import InstructionCollisionError
    from agent_assets.preflight_files import safe_instruction_target

    path = tmp_path / "outside" / "AGENTS.md"
    root = tmp_path / "approved"

    with pytest.raises(InstructionCollisionError) as error_info:
        safe_instruction_target(path, root)

    assert error_info.value.code == "instruction-root-mismatch"
