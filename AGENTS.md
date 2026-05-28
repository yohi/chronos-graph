# ChronosGraph

**ChronosGraph** is an MCP server that provides persistent, multi-layered long-term memory for AI agents using a temporal knowledge graph.

## Tech Stack
- **Backend:** Python 3.12+ (via `uv`), FastAPI, FastMCP, LiteLLM
- **Frontend:** React 18, Vite, Tailwind CSS (via `npm` in `frontend/`)
- **Storage:** SQLite (`sqlite-vec`), PostgreSQL (`pgvector`), Neo4j, Redis, Supabase

## Workflow Commands
Execute all backend commands **inside the Devcontainer**. Use deterministic tools to verify changes; do not manually format/lint.

### Backend (Python via `uv`)
- **Sync:** `uv sync --all-extras`
- **Test:** `uv run pytest tests/unit/ -v`
- **Lint:** `uv run ruff check src/ tests/`
- **Format:** `uv run ruff format --check src/ tests/`
- **Types:** `uv run mypy src/`

### Frontend (`frontend/` via `npm`)
- **Lint & Types:** `npm run lint` & `npx tsc --noEmit`
- **E2E Test:** `npx playwright test`

## Pointers (Read when needed)
- **Architecture & Specifications:** `SPEC.md`
- **Setup & Environment:** `README.md`
- **Memory Ingestion Prompts:** `docs/agent-prompts/memory-save-system-prompt.md`

## Critical Rules
- **Database Migrations:** Never hardcode DDL. Use `.sql` files in `src/context_store/storage/migrations/{backend}/` or `supabase/migrations/`.
- **Memory Format:** All stored memory content MUST be prefixed strictly with `[📜 Episodic]`, `[🧠 Semantic]`, or `[🕒 Procedural]`.

## High-Leverage Rules
- **Supabase Operations:** Prioritize `client.rpc()` to prevent race conditions in concurrent operations.
- **Fail-Soft Evaluator:** Automatically fallback to default values with a warning for invalid `max_tokens` or `timeout_seconds`.
