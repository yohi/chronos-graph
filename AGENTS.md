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

エージェントが最初に行うべきセットアップ手順です。

**重要（対話の義務化）**: セットアップを開始する前に、**各AIエージェントが提供する対話ツール（例: `ask_user`）を必ず使用して**、以下のオプションをユーザーに提示し、選択を待ってください。独断でデフォルト値を使用して進めてはいけません。

### 1. 基本構成の確認
- **ストレージバックエンド**: `sqlite` (軽量) または `postgres` (フル機能)
- **モデルプロバイダー**: `openai`, `litellm`, `local`, `custom`
- **MCP設定のターゲット**: `claude`, `cursor`, または `generic`
- **MCP起動方法**: `python` (直接実行) または `uvx` (パッケージ管理ツール経由)

**注記**: `bootstrap.sh` は内部的に `local` を `local-model` に、`custom` を `custom-api` にマッピングして環境変数を設定します。

### 2. 環境変数の確認
- **APIキーの準備**: `OPENAI_API_KEY` などのキーを今すぐ設定するか、後で `.env` を手動編集するか。
- **グラフ機能の有効化**: `GRAPH_ENABLED` (デフォルト: true)

### 3. 実行オプション
- **ユニットテストの実行**: セットアップ後にテストを実行するかどうか。

**注記（エージェント向け）**:
- セットアップ実行中にエラー（テスト失敗など）が発生した場合は、**独断でソースコードの修正を開始せず**、まずはエラー内容をユーザーに報告して指示を仰いでください。
- 確認したオプションを引数として `scripts/bootstrap.sh` を実行します。

### セットアップ実行例

```bash
# 基本的な実行
bash scripts/bootstrap.sh --backend sqlite --embedding openai --mcp-output cursor

# ローカルモデルを使用し、テストをスキップする場合
bash scripts/bootstrap.sh --backend sqlite --embedding local --skip-tests --mcp-output claude
```

**個別のコマンド**:
```bash
uv sync --all-extras    # 依存関係のインストール
uv run pytest tests/unit/ -v  # テスト実行
```

**Tasks** (Ctrl+Shift+P → Tasks: Run Task):
- `Run Tests` — pytest tests/ -v
- `Run Ruff Check` — ruff check src/ tests/
- `Run MyPy` — mypy src/
- `Run Full Lint` — ruff + mypy
- `Run All Checks (CI)` — lint + tests
