#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}/.."
export UV_PROJECT_ENVIRONMENT=/home/vscode/.venv
export PATH="${UV_PROJECT_ENVIRONMENT}/bin:${PATH}"

echo "Installing dependencies..."
uv venv "${UV_PROJECT_ENVIRONMENT}"
uv sync --frozen --all-extras

# Phase 6 の scripts/check_evaluator.sh が DEVCONTAINER=1 を要求するため、
# devcontainer 経由で起動した bash で確実に export されるよう ~/.bashrc に追記する。
if ! grep -qxF 'export DEVCONTAINER=1' "${HOME}/.bashrc" 2>/dev/null; then
    echo 'export DEVCONTAINER=1' >> "${HOME}/.bashrc"
fi

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
