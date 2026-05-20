# ChronosGraph Agent Guidelines

## 1. WHAT & WHY
**ChronosGraph** is an MCP server providing persistent, multi-layered long-term memory for AI agents via a temporal knowledge graph. It tracks state changes and knowledge evolution across sessions.

## 2. TECH STACK & TOOLS
- **Backend**: Python 3.12+, FastAPI, MCP (Package Manager: `uv`)
- **Frontend**: React 18, Vite, Tailwind CSS (Package Manager: `npm`)
- **Data**: PostgreSQL (pgvector), SQLite (sqlite-vec), Neo4j, Redis, Supabase (Data API/PostgREST)

## 3. HOW TO CONTRIBUTE (Commands)
*Always run tests and linters to verify your changes. Delegate style rules to these tools.*

**Backend (Python)** (Run inside Devcontainer)
- Install: `uv sync --all-extras`
- Test: `uv run pytest tests/unit/ -v`
- Lint & Format: `uv run ruff check src/ tests/` / `uv run ruff format src/ tests/`
- Type Check: `uv run mypy src/`

**Frontend (React)** (Run from `frontend/` directory)
- Install & Build: `npm install && npm run build`
- Lint: `npm run lint`
- Type Check: `npx tsc --noEmit`
- E2E Tests: `npx playwright test`

## 4. PROGRESSIVE DISCLOSURE
Do not guess implementation details. Search or read these files for domain context:
- **Architecture, Data Models, & Logic**: `SPEC.md`
- **Setup & Environment**: `README.md`
- **Memory Formats**: `docs/agent-prompts/memory-save-system-prompt.md`

## 5. ESSENTIAL RULES
- **Database Migrations**: NEVER hardcode DDL (`CREATE`, `ALTER`) in application code. Generate and apply `.sql` migration files under `src/context_store/storage/migrations/{backend}/`. For Supabase, migrations are strictly managed via `supabase/migrations/*.sql` and Supabase CLI.
- **Supabase Backend**: Prefer Postgres RPC functions (`client.rpc()`) for complex logic (e.g., vector search, server-side distinct, atomic increments) to avoid HTTP Read-Modify-Write race conditions via PostgREST.
- **Memory Management**: Use `memory_save` autonomously for Semantic/Procedural insights; use `session_flush` for Episodic batch saving. Prefix inputs with `[📜 Episodic]`, `[🧠 Semantic]`, or `[🕒 Procedural]`.
- **Error Handling**: If environment setup fails, stop and ask the user; do not attempt blind autonomous fixes.
