#!/bin/bash
set -e

cd /workspaces/chronos-graph

echo "Installing dependencies..."
# Only install base dependencies and dev group to keep startup fast.
# Heavy extras like 'embedding-local' (PyTorch/NVIDIA) can be installed manually if needed.
uv sync --frozen

echo "Devcontainer setup complete!"
echo ""
echo "Note: Heavy dependencies (PyTorch/NVIDIA) are NOT installed by default."
echo "To use local embeddings, run: uv sync --extra embedding-local"
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
