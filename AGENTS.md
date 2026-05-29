# ChronosGraph Agent Instructions

**Project Overview**: ChronosGraph is an MCP server providing persistent, multi-layered long-term memory for AI agents using a temporal knowledge graph, paired with a Universal Evaluator Gateway for security.

## 🏗️ Architecture & Tech Stack
- **Backend**: Python 3.12+ (managed by `uv`), FastMCP, FastAPI, LiteLLM, asyncpg, aiosqlite, tenacity.
- **Frontend**: React 18, Vite, Tailwind CSS, Zustand, Cytoscape.js (via `npm` in `frontend/`).
- **Storage Backends**: SQLite (`sqlite-vec`), PostgreSQL (`pgvector`), Neo4j, Redis, Supabase.
- **Topological Rule**: `mcp_gateway/` (Security/Auth/Policy) is strictly isolated from `context_store/` (Storage/Memory). They communicate entirely via standard I/O (stdio) MCP.

## 🗺️ Project Navigation
- `src/context_store/`: Core memory system (ingestion, retrieval, graph linker, embeddings).
- `src/mcp_gateway/`: Security proxy, Intent-Based Access Control (IBAC), LLM evaluator.
- `frontend/`: Read-only visual dashboard for the graph.
- `SPEC.md`: Single Source of Truth for architecture and specifications.
- `supabase/migrations/`: Cloud PostgreSQL DDL.

## 💻 Development Workflow
**Execute all backend commands INSIDE the Devcontainer.**

- **Dependencies**: `uv sync --all-extras`
- **Test**: `uv run pytest tests/unit/ -v`
- **Lint**: `uv run ruff check src/ tests/`
- **Format**: `uv run ruff format src/ tests/`
- **Type Check**: `uv run mypy src/`
- **Frontend Checks**: `cd frontend && npm run lint && npx tsc --noEmit`

## 🚨 Critical Constraints (NEVER DO THESE)
1. **No Dependency Bleed**: NEVER import `context_store` modules into `mcp_gateway` modules or vice versa.
2. **Strict Stdout Pureness**: NEVER use `print()` in `mcp_gateway` (especially `cli.py`). Standard output MUST contain exactly one JSON line. Log all diagnostics to `sys.stderr` via the `logging` module.
3. **No I/O inside DB Locks**: NEVER execute `EmbeddingProvider.embed()` or other network I/O inside a database transaction lock (e.g., `save_memory`). This causes catastrophic `SQLITE_BUSY` errors.
4. **No Hardcoded DDL**: NEVER execute raw schema modifications. Always use `.sql` files in `src/context_store/storage/migrations/{backend}/` or `supabase/migrations/`.

## 📝 Coding Conventions
- **Typing**: Use strict Python 3.12+ type hints. Always include `from __future__ import annotations` at the very top of Python files.
- **Concurrency**: Use `asyncio.gather` for parallel I/O, bounded by `asyncio.Semaphore` where appropriate. Use `asyncio.wait_for` to strictly enforce timeouts to prevent system hangs.
- **Fail-Soft Engineering**: When parsers, network calls, or non-critical LLM evaluations fail, catch specific exceptions and fallback to safe defaults (e.g., "ask" for evaluators, default values for configurations) rather than crashing the process.
- **Atomicity**: For Supabase backends, prioritize `client.rpc()` for operations requiring atomicity (e.g., counters, bulk updates).

## 🧠 Agent Self-Awareness
When working in this repository, you are a developer extending the system.
- If you discover a new project convention or architecture rule, update this `AGENTS.md` or `SPEC.md` directly using the `replace` tool.
- Always write tests (`tests/unit/`) when creating new modules or fixing bugs before reporting completion.
