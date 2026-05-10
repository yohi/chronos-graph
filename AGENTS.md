# ChronosGraph Agent Guidelines

## WHAT & WHY
**ChronosGraph** is an MCP server providing persistent, multi-layered long-term memory for AI agents via a temporal knowledge graph.
- **Goal**: Track state changes and knowledge evolution across sessions.
- **Architecture**: Pipeline-oriented backend (FastAPI/MCP) with a Read-Only React Dashboard.

## PROGRESSIVE DISCLOSURE (Map)
Do not guess. Always read these files for domain knowledge before acting:
- **Architecture, Models, & Core Logic**: `SPEC.md`
- **Setup & Agent Configuration**: `README.md`
- **System Prompts**: `docs/agent-prompts/memory-save-system-prompt.md`
- **Superpowers Specs/Plans**: `docs/superpowers/` (for multi-step agent plans)

## HOW (Commands)
*Note: All commands must be run inside the project Devcontainer.*

**Backend (Python 3.12+, uv)**
- Install: `uv sync --all-extras`
- Test: `uv run pytest tests/unit/ -v`
- Lint/Format: `uv run ruff check src/ tests/` / `uv run ruff format src/ tests/`
- Type Check: `uv run mypy src/`

**Frontend (React 18, Vite)** (Run from `frontend/` directory)
- Install & Build: `npm install && npm run build`
- E2E Tests: `npx playwright test`

## ESSENTIAL RULES
- **Stop on Errors**: If you encounter errors during environment setup, do not attempt autonomous fixes. Report to the user and wait.
- **Migrations**: NEVER hardcode DDL (`CREATE`, `ALTER`). Always add `.sql` migration files to `src/context_store/storage/migrations/{sqlite,postgres}/`.
- **Memory Strategy**: Use `memory_save` autonomously for Semantic/Procedural insights. Use `session_flush` for Episodic batch saving. Prefix inputs with `[📜 Episodic]`, `[🧠 Semantic]`, or `[🕒 Procedural]`.