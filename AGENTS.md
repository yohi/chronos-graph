# ChronosGraph Agent Guidelines

## Project

MCP server providing persistent long-term memory for AI agents with a temporal knowledge graph.

## Memory Strategy (Important for Agents)

As an agent, you must utilize the following two tools selectively for saving memories:

1.  **`memory_save` (Autonomous Saving / Semantic & Procedural)**:
    - Save information with high reuse value for future sessions, such as user preferences, critical knowledge, and procedures used to resolve errors.
    - Summarize the saved text so it can be understood without context.
    - Execute silently at your own discretion; do not ask the user for confirmation.

2.  **`session_flush` (Batch Saving / Episodic)**:
    - Save the entire conversation context.
    - Invoke this tool when the conversation becomes long (approx. 8,000 characters) or at logical task boundaries.
    - **Note**: This tool only reports acceptance (Receipt) immediately; the actual saving process occurs asynchronously in the background. Therefore, saved data may not be searchable immediately after the tool returns. If taking actions dependent on saved data, allow sufficient time or wait until explicit completion is confirmed.

## Environment

**Package manager**: uv

**Git Hooks**:
- **Commit Stage**: `ruff` (Lint/Format) runs automatically. Environment-agnostic.
- **Push Stage**: `mypy` (Type Check) runs. Requires devcontainer or `uv sync` environment.

**Devcontainer required**: All testing and static analysis MUST run in devcontainer. See `.devcontainer/`.

```bash
# Reopen in devcontainer: Ctrl+Shift+P → Dev Containers: Reopen in Container
```

## Setup & Onboarding

Initial setup procedure for agents.

**Mandatory Interaction**: Before starting setup, **you MUST use the agent's interaction tool (e.g., `ask_user`)** to present the following options to the user and wait for their selection. Do not proceed with default values autonomously.

### 1. Basic Configuration
- **Storage Backend**: `sqlite` (Lightweight) or `postgres` (Full-featured)
- **Model Provider**: `openai`, `litellm`, `local`, `custom`
- **MCP Target**: `claude`, `cursor`, or `generic`
- **MCP Activation Method**: `python` (Direct) or `uvx` (via uv)

**Note**: `bootstrap.sh` internally maps `local` to `local-model` and `custom` to `custom-api` for environment variables.

### 2. Environment Variables
- **API Key Readiness**: Whether to set `OPENAI_API_KEY` now or edit `.env` manually later.
- **Graph Features**: `GRAPH_ENABLED` (Default: true)

### 3. Execution Options
- **Run Unit Tests**: Whether to run tests immediately after setup.

### 4. Persisting Agent Instructions (Recommended Global Config)
- **Global Config Update**: Add the content of `docs/agent-prompts/memory-save-system-prompt.md` to your agent's **GLOBAL configuration** (e.g., `~/.gemini/GEMINI.md`, `~/.clauderules`, or Cursor's `Rules for AI`).
- **Reason**: Appending rules to project-root files like `.cursorrules` affects the entire team. Keeping them in your global environment is better practice.
- **Note**: `.gitignore` intentionally excludes `CLAUDE.md`, `GEMINI.md`, etc., to prevent accidental commits of personal API keys or preferences. To commit project-shared settings, update `AGENTS.md` or `README.md`, or use `git add -f`.
- **Note**: Agents will not perform autonomous `memory_save` unless these instructions are added to their global prompt.

**Note for Agents**:
- If errors (e.g., test failures) occur during setup, **do not start fixing source code autonomously**. Report the error to the user and ask for instructions.
- Run `scripts/bootstrap.sh` with the confirmed options as arguments.

### Setup Example

```bash
# Basic execution
bash scripts/bootstrap.sh --backend sqlite --embedding openai --mcp-output cursor

# Using local model and skipping tests
bash scripts/bootstrap.sh --backend sqlite --embedding local --skip-tests --mcp-output claude
```

**Individual Commands**:
```bash
uv sync --all-extras    # Install dependencies
uv run pytest tests/unit/ -v  # Run tests
```

**Tasks** (Ctrl+Shift+P → Tasks: Run Task):
- `Run Tests` — pytest tests/ -v
- `Run Migration Tests` — pytest tests/unit/test_migration_runner.py tests/unit/test_sqlite_storage.py tests/integration/test_postgres_schema.py -v
- `Run Ruff Check` — ruff check src/ tests/
- `Run MyPy` — mypy src/
- `Run Full Lint` — ruff + mypy
- `Run All Checks (CI)` — lint + tests

## Internal Knowledge (For Developers)

- **Schema Management**: Database DDL is managed by the custom migration system.
  - SQL files are located in `src/context_store/storage/migrations/{sqlite,postgres}/`.
  - Do not hardcode table creation queries in Python code. Instead, add a new `.sql` file to the migration directories.
- **Logging**: All system logs are directed to `stderr` to avoid interfering with MCP stdout communication.

**Frontend (Dashboard) commands**:
```bash
cd frontend
npm install            # Install dependencies
npx tsc --noEmit       # Type check
npm run lint           # ESLint
npm run build          # Production build
npx playwright test    # E2E tests (auto-starts webServer)
```

## Dashboard

Read-Only visualization dashboard. Operates as a separate process independent of the MCP server.

- **Start**: `uv run python -m context_store.dashboard.api_server` (DB must be initialized)
- **Docker**: `docker compose up -d chronos-dashboard`
- **URL**: `http://localhost:8000`
- **Source**: Backend in `src/context_store/dashboard/`, Frontend in `frontend/`
- **Read-Only**: SQLite uses `file:...?mode=ro` URI; Neo4j connects with `READ_ACCESS` session.
- **E2E Tests**: `frontend/e2e/dashboard.spec.ts` (Playwright + axe-core a11y)
