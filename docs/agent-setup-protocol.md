# Agent Setup Protocol

> [!CAUTION]
> **Mandatory instruction for AI agents:**
> If you are an AI agent (Claude Code, Gemini CLI, Cursor, etc.), you MUST follow this protocol before taking any action with side effects (installing software, creating or modifying files, running commands).
>
> The actual setup is performed mechanically through `scripts/bootstrap.sh`. AI agents are strictly forbidden from creating configuration files or hook scripts from scratch, in order to avoid configuration drift.
>
> Your role is to ask the user for the required settings, then pass the answers as arguments to `scripts/bootstrap.sh`.
>
> Even if `.env` or configuration files already exist, start again from Phase 1 unless you are certain they were created through this protocol.

> [!IMPORTANT]
> **Strict ask constraint:**
> When executing any **BLOCKING STEP** in this protocol, do not rely on plain chat interaction. Use `ask_question` or an equivalent tool so the user explicitly selects or agrees in the UI.

---

## Setup Phases

### Phase 1: Determine the goal and execution mode (BLOCKING STEP)

Before calling any tool that makes changes, ask the user:

1. **Setup target:**
   - `mcp` — configure the long-term-memory MCP server.
   - If the user wants a pre-execution safety-evaluation hook, stop and point them to the separate [ChronosGate](https://github.com/yohi/chronos-gate) repository instead.
2. **Execution mode:**
   - `production` — actually build or change the environment.
   - `dry-run` — only simulate and explain; make no changes.

---

### Phase 2: Confirm detailed settings (BLOCKING STEP)

#### Case A: Long-term-memory MCP

Use `ask_question` (or equivalent) to collect the following choices at once.

*(Note: ChronosGraph's long-term-memory MCP setup does not include an LLM evaluator. Safety evaluation is handled by ChronosGate.)*

1. **Source / launch method:**
   - `remote` (recommended): run on-the-fly with `uvx` without cloning the repository.
   - `local`: run directly inside a local clone of this repository.
2. **Ingestion mode:**
   - `all`: automatically save the full conversation log at the end of each agent turn. Requires a hook script.
   - `selective` (recommended): the agent saves only important information via the `memory_save` tool. No hook script is required.
3. **Storage backend:**
   - `sqlite` (recommended): zero-config, lightweight.
   - `postgres`: production backend with pgvector.
   - `supabase`: production backend through the Supabase Data API.
4. **Graph relationships:**
   - enabled: SQLite uses an internal graph; PostgreSQL uses an external Neo4j.
   - disabled (recommended): fast, simple, lightweight setup.
5. **Cache:**
   - `inmemory` (recommended): managed in process memory.
   - `redis`: external Redis cache server.
6. **Embedding provider:**
   - `local-model` (recommended): local model such as `cl-nagoya/ruri-v3-310m`.
   - `openai`: OpenAI Embedding API.
   - `litellm`: model accessed through LiteLLM.
   - `custom-api`: your own custom API.

Additional inputs:

- **When PostgreSQL is selected:** confirm that pgvector is enabled.
- **When `local-model` is selected:** ask for the local model name (default: `cl-nagoya/ruri-v3-310m`).
- **When `openai`, `litellm`, or `custom-api` is selected:** ask for the embedding model name (e.g. `text-embedding-3-small`).

#### Case B: Safety-evaluation hook

ChronosGraph itself does not set up safety-evaluation hooks. If the user asks for one, point them to the ChronosGate repository and do **not** run `scripts/bootstrap.sh`.

---

### Phase 3: Collect parameters (BLOCKING STEP)

Based on the answers above, use input tools to collect any required parameters.

> **Security note:** When a URL contains a password, ask the user to enter the password part as a placeholder such as `[YOUR-PASSWORD]`. Set the real password directly in `.env` in Phase 6.

#### Case A: Long-term-memory MCP

- **PostgreSQL connection URL:** e.g. `postgresql://postgres:[YOUR-PASSWORD]@localhost:5432/postgres`.
- **Supabase project URL:** e.g. `https://your-project.supabase.co` (enter the API key in Phase 6).
- **Neo4j connection URI:** e.g. `neo4j+s://[YOUR-USER]:[YOUR-PASSWORD]@host`.
- **Redis connection URL:** e.g. `redis://default:[YOUR-PASSWORD]@host:port`.

#### Case B: Safety-evaluation hook

Defer to the ChronosGate instructions. Do **not** write `CHRONOS_EVALUATOR_*` settings into ChronosGraph's `.env` from this protocol.

---

### Phase 4: Select target AI agents (BLOCKING STEP)

Use `ask_question` (or equivalent) to let the user select one or more of `claudecode`, `codex`, or `opencode`. Empty selection is invalid.

Even in `--non-interactive` mode, do not implicitly select an agent. Pass the explicit selection to `--agents` as a single CSV value.

---

### Phase 5: Run `scripts/bootstrap.sh`

Invoke `scripts/bootstrap.sh` with the collected parameters. Do not edit or create files directly; let the script do all the work.

`--agents` must be a single CSV value. The bootstrap script canonicalizes the value before it starts side effects and installs or synchronizes the Skills and instructions for both ingestion modes.

`--source=local|remote` only controls how the MCP server runs. The SSOT for agent assets is always `agent-assets/` in the current checkout or release tarball.

If `opencode` is selected in `all` mode, confirm before running that the user's `~/.npmrc` already has the `@yohi` GitHub Packages registry mapping and a credential source with read access. The agent must not create, update, or save `.npmrc` or tokens.

#### Example command

```bash
./scripts/bootstrap.sh \
  --type <type> \
  --mode <mode> \
  --backend <backend> \
  --embedding <embedding> \
  --cache <cache> \
  --graph <graph> \
  --source <source> \
  --ingestion-mode <ingestion-mode> \
  --agents <comma_separated_agents> \
  [--db-host <db_host>] [--db-port <db_port>] [--db-name <db_name>] [--db-user <db_user>] \
  [--neo4j-uri <neo4j_uri>] [--neo4j-user <neo4j_user>] \
  [--redis-url <redis_url>] \
  [--embedding-model <embedding_model>]
```

---

### Phase 6: Enter secrets

1. Ask the user to open `.env` and replace placeholders such as `[YOUR-PASSWORD]` with real passwords and API keys (e.g. `OPENAI_API_KEY`, `SUPABASE_KEY`).
2. Wait for the user to confirm that the secrets have been entered before proceeding.

---

### Phase 7: Verify the synchronization result

After a successful synchronization, verify the transaction commit, installed instructions, both Skills, digest match, preservation of out-of-marker instructions, preservation of other Skills, allowed legacy warnings, and hook-artifact success for `all` mode.

If `all` mode is rejected because an old Save prompt is detected as a preflight collision, ask the user to delete the detected old Save prompt manually and re-run bootstrap. The rejection happens before writes and hook setup, and bootstrap does not automatically delete old or duplicated prompts.

If `selective` mode is used, or if an old Recall prompt is detected in `all` mode, confirm the warning and re-run after manual deletion if needed.
