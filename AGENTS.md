# ChronosGraph Agent Guidelines

## 🎯 What & Why
ChronosGraph is a Model Context Protocol (MCP) server providing persistent long-term memory for AI agents. It uses a temporal knowledge graph to track state changes and provides multi-layered memory ([📜 Episodic], [🧠 Semantic], [🕒 Procedural]).

## 🛠️ Tech Stack & Environment
- **Backend:** Python 3.12+, FastAPI, FastMCP, `uv` for dependency management.
- **Storage:** PostgreSQL (pgvector) or SQLite (sqlite-vec), Neo4j (Graph), Redis (Cache).
- **Frontend:** React 18, Vite, Tailwind CSS, Zustand, Cytoscape.js.
- **Constraint:** **ALL testing and static analysis MUST run inside the provided Devcontainer.** Do not use your local environment.

## 🚀 How (Commands & Workflow)
- **Install & Sync:** `uv sync --all-extras`
- **Tests:** `uv run pytest tests/unit/ -v`
- **Lint & Format:** `uv run ruff check src/ tests/` and `uv run ruff format src/ tests/`
- **Type Check:** `uv run mypy src/`
- **Database Migrations:** Never hardcode DDL. Add `.sql` files to `src/context_store/storage/migrations/{sqlite,postgres}/`.
- **Frontend Workflow:** `cd frontend && npm install && npm run build` (E2E tests: `npx playwright test`)

## 🧠 Memory Strategy (Crucial for Agents)
When developing or using this server, apply these tools selectively:
- **`memory_save`**: Use autonomously to persist high-value insights (Semantic/Procedural) without asking the user.
- **`session_flush`**: Use for episodic batch saving at task boundaries or when context reaches ~8,000 chars.
- **Tags**: Prefix memory content with `[📜 Episodic]`, `[🧠 Semantic]`, or `[🕒 Procedural]` unless a strict schema is required.
- **System Prompt**: Incorporate `docs/agent-prompts/memory-save-system-prompt.md` into your global config (`~/.gemini/GEMINI.md`, `~/.clauderules`, etc.) to enable autonomous saving.

## 📁 Architecture & Specs
For deep architectural details, data models, and the ingestion/retrieval pipeline logic, always refer to **`SPEC.md`**. Avoid searching blindly—the `SPEC.md` is your single source of truth for design decisions.
