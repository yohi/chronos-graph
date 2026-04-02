# ChronosGraph Agent Guidelines

## Project

MCP server providing persistent long-term memory for AI agents with temporal knowledge graph.

## Environment

**Package manager**: uv

**Devcontainer required**: All testing and static analysis MUST run in devcontainer. See `.devcontainer/`.

```bash
# Reopen in devcontainer: Ctrl+Shift+P → Dev Containers: Reopen in Container
```

**Tasks** (Ctrl+Shift+P → Tasks: Run Task):
- `Run Tests` — pytest tests/ -v
- `Run Ruff Check` — ruff check src/ tests/
- `Run MyPy` — mypy src/
- `Run Full Lint` — ruff + mypy
- `Run All Checks (CI)` — lint + tests

## Commands

```bash
uv sync --all-extras    # Install dependencies
pytest tests/ -v        # Run tests
ruff check src/ tests/  # Lint
ruff format src/ tests/  # Format
mypy src/               # Type check
```
