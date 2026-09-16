from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_bootstrap_does_not_include_legacy_autonomous_memory_guidance() -> None:
    bootstrap_text = (REPO_ROOT / "scripts" / "bootstrap.sh").read_text(encoding="utf-8")

    assert "Final Step: Enabling Autonomous Memory" not in bootstrap_text
    assert "docs/agent-prompts/memory-save-system-prompt.md" not in bootstrap_text


def test_bootstrap_joins_canonical_agents_without_ifs_assignment() -> None:
    bootstrap_text = (REPO_ROOT / "scripts" / "bootstrap.sh").read_text(encoding="utf-8")

    assert "IFS=," not in bootstrap_text


def test_bootstrap_uses_uv_for_local_mcp_launch_by_default() -> None:
    bootstrap_text = (REPO_ROOT / "scripts" / "bootstrap.sh").read_text(encoding="utf-8")

    assert 'MCP_METHOD="uv"' in bootstrap_text


def test_bootstrap_accepts_required_provider_endpoints() -> None:
    bootstrap_text = (REPO_ROOT / "scripts" / "bootstrap.sh").read_text(encoding="utf-8")

    assert "--litellm-api-base" in bootstrap_text
    assert "--custom-api-endpoint" in bootstrap_text
    assert 'update_env_key "LITELLM_API_BASE"' in bootstrap_text
    assert 'update_env_key "CUSTOM_API_ENDPOINT"' in bootstrap_text


def test_bootstrap_protects_env_files() -> None:
    bootstrap_text = (REPO_ROOT / "scripts" / "bootstrap.sh").read_text(encoding="utf-8")

    assert "umask 077" in bootstrap_text
    assert "[ -L .env ]" in bootstrap_text
    assert "chmod 600 .env" in bootstrap_text


def test_bootstrap_uses_safe_supabase_defaults_and_defers_missing_config() -> None:
    bootstrap_text = (REPO_ROOT / "scripts" / "bootstrap.sh").read_text(encoding="utf-8")

    assert (
        'if [ "$BACKEND" = "supabase" ] && [[ "$EXPLICIT_FLAGS" != *"GRAPH_ENABLED"* ]]; then'
        in bootstrap_text
    )
    assert "MCP_CONFIG_READY=false" in bootstrap_text
    assert "Skipping MCP configuration generation until required secrets are set" in bootstrap_text
    assert "https://your-*" in bootstrap_text


def test_checked_in_turn_hook_has_the_managed_marker() -> None:
    hook_lines = (
        (REPO_ROOT / "scripts/chronos-turn-hook.sh").read_text(encoding="utf-8").splitlines()
    )

    assert hook_lines[1] == "# chronosgraph-managed: turn-hook-wrapper format=1"


def test_bootstrap_defers_supabase_config_for_template_placeholders(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    scripts_dir = project / "scripts"
    scripts_dir.mkdir()
    shutil.copy2(REPO_ROOT / "pyproject.toml", project / "pyproject.toml")
    shutil.copy2(REPO_ROOT / ".env.example", project / ".env.example")
    shutil.copy2(REPO_ROOT / "scripts/bootstrap.sh", scripts_dir / "bootstrap.sh")
    (scripts_dir / "sync_agent_assets.py").write_text(
        "import sys\nif sys.argv[1] == 'canonicalize':\n    print('codex')\n",
        encoding="utf-8",
    )

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "python3").symlink_to(sys.executable)
    fake_uv = bin_dir / "uv"
    fake_uv.write_text('#!/bin/sh\n[ "$1" = sync ]\n', encoding="utf-8")
    fake_uv.chmod(0o755)

    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "home")
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    bash_path = shutil.which("bash")
    assert bash_path is not None
    result = subprocess.run(  # noqa: S603 - bash_path is resolved from PATH
        [
            bash_path,
            "scripts/bootstrap.sh",
            "--backend",
            "supabase",
            "--embedding",
            "local-model",
            "--agents",
            "codex",
            "--skip-tests",
        ],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Skipping MCP configuration generation until required secrets are set" in result.stdout
    assert not (project / "mcp_config.json").exists()
    assert stat.S_IMODE((project / ".env").stat().st_mode) == 0o600
