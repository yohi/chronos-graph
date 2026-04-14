# Update Pre-commit Hooks Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move Git hooks (ruff, mypy) from `pre-push` to `pre-commit` stage for faster feedback.

**Architecture:** Update `.pre-commit-config.yaml` to remove `stages: [pre-push]` and adjust `entry` commands to support standard `pre-commit` file filtering for `ruff`, while maintaining full-project check for `mypy`.

**Tech Stack:** pre-commit, ruff, mypy

---

### Task 1: Update `.pre-commit-config.yaml`

**Files:**
- Modify: `.pre-commit-config.yaml`

**Step 1: Update ruff-check hook**
Remove `stages: [pre-push]` and `require_serial: true`. Change `entry` to `ruff check`. Set `pass_filenames: true` (or remove as it's default).

**Step 2: Update ruff-format-check hook**
Remove `stages: [pre-push]` and `require_serial: true`. Change `entry` to `ruff format --check`. Set `pass_filenames: true` (or remove as it's default).

**Step 3: Update mypy hook**
Remove `stages: [pre-push]` and `require_serial: true`. Keep `entry: mypy src/` and `pass_filenames: false`.

**Step 4: Verify syntax**
Run: `pre-commit validate-config`
Expected: `Config is valid.`

**Step 5: Commit changes**
```bash
git add .pre-commit-config.yaml
git commit -m "build: move lint and type checks from pre-push to pre-commit"
```

### Task 2: Install and Verify Hooks

**Files:**
- Modify: `.pre-commit-config.yaml` (already modified)

**Step 1: Re-install pre-commit hooks**
Run: `pre-commit install --hook-type pre-commit --hook-type pre-push`
Expected: Hooks are updated in `.git/hooks`.

**Step 2: Run all hooks manually**
Run: `pre-commit run --all-files`
Expected: All hooks pass or report existing issues.

**Step 3: Verify ruff only checks modified files**
1. Modify a single python file (e.g., add a newline at the end of `src/context_store/config.py`).
2. Run: `pre-commit run ruff-check --files src/context_store/config.py`
3. Verify it only checks that file.

**Step 4: Verify mypy checks src/ regardless of filenames**
1. Run: `pre-commit run mypy --files some_random_file.py`
2. Verify it still runs `mypy src/`.

**Step 5: Final Commit (if any further adjustments were needed)**
```bash
git add .pre-commit-config.yaml
git commit -m "build: finalize pre-commit hook configuration"
```
