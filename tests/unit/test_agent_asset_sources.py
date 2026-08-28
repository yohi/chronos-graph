from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
ASSET_ROOT = REPO_ROOT / "agent-assets"
SENTINEL = "owner=chronosgraph\nformat=1\n"


def test_skill_sources_have_required_names_and_sentinels() -> None:
    expected = {
        "chronos-memory-recall": "chronos-memory-recall",
        "chronos-memory-save": "chronos-memory-save",
    }

    for directory_name, skill_name in expected.items():
        skill_root = ASSET_ROOT / "skills" / directory_name
        document = (skill_root / "SKILL.md").read_text(encoding="utf-8")
        _, frontmatter, _ = document.split("---", maxsplit=2)

        assert yaml.safe_load(frontmatter)["name"] == skill_name
        assert (skill_root / ".chronosgraph-managed").read_text(encoding="utf-8") == SENTINEL


def test_minimal_instruction_template_has_only_runtime_render_tokens() -> None:
    template = (ASSET_ROOT / "minimal-instructions.md").read_text(encoding="utf-8")

    assert "{{BUNDLE_SHA256}}" in template
    assert "{{INGESTION_MODE}}" in template
    assert "{{SAVE_MODE_RULE}}" in template
    assert "<!-- BEGIN CHRONOSGRAPH MANAGED: agent-memory -->" in template
    assert "<!-- END CHRONOSGRAPH MANAGED: agent-memory -->" in template


def test_legacy_test_fixtures_match_pinned_detector_versions() -> None:
    fixtures = REPO_ROOT / "tests" / "fixtures" / "agent_assets"

    assert hashlib.sha256((fixtures / "legacy-save-v1.md").read_bytes()).hexdigest() == (
        "e7641028c918c614d42cf548f67e4a810e02fa204f641e2cd0b8fd3a3c7ebfb1"
    )
    assert hashlib.sha256((fixtures / "legacy-recall-v1.md").read_bytes()).hexdigest() == (
        "171c000346a5880f4c8a846f1ab34147708ff9a3f25baf7f3ee051504b0bfca5"
    )


def test_legacy_prompt_source_files_are_absent() -> None:
    prompts = REPO_ROOT / "docs" / "agent-prompts"

    assert not (prompts / "memory-save-system-prompt.md").exists()
    assert not (prompts / "memory-search-system-prompt.md").exists()


def test_agent_guidance_points_to_repository_asset_ssot() -> None:
    agents_document = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert "agent-assets/" in agents_document
    assert "memory-save-system-prompt.md" not in agents_document
    assert "memory-search-system-prompt.md" not in agents_document
