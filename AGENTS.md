# ChronosGraph Agent Guidelines

## 🎯 What & Why
ChronosGraph is a Model Context Protocol (MCP) server providing persistent long-term memory for AI agents. It uses a temporal knowledge graph to track state changes and provides multi-layered memory ([📜 Episodic], [🧠 Semantic], [🕒 Procedural]).

## 🛠️ Tech Stack & Environment
- **Backend:** Python 3.12+, FastAPI, FastMCP, `uv` for dependency management.
- **Storage:** PostgreSQL (pgvector) or SQLite (sqlite-vec), Neo4j (Graph), Redis (Cache).
- **Frontend:** React 18, Vite, Tailwind CSS, Zustand, Cytoscape.js.
- **Constraint:** すべてのテストと静的解析は提供された Devcontainer 内で実行することを推奨します。ただし、ローカル環境のツールチェーン（`uv`, `ruff`, `mypy`, Python のバージョン等）が Devcontainer と同等に設定されていることが保証される場合は、ローカルでの実行も許可されます。

## 🚀 How (Commands & Workflow)
- **Mandatory Interaction:** セットアップ中にエラー（テスト失敗など）が発生した場合、ソースコードを自律的に修正し始めてはいけません。エラーをユーザーに報告し、指示を仰ぐこと.
- **Install & Sync:** `uv sync --all-extras`
- **Tests:** `uv run pytest tests/unit/ -v`
- **Linting:** `uv run ruff check src/ tests/`
- **Formatting:** `uv run ruff format src/ tests/`
- **Type Check:** `uv run mypy src/`
- **Database Migrations (DDL):**
  - **用語定義:** DDL（Data Definition Language: データ定義言語）とは、`CREATE` / `ALTER` / `DROP` 等のテーブル構造を定義・変更する命令です。
  - **実践指示:** DDL をコード内に直書きせず、マイグレーション用の `.sql` ファイルを所定の `src/context_store/storage/migrations/{sqlite,postgres}/` フォルダに追加してください。
- **Frontend Workflow:**
  1. ディレクトリ移動: `cd frontend`
  2. 依存関係のインストール: `npm install`
  3. ビルド: `npm run build`
  4. E2Eテストの実行: `npx playwright test` （※事前にアプリを起動しておくこと。必要な環境変数やポート設定を確認してください。）

## 🧠 Memory Strategy (Crucial for Agents)
When developing or using this server, apply these tools selectively:
- **`memory_save`**: Use autonomously to persist high-value insights (Semantic/Procedural) without asking the user.
- **`session_flush`**: Use for episodic batch saving at task boundaries or when context reaches ~8,000 chars. **注意:** このツールは即座に受領 (Receipt) を報告するだけで、実際の保存処理はバックグラウンドで非同期に行われます。そのため、ツールが返った直後にデータが検索可能になるとは限りません。
- **Tags**: Prefix memory content with `[📜 Episodic]`, `[🧠 Semantic]`, or `[🕒 Procedural]` unless a strict schema is required.
- **System Prompt**: Incorporate the contents of `docs/agent-prompts/memory-save-system-prompt.md` into your global config.
  - **Gemini CLI:**
    1. 設定追加: `~/.gemini/GEMINI.md` に `system_prompt` ブロックとして内容を追加します。
    2. 動作確認: エージェントを実行し、ログで `memory_save=true` となっていることを確認します。
  - **Claude Code:**
    1. 設定追加: `~/.clauderules` に `system_prompt` エントリとして内容を追加します。
    2. 動作確認: サンプルの `memory_save` テストコマンドを実行して検証します。
  - **Other Tools:** 各 CLI/エージェントの設定に合わせて、同様のステップで設定と検証を行ってください。

## 📁 Architecture & Specs
設計の詳細やデータモデル、パイプラインのロジックについては、ソフトウェア仕様書（Software/Service SPECification, **SPEC.md**）を参照することを強く推奨します。設計上の意思決定における信頼できる唯一の情報源（Single Source of Truth）として仕様書を活用してください。
