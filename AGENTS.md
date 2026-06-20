# ChronosGraph

> MCP-based long-term memory system for AI agents using temporal knowledge graphs.

## What is this project?

ChronosGraph provides persistent, multi-layered memory to AI agents (Claude, Gemini, Cursor, etc.) via the Model Context Protocol (MCP). The core is a Python 3.12+ FastMCP server. Storage backends include SQLite (`sqlite-vec`), PostgreSQL (`pgvector`), Supabase, Neo4j (for graph relationships), and Redis (for caching).

## How to work on this project

- **Install deps**: `uv sync --all-extras`
- **Run tests**: `uv run pytest tests/unit/ -v`
- **Lint / Format**: `uv run ruff check src/ tests/` and `uv run ruff format src/ tests/`
- **Type check**: `uv run mypy src/`
- **Frontend** (in `frontend/`): `pnpm install && pnpm run lint && pnpm run test:unit`

## Critical constraints

1. **ChronosGate Separation**: Do not reintroduce `mcp_gateway/` into ChronosGraph. Security/policy gateway code belongs in the separate [ChronosGate](https://github.com/yohi/chronos-gate) repository.
2. **No I/O Inside DB Locks**: NEVER execute `EmbeddingProvider.embed()` or other network/LLM I/O inside a database transaction lock (e.g. `save_memory`). This causes SQLite lock contention.
3. **No Hardcoded DDL**: Raw schema modifications are forbidden. Always use migration files under `src/context_store/storage/migrations/` or `supabase/migrations/`.
4. **Strict Setup Protocol**: Any setup task MUST follow `docs/agent-setup-protocol.md`. You MUST read it before running `scripts/bootstrap.sh` or making configuration changes.
5. **Never create new agent config files**: Do not create new AI agent configuration directories (e.g. `.opencode/`, `.claude/`) or files (e.g. `opencode.jsonc`). Configuration must flow through the established SSOT pipeline only.

## Progressive Disclosure

The following resources are available for task-specific context. Read them only when relevant to your current task.

| Topic | Location |
|---|---|
| **System architecture & database schema** | `SPEC.md` |
| **Setup flow and environment variables** | `docs/agent-setup-protocol.md` |
| **Guidelines for the `memory_save` tool** | `docs/agent-prompts/memory-save-system-prompt.md` |
| **All agent-facing prompts** | `docs/agent-prompts/` |
| **Troubleshooting guides** | `docs/troubleshooting/` |
