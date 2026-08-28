from __future__ import annotations

import hashlib
import json
import os
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


def test_rendered_all_block_has_no_unresolved_token() -> None:
    bundle = build_bundle(REPO_ROOT / "agent-assets")
    rendered = render_managed_block(bundle, IngestionMode.ALL)

    assert b"{{" not in rendered
    assert bundle.digest.encode("ascii") in rendered
    assert b"ingestion-mode=all" in rendered


def preflight_request_for(agent: AgentId, home: Path) -> SyncRequest:
    return SyncRequest(
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


def prepared_plan_for(
    agent: AgentId,
    home: Path,
    ingestion_mode: IngestionMode,
    repo_root: Path = REPO_ROOT,
) -> SyncPlan:
    request = SyncRequest(
        repo_root=repo_root,
        home=home,
        mode=ExecutionMode.PRODUCTION,
        ingestion_mode=ingestion_mode,
        agent_ids=(agent,),
    )
    return preflight(request, build_bundle(repo_root / "agent-assets"))


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


def test_all_mode_rejects_missing_opencode_plugin_registry_before_any_apply(
    tmp_path: Path,
) -> None:
    from agent_assets.hooks import PluginRegistryPrerequisiteError

    with pytest.raises(PluginRegistryPrerequisiteError):
        prepared_plan_for(AgentId.OPENCODE, tmp_path / "home", IngestionMode.ALL)

    assert not (tmp_path / "home" / ".config" / "opencode" / "opencode.json").exists()


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


def test_opencode_package_probe_is_read_only_and_redacts_access_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import agent_assets.hooks as hooks
    from agent_assets.hooks import PluginRegistryPrerequisiteError

    home = tmp_path / "home"
    configure_opencode_plugin_registry(home, monkeypatch)
    monkeypatch.setattr(hooks, "probe_package_metadata", lambda _: None)
    prepared_plan_for(AgentId.OPENCODE, home, IngestionMode.ALL)
    assert not (home / ".config" / "opencode" / "opencode.json").exists()

    token = "sensitive-test-token"
    monkeypatch.setenv("CHRONOS_OPENCODE_PACKAGES_TOKEN", token)

    def fail_probe(_: str) -> None:
        raise PluginRegistryPrerequisiteError("registry-probe-access")

    monkeypatch.setattr(hooks, "probe_package_metadata", fail_probe)
    with pytest.raises(PluginRegistryPrerequisiteError) as error:
        prepared_plan_for(AgentId.OPENCODE, home, IngestionMode.ALL)

    assert token not in str(error.value)
    assert "response-body" not in str(error.value)


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
