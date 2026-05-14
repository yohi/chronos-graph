#!/bin/bash
set -e

cd /workspaces/chronos-graph

# Node.js (Prisma CLI 用) - GPG 署名検証を含むセキュアなインストール
if ! command -v node >/dev/null 2>&1; then
  NODE_MAJOR=20
  sudo apt-get update && sudo apt-get install -y ca-certificates curl gnupg
  sudo mkdir -p /etc/apt/keyrings
  curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
    | sudo gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg
  echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_${NODE_MAJOR}.x nodistro main" \
    | sudo tee /etc/apt/sources.list.d/nodesource.list
  sudo apt-get update && sudo apt-get install -y nodejs
fi

echo "Installing dependencies..."
uv sync --frozen --all-extras

# Prisma Client Python の生成 (schema.prisma → ./prisma/ パッケージ生成)
if [ -f ./prisma/schema.prisma ]; then
  uv run prisma generate --schema=./prisma/schema.prisma
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
