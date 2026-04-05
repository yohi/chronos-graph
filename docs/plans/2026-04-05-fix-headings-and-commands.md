# Fix Document Headings and Commands Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Correct markdown headings and pre-commit commands in planning documents to ensure they follow markdownlint MD001 and use correct verification commands.

**Architecture:** Surgical replacement of markdown headings and command strings in existing plan files.

**Tech Stack:** Markdown

---

### Task 1: Fix `docs/plans/2026-04-03-pre-commit-task-2-verification.md`

**Files:**
- Modify: `docs/plans/2026-04-03-pre-commit-task-2-verification.md`

**Step 1: Replace headings and commands**

Action:
1. Replace `### Task 2.x` headings with `## Task 2.x`.
2. In Task 2.3 Step 2, replace `pre-commit run ruff-check --files src/context_store/config.py` with `pre-commit run ruff --files src/context_store/config.py`.
3. In Task 2.4 Step 1, replace `pre-commit run mypy --files some_random_file.py` with `pre-commit run mypy --files README.md`.
4. Add a note in Task 2.4 about `pass_filenames: false` for mypy.

**Step 2: Verify changes**

Run: `grep "## Task 2.1" docs/plans/2026-04-03-pre-commit-task-2-verification.md`
Expected: `## Task 2.1: Re-install Hooks`

Run: `grep "pre-commit run ruff --files" docs/plans/2026-04-03-pre-commit-task-2-verification.md`
Expected: `Run: pre-commit run ruff --files src/context_store/config.py`

Run: `grep "pre-commit run mypy --files README.md" docs/plans/2026-04-03-pre-commit-task-2-verification.md`
Expected: `Run: pre-commit run mypy --files README.md`

**Step 3: Commit**

```bash
git add docs/plans/2026-04-03-pre-commit-task-2-verification.md
git commit -m "docs: fix headings and commands in task 2 verification plan"
```

### Task 2: Fix `docs/plans/2026-04-04-fix-reported-issues-plan.md`

**Files:**
- Modify: `docs/plans/2026-04-04-fix-reported-issues-plan.md`

**Step 1: Replace headings**

Action: Replace all `### Task N` headings with `## Task N`.

**Step 2: Verify changes**

Run: `grep "## Task 1" docs/plans/2026-04-04-fix-reported-issues-plan.md`
Expected: `## Task 1: Fix Consolidator Project Boundaries`

**Step 3: Commit**

```bash
git add docs/plans/2026-04-04-fix-reported-issues-plan.md
git commit -m "docs: fix headings in fix-reported-issues plan"
```
