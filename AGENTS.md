# ChronosGraph Agent Guidelines

## 1. Project Overview
**ChronosGraph** is an MCP server providing persistent, multi-layered long-term memory for AI agents via a temporal knowledge graph.

## 2. Tech Stack & Tools
- **Backend**: Python 3.12+, FastAPI, FastMCP (`uv` for package management)
- **Frontend**: React 18, Vite, Tailwind CSS (`npm` for package management)
- **Data**: PostgreSQL (pgvector), SQLite (sqlite-vec), Neo4j, Redis, Supabase

## 3. Workflow Commands
Always run verification commands before claiming success. Delegate style rules to linters.

**Backend** (Run inside Devcontainer):
- Test: `uv run pytest tests/unit/ -v`
- Lint: `uv run ruff check src/ tests/` & `uv run mypy src/`

**Frontend** (Run in `frontend/`):
- Test & Lint: `npm run lint` & `npx tsc --noEmit` & `npx playwright test`

## 4. Progressive Disclosure
Do not guess implementation details. Read these files when working on specific domains:
- **Architecture, Models & Gateway**: `SPEC.md`
- **Setup & Constraints**: `README.md`
- **Memory Formats**: `docs/agent-prompts/memory-save-system-prompt.md`

## 5. Essential Rules
- **Migrations**: NEVER hardcode DDL. Use `.sql` in `src/context_store/storage/migrations/{backend}/` or `supabase/migrations/`.
- **Supabase**: Prefer Postgres RPC (`client.rpc()`) for complex logic to avoid race conditions.
- **Memory**: Prefix inputs with `[📜 Episodic]`, `[🧠 Semantic]`, or `[🕒 Procedural]`.
- **Errors**: If setup fails, stop and ask the user. Do not attempt blind fixes.
