# Pre-commit Hooks Verification (Task 2) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Re-install pre-commit hooks and verify the behavior of ruff and mypy as specified in the Task 2 of 'Update Pre-commit Hooks Implementation Plan'.

**Architecture:** 
- Manual installation of pre-commit hooks.
- Systematic verification using 'pre-commit run' with specific file filters and manual file modification.
- Verification of 'ruff' checking only changed files and 'mypy' checking the entire 'src/' directory regardless of arguments.

**Tech Stack:** 
- pre-commit
- ruff
- mypy

---

## Task 2.1: Re-install Hooks

**Files:**
- N/A

**Step 1: Install hooks**

Run: `pre-commit install --hook-type pre-commit --hook-type pre-push`
Expected: "pre-commit installed at .git/hooks/pre-commit" and "pre-push installed at .git/hooks/pre-push"

## Task 2.2: Initial Full Run

**Files:**
- N/A

**Step 1: Run all hooks on all files**

Run: `pre-commit run --all-files`
Expected: All hooks pass or reveal existing issues that need to be addressed.

## Task 2.3: Verify Ruff Only Checks Modified Files

**Files:**
- Modify: `src/context_store/config.py`

**Step 1: Modify a file**

Action: Add a newline to the end of `src/context_store/config.py`.

**Step 2: Run ruff on the modified file**

Run: `pre-commit run ruff --files src/context_store/config.py`
Expected: Output showing ruff passed (or failed) only for the specified file. (Check the count of files processed if shown).

## Task 2.4: Verify Mypy Checks Entire src/ Regardless of Filenames

**Files:**
- N/A

**Step 1: Run mypy with README.md**

Run: `pre-commit run mypy --files README.md`
Expected: Mypy output should indicate it is checking `src/` (e.g., "Success: no issues found in [N] source files" where N is the total number of files in src/). Even if `README.md` is provided, it should still run on `src/` because `.pre-commit-config.yaml` sets mypy's `pass_filenames: false`.

## Task 2.5: Finalize and Commit

**Files:**
- Modify: `.pre-commit-config.yaml` (if needed)

**Step 1: Commit final changes**

Run: `git add .pre-commit-config.yaml`
Run: `git commit -m "build: finalize pre-commit hook configuration"`
Expected: Successful commit.

---
