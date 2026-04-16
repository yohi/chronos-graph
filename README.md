# ChronosGraph 🚀

**MCP-based Long-Term Memory System for AI Agents**

---

[![CI](https://github.com/yohi/chronos-graph/actions/workflows/ci.yml/badge.svg)](https://github.com/yohi/chronos-graph/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

ChronosGraph は、AIエージェント（Claude Code / Gemini CLI / Cursor 等）にセッションを跨いだ**永続的な長期記憶**を提供する Model Context Protocol (MCP) サーバーです。

## 核心的なアプローチ

1. **多層記憶グラフ (MAGMA):** 情報を単なるベクトルとして保存するのではなく、時間軸を伴うグラフ構造として保持。Episodic（経験）・Semantic（知識）・Procedural（手順）の変遷を正確に追跡します。
2. **動的忘却アルゴリズム:** 指数関数的な減衰モデルと重要度評価により、記憶の肥大化を防ぎつつ、重要な教訓を「意味記憶」として抽出します。
3. **RL 拡張ポイント:** 将来の強化学習（PPO 等）統合に向けたインターフェースを設計。ユーザーとの対話を通じたエージェントの行動論理の継続的アップデートを可能にします。

---

## 特徴

- **ハイブリッド検索** — ベクトル検索 + キーワード検索 + グラフトラバーサルを RRF で融合
- **多層記憶モデル** — Episodic / Semantic / Procedural の自動分類
- **時間的減衰** — 指数関数的減衰スコアで古い記憶を自動アーカイブ
- **重複排除** — Append-only 置換 + SUPERSEDES グラフエッジで変遷を追跡
- **ライトウェイトモード** — SQLite + sqlite-vec でゼロ設定で起動
- **スケーラブル** — PostgreSQL + Neo4j + Redis への切り替え対応
- **RL 拡張ポイント** — ActionLogger / RewardSignal / PolicyHook インターフェース
- **Dashboard Web UI** — Cytoscape.js グラフ可視化・リアルタイムログストリーミング・severity フィルター（React + FastAPI）
## Setup

### For Humans (推奨)

> [!TIP]
> **人間は設定を打ち間違えることがあります。** このプロジェクトのインストールと設定は、AIエージェント（Claude Code / Gemini CLI / Cursor 等）に丸投げすることを強く推奨します。

### Quick Start (uvx を使用する場合)

リポジトリをクローンせずに、`uvx` を使用して MCP サーバーとして即座に実行することも可能です。Claude Desktop 等の設定に以下のようなエントリを追加してください：

```json
{
  "mcpServers": {
    "chronos-graph": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/yohi/chronos-graph.git",
        "context-store"
      ],
      "env": {
        "OPENAI_API_KEY": "YOUR_API_KEY_HERE"
      }
    }
  }
}
```

リポジトリをクローンしている場合は `scripts/generate_config.py` を実行して設定を自動生成できます（例: `python scripts/generate_config.py --method uvx --output claude`）。クローンしない場合は生成される JSON を MCP クライアント設定に手動で追加してください。

---

### リポジトリを直接クローンする場合

以下のプロンプトをコピーしてエージェントに渡してください：

```text
Install and configure ChronosGraph by following the instructions here:
https://raw.githubusercontent.com/yohi/chronos-graph/refs/heads/master/README.md
```

<details>
<summary><b>For Agents (AIエージェント向け手順)</b></summary>

あなたがターミナル操作可能なAIエージェントであるなら、以下の手順でインストールとセットアップを自律的に遂行してください：

1.  **[ ] 依存関係の解決:**
    *   `uv` (推奨) または `pip` を使用して、開発用依存関係をインストールしてください。
    *   `uv sync --all-extras` または `pip install -e ".[all]"`
2.  **[ ] 環境設定:**
    *   `.env.example` を `.env` にコピーし、必要な環境変数を設定してください。
    *   `EMBEDDING_PROVIDER` は `openai` がデフォルトですが、必要に応じて `local-model` などに切り替えてください。
3.  **[ ] 動作確認:**
    *   ユニットテストを実行して、環境が正しく構築されているか確認してください。
    *   `uv run pytest tests/unit/ -v`
4.  **[ ] MCP設定の生成:**
    *   `uv run python scripts/generate_config.py > mcp_config.json` を実行し、MCPクライアント用の設定ファイルを生成してください。

上記の全手順を、ユーザーと対話しながら一括で行うには `bash scripts/bootstrap.sh` を実行してください。

フラグを使用して非対話的に実行することも可能です：
```bash
bash scripts/bootstrap.sh --backend sqlite --embedding openai --graph true --mcp-output cursor
```
各フラグの詳細は [AGENTS.md](AGENTS.md) を参照してください。
</details>

---

## Docker Compose（フルモード）

PostgreSQL + Neo4j + Redis を使用する場合：

```bash
docker compose up -d
```

`.env` でバックエンドを切り替える：

```bash
STORAGE_BACKEND=postgres
GRAPH_ENABLED=true
CACHE_BACKEND=redis

POSTGRES_HOST=localhost
POSTGRES_PASSWORD=dev_password
NEO4J_PASSWORD=dev_password
REDIS_URL=redis://localhost:6379
```

### Dashboard Web UI の起動

記憶グラフを可視化するダッシュボードは独立したサービスとして提供されています：

```bash
# Docker Compose で起動（http://localhost:8000 でアクセス可能）
docker compose up -d chronos-dashboard

# または直接起動
uv run python -m context_store.dashboard.api_server
```

> **注意**: Dashboard は Read-Only モードで動作します。MCP サーバーを最低一度起動して DB を初期化してから起動してください。

---

## 設定リファレンス

| 環境変数 | デフォルト | 説明 |
|---|---|---|
| `STORAGE_BACKEND` | `sqlite` | ストレージバックエンド (`sqlite` / `postgres`) |
| `SQLITE_DB_PATH` | `~/.context-store/memories.db` | SQLite DB ファイルパス |
| `EMBEDDING_PROVIDER` | `openai` | 埋め込みプロバイダー (`openai` / `local-model` / `litellm` / `custom-api`) |
| `OPENAI_API_KEY` | `` | OpenAI API キー |
| `LOCAL_MODEL_NAME` | `cl-nagoya/ruri-v3-310m` | ローカルモデル名（詳細は [埋め込みモデル選定ガイド](docs/embedding-models.md) を参照） |
| `GRAPH_ENABLED` | `false` | グラフ機能の有効化 |
| `DECAY_HALF_LIFE_DAYS` | `30` | 記憶の半減期（日数） |
| `ARCHIVE_THRESHOLD` | `0.05` | アーカイブ閾値 |
| `SIMILARITY_THRESHOLD` | `0.70` | 類似度検索の閾値 |
| `DEDUP_THRESHOLD` | `0.90` | 重複排除の閾値 |
| `DEFAULT_TOP_K` | `10` | デフォルト検索件数 |
| `GRAPH_MAX_LOGICAL_DEPTH` | `5` | グラフ検索の最大論理深さ |
| `URL_FETCH_CONCURRENCY` | `3` | URL フェッチの同時実行数 |
| `ALLOW_PRIVATE_URLS` | `false` | プライベート URL の許可 (SSRF 対策) |
| `DASHBOARD_HOST` | `0.0.0.0` | Dashboard サーバーのバインドアドレス |
| `DASHBOARD_PORT` | `8000` | Dashboard サーバーのポート番号 |

`.env.example` に全設定の一覧があります。

---

## MCP ツール一覧

| ツール | 説明 |
|---|---|
| `session_flush` | 会話ログをバックグラウンドでバッチ保存。即座に `status: "accepted"` と `estimated_chunks`（概算チャンク数）を含むレスポンスを返す |
| `memory_save` | テキストを記憶として保存 |
| `memory_save_url` | URL からコンテンツを取得して保存 |
| `memory_search` | ハイブリッド検索（ベクトル + キーワード + グラフ） |
| `memory_search_graph` | グラフトラバーサル検索 |
| `memory_delete` | 記憶を削除 |
| `memory_prune` | 古い記憶をクリーンアップ |
| `memory_stats` | ストレージの統計情報を取得 |

### リソース

| リソース URI | 説明 |
|---|---|
| `memory://stats` | ストレージ統計情報 |
| `memory://projects` | プロジェクト一覧 |

---

## アーキテクチャ

```text
MCP Client (Claude / Cursor / etc.)
        │  MCP Protocol (stdio / SSE)
        ▼
  ChronosGraph MCP Server (FastMCP)
        │
  Orchestrator
  ├── Ingestion Pipeline
  │     Adapter → Chunker → Classifier → Embedding → Deduplicator → GraphLinker
  ├── Batch Processor (Batch Ingestion)
  │     TaskRegistry → Ingestion Pipeline 委譲
  ├── Retrieval Pipeline
  │     QueryAnalyzer → [VectorSearch + KeywordSearch + GraphTraversal] → ResultFusion → PostProcessor
  └── Lifecycle Manager
        DecayScorer → Archiver → Consolidator → Purger

Storage Layer (Protocol-based)
  ├── SQLiteStorageAdapter (sqlite-vec + FTS5)
  ├── SQLiteGraphAdapter (recursive CTE)
  ├── PostgresStorageAdapter (pgvector + pg_bigm)
  ├── Neo4jGraphAdapter
  ├── InMemoryCacheAdapter
  └── RedisCacheAdapter

Dashboard (独立プロセス・Read-Only CQRS)
  ├── FastAPI (api_server.py)  ← StorageAdapter / GraphAdapter を直接利用
  └── React + Vite (frontend/)
        ├── NetworkView  (Cytoscape.js グラフ可視化)
        ├── LogExplorer  (WebSocket リアルタイムログ)
        └── Dashboard    (統計カード)
```

---

## 開発 (Development)

開発環境のセットアップやワークフローの詳細は [AGENTS.md](AGENTS.md) を参照してください。

```bash
# テスト実行
uv run pytest tests/unit/ -v

# E2E 統合テスト（外部サービス不要）
uv run pytest tests/integration/test_e2e.py -v

# リント
ruff check src/ tests/
ruff format --check src/ tests/

# 型チェック
mypy src/
```

**フロントエンド（Dashboard）:**

```bash
cd frontend

# 依存関係のインストール
npm install

# 型チェック
npx tsc --noEmit

# リント
npm run lint

# プロダクションビルド
npm run build

# Playwright E2E テスト（サーバー自動起動）
npx playwright test
```

### Git フックの運用

本プロジェクトでは、コード品質を保つために `pre-commit` を活用しています。

- **コミット時 (`pre-commit`)**: `ruff` (Lint/Format) が自動実行されます。ホスト側でのコミットも可能です。
- **プッシュ時 (`pre-push`)**: `mypy` (型チェック) が実行されます。依存ライブラリが必要なため、`devcontainer` 内または `uv sync` 済みの環境での実行を推奨します。

---

## ライセンス

MIT License — [LICENSE](LICENSE)
