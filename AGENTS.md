# ChronosGraph

> MCP-based long-term memory system for AI agents using temporal knowledge graphs.

## What is this project?

ChronosGraph provides persistent, multi-layered memory to AI agents (Claude, Gemini, Cursor, etc.) via the Model Context Protocol (MCP). The core is a Python 3.12+ FastMCP server (`src/context_store/`). Storage backends include SQLite (`sqlite-vec`), PostgreSQL (`pgvector`), Supabase, Neo4j (for graph relationships), and Redis (for caching). A React + FastAPI dashboard lives in `frontend/`.

The memory save/recall rules that AI agents themselves follow are distributed as global Agent Skills from `agent-assets/`, with the repository as the single source of truth (SSOT).

## How to work on this project

Run all Python commands through `uv` (never plain `python`/`pip`).

- **Install deps**: `uv sync --all-extras`
- **Run tests**: `uv run pytest tests/unit/ -v` (integration: `uv run pytest tests/integration/ -v`)
- **Lint / Format**: `uv run ruff check src/ tests/` and `uv run ruff format src/ tests/`
- **Type check**: `uv run mypy src/`
- **Frontend** (in `frontend/`): `pnpm install && pnpm run lint && pnpm run test:unit`

Before declaring work complete, run the lint, type check, and tests relevant to your change and confirm they pass.

## Critical constraints

1. **ChronosGate Separation**: Do not reintroduce `mcp_gateway/` into ChronosGraph. Security/policy gateway code belongs in the separate [ChronosGate](https://github.com/yohi/chronos-gate) repository.
2. **No Dependency Bleed**: Keep `context_store/` focused on memory/storage. ChronosGraph may expose shared primitives such as `chronos_shared`, but it must not depend on [ChronosGate](https://github.com/yohi/chronos-gate).
3. **No I/O Inside DB Locks**: NEVER execute `EmbeddingProvider.embed()` or other network/LLM I/O inside a database transaction lock (e.g. `save_memory`). This causes SQLite lock contention.
4. **No Hardcoded DDL**: Raw schema modifications are forbidden. Always use migration files under `src/context_store/storage/migrations/` or `supabase/migrations/`.
5. **Strict Setup Protocol**: Any setup task MUST follow `docs/agent-setup-protocol.md`. You MUST read it before running `scripts/bootstrap.sh` or making configuration changes.
6. **Never create new agent config files**: Do not create new AI agent configuration directories (e.g. `.opencode/`, `.claude/`) or files (e.g. `opencode.jsonc`). Configuration must flow through the established SSOT pipeline only.

## Progressive Disclosure

The following resources are available for task-specific context. Read them only when relevant to your current task.

## Agent-driven setup

This section defines the contract when an AI coding agent is asked to set up
this repository. The setup path branches depending on the user's goal:

- **Use ChronosGraph as a long-term-memory MCP server** — follow
  [docs/agent-setup-protocol.md](docs/agent-setup-protocol.md) as the canonical
  setup source. This path installs and configures the MCP server for end-user
  agents. It is described in the dedicated protocol and is not duplicated here.
- **Set up the repository for local development** — follow the "How to work on
  this project" section in this file (AGENTS.md) as the canonical setup source.
  This path installs Python dependencies through `uv`, runs tests, and prepares
  the working tree for code changes.

When the user's goal is unclear, use `structured_ask` to determine which branch
to follow before running any setup command.

### Generic capability contract

The agent may use the following generic capabilities to perform the setup:

- `repository_inspection` — read files, list directories, grep, glob.
- `file_operations` — create, read, edit, move, delete repository-local files.
- `command_execution` — run shell commands in the working directory.
- `structured_ask` — ask the user for approval, a choice, or missing free-form
  input before privileged or destructive operations.
- `secret_input` — accept a secret through a safe, non-chat channel when
  available.

### Autonomous decisions

The agent may decide the following without asking:

- Whether `uv` is available and whether to use it as the Python runner.
- Whether dependencies are already installed and whether `uv sync --all-extras`
  needs to be run.
- Which verification commands to run based on the changed files (unit tests,
  lint, type check, frontend tests).
- Whether to create a `.env` from `.env.example` for local development.

### Required structured Ask

The agent MUST use `structured_ask` (or plain chat if unavailable) before:

- Running commands that mutate external state (e.g. database migrations on a
  non-local database, cloud resource creation, package publishing).
- Modifying machine-global configuration.
- Installing agent assets or modifying files outside the repository root,
  because those operations may affect the user's home directory or other
  applications.
- Any operation whose risk cannot be inferred from the repository alone.

### Secret policy

- Never ask for a secret value in normal chat.
- Use `secret_input` or a trusted terminal / credential-store fallback when a
  secret is required.
- Prefer official login flows (e.g. `gh auth login`) over command-line
  literals such as `export KEY='<value>'.`
- If a `.env` file is created or updated, confirm that `.gitignore` excludes
  real `.env` files (this repository does).
- Verify capability (env var presence, auth status, a minimal test) rather than
  the secret value itself.

### Verification steps

After local development setup, the agent MUST run the repository-defined
verification commands that match the files it touched:

1. Python backend: `uv run pytest tests/unit/ -v`
2. Lint: `uv run ruff check src/ tests/`
3. Format: `uv run ruff format src/ tests/`
4. Type check: `uv run mypy src/`
5. Frontend (if `frontend/` changed): `cd frontend/ && pnpm install && pnpm run lint && pnpm run test:unit`

If a command fails, report the non-secret output, current repository state,
and the next safe action. Do not suppress type errors or delete failing tests.

### What not to do

- Do not commit, push, or open a pull request unless the user explicitly asks.
- Do not create new AI agent configuration files or directories (e.g. `.opencode/`,
  `.claude/`, `opencode.jsonc`). Configuration flows through the established
  SSOT pipeline in this repository.
- Do not reintroduce `mcp_gateway/` or depend on the separate ChronosGate
  repository from `context_store/`.
- Do not run `EmbeddingProvider.embed()` or other network/LLM I/O inside a
  database transaction lock.
| Topic | Location |
|---|---|
| **System architecture & database schema** | `SPEC.md` |
| **Agent Skills distribution & sync contract** | `SPEC.md` §19 |
| **Setup flow and environment variables** | `docs/agent-setup-protocol.md` |
| **Repository-owned Agent instruction source** | `agent-assets/` |
| **Dashboard frontend** | `frontend/` |
| **Troubleshooting guides** | `docs/troubleshooting/` |
