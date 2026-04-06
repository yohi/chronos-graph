# ChronosGraph Agent Guidelines

## Project

MCP server providing persistent long-term memory for AI agents with temporal knowledge graph.

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

エージェントが最初に行うべきセットアップ手順です：

```bash
# 1. ブートストラップの実行（推奨）
# 依存関係の解決、.env作成、テスト、MCP設定生成を一括で行います
bash scripts/bootstrap.sh

# 2. 個別のコマンド
uv sync --all-extras    # 依存関係のインストール
uv run pytest tests/unit/ -v  # テスト実行
```

**Tasks** (Ctrl+Shift+P → Tasks: Run Task):
- `Run Tests` — pytest tests/ -v
- `Run Ruff Check` — ruff check src/ tests/
- `Run MyPy` — mypy src/
- `Run Full Lint` — ruff + mypy
- `Run All Checks (CI)` — lint + tests
