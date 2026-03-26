# ChronosGraph (Context Store MCP v2.0) 🚀
**Temporal Knowledge Graph & RL-based Long-Term Memory for AI Agents**

`ChronosGraph` は、AIエージェント（Claude Code / Gemini CLI / Cursor等）にセッションを跨いだ永続的な長期記憶を提供する、Model Context Protocol (MCP) サーバーの最新実装です。

「情報の断片化（ステートレス性）」を解決し、文脈を捉えた記憶保持と、時間経過に応じた自己進化を実現します。

## 🌟 主な特徴

- **多層記憶モデル:** Episodic（経験）・Semantic（知識）・Procedural（手順）の自動分類。
- **ハイブリッド検索:** ベクトル検索 (pgvector) + キーワード検索 (FTS) + グラフ推論 (Neo4j) を RRF (Reciprocal Rank Fusion) で統合。
- **自動クリーンアップ:** 指数関数的な時間減衰、重複排除、および自動アーカイブによる記憶ライフサイクル管理。
- **プロバイダー抽象化:** OpenAI / ローカルモデル (sentence-transformers) / LiteLLM / カスタム API を柔軟に切り替え可能。
- **RL 拡張ポイント:** 将来の強化学習（自己最適化ループ）統合を見据えたインターフェース設計。

## 🏗️ アーキテクチャ

処理を 3 つの独立したパイプラインに分離し、`Orchestrator` が統合・調整を行う「パイプライン指向アーキテクチャ」を採用しています。

```text
┌─────────────────────────────────────────────────────────┐
│                    MCP Server (FastMCP)                  │
│  ┌──────────────────────────────────────────────────┐   │
│  │                   Orchestrator                    │   │
│  │                                                    │   │
│  │  ┌──────────────┐ ┌──────────────┐ ┌───────────┐ │   │
│  │  │  Ingestion   │ │  Retrieval   │ │ Lifecycle │ │   │
│  │  │  Pipeline    │ │  Pipeline    │ │ Manager   │ │   │
│  │  └──────┬───────┘ └──────┬───────┘ └─────┬─────┘ │   │
│  │         │                │               │        │   │
│  │  ┌──────┴────────────────┴───────────────┴─────┐  │   │
│  │  │            Storage Layer (抽象)              │  │   │
│  │  └──────┬──────────────┬──────────────┬────────┘  │   │
│  └─────────┼──────────────┼──────────────┼───────────┘   │
│            │              │              │               │
│     ┌──────┴──────┐ ┌────┴────┐   ┌─────┴─────┐        │
│     │ PostgreSQL  │ │  Neo4j  │   │   Redis   │        │
│     │ + pgvector  │ │         │   │           │        │
│     └─────────────┘ └─────────┘   └───────────┘        │
└─────────────────────────────────────────────────────────┘
```

## 🛠️ 技術スタック

| カテゴリ | 技術 |
|---|---|
| 言語 | Python 3.12+ |
| MCP フレームワーク | FastMCP |
| ストレージ | PostgreSQL 16 (pgvector, pg_bigm), Neo4j 5.x, Redis 7.x |
| 埋め込み | sentence-transformers (local) / OpenAI |
| スケジューラ | APScheduler |
| 設定管理 | pydantic-settings |

## 🚀 クイックスタート

### 1. 依存関係の起動 (Docker)

```bash
docker compose up -d
```

### 2. 環境設定

`.env.example` を `.env` にコピーし、API キー等を設定します。

```bash
cp .env.example .env
```

### 3. インストール

```bash
pip install -e ".[dev]"
```

### 4. 実行

```bash
python -m context_store
```

## 🧰 利用可能な MCP ツール

| ツール | 用途 |
|---|---|
| `memory_save` | 記憶の保存（種類は自動分類） |
| `memory_save_url` | URL からコンテンツを取り込んで記憶化 |
| `memory_search` | ハイブリッド検索（ベクトル + キーワード + グラフ） |
| `memory_search_graph` | グラフトラバーサル特化（因果関係・依存関係の探索） |
| `memory_delete` | 記憶の削除 |
| `memory_prune` | 古い/低スコアの記憶のクリーンアップ |
| `memory_stats` | 統計情報 |

## 📄 ライセンス

MIT License
