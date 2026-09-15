# Agent Setup Prompt Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make AI-agent setup prompts produce a usable, verifiable ChronosGraph installation while using GitHub Raw URLs for document references.

**Architecture:** Keep `scripts/bootstrap.sh` as the setup entry point and `agent-assets/` as the SSOT. Extend bootstrap only for provider values that are required by the existing settings model, make generated Supabase configuration reflect the selected graph mode, and document client registration and end-to-end verification without modifying machine-global client configuration automatically.

**Tech Stack:** Bash, Python 3.12+, Markdown, pytest, Ruff.

## Global Constraints

- Run Python commands through `uv`.
- Do not put secrets in documentation, logs, commits, or generated fixtures.
- Document references in user-facing setup prompts use `https://raw.githubusercontent.com/yohi/chronos-graph/master/...`.
- Keep checkout-local execution commands such as `./scripts/bootstrap.sh` relative to the verified checkout.
- Do not create new AI-agent configuration files or automatically edit machine-global client configuration.
- Do not reintroduce ChronosGate gateway code into ChronosGraph.

---

### Task 1: Lock configuration behavior with regression tests

**Files:**
- Modify: `tests/unit/test_generate_config.py`
- Modify: `tests/unit/test_bootstrap_messages.py`

**Interfaces:**
- Consumes: `generate_supabase_config()`, `build_start_command()`, and bootstrap defaults.
- Produces: Regression assertions for Supabase graph output, local `uv` launch selection, and provider option presence.

- [x] **Step 1: Add a failing Supabase graph configuration test**

Add a test that sets non-secret placeholder values for `SUPABASE_URL`, `SUPABASE_KEY`, `NEO4J_URI`, `NEO4J_USER`, and `NEO4J_PASSWORD`, invokes `generate_config.py` with `--backend supabase --graph true`, and asserts:

```python
assert env["GRAPH_ENABLED"] == "true"
assert env["GRAPH_SYNC_MODE"] == "async_outbox"
assert env["NEO4J_URI"] == "neo4j+s://example.databases.neo4j.io"
```

- [x] **Step 2: Add failing bootstrap contract assertions**

Assert that `scripts/bootstrap.sh` defaults `MCP_METHOD` to `uv`, accepts `--litellm-api-base` and `--custom-api-endpoint`, and writes the corresponding environment keys.

- [x] **Step 3: Run the focused tests and confirm failure**

Run `uv run pytest tests/unit/test_generate_config.py tests/unit/test_bootstrap_messages.py -q`.

Expected result: the new assertions fail because Supabase graph output is currently forced off, bootstrap defaults to `python`, and the provider flags do not exist.

### Task 2: Extend bootstrap provider and local launch handling

**Files:**
- Modify: `scripts/bootstrap.sh`

**Interfaces:**
- Consumes: Existing `.env` update helper and `--embedding-model` handling.
- Produces: `--litellm-api-base` and `--custom-api-endpoint` values in `.env`, with local MCP configuration defaulting to `uv`.

- [x] **Step 1: Change the default MCP method**

Set `MCP_METHOD="uv"` and update the help text so local setup generates `uv run --quiet context-store` rather than a system `python3` command.

- [x] **Step 2: Parse provider endpoint options**

Add `LITELLM_API_BASE` and `CUSTOM_API_ENDPOINT` variables, parse `--litellm-api-base` and `--custom-api-endpoint`, and reject missing option values using the existing argument validation style.

- [x] **Step 3: Persist endpoint values**

After the existing embedding model update block, call `update_env_key "LITELLM_API_BASE" "$LITELLM_API_BASE"` and `update_env_key "CUSTOM_API_ENDPOINT" "$CUSTOM_API_ENDPOINT"` when values were provided.

- [x] **Step 4: Run the bootstrap contract tests**

Run `uv run pytest tests/unit/test_bootstrap_messages.py -q`.

Expected result: the new bootstrap assertions pass.

### Task 3: Preserve Supabase graph settings in generated MCP configuration

**Files:**
- Modify: `scripts/generate_config.py`
- Modify: `tests/unit/test_generate_config.py`

**Interfaces:**
- Consumes: CLI `--graph` and validated `Settings` values.
- Produces: `generate_supabase_config(python_path, embedding, graph, cache, ssl, method, uv_from)` that emits graph and outbox settings consistently.

- [x] **Step 1: Add graph and Neo4j environment output**

Update `generate_supabase_config()` to accept `graph: bool`. Set `GRAPH_ENABLED` from that argument and set `GRAPH_SYNC_MODE` to `async_outbox` when graph is enabled, otherwise `sync`. When graph is enabled, include `NEO4J_URI`, `NEO4J_USER`, and `NEO4J_PASSWORD` from settings.

- [x] **Step 2: Pass the CLI graph value**

Update the Supabase branch in `main()` to pass `args.graph` to `generate_supabase_config()` without changing SQLite or PostgreSQL behavior.

- [x] **Step 3: Run the focused generator tests**

Run `uv run pytest tests/unit/test_generate_config.py -q`.

Expected result: both existing Supabase tests and the new graph test pass.

### Task 4: Make the prompts and protocol operationally complete

**Files:**
- Modify: `README.md`
- Modify: `README.ja.md`
- Modify: `docs/agent-setup-protocol.md`
- Modify: `docs/agent-setup-protocol.ja.md`

**Interfaces:**
- Consumes: The Raw URL policy and the corrected bootstrap/configuration behavior.
- Produces: Paste-ready prompts and parallel English/Japanese protocol guidance.

- [x] **Step 1: Replace document references in README prompts**

Use these URLs in the prompt text:

```text
https://raw.githubusercontent.com/yohi/chronos-graph/master/docs/agent-setup-protocol.md
https://raw.githubusercontent.com/yohi/chronos-graph/master/AGENTS.md
```

Require structured questions before any side effect, not only before privileged or destructive operations.

- [x] **Step 2: Clarify provider and backend questions**

Collect LiteLLM base URL and custom API endpoint, require Neo4j settings for Supabase graph mode, and explain that generated configuration is not automatically registered with an MCP client.

- [x] **Step 3: Add completion and failure criteria**

Require the user to register the generated MCP configuration, restart or reload the client, and perform an MCP initialization plus memory tool smoke test. For `all` mode, require gateway availability and client-specific hook/plugin registration. State that dry-run must use an existing checkout and must not download, extract, or write files.

- [x] **Step 4: Use Raw URLs for document-only references**

Replace setup-protocol references to `AGENTS.md`, `docs/configuration.md`, and `docs/migration.md` with their `master` Raw URLs when the instruction is to read documentation. Keep local command paths such as `./scripts/bootstrap.sh` unchanged.

- [x] **Step 5: Check language parity and stale version text**

Ensure English and Japanese protocols describe the same branches, remove the stale `v2.0.0` example in favor of a neutral release placeholder, and state that official asset synchronization targets are `claudecode`, `codex`, and `opencode`.

### Task 5: Verify the complete change

**Files:**
- Test: `tests/unit/`
- Verify: `README.md`, `README.ja.md`, `docs/agent-setup-protocol.md`, `docs/agent-setup-protocol.ja.md`, `scripts/bootstrap.sh`, `scripts/generate_config.py`

**Interfaces:**
- Consumes: Tasks 1-4.
- Produces: Evidence that configuration behavior, prompt references, and setup safety rules are consistent.

- [x] **Step 1: Run focused and full checks**

Run `uv run pytest tests/unit/test_generate_config.py tests/unit/test_bootstrap_messages.py -q`, then `uv run pytest tests/unit/ -q`, `uv run ruff check src/ tests/`, and `uv run ruff format --check src/ tests/`.

- [x] **Step 2: Validate shell and documentation references**

Run `bash -n scripts/bootstrap.sh scripts/chronos-turn-hook.sh` and verify that user-facing document-read instructions contain Raw URLs rather than relative paths.

- [x] **Step 3: Inspect repository state**

Run `git diff --check`, `git status --short --branch`, and inspect the diff for credentials, new agent configuration files, unrelated edits, and accidental changes to the storage schema.
