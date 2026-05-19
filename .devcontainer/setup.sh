#!/bin/bash
set -e

cd /workspaces/chronos-graph
export UV_PROJECT_ENVIRONMENT=/home/vscode/.venv
export PATH="${UV_PROJECT_ENVIRONMENT}/bin:${PATH}"

# Node.js is installed in .devcontainer/Dockerfile so this setup script can run
# without sudo in the non-root devcontainer user.
node --version

echo "Installing dependencies..."
uv venv "${UV_PROJECT_ENVIRONMENT}"
uv pip install --python "${UV_PROJECT_ENVIRONMENT}/bin/python" \
  -e ".[all]" \
  asgi-lifespan \
  mypy \
  pre-commit \
  pytest \
  pytest-asyncio \
  pytest-benchmark \
  pytest-cov \
  ruff

# Prisma Client Python の生成 (schema.prisma → ./prisma/ パッケージ生成)
if [ -f ./prisma/schema.prisma ]; then
  prisma generate --schema=./prisma/schema.prisma
fi

echo "Devcontainer setup complete!"
echo ""
echo "Available tasks (Ctrl+Shift+P → Tasks: Run Task):"
echo "  - Run Tests"
echo "  - Run Ruff Check"
echo "  - Run MyPy"
echo "  - Run Full Lint"
echo "  - Start Infrastructure"
echo "  - Prisma Generate"
echo ""
echo "Or run manually:"
echo "  pytest tests/ -v"
echo "  ruff check src/ tests/"
echo "  mypy src/"
echo "  prisma generate --schema=./prisma/schema.prisma"
