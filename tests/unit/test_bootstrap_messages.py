from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_opencode_skip_message_mentions_type_and_ingestion_mode_requirements() -> None:
    bootstrap_text = (REPO_ROOT / "scripts" / "bootstrap.sh").read_text(encoding="utf-8")

    assert "requires TYPE=mcp and CHRONOS_INGESTION_MODE=all" in bootstrap_text
    assert "because CHRONOS_INGESTION_MODE is not all" not in bootstrap_text
