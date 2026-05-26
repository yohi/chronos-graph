# ChronosGraph Agent Guidelines

## 1. Project Overview & Purpose (WHY & WHAT)
**ChronosGraph** is an MCP server providing persistent, multi-layered long-term memory for AI agents via a temporal knowledge graph.
- **Goal**: Maintain semantic, procedural, and episodic memories dynamically to support stateful agent interactions.
- **Architecture**: FastMCP Gateway (Tier 1 deterministic rules + Tier 2 Universal LLM Evaluator via LiteLLM) bridging dynamic Memory Clients and persistent context adapters.

## 2. Technology Stack
- **Backend**: Python 3.12+ (managed via `uv`), FastAPI, FastMCP, LiteLLM
- **Frontend**: React 18, Vite, Tailwind CSS (managed via `npm` in `frontend/`)
- **Storage Layer**: SQLite (`sqlite-vec`), PostgreSQL (`pgvector`), Neo4j, Redis, Supabase

## 3. Workflow Commands (HOW to Verify)
Always verify changes using deterministic linters/formatters. Never guess or let LLM perform manual linting.

### Backend (Execute inside Devcontainer):
- **Dependency sync**: `uv sync --all-extras`
- **Unit Testing**: `uv run pytest tests/unit/ -v`
- **Specific Evaluator Test**: `uv run pytest tests/unit/test_mcp_gateway_llm_evaluator.py -v`
- **Integration Test**: `uv run pytest tests/integration/ -v`
- **Linting & Formatting**: `uv run ruff check src/ tests/` and `uv run mypy src/`

### Frontend (Execute inside `frontend/`):
- **Linting & Typecheck**: `npm run lint` & `npx tsc --noEmit`
- **E2E Testing**: `npx playwright test`

## 4. Progressive Disclosure (Read ONLY when needed)
Do not guess implementation details. Consult the following specialized specs:
- **Core Architecture & Model Gateway**: `SPEC.md`
- **Environment & Deploy Details**: `README.md`
- **Memory Ingestion Prompting**: `docs/agent-prompts/memory-save-system-prompt.md`

## 5. High-Leverage Rules (Guiding Principles)
- **Migrations**: NEVER hardcode DDL. Place `.sql` files in `src/context_store/storage/migrations/{backend}/` or `supabase/migrations/`.
- **Supabase Operations**: Always prefer Postgres RPC (`client.rpc()`) for complex logic to prevent concurrency race conditions.
- **Memory Formats**: Inputs must be prefixed strictly with `[📜 Episodic]`, `[🧠 Semantic]`, or `[🕒 Procedural]`.
- **Fail-Soft Evaluator**: Universal Evaluator settings like `max_tokens` or `timeout_seconds` maintain fail-soft logic (invalid values default automatically with warnings).
