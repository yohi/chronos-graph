# ChronosGraph Agent Instructions

## 🎯 Welcome & Project Overview
**ChronosGraph** is an MCP server providing persistent, multi-layered long-term memory for AI agents using a temporal knowledge graph, paired with a Universal Evaluator Gateway for security.

## 🏗️ Architecture & Tech Stack
- **Backend**: Python 3.12+ (managed by `uv`), FastMCP, FastAPI, LiteLLM, asyncpg, aiosqlite, tenacity.
- **Frontend**: React 18, Vite, Tailwind CSS, Zustand, Cytoscape.js (in `frontend/`).
- **Storage Backends**: SQLite (`sqlite-vec`), PostgreSQL (`pgvector`), Neo4j, Redis, Supabase.

---

## 🗺️ Documentation Map (Progressive Disclosure)
- [SPEC.md](file:///home/y_ohi/program/private/chronos-graph2/SPEC.md): Single Source of Truth for system architecture, database schema, and specifications.
- [docs/agent-setup-protocol.md](file:///home/y_ohi/program/private/chronos-graph2/docs/agent-setup-protocol.md): Setup flow and environment variables validation rules.
- [docs/agent-prompts/memory-save-system-prompt.md](file:///home/y_ohi/program/private/chronos-graph2/docs/agent-prompts/memory-save-system-prompt.md): Explicit instructions and format guidelines for the `memory_save` tool.

---

## 🚨 Critical Constraints (DO NOT VIOLATE)
1. **Strict Stdout Pureness**: **NEVER** print debug statements to stdout in `mcp_gateway` (especially in `cli.py` or MCP entrypoints). Stdout must only output JSON messages for MCP transport. Log diagnostics to `sys.stderr` via python `logging`.
2. **No Dependency Bleed**: Keep `mcp_gateway/` (security/policy) strictly decoupled from `context_store/` (memory/storage). Do not cross-import modules between them.
3. **No I/O Inside DB Locks**: NEVER execute `EmbeddingProvider.embed()` or other network/LLM I/O inside a database transaction lock (e.g. `save_memory`). This causes SQLite lock contention.
4. **No Hardcoded DDL**: Raw schema modifications are forbidden. Always use migration files under `src/context_store/storage/migrations/` or `supabase/migrations/`.

---

## 💻 Development Workflow
Always run commands (tests, linting, formatting) inside the devcontainer.

### Key Operations
- **Install deps**: `uv sync --all-extras`
- **Run tests**: `uv run pytest tests/unit/ -v`
- **Lint / Format**: `uv run ruff check src/ tests/` and `uv run ruff format src/ tests/`
- **Type Check**: `uv run mypy src/`
- **Frontend Checks**: `cd frontend && npm run lint && npx tsc --noEmit`

---

## 🧠 Memory Management & Self-Awareness
- **Memory Ingestion**: You must autonomously record key learnings or errors you've resolved. Follow the protocol in [memory-save-system-prompt.md](file:///home/y_ohi/program/private/chronos-graph2/docs/agent-prompts/memory-save-system-prompt.md) using the `memory_save` tool.
- **Rule Evolution**: If you discover a new codebase convention, update `AGENTS.md` or `SPEC.md` directly.
- **Test-Driven**: Always write or update tests in `tests/` when modifying logic before completing your task.
