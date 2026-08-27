# Agent Skills Distribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Do not dispatch subagents. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace manually copied ChronosGraph memory prompts with repository-owned global Save and Recall Skills that `scripts/bootstrap.sh` installs, synchronizes, verifies, and rolls back safely for Claude Code, Codex CLI, and OpenCode.

**Architecture:** Keep the durable source material in `agent-assets/`, then expose a thin `scripts/sync_agent_assets.py` internal CLI backed by small, typed modules under `scripts/agent_assets/`. Bootstrap parses the raw `--agents` CSV once into a canonical set before any side effect, then delegates all selected-agent mutations, post-write verification, and `all`-mode hook setup to the helper's single transaction.

**Tech Stack:** Python 3.12 standard library, Bash, pytest, ruff, mypy, `gh stack`.

## Global Constraints

- Support exactly `claudecode`, `codex`, and `opencode`; reject every other identifier, including `notcodex`.
- Install both `chronos-memory-save` and `chronos-memory-recall` for every selected Agent in both `selective` and `all` modes.
- Use these global paths: Claude Code `~/.claude/skills/` and `~/.claude/CLAUDE.md`; Codex `~/.agents/skills/` and `~/.codex/AGENTS.md`; OpenCode `~/.config/opencode/skills/` and `~/.config/opencode/AGENTS.md`.
- Treat `agent-assets/` in the checkout or release tarball running bootstrap as the only Agent asset SSOT. `--source=local|remote` must not alter the asset source.
- Preserve existing non-ChronosGraph instructions byte-for-byte and preserve non-ChronosGraph Skill paths, types, and content hashes.
- Own only the HTML marker block `<!-- BEGIN CHRONOSGRAPH MANAGED: agent-memory -->` through `<!-- END CHRONOSGRAPH MANAGED: agent-memory -->` and Skill directories with an exact `.chronosgraph-managed` sentinel.
- Compute the bundle SHA-256 by sorting all regular files below `agent-assets/` by relative POSIX path and hashing `relative-path`, NUL, file bytes, NUL for each file. Reject symlinks and undefined file types in the SSOT.
- Treat duplicated, partial, or nested instruction markers; non-owned same-name Skills; unsafe symlinks; malformed SSOT; and legacy Save plus `all` mode as preflight failures with no writes.
- Resolve existing instruction symlinks before writing, permit only regular-file targets canonically contained within the Agent's approved instructions root, and reject broken, cyclic, parent, root-external, and shared symlinks. Do not add shared-symlink opt-in flags in this implementation.
- `selective` permits read-only warnings for legacy Save or Recall prompts. `all` permits a legacy Recall warning but rejects a legacy Save prompt before any write or hook setup.
- `dry-run` performs the same parse, validation, render, comparison, and conflict detection as production, but must not create directories, temporary files, backups, staging directories, or hook artifacts.
- Include Skills, managed instruction blocks, wrappers, and OpenCode plugin registration in one transaction. Commit only after post-write verification and selected `all`-mode hooks succeed; otherwise roll back only paths proven to be ChronosGraph-owned changes from the current transaction.
- Error and warning output may include Agent ID, path, phase, action, mismatch category, digest, and recovery artifact identifier. It must not print existing instructions, other Skill contents, prompt bodies, or credentials.
- Do not change `memory_save`, `memory_search`, `session_flush`, ingestion semantics, storage/retrieval code, or the Cursor/Antigravity payload parsing in `scripts/agent_turn_hook.py`.
- Keep each new Python module at or below 250 pure lines. Use frozen, slotted dataclasses and typed exceptions; add no runtime dependency.
- Do not use subagents during planning or execution of this plan.
- Create a linear `gh stack` before writing implementation code. Each layer must contain only the code-diff concern listed below, and no PR may be merged by the implementation worker.

## Stacked PR Delivery

Create the stack in a dedicated worktree before Task 1. Use non-interactive commands only. Replace `origin` below only when a different configured remote is the intended PR remote.

```bash
gh stack init agent-skills/assets
gh stack view --json
```

| Layer | Branch | Base | Scope |
| --- | --- | --- | --- |
| 1 | `agent-skills/assets` | current trunk | Agent asset SSOT and its structural tests |
| 2 | `agent-skills/sync-preflight` | `agent-skills/assets` | Typed adapter model, bundle rendering, marker parsing, ownership, symlink, and legacy preflight |
| 3 | `agent-skills/sync-transaction` | `agent-skills/sync-preflight` | Atomic apply, rollback, hook registration, and temporary-HOME integration tests |
| 4 | `agent-skills/bootstrap` | `agent-skills/sync-transaction` | One-time `--agents` canonicalization and bootstrap delegation/regression tests |
| 5 | `agent-skills/docs` | `agent-skills/bootstrap` | Documentation migration and removal of legacy prompt files |

After each layer's scoped tests pass, stage only that layer's listed files and commit it before creating the next branch. Do not split a completed mixed diff after the fact.

## File Structure

| Path | Responsibility |
| --- | --- |
| `agent-assets/minimal-instructions.md` | Render-token template for the managed global instruction block |
| `agent-assets/skills/chronos-memory-recall/SKILL.md` | Recall behavior SSOT with load-routing frontmatter |
| `agent-assets/skills/chronos-memory-recall/.chronosgraph-managed` | Exact ownership sentinel for Recall Skill copies |
| `agent-assets/skills/chronos-memory-save/SKILL.md` | Selective-mode Save behavior SSOT with mode-guard frontmatter |
| `agent-assets/skills/chronos-memory-save/.chronosgraph-managed` | Exact ownership sentinel for Save Skill copies |
| `scripts/sync_agent_assets.py` | Thin executable entry point for `canonicalize` and `sync` subcommands |
| `scripts/agent_assets/models.py` | Agent IDs, modes, adapters, typed requests, plans, snapshots, and safe diagnostics |
| `scripts/agent_assets/bundle.py` | SSOT validation, bundle digest calculation, and minimal block rendering |
| `scripts/agent_assets/preflight.py` | Marker parsing, instruction symlink containment, Skill ownership inspection, legacy detection, and immutable preflight plans |
| `scripts/agent_assets/hooks.py` | `all`-mode wrapper and strict-JSON OpenCode registration planning and verification |
| `scripts/agent_assets/transaction.py` | Staging, atomic replacement, journaled rollback, and post-write verification |
| `scripts/agent_assets/cli.py` | Command-line boundary, deterministic plan output, and redacted diagnostics |
| `tests/unit/test_agent_asset_sources.py` | Source asset layout and machine-consumed frontmatter/sentinel tests |
| `tests/unit/test_sync_agent_assets.py` | Pure parser, digest, marker, ownership, symlink, legacy, transaction, and diagnostic tests |
| `tests/integration/test_sync_agent_assets.py` | Temporary-HOME end-to-end synchronization and rollback scenarios |
| `tests/unit/test_bootstrap_agent_assets.py` | Bootstrap CLI contract, delegation, dry-run, and completion-message regression tests |
| `tests/unit/test_bootstrap_messages.py` | Narrow regression checks for removed legacy bootstrap guidance |
| `tests/fixtures/agent_assets/legacy-save-v1.md` | Test-only historical Save prompt bytes used to prove read-only fingerprint detection |
| `tests/fixtures/agent_assets/legacy-recall-v1.md` | Test-only historical Recall prompt bytes used to prove read-only fingerprint detection |
| `scripts/bootstrap.sh` | Canonical-set creation and delegation to the internal helper |
| `README.md` | User-facing description of managed global Skills and removal of manual prompt copy guidance |
| `AGENTS.md` | Progressive-disclosure references redirected from old templates to `agent-assets/` |
| `docs/agent-setup-protocol.md` | Phases 4, 5, and 7 aligned with the selected-Agent asset lifecycle |

---

### Task 1: Add the Agent Asset SSOT

**Files:**

- Create: `agent-assets/minimal-instructions.md`
- Create: `agent-assets/skills/chronos-memory-recall/SKILL.md`
- Create: `agent-assets/skills/chronos-memory-recall/.chronosgraph-managed`
- Create: `agent-assets/skills/chronos-memory-save/SKILL.md`
- Create: `agent-assets/skills/chronos-memory-save/.chronosgraph-managed`
- Create: `tests/unit/test_agent_asset_sources.py`
- Create: `tests/fixtures/agent_assets/legacy-save-v1.md`
- Create: `tests/fixtures/agent_assets/legacy-recall-v1.md`

**Interfaces:**

- Consumes: the behavior currently defined in `docs/agent-prompts/memory-save-system-prompt.md` and `docs/agent-prompts/memory-search-system-prompt.md`.
- Produces: the `agent-assets/` directory tree consumed by `build_bundle(asset_root: Path) -> AssetBundle` in Task 2.

- [ ] **Step 1: Write the failing source-layout tests**

Create `tests/unit/test_agent_asset_sources.py` with structural assertions only. Do not pin natural-language prose; check frontmatter routing fields, render tokens, asset names, and exact sentinel bytes.

```python
from __future__ import annotations

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
```

- [ ] **Step 2: Run the source-layout test to confirm the missing assets fail**

Run: `uv run pytest tests/unit/test_agent_asset_sources.py -v`

Expected: FAIL because `agent-assets/` does not yet exist.

- [ ] **Step 3: Create the minimal global-instructions template**

Create `agent-assets/minimal-instructions.md` with this complete marker structure. Keep the three render tokens literal in the SSOT; the sync helper replaces all of them before writing a target.

```markdown
<!-- BEGIN CHRONOSGRAPH MANAGED: agent-memory -->
<!-- chronosgraph-bundle:
sha256={{BUNDLE_SHA256}};
ingestion-mode={{INGESTION_MODE}}
-->
ChronosGraph memory Skills are available. Load and follow the
`chronos-memory-recall` Skill at task start and genuine error or
convention-decision points. {{SAVE_MODE_RULE}}
<!-- END CHRONOSGRAPH MANAGED: agent-memory -->
```

Use these exact rendered `{{SAVE_MODE_RULE}}` values in Task 2:

```text
selective: In selective mode, load and follow `chronos-memory-save` when its save trigger applies.
all: In all mode, do not call `memory_save` or `session_flush`; turn-end ingestion owns saving.
```

- [ ] **Step 4: Create the Recall Skill from the existing Recall behavior**

Create `agent-assets/skills/chronos-memory-recall/SKILL.md` with this frontmatter, followed by the exact XML content from the existing Recall template between `<recall_role>` and `</recall_quick_rubric>`. Exclude the old title, template explanation, and outer Markdown fence; preserve the tool routing, project scoping, visible-recall requirement, grounding rule, one-search-per-session guidance, and rubric without semantic change.

```markdown
---
name: chronos-memory-recall
description: Load at task start, when prior work is referenced, when a known resolution may help an error, or before a convention decision. Use ChronosGraph recall tools, surface the result, and ground it against current state.
---
```

Create `agent-assets/skills/chronos-memory-recall/.chronosgraph-managed` with exactly:

```text
owner=chronosgraph
format=1
```

- [ ] **Step 5: Create the Save Skill from the existing Save behavior**

Create `agent-assets/skills/chronos-memory-save/SKILL.md` with this frontmatter, followed by the exact XML content from the existing Save template between `<role>` and `</quick_rubric>`. Exclude the old title, template explanation, and outer Markdown fence; preserve the completion and failure-to-success triggers, semantic/procedural formats, autonomous `memory_save`, 8,000-character `session_flush`, noise avoidance, and rubric without semantic change.

```markdown
---
name: chronos-memory-save
description: In `CHRONOS_INGESTION_MODE=selective`, load after a user instruction completes or a command changes from failure to success to decide whether durable ChronosGraph memory should be saved. Do not use this Skill in `all` mode because turn-end ingestion owns saving.
---
```

Create `agent-assets/skills/chronos-memory-save/.chronosgraph-managed` with exactly:

```text
owner=chronosgraph
format=1
```

- [ ] **Step 6: Preserve test-only legacy detector fixtures**

Copy the current full bytes of each legacy template into the corresponding file below before Task 7 deletes the runtime documentation sources. These files are fixtures only: runtime code must never read them, README and `AGENTS.md` must never link to them, and no setup path may treat them as fallback instructions.

```text
docs/agent-prompts/memory-save-system-prompt.md -> tests/fixtures/agent_assets/legacy-save-v1.md
docs/agent-prompts/memory-search-system-prompt.md -> tests/fixtures/agent_assets/legacy-recall-v1.md
```

Add this test so the pinned detector values have a regression-proof test input after the public template files are removed.

```python
import hashlib


def test_legacy_test_fixtures_match_pinned_detector_versions() -> None:
    fixtures = REPO_ROOT / "tests" / "fixtures" / "agent_assets"

    assert hashlib.sha256((fixtures / "legacy-save-v1.md").read_bytes()).hexdigest() == (
        "e7641028c918c614d42cf548f67e4a810e02fa204f641e2cd0b8fd3a3c7ebfb1"
    )
    assert hashlib.sha256((fixtures / "legacy-recall-v1.md").read_bytes()).hexdigest() == (
        "171c000346a5880f4c8a846f1ab34147708ff9a3f25baf7f3ee051504b0bfca5"
    )
```

- [ ] **Step 7: Run the source-layout tests and inspect the staged asset tree**

Run: `uv run pytest tests/unit/test_agent_asset_sources.py -v`

Expected: PASS. The tests prove the machine-consumed asset layout, ownership sentinels, frontmatter names, and render tokens without freezing editorial wording.

- [ ] **Step 8: Commit the first stack layer and create the next layer**

```bash
git add agent-assets tests/fixtures/agent_assets tests/unit/test_agent_asset_sources.py
uv run ruff check tests/unit/test_agent_asset_sources.py
uv run ruff format tests/unit/test_agent_asset_sources.py
uv run pytest tests/unit/test_agent_asset_sources.py -v
git commit -m "feat(agent-assets): メモリSkillのSSOTを追加"
gh stack add agent-skills/sync-preflight
```

---

### Task 2: Build Typed Agent Selection, Bundle, and Render Primitives

**Files:**

- Create: `scripts/agent_assets/__init__.py`
- Create: `scripts/agent_assets/models.py`
- Create: `scripts/agent_assets/bundle.py`
- Create: `scripts/agent_assets/cli.py`
- Create: `scripts/sync_agent_assets.py`
- Create: `tests/unit/test_sync_agent_assets.py`

**Interfaces:**

- Consumes: `agent-assets/` created in Task 1 and raw `--agents` CSV input from bootstrap.
- Produces: `parse_agent_csv(raw: str) -> tuple[AgentId, ...]`, `build_bundle(asset_root: Path) -> AssetBundle`, and `render_managed_block(bundle: AssetBundle, mode: IngestionMode) -> bytes`.

- [ ] **Step 1: Write failing tests for Agent parsing and path adapters**

Add these tests to `tests/unit/test_sync_agent_assets.py`. Load the scripts package by prepending `REPO_ROOT / "scripts"` to `sys.path`; do not import from the installed wheel.

```python
from __future__ import annotations

from pathlib import Path

import pytest

from agent_assets.models import AgentId, AgentSelectionError, adapter_for, parse_agent_csv


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
```

- [ ] **Step 2: Run the parser tests to confirm the module is absent**

Run: `uv run pytest tests/unit/test_sync_agent_assets.py -k "parse_agent_csv or adapter_for" -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'agent_assets'`.

- [ ] **Step 3: Implement immutable agent models and canonical parsing**

In `scripts/agent_assets/models.py`, define closed Agent and mode variants, an adapter record, and a controlled selection error. Keep the canonical order in one `Final` tuple. `adapter_for` must derive all three paths from the passed home path, never from an environment variable or substring rule.

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final


class AgentId(StrEnum):
    CLAUDECODE = "claudecode"
    CODEX = "codex"
    OPENCODE = "opencode"


class IngestionMode(StrEnum):
    SELECTIVE = "selective"
    ALL = "all"


class ExecutionMode(StrEnum):
    PRODUCTION = "production"
    DRY_RUN = "dry-run"


CANONICAL_AGENT_ORDER: Final = (
    AgentId.CLAUDECODE,
    AgentId.CODEX,
    AgentId.OPENCODE,
)


@dataclass(frozen=True, slots=True)
class AgentAdapter:
    agent_id: AgentId
    skills_root: Path
    instructions_path: Path
    instructions_root: Path


@dataclass(frozen=True, slots=True)
class SyncRequest:
    repo_root: Path
    home: Path
    mode: ExecutionMode
    ingestion_mode: IngestionMode
    agent_ids: tuple[AgentId, ...]


@dataclass(frozen=True, slots=True)
class AssetBundle:
    root: Path
    digest: str
    minimal_template: bytes
    skill_roots: tuple[Path, Path]


class AgentSelectionError(RuntimeError):
    """Raised when raw `--agents` input cannot become a supported canonical set."""


def parse_agent_csv(raw: str) -> tuple[AgentId, ...]:
    """Parse one comma-separated CLI value into canonical supported Agent IDs."""
    values = tuple(piece.strip() for piece in raw.split(","))
    if not values or any(not value for value in values):
        raise AgentSelectionError("invalid-agent-selection")

    requested: set[AgentId] = set()
    for value in values:
        match value:
            case "claudecode":
                requested.add(AgentId.CLAUDECODE)
            case "codex":
                requested.add(AgentId.CODEX)
            case "opencode":
                requested.add(AgentId.OPENCODE)
            case _:
                raise AgentSelectionError("unsupported-agent")

    return tuple(agent for agent in CANONICAL_AGENT_ORDER if agent in requested)
```

- [ ] **Step 4: Write failing SSOT-validation, digest, and rendering tests**

Add a temporary asset-tree fixture that copies `agent-assets/`, then assert the digest changes only when a regular file changes, and assert SSOT symlinks are rejected.

```python
import shutil

from agent_assets.bundle import AssetValidationError, build_bundle, render_managed_block
from agent_assets.models import IngestionMode


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
```

- [ ] **Step 5: Run the bundle tests to confirm the implementation is absent**

Run: `uv run pytest tests/unit/test_sync_agent_assets.py -k "bundle or rendered" -v`

Expected: FAIL with an import error for `agent_assets.bundle`.

- [ ] **Step 6: Implement SSOT validation, SHA-256, rendering, and the thin CLI boundary**

In `models.py`, define `AssetBundle` as a frozen dataclass carrying `root: Path`, `digest: str`, `minimal_template: bytes`, and the two expected Skill roots. In `bundle.py`, reject every symlink before reading content and hash each sorted regular file using the specified path/NUL/content/NUL sequence.

```python
class AssetValidationError(RuntimeError):
    """Raised when the repository-owned Agent asset tree is malformed."""


def compute_bundle_digest(asset_root: Path) -> str:
    """Return the deterministic digest for all validated regular SSOT files."""
    digest = hashlib.sha256()
    candidates = sorted(
        asset_root.rglob("*"),
        key=lambda candidate: candidate.relative_to(asset_root).as_posix(),
    )
    for candidate in candidates:
        metadata = candidate.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise AssetValidationError(candidate, "symlink")
        if candidate.is_dir():
            continue
        if not candidate.is_file():
            raise AssetValidationError(candidate, "unsupported-file-type")
        relative_path = candidate.relative_to(asset_root).as_posix().encode("utf-8")
        digest.update(relative_path)
        digest.update(b"\x00")
        digest.update(candidate.read_bytes())
        digest.update(b"\x00")
    return digest.hexdigest()
```

`render_managed_block` must replace all three tokens with the digest, `selective` or `all`, and the exact mode rule from Task 1. `cli.py` must expose two commands:

```text
python scripts/sync_agent_assets.py canonicalize --agents claudecode,codex
python scripts/sync_agent_assets.py sync --repo-root . --mode dry-run --ingestion-mode selective --agent claudecode --agent codex
```

The `canonicalize` command is the only command that accepts comma-separated Agent input. It emits one canonical Agent ID per line. The `sync` command accepts repeated already-canonical `--agent` values in canonical order and does not split a CSV value.

- [ ] **Step 7: Run focused unit checks**

Run: `uv run pytest tests/unit/test_sync_agent_assets.py -k "parse_agent_csv or adapter_for or bundle or rendered" -v`

Expected: PASS.

- [ ] **Step 8: Commit the parser, adapter, and bundle layer**

```bash
git add scripts/agent_assets/__init__.py scripts/agent_assets/models.py scripts/agent_assets/bundle.py scripts/agent_assets/cli.py scripts/sync_agent_assets.py tests/unit/test_sync_agent_assets.py
uv run ruff check scripts/sync_agent_assets.py scripts/agent_assets tests/unit/test_sync_agent_assets.py
uv run ruff format scripts/sync_agent_assets.py scripts/agent_assets tests/unit/test_sync_agent_assets.py
uv run mypy scripts/sync_agent_assets.py scripts/agent_assets
uv run pytest tests/unit/test_sync_agent_assets.py -k "parse_agent_csv or adapter_for or bundle or rendered" -v
git commit -m "feat(agent-sync): Agent資産のSSOT検証を追加"
```

---

### Task 3: Add Non-Destructive Preflight and Safe Diagnostics

**Files:**

- Create: `scripts/agent_assets/preflight.py`
- Modify: `scripts/agent_assets/models.py`
- Modify: `scripts/agent_assets/cli.py`
- Modify: `tests/unit/test_sync_agent_assets.py`

**Interfaces:**

- Consumes: `SyncRequest`, `AssetBundle`, and the adapter table from Task 2.
- Produces: `preflight(request: SyncRequest, bundle: AssetBundle) -> SyncPlan`, where `SyncPlan` contains immutable target snapshots, planned actions, and safe diagnostics without target content.

- [ ] **Step 1: Write failing marker and Skill-ownership tests**

Add tests for marker append, replacement, unchanged output, every malformed marker state, owned Skill update, and non-owned same-name Skill collision.

```python
from agent_assets.bundle import build_bundle
from agent_assets.models import AgentId, ExecutionMode, IngestionMode, SyncRequest
from agent_assets.preflight import MarkerError, SkillCollisionError, preflight, parse_instruction_sections


def preflight_request_for(agent: AgentId, home: Path):
    request = SyncRequest(
        repo_root=REPO_ROOT,
        home=home,
        mode=ExecutionMode.PRODUCTION,
        ingestion_mode=IngestionMode.SELECTIVE,
        agent_ids=(agent,),
    )
    return preflight(request, build_bundle(REPO_ROOT / "agent-assets"))


def test_parse_instruction_sections_preserves_bytes_outside_one_marker_block() -> None:
    original = b"before\n<!-- BEGIN CHRONOSGRAPH MANAGED: agent-memory -->\nold\n<!-- END CHRONOSGRAPH MANAGED: agent-memory -->\nafter\n"

    sections = parse_instruction_sections(original)

    assert sections.prefix == b"before\n"
    assert sections.suffix == b"\nafter\n"


@pytest.mark.parametrize(
    "malformed",
    [
        b"<!-- BEGIN CHRONOSGRAPH MANAGED: agent-memory -->\n",
        b"<!-- END CHRONOSGRAPH MANAGED: agent-memory -->\n",
        b"<!-- BEGIN CHRONOSGRAPH MANAGED: agent-memory --><!-- BEGIN CHRONOSGRAPH MANAGED: agent-memory -->",
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
        preflight_request_for(AgentId.CLAUDECODE, tmp_path)
```

- [ ] **Step 2: Run marker and ownership tests to confirm preflight is absent**

Run: `uv run pytest tests/unit/test_sync_agent_assets.py -k "instruction_sections or same_name_skill" -v`

Expected: FAIL with an import error for `agent_assets.preflight`.

- [ ] **Step 3: Implement byte-preserving marker parsing and ownership snapshots**

Define a frozen `InstructionSections` with `prefix: bytes`, `managed: bytes | None`, and `suffix: bytes`. Validate exactly zero or one complete marker pair, reject a lone marker, multiple begin/end markers, and begin/end ordering errors before generating any output. Build new target bytes only as `prefix + rendered_block + suffix`.

```python
BEGIN_MARKER = b"<!-- BEGIN CHRONOSGRAPH MANAGED: agent-memory -->"
END_MARKER = b"<!-- END CHRONOSGRAPH MANAGED: agent-memory -->"


def parse_instruction_sections(original: bytes) -> InstructionSections:
    """Split one valid managed block from immutable surrounding bytes."""
    begin_count = original.count(BEGIN_MARKER)
    end_count = original.count(END_MARKER)
    if begin_count == 0 and end_count == 0:
        return InstructionSections(prefix=original, managed=None, suffix=b"")
    if begin_count != 1 or end_count != 1:
        raise MarkerError("marker-count")

    begin = original.index(BEGIN_MARKER)
    end_start = original.index(END_MARKER)
    if end_start < begin:
        raise MarkerError("marker-order")
    end = end_start + len(END_MARKER)
    return InstructionSections(
        prefix=original[:begin],
        managed=original[begin:end],
        suffix=original[end:],
    )
```

For each selected Skill root, snapshot every non-ChronosGraph entry as relative path, `lstat` type, and content hash. A same-name target is owned only when `.chronosgraph-managed` is a regular file containing exactly `owner=chronosgraph\nformat=1\n`; otherwise raise `SkillCollisionError` before apply.

- [ ] **Step 4: Write failing symlink, legacy-prompt, and redaction tests**

Add temporary-HOME unit tests for an in-root instruction symlink, an out-of-root symlink, a broken symlink, a cyclic symlink, a parent-directory symlink, and a non-regular resolved target. Add legacy tests using the current fingerprints and a secret-bearing surrounding instruction body.

```python
import hashlib

from agent_assets.preflight import (
    InstructionCollisionError,
    LegacyKind,
    LegacySignature,
    detect_legacy_prompts,
    safe_diagnostic,
)


def test_preflight_rejects_instruction_symlink_outside_approved_root(tmp_path: Path) -> None:
    home = tmp_path / "home"
    external = tmp_path / "external.md"
    external.write_text("private instructions", encoding="utf-8")
    instruction = home / ".claude" / "CLAUDE.md"
    instruction.parent.mkdir(parents=True)
    instruction.symlink_to(external)

    with pytest.raises(InstructionCollisionError):
        preflight_request_for(AgentId.CLAUDECODE, home)


def test_legacy_warning_does_not_echo_existing_instruction_or_secret() -> None:
    legacy_template = (
        REPO_ROOT / "tests" / "fixtures" / "agent_assets" / "legacy-recall-v1.md"
    ).read_bytes()
    signature = LegacySignature(
        kind=LegacyKind.RECALL,
        heading=b"# Memory Recall \xe2\x80\x94 Agent System Prompt Template",
        digest=hashlib.sha256(legacy_template).hexdigest(),
        byte_length=len(legacy_template),
    )
    instruction = b"credential=do-not-print\n" + legacy_template

    detected = detect_legacy_prompts(instruction, (signature,))
    rendered = safe_diagnostic(detected[0], Path("AGENTS.md")).render()

    assert "do-not-print" not in rendered
    assert "Memory Recall" not in rendered
```

- [ ] **Step 5: Run safety tests to confirm they fail before implementation**

Run: `uv run pytest tests/unit/test_sync_agent_assets.py -k "symlink or legacy_warning" -v`

Expected: FAIL because safe target resolution and legacy detection are not implemented.

- [ ] **Step 6: Implement canonical-path containment and read-only legacy detection**

Inspect every existing instruction path and parent with `lstat` before resolving. Preserve an approved leaf symlink and write only its resolved regular-file target. Reject every root-external or shared destination by comparing `resolved_target.relative_to(resolved_approved_root)` and converting `ValueError` to a typed collision. Do not add `--allow-shared-instructions-symlink` or `--shared-instructions-root`.

Store these fixed fingerprints in `preflight.py` and detect them only in memory:

```python
LEGACY_SAVE_SHA256 = "e7641028c918c614d42cf548f67e4a810e02fa204f641e2cd0b8fd3a3c7ebfb1"
LEGACY_RECALL_SHA256 = "171c000346a5880f4c8a846f1ab34147708ff9a3f25baf7f3ee051504b0bfca5"
LEGACY_SAVE_HEADING = b"# Memory Save \xe2\x80\x94 Agent System Prompt Template"
LEGACY_RECALL_HEADING = b"# Memory Recall \xe2\x80\x94 Agent System Prompt Template"
LEGACY_SAVE_BYTE_LENGTH = 5273
LEGACY_RECALL_BYTE_LENGTH = 5238
```

Use each stable heading to locate a candidate former template, slice exactly its versioned byte length from that heading, and compare the slice's SHA-256. Record only `save` or `recall` and the target path. In `selective`, attach a generic manual-removal warning for either kind. In `all`, convert a detected Save signature into `LegacySaveAllModeCollision`; Recall remains a warning. `cli.py` must serialize typed failures and warnings using safe fields only, never `str()` from an exception that could contain user data.

Add `PlannedAction`, `PlannedTarget`, `SafeDiagnostic`, and `SyncPlan` to `models.py`, so `bundle.py` and `preflight.py` both depend only on models. Add `LegacyKind`, `LegacySignature`, the detector, and `preflight` to `preflight.py`. This prevents a `models -> bundle -> models` import cycle while preserving one typed contract for callers and tests.

```python
from dataclasses import dataclass
from enum import StrEnum


class LegacyKind(StrEnum):
    SAVE = "save"
    RECALL = "recall"


@dataclass(frozen=True, slots=True)
class LegacySignature:
    kind: LegacyKind
    heading: bytes
    digest: str
    byte_length: int


class PlannedAction(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    UNCHANGED = "unchanged"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class PlannedTarget:
    path: Path
    action: PlannedAction


@dataclass(frozen=True, slots=True)
class SafeDiagnostic:
    phase: str
    action: str
    path: Path
    mismatch: str

    def render(self) -> str:
        return f"{self.phase}:{self.action}:{self.path}:{self.mismatch}"


@dataclass(frozen=True, slots=True)
class SyncPlan:
    request: SyncRequest
    bundle: AssetBundle
    targets: tuple[PlannedTarget, ...]
    diagnostics: tuple[SafeDiagnostic, ...]


def preflight(request: SyncRequest, bundle: AssetBundle) -> SyncPlan:
    """Build a no-write plan after validating every selected target."""


def detect_legacy_prompts(
    instruction: bytes,
    signatures: tuple[LegacySignature, ...],
) -> tuple[LegacySignature, ...]:
    """Return matching signature records without retaining target instruction text."""


def safe_diagnostic(signature: LegacySignature, path: Path) -> SafeDiagnostic:
    """Build a redacted warning using only kind and target path."""
```

- [ ] **Step 7: Run preflight unit tests**

Run: `uv run pytest tests/unit/test_sync_agent_assets.py -k "instruction_sections or same_name_skill or symlink or legacy_warning" -v`

Expected: PASS. The test suite proves that all unsafe states fail before an apply attempt and that user content is not emitted.

- [ ] **Step 8: Commit the preflight layer and create the transaction branch**

```bash
git add scripts/agent_assets/models.py scripts/agent_assets/preflight.py scripts/agent_assets/cli.py tests/unit/test_sync_agent_assets.py
uv run ruff check scripts/agent_assets tests/unit/test_sync_agent_assets.py
uv run ruff format scripts/agent_assets tests/unit/test_sync_agent_assets.py
uv run mypy scripts/agent_assets
uv run pytest tests/unit/test_sync_agent_assets.py -v
git commit -m "feat(agent-sync): 非破壊preflightを追加"
gh stack add agent-skills/sync-transaction
```

---

### Task 4: Apply Assets and Hooks as One Reversible Transaction

**Files:**

- Create: `scripts/agent_assets/hooks.py`
- Create: `scripts/agent_assets/transaction.py`
- Modify: `scripts/agent_assets/cli.py`
- Modify: `scripts/agent_assets/preflight.py`
- Modify: `tests/unit/test_sync_agent_assets.py`

**Interfaces:**

- Consumes: a fully successful `SyncPlan` from Task 3.
- Produces: `apply_sync(plan: SyncPlan, operations: FileOperations, verify: Callable[[SyncPlan], bool] | None = None) -> SyncResult`, which either verifies all managed artifacts and hooks or restores the transaction's owned changes in reverse order.

- [ ] **Step 1: Write failing apply and rollback tests**

Add a file-operation seam so tests can inject an `OSError` after a controlled replacement. Cover owned Skill update, new Skill creation, instruction replacement, verification failure, and rollback result.

```python
import shutil

from agent_assets.transaction import ApplyError, HookSetupError, SystemFileOperations, apply_sync


def isolated_repo_root(tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo"
    shutil.copytree(REPO_ROOT / "agent-assets", repo_root / "agent-assets")
    (repo_root / "scripts").mkdir()
    shutil.copy2(
        REPO_ROOT / "scripts" / "agent_turn_hook.py",
        repo_root / "scripts" / "agent_turn_hook.py",
    )
    return repo_root


def prepared_plan_for(
    agent: AgentId,
    home: Path,
    ingestion_mode: IngestionMode,
    repo_root: Path = REPO_ROOT,
):
    request = SyncRequest(
        repo_root=repo_root,
        home=home,
        mode=ExecutionMode.PRODUCTION,
        ingestion_mode=ingestion_mode,
        agent_ids=(agent,),
    )
    return preflight(request, build_bundle(repo_root / "agent-assets"))


def test_apply_sync_restores_owned_instruction_after_verification_failure(tmp_path: Path) -> None:
    home = tmp_path / "home"
    instruction = home / ".claude" / "CLAUDE.md"
    instruction.parent.mkdir(parents=True)
    instruction.write_bytes(b"user-before\n")
    plan = prepared_plan_for(AgentId.CLAUDECODE, home, IngestionMode.SELECTIVE)

    with pytest.raises(ApplyError):
        apply_sync(plan, SystemFileOperations(), verify=lambda _: False)

    assert instruction.read_bytes() == b"user-before\n"


def test_apply_sync_removes_only_new_transaction_artifacts_on_failure(tmp_path: Path) -> None:
    home = tmp_path / "home"
    plan = prepared_plan_for(AgentId.CODEX, home, IngestionMode.SELECTIVE)

    with pytest.raises(ApplyError):
        apply_sync(plan, replace_failure_after_first_skill(home))

    assert not (home / ".agents" / "skills" / "chronos-memory-save").exists()
    assert not (home / ".agents" / "skills" / "chronos-memory-recall").exists()
```

- [ ] **Step 2: Run transaction tests to confirm apply is unavailable**

Run: `uv run pytest tests/unit/test_sync_agent_assets.py -k "apply_sync" -v`

Expected: FAIL with an import error for `agent_assets.transaction`.

- [ ] **Step 3: Implement staged Skills, atomic instruction replacement, and journaled rollback**

Use a frozen `TransactionJournalEntry` for the preflight state and a mutable transaction-local journal only while apply is active. Stage each expected Skill directory under its destination parent, byte-compare against an owned target, move an owned target to its private backup, then atomically replace it with the staged directory. Write an instruction update to a temporary file in the resolved target's directory, preserve the existing permission bits, and replace only the resolved file target.

```python
from collections.abc import Callable
from typing import Protocol


class FileOperations(Protocol):
    def replace(self, source: Path, destination: Path) -> None:
        """Atomically replace one destination path."""

    def move(self, source: Path, destination: Path) -> None:
        """Move an owned path into or out of the transaction journal."""

    def remove(self, path: Path) -> None:
        """Remove a path created by the current transaction."""


class SystemFileOperations:
    """Filesystem implementation used by production synchronization."""


class ReplaceFailureAfterFirstSkill(SystemFileOperations):
    def __init__(self, failure_target: Path) -> None:
        self._failure_target = failure_target

    def replace(self, source: Path, destination: Path) -> None:
        if destination == self._failure_target:
            raise OSError("injected replace failure")
        super().replace(source, destination)


def replace_failure_after_first_skill(home: Path) -> FileOperations:
    return ReplaceFailureAfterFirstSkill(
        home / ".agents" / "skills" / "chronos-memory-recall"
    )


def apply_sync(
    plan: SyncPlan,
    operations: FileOperations,
    verify: Callable[[SyncPlan], bool] | None = None,
) -> SyncResult:
    """Apply one preflighted plan or restore every owned change made by this call."""
    journal = TransactionJournal.create(plan)
    verifier = verify or verify_post_write_state
    try:
        stage_skill_directories(plan, journal, operations)
        replace_owned_skill_directories(plan, journal, operations)
        replace_managed_instruction_blocks(plan, journal, operations)
        install_selected_hooks(plan, journal, operations)
        if not verifier(plan):
            raise PostWriteVerificationError("verification-failed")
    except (OSError, HookSetupError, PostWriteVerificationError) as error:
        rollback_result = rollback_transaction(journal, operations)
        raise ApplyError.from_failure(error, rollback_result) from error
    return journal.commit()
```

Define `ApplyError`, `HookSetupError`, and `PostWriteVerificationError` as typed `RuntimeError` subclasses. Define `TransactionJournalEntry` as a frozen, slotted preflight snapshot and keep mutable backup paths only in the transaction-local `TransactionJournal`.

`verify_post_write_state` must compare both installed Skill trees byte-for-byte to the current SSOT, compare the entire rendered managed block byte-for-byte, compare marker-external instruction bytes to the preflight snapshot, compare all non-ChronosGraph Skill snapshots, and recompute the source bundle digest. Do not trust the prior preflight digest alone.

- [ ] **Step 4: Write failing `all`-mode hook and hook-rollback tests**

Add tests for wrapper creation, OpenCode registration, selective-mode hook absence, plugin idempotence, hook setup failure, and external-change preservation during rollback.

```python
import json
import os

import agent_assets.transaction as transaction
from agent_assets.hooks import HookConfigCollision


def test_all_mode_registers_opencode_plugin_without_replacing_other_config(tmp_path: Path) -> None:
    home = tmp_path / "home"
    config = home / ".config" / "opencode" / "opencode.json"
    config.parent.mkdir(parents=True)
    config.write_text('{"theme":"dark","plugins":["other-plugin"]}', encoding="utf-8")
    plan = prepared_plan_for(AgentId.OPENCODE, home, IngestionMode.ALL)

    apply_sync(plan, SystemFileOperations())
    apply_sync(
        prepared_plan_for(AgentId.OPENCODE, home, IngestionMode.ALL),
        SystemFileOperations(),
    )

    registered = json.loads(config.read_text(encoding="utf-8"))
    assert registered["theme"] == "dark"
    assert registered["plugins"] == ["other-plugin", "@yohi/opencode-plugin-chronos-turn-end"]


@pytest.mark.parametrize("filename", ["opencode.jsonc", "oh-my-opencode.jsonc"])
def test_all_mode_rejects_opencode_jsonc_before_any_apply(
    tmp_path: Path,
    filename: str,
) -> None:
    home = tmp_path / "home"
    jsonc = home / ".config" / "opencode" / filename
    jsonc.parent.mkdir(parents=True)
    jsonc.write_text("// managed elsewhere\n{}", encoding="utf-8")

    with pytest.raises(HookConfigCollision):
        prepared_plan_for(AgentId.OPENCODE, home, IngestionMode.ALL)


def test_all_mode_creates_wrapper_and_selective_mode_does_not(tmp_path: Path) -> None:
    all_repo = isolated_repo_root(tmp_path / "all")
    all_home = tmp_path / "all-home"
    apply_sync(
        prepared_plan_for(AgentId.CLAUDECODE, all_home, IngestionMode.ALL, all_repo),
        SystemFileOperations(),
    )
    wrapper_name = "chronos-turn-hook.cmd" if os.name == "nt" else "chronos-turn-hook.sh"
    assert (all_repo / "scripts" / wrapper_name).is_file()

    selective_repo = isolated_repo_root(tmp_path / "selective")
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


def test_all_mode_hook_failure_restores_skills_instructions_and_wrapper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    repo_root = isolated_repo_root(tmp_path)
    plan = prepared_plan_for(AgentId.CLAUDECODE, home, IngestionMode.ALL, repo_root)

    def fail_hooks(plan, journal, operations) -> None:
        raise HookSetupError("injected hook failure")

    monkeypatch.setattr(transaction, "install_selected_hooks", fail_hooks)

    with pytest.raises(ApplyError):
        apply_sync(plan, SystemFileOperations())

    assert not (home / ".claude" / "skills" / "chronos-memory-save").exists()
    wrapper_name = "chronos-turn-hook.cmd" if os.name == "nt" else "chronos-turn-hook.sh"
    assert not (plan.repo_root / "scripts" / wrapper_name).exists()
```

- [ ] **Step 5: Run hook tests to confirm hook installation is absent**

Run: `uv run pytest tests/unit/test_sync_agent_assets.py -k "opencode_plugin or hook_failure" -v`

Expected: FAIL because hook planning and installation have not been implemented.

- [ ] **Step 6: Implement selected `all`-mode hook artifacts**

In `hooks.py`, generate `scripts/chronos-turn-hook.sh` on POSIX and `scripts/chronos-turn-hook.cmd` on Windows only when the selected canonical set contains Claude Code or Codex. Put an exact ChronosGraph management marker immediately after the interpreter header (`# chronosgraph-managed: turn-hook-wrapper format=1` for POSIX, `rem chronosgraph-managed: turn-hook-wrapper format=1` for Windows). During preflight, an existing same-name wrapper without that exact marker is a hook collision; do not overwrite it. Preserve the existing wrapper behavior: prefer a local virtualenv interpreter, otherwise `uv`, then `python`; invoke `scripts/agent_turn_hook.py` with all received arguments. Do not modify `scripts/agent_turn_hook.py`.

For selected OpenCode in `all` mode, have `preflight.py` validate the hook configuration before returning `SyncPlan`, then let `hooks.py` apply only that approved plan. Update an existing strict-JSON `~/.config/opencode/opencode.json` by appending `@yohi/opencode-plugin-chronos-turn-end` exactly once to `plugins`, preserving every other parsed value. If no OpenCode JSON configuration exists, create a minimal one containing that plugin. If an existing `opencode.jsonc` or `oh-my-opencode.jsonc` would take precedence, or if an existing JSON file cannot be parsed as JSON, raise a preflight hook-config collision instead of creating a competing file or rewriting comments.

```python
OPENCODE_PLUGIN = "@yohi/opencode-plugin-chronos-turn-end"


def updated_plugin_config(original: bytes | None) -> bytes:
    """Return strict JSON preserving existing non-plugin configuration values."""
    try:
        config = {} if original is None else json.loads(original.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HookConfigCollision("opencode-json") from error
    if not isinstance(config, dict):
        raise HookConfigCollision("opencode-config-root")
    plugins = config.get("plugins", [])
    if not isinstance(plugins, list) or not all(isinstance(plugin, str) for plugin in plugins):
        raise HookConfigCollision("opencode-plugin-list")
    plugins = list(plugins)
    if OPENCODE_PLUGIN not in plugins:
        plugins.append(OPENCODE_PLUGIN)
    config["plugins"] = plugins
    return (json.dumps(config, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
```

Include wrappers and OpenCode configuration files in the same journal, backup, post-write verification, and reverse rollback path as Skills and instructions. If rollback sees a target value differing from the transaction's recorded value, leave that external change untouched, report only the owned path that could not be restored, retain its backup artifact, and return non-zero.

- [ ] **Step 7: Run all transaction unit tests**

Run: `uv run pytest tests/unit/test_sync_agent_assets.py -k "apply_sync or opencode_plugin or hook_failure" -v`

Expected: PASS. Failure injection must prove that apply, verification, and hook errors never leave an unverified success state.

- [ ] **Step 8: Commit the transactional implementation**

```bash
git add scripts/agent_assets/hooks.py scripts/agent_assets/transaction.py scripts/agent_assets/cli.py scripts/agent_assets/preflight.py tests/unit/test_sync_agent_assets.py
uv run ruff check scripts/agent_assets tests/unit/test_sync_agent_assets.py
uv run ruff format scripts/agent_assets tests/unit/test_sync_agent_assets.py
uv run mypy scripts/agent_assets
uv run pytest tests/unit/test_sync_agent_assets.py -v
git commit -m "feat(agent-sync): 資産同期をトランザクション化"
```

---

### Task 5: Prove the Synchronizer with Temporary-HOME Integration Tests

**Files:**

- Create: `tests/integration/test_sync_agent_assets.py`

**Interfaces:**

- Consumes: the real `scripts/sync_agent_assets.py` and a copied `agent-assets/` tree as an isolated SSOT fixture.
- Produces: subprocess-level evidence for normal CLI flows and real-filesystem evidence for injected failure flows that the synchronizer preserves non-owned content, is idempotent, and rolls back runtime artifacts.

- [ ] **Step 1: Write the integration harness and initial clean-install failure test**

Build a fixture that copies `agent-assets/` to `tmp_path / "repo" / "agent-assets"`, copies `scripts/agent_turn_hook.py` to `tmp_path / "repo" / "scripts"`, and invokes the real helper with a temporary `HOME` environment. The helper must receive the copied repository root so source updates and `all`-mode wrapper installation never modify the checkout.

```python
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER = REPO_ROOT / "scripts" / "sync_agent_assets.py"
SCRIPTS_ROOT = REPO_ROOT / "scripts"

if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))


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
    environment = {**os.environ, "HOME": str(home)}
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
    return subprocess.run(command, capture_output=True, check=False, env=environment, text=True)


def test_sync_installs_both_skills_and_one_managed_block_when_home_is_empty(tmp_path: Path) -> None:
    source_root = copied_repo_root(tmp_path)

    result = invoke_sync(source_root, tmp_path / "home", "production", ["claudecode"])

    assert result.returncode == 0
    assert (tmp_path / "home" / ".claude" / "skills" / "chronos-memory-save" / "SKILL.md").is_file()
    assert (tmp_path / "home" / ".claude" / "skills" / "chronos-memory-recall" / "SKILL.md").is_file()
    instructions = tmp_path / "home" / ".claude" / "CLAUDE.md"
    assert instructions.read_bytes().count(b"<!-- BEGIN CHRONOSGRAPH MANAGED: agent-memory -->") == 1
```

- [ ] **Step 2: Run the clean-install test to confirm the helper has no end-to-end behavior yet**

Run: `uv run pytest tests/integration/test_sync_agent_assets.py -k "home_is_empty" -v`

Expected: FAIL until `sync` applies a preflighted plan.

- [ ] **Step 3: Implement only the minimal CLI wiring needed for the clean-install test**

Wire `cli.py` so the `sync` subcommand constructs `SyncRequest`, calls `build_bundle`, `preflight`, and `apply_sync` in that order for production mode. For dry-run, call `build_bundle` and `preflight`, print one `create`, `update`, `unchanged`, or `conflict` action per planned target plus the expected digest, then return without creating any filesystem artifact.

```python
def run_sync(request: SyncRequest) -> int:
    """Run the entire selected-Agent synchronization lifecycle."""
    bundle = build_bundle(request.repo_root / "agent-assets")
    plan = preflight(request, bundle)
    if request.mode is ExecutionMode.DRY_RUN:
        print_dry_run_plan(plan)
        return 0
    apply_sync(plan, SystemFileOperations())
    print_success(plan)
    return 0
```

- [ ] **Step 4: Add the required integration scenario matrix**

Add individually named tests for these observable outcomes. Use a fresh `tmp_path` per test and one `When` per test.

```text
clean install for claudecode, codex, and opencode
existing instructions before and after the marker remain byte-identical
unrelated Skills remain present with the same type and digest
second execution against unchanged SSOT reports unchanged and performs no replacement
one copied SSOT file change updates only ChronosGraph-owned targets
selective-to-all replaces only the managed block and adds selected hook artifacts
multi-Agent collision causes no partial update for another selected Agent
injected I/O failure restores owned Skills, instructions, wrappers, and plugin registration
post-write verification failure restores owned artifacts
hook setup failure restores backups and removes new artifacts
rollback failure preserves non-owned external changes and reports unrecovered owned paths
in-root instruction symlink remains a symlink while its target updates
root-external, broken, cyclic, and parent symlinks fail with no write
legacy Save and Recall warnings do not modify the instruction file
legacy Save blocks selective-to-all before hook setup; manual removal allows the next all-mode run
dry-run filesystem snapshot is identical before and after execution
```

Run normal-flow cases through `invoke_sync`. For deterministic I/O, verification, hook, and rollback failure cases, use the same copied repository and temporary HOME but import `agent_assets.cli`, monkeypatch its `SystemFileOperations` factory or the transaction hook/verification seam, then call `run_sync(request)` directly. This exercises the real CLI lifecycle and filesystem paths without adding environment-variable test switches or fault-injection behavior to production code.

- [ ] **Step 5: Run the temporary-HOME integration suite**

Run: `uv run pytest tests/integration/test_sync_agent_assets.py -v`

Expected: PASS. Each scenario must assert target existence or preserved snapshots, exit status, and redacted diagnostics rather than implementation internals.

- [ ] **Step 6: Commit integration coverage and create the bootstrap layer**

```bash
git add tests/integration/test_sync_agent_assets.py scripts/agent_assets/cli.py
uv run ruff check scripts/agent_assets/cli.py tests/integration/test_sync_agent_assets.py
uv run ruff format scripts/agent_assets/cli.py tests/integration/test_sync_agent_assets.py
uv run mypy scripts/agent_assets/cli.py
uv run pytest tests/unit/test_sync_agent_assets.py tests/integration/test_sync_agent_assets.py -v
git commit -m "test(agent-sync): 一時HOMEの同期シナリオを追加"
gh stack add agent-skills/bootstrap
```

---

### Task 6: Integrate the Canonical Agent Set into Bootstrap

**Files:**

- Modify: `scripts/bootstrap.sh:10-207,258-289,532-641`
- Create: `tests/unit/test_bootstrap_agent_assets.py`
- Modify: `tests/unit/test_bootstrap_messages.py`

**Interfaces:**

- Consumes: exactly one raw `--agents` value and the `canonicalize`/`sync` helper commands from Task 2.
- Produces: one stored canonical Agent array passed unchanged to dry-run presentation and the single helper invocation; success output only after helper success.

- [ ] **Step 1: Write failing bootstrap CLI contract tests**

Create subprocess tests that invoke `bash scripts/bootstrap.sh` in `--mode dry-run` with a temporary `HOME`. Supply `--backend sqlite --embedding local-model --agents` so no interactive default applies.

```python
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def run_bootstrap_args(home: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash",
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
```

- [ ] **Step 2: Run bootstrap contract tests to confirm current behavior accepts invalid input**

Run: `uv run pytest tests/unit/test_bootstrap_agent_assets.py -v`

Expected: FAIL because the existing script accepts `notcodex`, does substring matching, and presents the raw value.

- [ ] **Step 3: Parse and canonicalize `--agents` once before every side effect**

In `bootstrap.sh`, count `--agents` occurrences while parsing options and reject missing, duplicate, value-less, and empty raw values. Immediately after argument parsing, run the helper's `canonicalize` command exactly once and retain its newline-delimited result in a Bash array. Do this before dependency installation, `.env` creation, MCP configuration generation, dry-run output, or hook processing.

```bash
AGENTS_SEEN=0
CANONICAL_AGENTS=()

case "$1" in
    --agents)
        AGENTS_SEEN=$((AGENTS_SEEN + 1))
        if [[ "$AGENTS_SEEN" -ne 1 || -z "${2:-}" || "$2" == -* ]]; then
            echo "Error: --agents requires one non-empty value" >&2
            exit 1
        fi
        AGENTS="$2"
        shift
        ;;
esac

if [[ "$AGENTS_SEEN" -ne 1 ]]; then
    echo "Error: --agents is required exactly once" >&2
    exit 1
fi

if ! CANONICAL_AGENT_LINES="$(
    python scripts/sync_agent_assets.py canonicalize --agents "$AGENTS"
)"; then
    exit 1
fi
mapfile -t CANONICAL_AGENTS <<< "$CANONICAL_AGENT_LINES"
CANONICAL_AGENT_CSV="$(IFS=,; printf '%s' "${CANONICAL_AGENTS[*]}")"
```

Use exact Bash array membership only. Remove every `[[ "$AGENTS" == *"agent"* ]]` expression, all unsupported Agent IDs, and the optional final manual-prompt guidance. Replace dry-run's raw-Agent display with `Selected Agent targets: $CANONICAL_AGENT_CSV`.

- [ ] **Step 4: Write failing bootstrap delegation and failure-message tests**

Add a copied temporary repository fixture for a production-mode test with a stub `uv` executable that returns success. Deliberately corrupt its copied `agent-assets/` tree, then assert bootstrap returns non-zero and never prints completion. Add an all-mode fixture with a legacy Save signature to assert the wrapper and plugin config are not created.

```python
def copied_bootstrap_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repo"
    (repository / "scripts").mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "pyproject.toml", repository / "pyproject.toml")
    shutil.copy2(REPO_ROOT / ".env.example", repository / ".env.example")
    shutil.copy2(REPO_ROOT / "scripts" / "bootstrap.sh", repository / "scripts" / "bootstrap.sh")
    shutil.copy2(
        REPO_ROOT / "scripts" / "sync_agent_assets.py",
        repository / "scripts" / "sync_agent_assets.py",
    )
    shutil.copy2(
        REPO_ROOT / "scripts" / "agent_turn_hook.py",
        repository / "scripts" / "agent_turn_hook.py",
    )
    shutil.copytree(REPO_ROOT / "scripts" / "agent_assets", repository / "scripts" / "agent_assets")
    shutil.copytree(REPO_ROOT / "agent-assets", repository / "agent-assets")

    bin_dir = repository / "bin"
    bin_dir.mkdir()
    uv_stub = bin_dir / "uv"
    uv_stub.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = run ] && [ \"$2\" = python ] && [ \"$3\" = scripts/generate_config.py ]; then\n"
        "  printf '%s\\n' '{\"mcpServers\":{}}'\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    uv_stub.chmod(0o755)
    return repository


def run_copied_bootstrap(
    repository: Path,
    home: Path,
    ingestion_mode: str,
    agents: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash",
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
    instruction.write_bytes(
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
```

- [ ] **Step 5: Delegate selected-Agent synchronization atomically**

Define one `run_agent_asset_sync` function immediately after canonicalization. Construct repeated `--agent` options from `CANONICAL_AGENTS` without splitting or interpreting any string again. Call it once from the existing dry-run block before `Simulation complete` and its early exit; call it once from the production path in place of the inline wrapper generation and OpenCode JSON editing block after existing MCP configuration work. Keep current unrelated environment, MCP generation, connectivity, and test behavior intact.

```bash
run_agent_asset_sync() {
    local sync_args=(
        sync
        --repo-root "$PWD"
        --mode "$MODE"
        --ingestion-mode "$INGESTION_MODE"
    )
    local agent
    for agent in "${CANONICAL_AGENTS[@]}"; do
        sync_args+=(--agent "$agent")
    done
    python scripts/sync_agent_assets.py "${sync_args[@]}"
}

# In the existing MODE=dry-run branch, after the simulation text and before exit 0:
run_agent_asset_sync

# In the production hook-configuration location, after MCP configuration work:
run_agent_asset_sync
```

Because `set -e` is active, a helper failure stops bootstrap before `Bootstrap complete!`. Update `--help` to describe `--agents [claudecode,codex,opencode]` as required target environments for Skills, instructions, and `all`-mode hooks. Remove the old `Final Step: Enabling Autonomous Memory` block and every reference to either legacy template path.

- [ ] **Step 6: Run bootstrap regression tests and shell syntax validation**

Run: `bash -n scripts/bootstrap.sh`

Run: `shellcheck scripts/bootstrap.sh`

Run: `uv run pytest tests/unit/test_bootstrap_agent_assets.py tests/unit/test_bootstrap_messages.py -v`

Expected: PASS. The test suite proves the early canonicalization boundary, no dry-run writes, canonical order, strict rejection, asset-plan output, and absence of success output after helper failure.

- [ ] **Step 7: Commit bootstrap integration and create the documentation layer**

```bash
git add scripts/bootstrap.sh tests/unit/test_bootstrap_agent_assets.py tests/unit/test_bootstrap_messages.py
shellcheck scripts/bootstrap.sh
uv run pytest tests/unit/test_bootstrap_agent_assets.py tests/unit/test_bootstrap_messages.py -v
git commit -m "feat(bootstrap): Agent資産同期を統合"
gh stack add agent-skills/docs
```

---

### Task 7: Replace Legacy Documentation and Prompt Sources

**Files:**

- Modify: `README.md:68-82,262-394`
- Modify: `AGENTS.md:26-37`
- Modify: `docs/agent-setup-protocol.md:84-132`
- Delete: `docs/agent-prompts/memory-save-system-prompt.md`
- Delete: `docs/agent-prompts/memory-search-system-prompt.md`
- Modify: `tests/unit/test_agent_asset_sources.py`

**Interfaces:**

- Consumes: the new repository SSOT and the completed bootstrap lifecycle from Tasks 1 through 6.
- Produces: one documented setup path through `docs/agent-setup-protocol.md` and no repository-owned legacy prompt source.

- [ ] **Step 1: Write failing documentation-source regression tests**

Extend the source test file to check repository structure and references, not prose wording.

```python
def test_legacy_prompt_source_files_are_absent() -> None:
    prompts = REPO_ROOT / "docs" / "agent-prompts"

    assert not (prompts / "memory-save-system-prompt.md").exists()
    assert not (prompts / "memory-search-system-prompt.md").exists()


def test_agent_guidance_points_to_repository_asset_ssot() -> None:
    agents_document = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert "agent-assets/" in agents_document
    assert "memory-save-system-prompt.md" not in agents_document
    assert "memory-search-system-prompt.md" not in agents_document
```

- [ ] **Step 2: Run the source regression test to confirm legacy files still exist**

Run: `uv run pytest tests/unit/test_agent_asset_sources.py -k "legacy_prompt_source or guidance_points" -v`

Expected: FAIL because the old prompt files and references remain.

- [ ] **Step 3: Update README, AGENTS, and the Agent Setup Protocol**

In `README.md`, replace the manual prompt-copy section with an explanation that the setup protocol selects supported global Agent environments and bootstrap installs both memory Skills plus a minimal managed global-instructions block. Remove links to old prompt templates and do not describe legacy prompts as a supported migration or fallback route. Retain the `all`-mode hook prerequisites, but list only Claude Code, Codex, and OpenCode as supported automated targets.

In `AGENTS.md`, replace the three `docs/agent-prompts/` Progressive Disclosure entries with one entry pointing to `agent-assets/` as the repository-owned Agent instruction source.

In `docs/agent-setup-protocol.md`, make these exact lifecycle statements:

```text
Phase 4: ask the user to select one or more of claudecode, codex, and opencode as ChronosGraph target environments; empty selection is invalid.
Phase 5: pass one --agents CSV value to bootstrap; bootstrap canonicalizes it before side effects and installs or synchronizes Skills and instructions in both ingestion modes.
Phase 7: verify selected instructions, both Skills, digest equality, marker-external instruction preservation, other-Skill preservation, legacy warning/collision outcome, and all-mode hook artifact success after transaction commit.
```

Delete the two old template files only after their behavior is present in Task 1 assets. Do not delete a user's copied legacy prompt; runtime detection and manual-removal warnings remain the only migration path.

- [ ] **Step 4: Run documentation-source and full targeted tests**

Run: `uv run pytest tests/unit/test_agent_asset_sources.py tests/unit/test_sync_agent_assets.py tests/integration/test_sync_agent_assets.py tests/unit/test_bootstrap_agent_assets.py tests/unit/test_bootstrap_messages.py -v`

Expected: PASS. The test suite confirms that source files and guidance point to the new asset model while installation behavior remains covered separately.

- [ ] **Step 5: Commit the documentation layer**

```bash
git add README.md AGENTS.md docs/agent-setup-protocol.md docs/agent-prompts/memory-save-system-prompt.md docs/agent-prompts/memory-search-system-prompt.md tests/unit/test_agent_asset_sources.py
uv run pytest tests/unit/test_agent_asset_sources.py -v
git commit -m "docs: メモリSkill配布方式へ移行"
```

---

## Final Verification and Stacked PR Creation

- [ ] Run the focused static checks from the correct development environment.

```bash
shellcheck scripts/bootstrap.sh
uv run ruff check scripts/sync_agent_assets.py scripts/agent_assets tests/unit/test_agent_asset_sources.py tests/unit/test_sync_agent_assets.py tests/integration/test_sync_agent_assets.py tests/unit/test_bootstrap_agent_assets.py tests/unit/test_bootstrap_messages.py
uv run mypy scripts/sync_agent_assets.py scripts/agent_assets
uv run pytest tests/unit/test_agent_asset_sources.py tests/unit/test_sync_agent_assets.py tests/integration/test_sync_agent_assets.py tests/unit/test_bootstrap_agent_assets.py tests/unit/test_bootstrap_messages.py -v
uv run pytest tests/unit/ -v
```

- [ ] Perform manual QA with a fresh temporary HOME for each supported Agent in both modes. Verify clean install, no-op re-sync, unrelated instructions and Skills, dry-run, mode switch, `all`-mode hook artifacts, each symlink class, legacy warning, and legacy Save `selective` to `all` rejection.

- [ ] Measure every newly created or modified Python module. Split any module that exceeds 250 pure lines before PR submission.

```bash
awk '!/^[[:space:]]*$/ && !/^[[:space:]]*(#|$)/' scripts/sync_agent_assets.py | wc -l
awk '!/^[[:space:]]*$/ && !/^[[:space:]]*(#|$)/' scripts/agent_assets/models.py | wc -l
awk '!/^[[:space:]]*$/ && !/^[[:space:]]*(#|$)/' scripts/agent_assets/bundle.py | wc -l
awk '!/^[[:space:]]*$/ && !/^[[:space:]]*(#|$)/' scripts/agent_assets/preflight.py | wc -l
awk '!/^[[:space:]]*$/ && !/^[[:space:]]*(#|$)/' scripts/agent_assets/hooks.py | wc -l
awk '!/^[[:space:]]*$/ && !/^[[:space:]]*(#|$)/' scripts/agent_assets/transaction.py | wc -l
awk '!/^[[:space:]]*$/ && !/^[[:space:]]*(#|$)/' scripts/agent_assets/cli.py | wc -l
```

- [ ] Create the five reviewable PRs from the planned stack only after all layer commits and checks are complete. The command creates a PR for each branch with the immediately lower branch as base; inspect the JSON view to confirm the linear order and narrow diffs.

```bash
gh stack submit --auto --open --remote origin
gh stack view --json
```

- [ ] Confirm these PR diffs are separated exactly as planned: source assets only, preflight only, transaction plus integration coverage only, bootstrap only, documentation only. Do not merge any PR.

## Self-Review

1. **Spec coverage:** Task 1 covers the two Skills, minimal instructions, names, and SSOT layout. Tasks 2 and 3 cover agent selection, adapter paths, digest, marker ownership, Skill collision, symlink containment, legacy detection, and safe output. Tasks 4 and 5 cover staged apply, verification, dry-run, hooks, rollback, and the required temporary-HOME matrix. Task 6 covers one-time bootstrap parsing and shared canonical targets. Task 7 removes old sources and aligns all documentation. The final section covers full validation and the required stacked PR delivery.

2. **Placeholder scan:** Every task names exact files, public interfaces, test commands, expected outcomes, commit boundaries, and implementation behavior. No unresolved implementation item remains.

3. **Type consistency:** `AgentId`, `IngestionMode`, `SyncRequest`, `AssetBundle`, and `SyncPlan` flow in that order from CLI parsing through preflight and transaction. Bootstrap passes repeated canonical `--agent` values only; the helper's CSV parser is used only by `canonicalize`.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-28-agent-skills-distribution.md`.

Execute it inline with `superpowers:executing-plans`; do not use subagents. The implementation must create the five-layer `gh stack` and its corresponding narrowly scoped PRs after verification.
