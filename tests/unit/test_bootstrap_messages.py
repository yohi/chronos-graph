from __future__ import annotations

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
