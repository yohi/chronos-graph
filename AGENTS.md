# ChronosGraph Agent Guidelines

## 🎯 WHAT & WHY
ChronosGraph is a Model Context Protocol (MCP) server providing persistent long-term memory for AI agents using a multi-layered temporal knowledge graph. 
- **Goal**: Give agents persistent memory across sessions to track state changes and knowledge evolution.
- **Architecture**: Pipeline-oriented backend (Ingestion/Retrieval) and a Read-Only React Dashboard.

## 📁 Progressive Disclosure (Where to look)
- **Architecture, Data Models, & Core Logic**: ALWAYS refer to `SPEC.md` as the Single Source of Truth before making architectural decisions.
- **Setup & Agent Configuration**: See `README.md`.
- **System Prompts**: See `docs/agent-prompts/memory-save-system-prompt.md`.

## 🛠️ HOW (Tech Stack & Workflow)
- **Environment**: All tests and static analysis should run inside the provided Devcontainer (or a strictly equivalent local environment).
- **Backend (Python 3.12+, uv, FastAPI, FastMCP)**
  - Install: `uv sync --all-extras`
  - Test: `uv run pytest tests/unit/ -v`
  - Lint / Format: `uv run ruff check src/ tests/` / `uv run ruff format src/ tests/`
  - Type Check: `uv run mypy src/`
- **Frontend (React 18, Vite, Tailwind, Cytoscape.js)**
  - Working directory: `cd frontend`
  - Install & Build: `npm install && npm run build`
  - E2E Tests: `npx playwright test`

## 🧠 Essential Rules
- **Stop on Errors**: If you encounter errors (e.g., test failures) during environment setup, do not attempt autonomous fixes. Report them to the user and wait for instructions.
- **Database Migrations**: NEVER hardcode DDL (`CREATE`, `ALTER`, etc.) in application code. Always add `.sql` migration files to `src/context_store/storage/migrations/{sqlite,postgres}/`.
- **Memory Strategy**: Use `memory_save` autonomously for Semantic/Procedural insights. Use `session_flush` for Episodic batch saving (note: this is asynchronous and returns immediately). Prefix inputs with `[📜 Episodic]`, `[🧠 Semantic]`, or `[🕒 Procedural]`.
