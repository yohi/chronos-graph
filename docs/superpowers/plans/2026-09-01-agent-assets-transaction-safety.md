# Agent Assets Transaction Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent bundle digest collisions, external writes through staged Skill symlinks, and data loss when rollback restoration moves fail.

**Architecture:** Keep bundle hashing deterministic with fixed-width length-prefixed path/content records. Keep Skill replacement staged locally, removing only a copied symlink before copying managed files. During rollback, move an existing target's backup into a target-local recovery stage before removing the applied target, and retain all unresolved backup locations in the rollback result.

**Tech Stack:** Python 3.12+, `pathlib`, `hashlib`, `shutil`, pytest, existing `FileOperations` and `TransactionJournal` abstractions.

## Global Constraints

- Do not execute embedding, network, or other external I/O inside database locks; this change is filesystem-only.
- Use `operations.move` through the existing `FileOperations` protocol; do not bypass injected test doubles with a concrete filesystem implementation.
- Do not expose raw filesystem errors or recovery paths through the existing CLI redacted error line.
- Preserve unmanaged Skill entries and external changes detected by the existing preflight and post-write checks.
- Use migration files for schema changes; no schema changes are part of this work.

---

### Task 1: Lock the digest collision regression

**Files:**
- Modify: `tests/unit/test_agent_asset_regressions.py:93-101`

**Interfaces:**
- Consumes: `compute_bundle_digest(asset_root: Path) -> str`.
- Produces: A regression test proving two distinct trees that serialize identically under the old NUL format receive different digests after the fix.

- [x] **Step 1: Replace the old delimiter-only assertion with two trees**

Create `first` with file `a` containing `b\0c\0d`; create `second` with file `a` containing `b` and file `c` containing `d`. Assert the trees differ and their computed digests differ.

- [x] **Step 2: Run the focused test to verify it fails before implementation**

Run: `uv run pytest tests/unit/test_agent_asset_regressions.py::test_bundle_digest_distinguishes_nul_record_collisions -q`

Expected: FAIL because the current raw NUL serialization returns the same digest for both trees.

### Task 2: Make bundle digest records injective

**Files:**
- Modify: `scripts/agent_assets/bundle.py:14-35`
- Test: `tests/unit/test_agent_asset_regressions.py:93-101`

**Interfaces:**
- Consumes: validated regular file paths and bytes.
- Produces: `compute_bundle_digest()` using an 8-byte big-endian length before each relative path and content field.

- [x] **Step 1: Encode each path/content field with a fixed-width length**

For every sorted regular file, update the SHA-256 input in this order:

```python
digest.update(len(relative_path).to_bytes(8, "big"))
digest.update(relative_path)
digest.update(len(content).to_bytes(8, "big"))
digest.update(content)
```

Remove the delimiter-only updates. Keep symlink and unsupported-file validation unchanged.

- [x] **Step 2: Run the digest regression and existing bundle tests**

Run: `uv run pytest tests/unit/test_agent_asset_regressions.py::test_bundle_digest_distinguishes_nul_record_collisions tests/unit/test_sync_agent_assets.py -q`

Expected: PASS, including the existing regular-asset-change and symlink-rejection tests.

### Task 3: Lock staged Skill symlink safety

**Files:**
- Modify: `tests/unit/test_sync_agent_assets.py` near the existing apply/rollback tests

**Interfaces:**
- Consumes: existing `preflight`, `apply_sync`, `SystemFileOperations`, and temporary home fixtures.
- Produces: A regression test that uses an owned Skill root whose `SKILL.md` points outside the root and verifies the external file is unchanged after a failed or rejected sync.

- [x] **Step 1: Add an owned Skill with an external `SKILL.md` symlink**

Prepare the selected Agent home with a managed sentinel, an external file containing `outside-before`, and `SKILL.md` symlinked to that external file. Run the preflighted sync and assert the external file remains unchanged and the staged/target Skill is not allowed to write through the link.

- [x] **Step 2: Run the new symlink regression before the fix**

Run: `uv run pytest tests/unit/test_sync_agent_assets.py::<new-symlink-test> -q`

Expected: FAIL because `shutil.copy2()` follows the staged destination symlink.

### Task 4: Remove staged managed-file symlinks before copying

**Files:**
- Modify: `scripts/agent_assets/transaction_apply.py:90-97`
- Test: `tests/unit/test_sync_agent_assets.py:<new-symlink-test>`

**Interfaces:**
- Consumes: `_stage_skill(source: Path, existing: Path | None, stage: Path)`.
- Produces: A staged Skill whose managed files are regular files before `shutil.copy2()` writes them.

- [x] **Step 1: Unlink copied managed-file symlinks in the stage only**

After `copytree(existing, stage, symlinks=True)`, inspect each managed destination before `copy2()`. If `stage / name` is a symlink, call `unlink()` on that staged link; never resolve or remove its target. Then copy the validated SSOT file so the destination is a regular file.

- [x] **Step 2: Run the symlink regression and transaction tests**

Run: `uv run pytest tests/unit/test_sync_agent_assets.py::<new-symlink-test> tests/unit/test_agent_asset_regressions.py -q`

Expected: PASS and no external link target changes.

### Task 5: Lock rollback recovery behavior

**Files:**
- Modify: `tests/unit/test_sync_agent_assets.py` near `ReplaceFailingFileOperations`

**Interfaces:**
- Consumes: `apply_sync`, a `FileOperations` fake that fails when moving a journal backup into the target-local recovery stage.
- Produces: Tests proving the target is not removed when staging the backup fails and `RollbackResult` retains the unresolved backup location.

- [x] **Step 1: Add a move-failure fake and regression test**

Use an existing instruction file so apply creates a backup. Force post-write verification to fail, then fail the backup-to-recovery-stage move. Assert the original target still exists, the backup remains, `rollback.succeeded` is false, and the result exposes the backup path through its structured recovery field.

- [x] **Step 2: Run the new rollback test before the fix**

Run: `uv run pytest tests/unit/test_sync_agent_assets.py::<new-rollback-test> -q`

Expected: FAIL because the current rollback removes the target before attempting the restore move and `RollbackResult` has no recovery-location field.

### Task 6: Add structured unresolved backup information

**Files:**
- Modify: `scripts/agent_assets/transaction_types.py:54-68`
- Test: `tests/unit/test_sync_agent_assets.py::<new-rollback-test>`

**Interfaces:**
- Consumes: rollback status/category and unresolved backup paths.
- Produces: `RollbackResult(succeeded, category=None, recovery_paths=())` with `recovery_paths: tuple[Path, ...]`; `failure()` continues to redact exception details.

- [x] **Step 1: Extend `RollbackResult` without changing existing constructor call compatibility**

Add a defaulted tuple field for unresolved recovery paths, include it in `__slots__`, and keep the existing two-argument construction valid. Do not change the CLI’s current category-only rendering.

- [x] **Step 2: Run result and existing error-format tests**

Run: `uv run pytest tests/unit/test_agent_asset_regressions.py::test_main_redacts_apply_errors tests/unit/test_sync_agent_assets.py::<new-rollback-test> -q`

Expected: PASS with no raw path added to the CLI error output.

### Task 7: Stage backups before target removal during rollback

**Files:**
- Modify: `scripts/agent_assets/transaction_rollback.py:11-35`
- Test: `tests/unit/test_sync_agent_assets.py::<new-rollback-test>`

**Interfaces:**
- Consumes: `TransactionJournal.stage_root_for`, `operations.move`, `operations.remove`, and `matches_applied`.
- Produces: Rollback that moves each existing target backup into a target-parent-local recovery stage before removing the applied target; failures retain the unresolved source path in `RollbackResult.recovery_paths`.

- [x] **Step 1: Move a backup to a target-local recovery stage before removal**

For an installed entry with a backup, create a recovery stage under `entry.target.path.parent`, call `operations.move(entry.backup, recovery_path)`, and only then call `operations.remove(entry.target.path)`. If the first move raises, record the original backup path, set rollback failure, and skip removal for that entry.

- [x] **Step 2: Restore from the recovery stage and retain paths on later failure**

After successful target removal, move the recovery-stage backup to the target. Record the recovery-stage path if this final move fails. Collect unresolved paths across all entries and return them for both rollback-failed and externally-changed outcomes. Clean target-local staging roots only after successful rollback; preserve roots containing recoverable backups on failure.

- [x] **Step 3: Run rollback and full targeted test coverage**

Run: `uv run pytest tests/unit/test_sync_agent_assets.py tests/unit/test_agent_asset_regressions.py -q`

Expected: PASS, including existing external-change preservation and post-write rollback tests.

### Task 8: Run final quality gates

**Files:**
- Test: `tests/unit/test_agent_asset_regressions.py`
- Test: `tests/unit/test_sync_agent_assets.py`
- Test: `tests/integration/test_sync_agent_assets.py`

- [x] **Step 1: Run the complete agent-assets unit and integration tests**

Run: `uv run pytest tests/unit/test_agent_asset_regressions.py tests/unit/test_sync_agent_assets.py tests/integration/test_sync_agent_assets.py -q`

Expected: PASS with zero failures.

- [x] **Step 2: Run formatting, lint, and type checks for changed Python files**

Run: `uv run ruff check scripts/agent_assets tests/unit/test_agent_asset_regressions.py tests/unit/test_sync_agent_assets.py tests/integration/test_sync_agent_assets.py && uv run ruff format --check scripts/agent_assets tests/unit/test_agent_asset_regressions.py tests/unit/test_sync_agent_assets.py tests/integration/test_sync_agent_assets.py && uv run mypy scripts/agent_assets`

Expected: All commands exit successfully without changing files.
