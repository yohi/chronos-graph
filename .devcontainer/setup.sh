#!/bin/bash
set -e

cd /workspaces/chronos-graph

echo "Installing dependencies..."
uv sync --frozen --all-extras

echo "Devcontainer setup complete!"
echo ""
echo "Available tasks (Ctrl+Shift+P → Tasks: Run Task):"
echo "  - Run Tests"
echo "  - Run Ruff Check"
echo "  - Run MyPy"
echo "  - Run Full Lint"
echo "  - Start Infrastructure"
echo ""
echo "Or run manually:"
echo "  pytest tests/ -v"
echo "  ruff check src/ tests/"
echo "  mypy src/"
