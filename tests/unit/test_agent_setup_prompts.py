from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_BASE = "https://raw.githubusercontent.com/yohi/chronos-graph/master/"


def test_readme_setup_prompts_use_raw_canonical_sources() -> None:
    for name in ("README.md", "README.ja.md"):
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        assert f"{RAW_BASE}docs/agent-setup-protocol.md" in text
        assert f"{RAW_BASE}AGENTS.md" in text
        assert "v2.0.0" not in text


def test_setup_protocols_include_raw_document_references() -> None:
    for name in ("docs/agent-setup-protocol.md", "docs/agent-setup-protocol.ja.md"):
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        assert f"{RAW_BASE}docs/configuration.md" in text
        assert f"{RAW_BASE}docs/migration.md" in text


def test_setup_protocols_define_end_to_end_completion() -> None:
    english = (REPO_ROOT / "docs/agent-setup-protocol.md").read_text(encoding="utf-8")
    japanese = (REPO_ROOT / "docs/agent-setup-protocol.ja.md").read_text(encoding="utf-8")

    assert "MCP initialization" in english
    assert "MCP初期化" in japanese
    assert "all" in english and "MCP_GATEWAY_URL" in english
    assert "all" in japanese and "MCP_GATEWAY_URL" in japanese
