from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def run_bootstrap_args(home: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    bash = shutil.which("bash")
    assert bash is not None
    return subprocess.run(  # noqa: S603
        [
            bash,
            "scripts/bootstrap.sh",
            "--mode",
            "dry-run",
            "--backend",
            "sqlite",
            "--embedding",
            "local-model",
            *args,
        ],
        capture_output=True,
        check=False,
        cwd=REPO_ROOT,
        env={**os.environ, "HOME": str(home)},
        text=True,
    )


def run_bootstrap(home: Path, agents: str) -> subprocess.CompletedProcess[str]:
    return run_bootstrap_args(home, ["--agents", agents])


def test_bootstrap_rejects_unknown_agent_before_dry_run_plan(tmp_path: Path) -> None:
    result = run_bootstrap(tmp_path / "home", "notcodex")

    assert result.returncode != 0
    assert "Simulation complete" not in result.stdout


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--agents", ""],
        ["--agents", "claudecode,"],
        ["--agents", "claudecode", "--agents", "codex"],
    ],
)
def test_bootstrap_rejects_invalid_agents_argument_shape(
    tmp_path: Path,
    args: list[str],
) -> None:
    result = run_bootstrap_args(tmp_path / "home", args)

    assert result.returncode != 0
    assert "Simulation complete" not in result.stdout


def test_bootstrap_uses_canonical_order_for_dry_run_plan(tmp_path: Path) -> None:
    result = run_bootstrap(tmp_path / "home", "opencode,claudecode,codex,opencode")

    assert result.returncode == 0
    assert "claudecode,codex,opencode" in result.stdout


def copied_bootstrap_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repo"
    (repository / "scripts").mkdir(parents=True)
    _ = shutil.copy2(REPO_ROOT / "pyproject.toml", repository / "pyproject.toml")
    _ = shutil.copy2(REPO_ROOT / ".env.example", repository / ".env.example")
    _ = shutil.copy2(
        REPO_ROOT / "scripts" / "bootstrap.sh",
        repository / "scripts" / "bootstrap.sh",
    )
    _ = shutil.copy2(
        REPO_ROOT / "scripts" / "sync_agent_assets.py",
        repository / "scripts" / "sync_agent_assets.py",
    )
    _ = shutil.copy2(
        REPO_ROOT / "scripts" / "agent_turn_hook.py",
        repository / "scripts" / "agent_turn_hook.py",
    )
    _ = shutil.copytree(
        REPO_ROOT / "scripts" / "agent_assets",
        repository / "scripts" / "agent_assets",
    )
    _ = shutil.copytree(REPO_ROOT / "agent-assets", repository / "agent-assets")

    bin_dir = repository / "bin"
    bin_dir.mkdir()
    uv_stub = bin_dir / "uv"
    uv_stub_condition = "".join(
        (
            "if [ \"$1\" = run ] && [ \"$2\" = python ] && ",
            "[ \"$3\" = scripts/generate_config.py ]; then",
        )
    )
    uv_stub_script = "\n".join(
        (
            "#!/bin/sh",
            uv_stub_condition,
            "  printf '%s\\n' '{\"mcpServers\":{}}'",
            "fi",
            "exit 0",
            "",
        )
    )
    _ = uv_stub.write_text(uv_stub_script, encoding="utf-8")
    uv_stub.chmod(0o755)
    return repository


def run_copied_bootstrap(
    repository: Path,
    home: Path,
    ingestion_mode: str,
    agents: str,
) -> subprocess.CompletedProcess[str]:
    bash = shutil.which("bash")
    assert bash is not None
    return subprocess.run(  # noqa: S603
        [
            bash,
            "scripts/bootstrap.sh",
            "--backend",
            "sqlite",
            "--embedding",
            "local-model",
            "--source",
            "remote",
            "--skip-tests",
            "--ingestion-mode",
            ingestion_mode,
            "--agents",
            agents,
        ],
        capture_output=True,
        check=False,
        cwd=repository,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{repository / 'bin'}{os.pathsep}{os.environ['PATH']}",
        },
        text=True,
    )


def write_legacy_save_to_claude_instructions(home: Path) -> None:
    instruction = home / ".claude" / "CLAUDE.md"
    instruction.parent.mkdir(parents=True)
    _ = instruction.write_bytes(
        (REPO_ROOT / "tests" / "fixtures" / "agent_assets" / "legacy-save-v1.md").read_bytes()
    )


def test_bootstrap_hides_completion_when_agent_asset_sync_fails(tmp_path: Path) -> None:
    repository = copied_bootstrap_repository(tmp_path)
    (repository / "agent-assets" / "minimal-instructions.md").unlink()

    result = run_copied_bootstrap(repository, tmp_path / "home", "selective", "claudecode")

    assert result.returncode != 0
    assert "Bootstrap complete!" not in result.stdout


def test_bootstrap_does_not_start_all_mode_hook_after_legacy_save_collision(tmp_path: Path) -> None:
    repository = copied_bootstrap_repository(tmp_path)
    write_legacy_save_to_claude_instructions(tmp_path / "home")

    result = run_copied_bootstrap(repository, tmp_path / "home", "all", "claudecode")

    assert result.returncode != 0
    wrapper_name = "chronos-turn-hook.cmd" if os.name == "nt" else "chronos-turn-hook.sh"
    assert not (repository / "scripts" / wrapper_name).exists()
