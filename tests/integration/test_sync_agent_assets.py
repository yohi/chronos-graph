from __future__ import annotations

# ruff: noqa: E402, I001

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER = REPO_ROOT / "scripts" / "sync_agent_assets.py"
SCRIPTS_ROOT = REPO_ROOT / "scripts"

if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from agent_assets.models import AgentId, ExecutionMode, IngestionMode, SyncRequest  # noqa: E402
from agent_assets.preflight import BEGIN_MARKER, END_MARKER, parse_instruction_sections  # noqa: E402
from agent_assets.transaction import (  # noqa: E402
    SystemFileOperations as RealSystemFileOperations,
    apply_sync as real_apply_sync,
)


def copied_repo_root(tmp_path: Path) -> Path:
    source_root = tmp_path / "repo"
    shutil.copytree(REPO_ROOT / "agent-assets", source_root / "agent-assets")
    (source_root / "scripts").mkdir()
    shutil.copy2(
        REPO_ROOT / "scripts" / "agent_turn_hook.py",
        source_root / "scripts" / "agent_turn_hook.py",
    )
    return source_root


def invoke_sync(
    repo_root: Path,
    home: Path,
    mode: str,
    agents: list[str],
    ingestion_mode: str = "selective",
) -> subprocess.CompletedProcess[str]:
    environment = {
        **os.environ,
        "HOME": str(home),
        "CODEX_HOME": str(home / ".codex"),
    }
    command = [
        sys.executable,
        str(HELPER),
        "sync",
        "--repo-root",
        str(repo_root),
        "--mode",
        mode,
        "--ingestion-mode",
        ingestion_mode,
    ]
    for agent in agents:
        command.extend(["--agent", agent])
    return subprocess.run(  # noqa: S603 - command is assembled from test-controlled arguments.
        command,
        capture_output=True,
        check=False,
        env=environment,
        text=True,
    )


def request(repo_root: Path, home: Path, *agents: AgentId, mode: IngestionMode) -> SyncRequest:
    return SyncRequest(
        command="sync",
        repo_root=repo_root,
        home=home,
        mode=ExecutionMode.PRODUCTION,
        ingestion_mode=mode,
        agent_ids=agents,
        codex_home=home / ".codex",
    )


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def instructions_for(home: Path, agent: str) -> Path:
    roots = {
        "claudecode": home / ".claude" / "CLAUDE.md",
        "codex": home / ".codex" / "AGENTS.md",
        "opencode": home / ".config" / "opencode" / "AGENTS.md",
    }
    return roots[agent]


def skills_for(home: Path, agent: str) -> Path:
    roots = {
        "claudecode": home / ".claude" / "skills",
        "codex": home / ".agents" / "skills",
        "opencode": home / ".config" / "opencode" / "skills",
    }
    return roots[agent]


@pytest.mark.parametrize("agent", ["claudecode", "codex", "opencode"])
def test_sync_clean_install_creates_skills_and_managed_block(tmp_path: Path, agent: str) -> None:
    source_root = copied_repo_root(tmp_path)

    result = invoke_sync(source_root, tmp_path / "home", "production", [agent])

    assert result.returncode == 0, result.stderr
    skill_root = skills_for(tmp_path / "home", agent)
    assert (skill_root / "chronos-memory-save" / "SKILL.md").is_file()
    assert (skill_root / "chronos-memory-recall" / "SKILL.md").is_file()
    assert instructions_for(tmp_path / "home", agent).read_bytes().count(BEGIN_MARKER) == 1


def test_sync_preserves_bytes_outside_existing_managed_block(tmp_path: Path) -> None:
    source_root = copied_repo_root(tmp_path)
    instruction = instructions_for(tmp_path / "home", "claudecode")
    instruction.parent.mkdir(parents=True)
    prefix, suffix = b"before\x00\n", b"\nafter\xff\n"
    instruction.write_bytes(prefix + BEGIN_MARKER + b"\nold\n" + END_MARKER + suffix)

    result = invoke_sync(source_root, tmp_path / "home", "production", ["claudecode"])

    content = instruction.read_bytes()
    assert result.returncode == 0, result.stderr
    assert content.startswith(prefix)
    assert content.endswith(suffix)


def test_sync_preserves_unrelated_skill_directory_and_content(tmp_path: Path) -> None:
    source_root = copied_repo_root(tmp_path)
    other_skill = tmp_path / "home" / ".claude" / "skills" / "user-skill"
    other_skill.mkdir(parents=True)
    (other_skill / "SKILL.md").write_bytes(b"user-owned")
    before = digest(other_skill / "SKILL.md")

    result = invoke_sync(source_root, tmp_path / "home", "production", ["claudecode"])

    assert result.returncode == 0, result.stderr
    assert other_skill.is_dir()
    assert digest(other_skill / "SKILL.md") == before


def test_sync_second_execution_reports_unchanged_without_replacing_files(tmp_path: Path) -> None:
    source_root = copied_repo_root(tmp_path)
    home = tmp_path / "home"
    assert invoke_sync(source_root, home, "production", ["claudecode"]).returncode == 0
    instruction = instructions_for(home, "claudecode")
    before_inode = instruction.stat().st_ino

    result = invoke_sync(source_root, home, "production", ["claudecode"])

    assert result.returncode == 0, result.stderr
    assert ":unchanged" in result.stdout
    assert instruction.stat().st_ino == before_inode


def test_sync_ssot_change_updates_only_owned_targets(tmp_path: Path) -> None:
    source_root = copied_repo_root(tmp_path)
    home = tmp_path / "home"
    assert invoke_sync(source_root, home, "production", ["claudecode"]).returncode == 0
    unrelated = home / ".claude" / "skills" / "user-skill"
    unrelated.mkdir()
    (unrelated / "SKILL.md").write_bytes(b"unchanged")
    before = digest(unrelated / "SKILL.md")
    source_skill = source_root / "agent-assets" / "skills" / "chronos-memory-save" / "SKILL.md"
    source_skill.write_bytes(source_skill.read_bytes() + b"\nupdated\n")

    result = invoke_sync(source_root, home, "production", ["claudecode"])

    assert result.returncode == 0, result.stderr
    assert (
        b"updated"
        in (home / ".claude" / "skills" / "chronos-memory-save" / "SKILL.md").read_bytes()
    )
    assert digest(unrelated / "SKILL.md") == before


def test_sync_selective_to_all_replaces_managed_block_and_adds_wrapper(tmp_path: Path) -> None:
    source_root = copied_repo_root(tmp_path)
    home = tmp_path / "home"
    assert invoke_sync(source_root, home, "production", ["claudecode"]).returncode == 0
    instruction = instructions_for(home, "claudecode")
    before = instruction.read_bytes()

    result = invoke_sync(source_root, home, "production", ["claudecode"], "all")

    wrapper = (
        source_root
        / "scripts"
        / ("chronos-turn-hook.cmd" if os.name == "nt" else "chronos-turn-hook.sh")
    )
    assert result.returncode == 0, result.stderr
    assert b"ingestion-mode=all" in instruction.read_bytes()
    assert (
        parse_instruction_sections(instruction.read_bytes()).prefix
        == parse_instruction_sections(before).prefix
    )
    assert (
        parse_instruction_sections(instruction.read_bytes()).suffix
        == parse_instruction_sections(before).suffix
    )
    assert wrapper.is_file()


def test_sync_collision_for_one_selected_agent_leaves_other_agent_unchanged(tmp_path: Path) -> None:
    source_root = copied_repo_root(tmp_path)
    collision = tmp_path / "home" / ".claude" / "skills" / "chronos-memory-save"
    collision.mkdir(parents=True)
    (collision / "SKILL.md").write_bytes(b"user-owned")

    result = invoke_sync(source_root, tmp_path / "home", "production", ["claudecode", "codex"])

    assert result.returncode == 2
    assert not (tmp_path / "home" / ".agents" / "AGENTS.md").exists()
    assert "user-owned" not in result.stderr


def test_sync_in_root_instruction_symlink_keeps_link_and_updates_target(tmp_path: Path) -> None:
    source_root = copied_repo_root(tmp_path)
    home = tmp_path / "home"
    instruction = instructions_for(home, "claudecode")
    instruction.parent.mkdir(parents=True)
    target = instruction.parent / "actual.md"
    target.write_bytes(b"before\n")
    instruction.symlink_to(target.name)

    result = invoke_sync(source_root, home, "production", ["claudecode"])

    assert result.returncode == 0, result.stderr
    assert instruction.is_symlink()
    assert BEGIN_MARKER in target.read_bytes()


@pytest.mark.parametrize("kind", ["external", "broken", "cycle", "parent"])
def test_sync_unsafe_instruction_symlink_fails_without_writes(tmp_path: Path, kind: str) -> None:
    source_root = copied_repo_root(tmp_path)
    home = tmp_path / "home"
    instruction = instructions_for(home, "claudecode")
    instruction.parent.mkdir(parents=True)
    if kind == "external":
        external = tmp_path / "external.md"
        external.write_bytes(b"private")
        instruction.symlink_to(external)
    elif kind == "broken":
        instruction.symlink_to("missing.md")
    elif kind == "cycle":
        instruction.symlink_to(instruction.name)
    else:
        actual = home / "actual"
        actual.mkdir()
        shutil.rmtree(instruction.parent)
        instruction.parent.symlink_to(actual, target_is_directory=True)

    result = invoke_sync(source_root, home, "production", ["claudecode"])

    assert result.returncode == 2
    assert not (home / ".claude" / "skills" / "chronos-memory-save").exists()
    assert "private" not in result.stderr


def test_sync_dry_run_leaves_filesystem_unchanged(tmp_path: Path) -> None:
    source_root = copied_repo_root(tmp_path)
    home = tmp_path / "home"
    before = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))

    result = invoke_sync(source_root, home, "dry-run", ["claudecode"])

    after = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
    assert result.returncode == 0, result.stderr
    assert before == after
    assert "bundle-digest:" in result.stdout
    assert ":create" in result.stdout


def test_sync_legacy_prompt_warns_but_selective_mode_updates_only_managed_block(
    tmp_path: Path,
) -> None:
    source_root = copied_repo_root(tmp_path)
    home = tmp_path / "home"
    instruction = instructions_for(home, "claudecode")
    instruction.parent.mkdir(parents=True)
    legacy = (REPO_ROOT / "tests" / "fixtures" / "agent_assets" / "legacy-save-v1.md").read_bytes()
    instruction.write_bytes(b"outside\n" + legacy)

    result = invoke_sync(source_root, home, "production", ["claudecode"])

    content = instruction.read_bytes()
    assert result.returncode == 0, result.stderr
    assert b"outside\n" + legacy in content
    assert BEGIN_MARKER in content
    assert "legacy-save-manual-removal" in result.stdout


def test_sync_legacy_save_rejects_all_before_hook_setup_then_allows_manual_removal(
    tmp_path: Path,
) -> None:
    source_root = copied_repo_root(tmp_path)
    home = tmp_path / "home"
    instruction = instructions_for(home, "claudecode")
    instruction.parent.mkdir(parents=True)
    legacy = (REPO_ROOT / "tests" / "fixtures" / "agent_assets" / "legacy-save-v1.md").read_bytes()
    instruction.write_bytes(legacy)

    rejected = invoke_sync(source_root, home, "production", ["claudecode"], "all")

    wrapper = (
        source_root
        / "scripts"
        / ("chronos-turn-hook.cmd" if os.name == "nt" else "chronos-turn-hook.sh")
    )
    assert rejected.returncode == 2
    assert instruction.read_bytes() == legacy
    assert not wrapper.exists()
    instruction.write_bytes(b"manual removal complete\n")

    accepted = invoke_sync(source_root, home, "production", ["claudecode"], "all")

    assert accepted.returncode == 0, accepted.stderr
    assert wrapper.is_file()


class FailingReplaceOperations:
    def __init__(self, fail_on_replace: int) -> None:
        self._delegate = RealSystemFileOperations()
        self._fail_on_replace = fail_on_replace
        self._replacements = 0

    def replace(self, source: Path, destination: Path) -> None:
        self._replacements += 1
        if self._replacements == self._fail_on_replace:
            raise OSError("injected-replace-failure")
        self._delegate.replace(source, destination)

    def move(self, source: Path, destination: Path) -> None:
        self._delegate.move(source, destination)

    def remove(self, path: Path) -> None:
        self._delegate.remove(path)


def test_run_sync_io_failure_restores_owned_skills_and_instructions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import agent_assets.cli as cli
    import agent_assets.transaction as transaction

    source_root = copied_repo_root(tmp_path)
    home = tmp_path / "home"
    instruction = instructions_for(home, "claudecode")
    instruction.parent.mkdir(parents=True)
    instruction.write_bytes(b"user-before\n")
    monkeypatch.setattr(transaction, "SystemFileOperations", lambda: FailingReplaceOperations(2))

    with pytest.raises(transaction.ApplyError):
        cli.run_sync(request(source_root, home, AgentId.CLAUDECODE, mode=IngestionMode.SELECTIVE))

    assert instruction.read_bytes() == b"user-before\n"
    assert not (home / ".claude" / "skills" / "chronos-memory-save").exists()
    assert not (home / ".claude" / "skills" / "chronos-memory-recall").exists()


class ExternalChangeOnFailureOperations(FailingReplaceOperations):
    def __init__(self, path: Path) -> None:
        super().__init__(fail_on_replace=2)
        self._path = path

    def replace(self, source: Path, destination: Path) -> None:
        if self._replacements + 1 == self._fail_on_replace:
            self._path.write_bytes(b"external-change")
        super().replace(source, destination)


def test_run_sync_rollback_failure_preserves_external_change_and_reports_unrecovered_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import agent_assets.cli as cli
    import agent_assets.transaction as transaction

    source_root = copied_repo_root(tmp_path)
    home = tmp_path / "home"
    instruction = instructions_for(home, "claudecode")
    instruction.parent.mkdir(parents=True)
    instruction.write_bytes(b"user-before\n")
    monkeypatch.setattr(
        transaction,
        "SystemFileOperations",
        lambda: ExternalChangeOnFailureOperations(instruction),
    )

    with pytest.raises(transaction.ApplyError) as error:
        cli.run_sync(request(source_root, home, AgentId.CLAUDECODE, mode=IngestionMode.SELECTIVE))

    assert instruction.read_bytes() == b"external-change"
    assert not error.value.rollback.succeeded
    assert error.value.rollback.category == "rollback-external-change"


def test_run_sync_rolls_back_owned_artifacts_when_post_write_verification_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import agent_assets.cli as cli
    import agent_assets.transaction as transaction

    source_root = copied_repo_root(tmp_path)
    home = tmp_path / "home"
    instruction = instructions_for(home, "claudecode")
    instruction.parent.mkdir(parents=True)
    instruction.write_bytes(b"user-before\n")
    monkeypatch.setattr(
        transaction,
        "apply_sync",
        lambda plan, operations: real_apply_sync(plan, operations, verify=lambda _: False),
    )

    with pytest.raises(transaction.ApplyError):
        cli.run_sync(request(source_root, home, AgentId.CLAUDECODE, mode=IngestionMode.SELECTIVE))

    assert instruction.read_bytes() == b"user-before\n"
    assert not (home / ".claude" / "skills" / "chronos-memory-save").exists()


def test_run_sync_rolls_back_after_hook_setup_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import agent_assets.cli as cli
    import agent_assets.transaction as transaction

    source_root = copied_repo_root(tmp_path)
    home = tmp_path / "home"
    instruction = instructions_for(home, "claudecode")
    instruction.parent.mkdir(parents=True)
    instruction.write_bytes(b"user-before\n")
    monkeypatch.setattr(
        transaction,
        "install_selected_hooks",
        lambda *_: (_ for _ in ()).throw(transaction.HookSetupError("injected-hook-failure")),
    )

    with pytest.raises(transaction.ApplyError):
        cli.run_sync(request(source_root, home, AgentId.CLAUDECODE, mode=IngestionMode.ALL))

    assert instruction.read_bytes() == b"user-before\n"
    assert not (home / ".claude" / "skills" / "chronos-memory-save").exists()
    assert not (source_root / "scripts" / "chronos-turn-hook.sh").exists()
