# ChronosGraph Agent Guidelines

## Project

MCP server providing persistent long-term memory for AI agents with temporal knowledge graph.

## Memory Strategy (Important for Agents)

エージェントとして、あなたは以下の2つのツールを使い分けて記憶を保存する必要があります：

1.  **`memory_save` (自律的保存 / Semantic・Procedural)**:
    - ユーザーの好み、重要な知識、解決したエラーの手順など、将来的に再利用価値が高い情報を保存します。
    - 保存するテキストは背景情報なしでも理解できるように要約してください。
    - あなたの判断でサイレントに実行し、ユーザーに確認する必要はありません。

2.  **`session_flush` (バッチ保存 / Episodic)**:
    - 会話の文脈全体を保存します。
    - 会話が長くなった場合（目安：8,000文字程度）や、作業の区切り、プロセスの終了前に呼び出してください。
    - 背景で非同期に処理されるため、大きな会話ログも即座に保存依頼できます。

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

**Frontend (Dashboard) commands**:
```bash
cd frontend
npm install            # 依存関係インストール
npx tsc --noEmit       # 型チェック
npm run lint           # ESLint
npm run build          # プロダクションビルド
npx playwright test    # E2E テスト（webServer 自動起動）
```

## Dashboard

Read-Only 可視化ダッシュボード。MCP サーバーとは独立した別プロセスで動作する。

- **起動**: `uv run python -m context_store.dashboard.api_server`（DB 初期化済みであること）
- **Docker**: `docker compose up -d chronos-dashboard`
- **URL**: `http://localhost:8000`
- **ソース**: バックエンド `src/context_store/dashboard/`、フロントエンド `frontend/`
- **Read-Only**: SQLite は `file:...?mode=ro` URI、Neo4j は `READ_ACCESS` セッションで接続
- **E2E テスト**: `frontend/e2e/dashboard.spec.ts`（Playwright + axe-core a11y）
