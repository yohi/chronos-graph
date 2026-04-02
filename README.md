# ChronosGraph 🚀

**MCP-based Long-Term Memory System for AI Agents**

[![CI](https://github.com/yohi/chronos-graph/actions/workflows/ci.yml/badge.svg)](https://github.com/yohi/chronos-graph/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

ChronosGraph は、AIエージェント（Claude Code / Gemini CLI / Cursor 等）にセッションを跨いだ**永続的な長期記憶**を提供する Model Context Protocol (MCP) サーバーです。

---

## 特徴

- **ハイブリッド検索** — ベクトル検索 + キーワード検索 + グラフトラバーサルを RRF で融合
- **多層記憶モデル** — Episodic / Semantic / Procedural の自動分類
- **時間的減衰** — 指数関数的減衰スコアで古い記憶を自動アーカイブ
- **重複排除** — Append-only 置換 + SUPERSEDES グラフエッジで変遷を追跡
- **ライトウェイトモード** — SQLite + sqlite-vec でゼロ設定で起動
- **スケーラブル** — PostgreSQL + Neo4j + Redis への切り替え対応
- **RL 拡張ポイント** — ActionLogger / RewardSignal / PolicyHook インターフェース

---

## クイックスタート

### 1. インストール

```bash
# uv を推奨
uv pip install -e ".[dev]"

# または pip
pip install -e ".[dev]"
```

### 2. 設定

```bash
cp .env.example .env
# .env を編集して OPENAI_API_KEY 等を設定
```

SQLite ライトウェイトモード（外部サービス不要）で起動する場合、`.env` は最小限で動作します：

```bash
EMBEDDING_PROVIDER=openai
OPENAI_API_KEY=sk-...
```

### 3. MCP サーバー起動

```bash
# stdio モード（MCPクライアントから利用）
python -m context_store

# または インストール後
context-store
```

### 4. MCP クライアント設定

```bash
# Claude Desktop / Cursor 用の設定ファイルを生成
python scripts/generate_config.py > mcp_config.json
```

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

---

## 設定リファレンス

| 環境変数 | デフォルト | 説明 |
|---|---|---|
| `STORAGE_BACKEND` | `sqlite` | ストレージバックエンド (`sqlite` / `postgres`) |
| `SQLITE_DB_PATH` | `~/.context-store/memories.db` | SQLite DB ファイルパス |
| `EMBEDDING_PROVIDER` | `openai` | 埋め込みプロバイダー (`openai` / `local-model` / `litellm` / `custom-api`) |
| `OPENAI_API_KEY` | `` | OpenAI API キー |
| `LOCAL_MODEL_NAME` | `cl-nagoya/ruri-v3-310m` | ローカルモデル名 |
| `GRAPH_ENABLED` | `false` | グラフ機能の有効化 |
| `DECAY_HALF_LIFE_DAYS` | `30` | 記憶の半減期（日数） |
| `ARCHIVE_THRESHOLD` | `0.05` | アーカイブ閾値 |
| `SIMILARITY_THRESHOLD` | `0.70` | 類似度検索の閾値 |
| `DEDUP_THRESHOLD` | `0.90` | 重複排除の閾値 |
| `DEFAULT_TOP_K` | `10` | デフォルト検索件数 |
| `GRAPH_MAX_LOGICAL_DEPTH` | `5` | グラフ検索の最大論理深さ |
| `URL_FETCH_CONCURRENCY` | `3` | URL フェッチの同時実行数 |
| `ALLOW_PRIVATE_URLS` | `false` | プライベート URL の許可 (SSRF 対策) |

`.env.example` に全設定の一覧があります。

---

## MCP ツール一覧

| ツール | 説明 |
|---|---|
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

```
MCP Client (Claude / Cursor / etc.)
        │  MCP Protocol (stdio / SSE)
        ▼
  ChronosGraph MCP Server (FastMCP)
        │
  Orchestrator
  ├── Ingestion Pipeline
  │     Adapter → Chunker → Classifier → Embedding → Deduplicator → GraphLinker
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
```

---

## 開発

```bash
# テスト実行
python -m pytest tests/unit/ -v

# E2E 統合テスト（外部サービス不要）
python -m pytest tests/integration/test_e2e.py -v

# リント
ruff check src/ tests/
ruff format --check src/ tests/

# 型チェック
mypy src/
```

---

## ライセンス

MIT License — [LICENSE](LICENSE)