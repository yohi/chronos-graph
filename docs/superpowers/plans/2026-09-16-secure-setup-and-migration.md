# Secure Setup and Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make remote setup immutable and checksum-verifiable, keep secrets out of dry-runs, and direct vector dimension mismatches to the safe migration runbook.

**Architecture:** Release automation creates a checksum asset for the GitHub archive addressed by the released commit. Setup documentation verifies that archive before extraction and passes the same commit URL to `--uv-from`; existing generic source handling is unchanged. The orchestrator only changes its recovery guidance, while its matching-dimension branch remains untouched.

**Tech Stack:** Markdown, GitHub Actions YAML, Bash, Python 3.12+, pytest, Ruff.

## Global Constraints

- Run Python commands through `uv`.
- Do not put secrets in documentation, logs, commits, or generated test fixtures.
- Do not execute network or LLM I/O inside database transaction locks.
- Do not introduce raw schema modifications; migration SQL remains under the existing migration directories.
- Do not create or modify AI-agent configuration files.
- Do not run CodeRabbitCLI.

---

### Task 1: Lock the dimension recovery contract with a regression test

**Files:**
- Modify: `tests/unit/test_orchestrator.py:226-238`
- Test: `tests/unit/test_orchestrator.py::TestDimensionCheck::test_dimension_mismatch_error_contains_recovery_hints`

**Interfaces:**
- Consumes: `Orchestrator._check_vector_dimension()` and its `ConfigurationError` text.
- Produces: Assertions requiring the migration guide and safe old-column/new-column workflow, while rejecting direct `ALTER COLUMN ... TYPE` guidance.

- [ ] **Step 1: Strengthen the existing failing assertion**

Add assertions to the existing mismatch test:

```python
assert "docs/migration.md" in msg
assert "embedding_old" in msg
assert "ALTER TABLE memories ALTER COLUMN embedding TYPE" not in msg
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `uv run pytest tests/unit/test_orchestrator.py::TestDimensionCheck::test_dimension_mismatch_error_contains_recovery_hints -v`

Expected: FAIL because the current message contains the direct `ALTER TABLE ... TYPE` instruction and does not mention `docs/migration.md` or `embedding_old`.

---

### Task 2: Update runtime dimension mismatch guidance

**Files:**
- Modify: `src/context_store/orchestrator.py:121-140`
- Test: `tests/unit/test_orchestrator.py::TestDimensionCheck::test_dimension_mismatch_error_contains_recovery_hints`

**Interfaces:**
- Consumes: The existing mismatch branch.
- Produces: A `ConfigurationError` that links to `docs/migration.md` and requires safe staged migration without changing matching-dimension behavior.

- [ ] **Step 1: Replace only the unsafe recovery line**

Replace the PostgreSQL/Supabase direct type alteration instruction with text that says to follow `docs/migration.md`, retain the existing `embedding` data in an old column, add a new column at the target dimension, re-embed into it, validate every row, and switch the index/column only after validation.

- [ ] **Step 2: Run the focused tests to verify they pass**

Run: `uv run pytest tests/unit/test_orchestrator.py::TestDimensionCheck -v`

Expected: PASS, including the existing matching-dimension test.

---

### Task 3: Publish a checksum for the immutable release archive

**Files:**
- Modify: `.github/workflows/release.yml:48-51`

**Interfaces:**
- Consumes: The checked-out release commit and `needs.release-please.outputs.tag_name`.
- Produces: A release asset named `chronos-graph-<full-commit-sha>.tar.gz.sha256` whose checksum covers the archive at `archive/<full-commit-sha>.tar.gz`.

- [ ] **Step 1: Add the source archive checksum step**

After checkout and before the smoke test, compute `git rev-parse HEAD`, download `https://github.com/${GITHUB_REPOSITORY}/archive/${COMMIT_SHA}.tar.gz`, run `sha256sum` on the downloaded archive, and upload only the checksum file to the corresponding GitHub Release with `gh release upload`.

- [ ] **Step 2: Validate workflow syntax**

Run: `ruby -e 'require "yaml"; YAML.load_file(".github/workflows/release.yml")'`

Expected: The workflow parses successfully. If the local Ruby YAML parser rejects GitHub expression syntax, use the repository's available YAML parser without altering workflow expressions.

---

### Task 4: Harden release setup documentation

**Files:**
- Modify: `docs/agent-setup-protocol.md:122-153`
- Modify: `docs/agent-setup-protocol.ja.md:121-152`

**Interfaces:**
- Consumes: The release checksum asset produced by Task 3 and the existing `bootstrap.sh --uv-from` flow.
- Produces: English and Japanese instructions using a full commit SHA, verifying before extraction, passing the same URL to `--uv-from`, and explicitly handling Supabase URL regeneration.

- [ ] **Step 1: Replace mutable tag download examples**

Define a release tag, full commit SHA, archive filename, immutable archive URL, and matching release checksum URL. Download the archive and checksum, verify with `sha256sum -c` on Linux or `shasum -a 256 -c` on macOS, then run `tar -xzf` and `bootstrap.sh`.

- [ ] **Step 2: Add Supabase URL instructions**

State that the collected project URL must be entered as `SUPABASE_URL` in the extracted checkout's `.env`. State that `generate_config.py` reads that value and that a registered `mcp_config.json` must be regenerated with the same backend, embedding, cache, method, and immutable `--uv-from` arguments after `.env` values are complete.

- [ ] **Step 3: Gate Phase 6 by execution mode**

State that production performs `.env` editing and secret entry, while dry-run collects no secrets and proceeds directly to Phase 7. Preserve the existing dry-run synchronization plan, digest, and diagnostics checks.

- [ ] **Step 4: Check both language versions for parity**

Search both files for mutable `archive/refs/tags` URLs, unconditional dry-run secret instructions, and missing `SUPABASE_URL` guidance. Expected: no mutable release URL remains in the protocol examples, and both versions describe the same control flow.

---

### Task 5: Harden the README release examples

**Files:**
- Modify: `README.md:60-86`
- Modify: `README.ja.md:60-86`

**Interfaces:**
- Consumes: The immutable archive URL convention from Task 4.
- Produces: Release examples that do not recommend mutable release tags and direct operators to the checksum verification protocol.

- [ ] **Step 1: Replace the tagged archive source**

Use a full commit SHA archive placeholder in both release examples and state that the checksum must be verified according to `docs/agent-setup-protocol.md` before registering the configuration.

- [ ] **Step 2: Preserve the development example semantics**

Keep the `master` development example but label it as development-only and not suitable for production setup.

---

### Task 6: Verify all changes and inspect the release diff

**Files:**
- Test: `tests/unit/`
- Verify: `.github/workflows/release.yml`, `docs/agent-setup-protocol.md`, `docs/agent-setup-protocol.ja.md`, `docs/migration.md`, `README.md`, `README.ja.md`

**Interfaces:**
- Consumes: Tasks 1-5.
- Produces: Evidence that behavior, documentation, shell syntax, and workflow syntax are valid.

- [ ] **Step 1: Run focused and full checks**

Run: `uv run pytest tests/unit/test_orchestrator.py -v`

Run: `uv run pytest tests/unit/ -v`

Run: `uv run ruff check src/ tests/`

Run: `uv run ruff format --check src/ tests/`

Run: `bash -n scripts/bootstrap.sh`

Expected: All commands exit successfully.

- [ ] **Step 2: Inspect the final diff**

Run: `git diff --check`

Run: `git diff --stat`

Run: `git diff -- . ':!docs/superpowers/plans/*' ':!docs/superpowers/specs/*'`

Expected: Only intended documentation, workflow, orchestrator, and test changes are present; no secrets or unrelated edits appear.

---

### Task 7: Commit and push

**Files:**
- Commit: All intended files from Tasks 1-6

**Interfaces:**
- Consumes: Verified working tree and current branch `docs/documentation-architecture-update`.
- Produces: A Japanese Conventional Commit pushed to `origin`.

- [ ] **Step 1: Review status, diff, and recent history**

Run: `git status --short --branch`

Run: `git diff --check`

Run: `git log --oneline -10`

- [ ] **Step 2: Commit the changes**

Run: `git add .github/workflows/release.yml README.md README.ja.md docs/agent-setup-protocol.md docs/agent-setup-protocol.ja.md docs/migration.md src/context_store/orchestrator.py tests/unit/test_orchestrator.py docs/superpowers/specs/2026-09-16-secure-setup-and-migration-design.md docs/superpowers/plans/2026-09-16-secure-setup-and-migration.md`

Run: `git commit -m "fix: セットアップの完全性検証と移行案内を強化"`

- [ ] **Step 3: Push the current branch**

Run: `git push origin docs/documentation-architecture-update`

Expected: The commit is accepted by the remote without force-push.

- [ ] **Step 4: Confirm the published state**

Run: `git status --short --branch`

Expected: The branch is up to date with `origin/docs/documentation-architecture-update`.
