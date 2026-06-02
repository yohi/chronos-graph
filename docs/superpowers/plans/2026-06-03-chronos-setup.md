# ChronosGraph Setup Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Install and configure ChronosGraph as a safety hook with Postgres storage.

**Architecture:** Use `scripts/bootstrap.sh` as the primary orchestration tool for installation.

**Tech Stack:** Bash, Python (uv), Postgres.

---

### Task 1: Execute Bootstrap Script

**Files:**
- Modify: `.env` (via script)
- Create: Hook scripts (via script)

- [ ] **Step 1: Run bootstrap.sh with parameters**

Run:
```bash
./scripts/bootstrap.sh \
  --type hook \
  --mode production \
  --backend postgres \
  --ingestion-mode all \
  --evaluator-model cloudflare-workers-ai/@cf/meta/llama-guard-3-8b \
  --source remote \
  --agents opencode \
  --db-host db.cojzbcmvvqlivowmjeza.supabase.co \
  --db-port 5432 \
  --db-name postgres \
  --db-user postgres \
  --graph false \
  --cache inmemory
```

- [ ] **Step 2: Verify script completion**

Expected: "Bootstrap completed successfully" in output.

- [ ] **Step 3: Check generated files**

Check if `.env` has been updated and if `opencode` related files are created.

### Task 2: Post-Setup Guidance

- [ ] **Step 1: Inform user about secrets**

Ask user to fill in `SUPABASE_KEY` (if applicable) or `POSTGRES_PASSWORD` and `CHRONOS_EVALUATOR_API_KEY` in `.env`.
