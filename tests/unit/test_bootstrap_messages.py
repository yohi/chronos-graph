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
