# ChronosGraph 🚀

**MCP-based Long-Term Memory System for AI Agents**

---

[![CI](https://github.com/yohi/chronos-graph/actions/workflows/ci.yml/badge.svg)](https://github.com/yohi/chronos-graph/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

ChronosGraph は、AIエージェント（Claude Code / Gemini CLI / Cursor 等）にセッションを跨いだ**永続的な長期記憶**を提供する Model Context Protocol (MCP) サーバーです。

## 核心的なアプローチ

1. **多層記憶グラフ (MAGMA):** 情報を単なるベクトルとして保存するのではなく、時間軸を伴うグラフ構造として保持。[📜 Episodic]（経験）・[🧠 Semantic]（知識）・[🕒 Procedural]（手順）の変遷を正確に追跡します。
2. **動的忘却アルゴリズム:** 指数関数的な減衰モデルと重要度評価により、記憶の肥大化を防ぎつつ、重要な教訓を「意味記憶」として抽出します。
3. **RL 拡張ポイント:** 将来の強化学習（PPO 等）統合に向けたインターフェースを設計。ユーザーとの対話を通じたエージェントの行動論理の継続的アップデートを可能にします。

---

## 特徴

- **ハイブリッド検索** — ベクトル検索 + キーワード検索 + グラフトラバーサルを RRF で融合
- **自動マイグレーション** — SQLite / PostgreSQL 両対応の SQL ベース軽量マイグレーション
- **多層記憶モデル** — [📜 Episodic] / [🧠 Semantic] / [🕒 Procedural] の自動分類
- **時間的減衰** — 指数関数的減衰スコアで古い記憶を自動アーカイブ
- **重複排除** — Append-only 置換 + SUPERSEDES グラフエッジで変遷を追跡
- **ライトウェイトモード** — SQLite + sqlite-vec でゼロ設定で起動
- **スケーラブル** — PostgreSQL + Neo4j + Redis への切り替え対応、Supabase Data API による HTTPS 経由のアクセス（社内 DPI 回避等 ※詳細は [SPEC.md](SPEC.md) を参照）
- **RL 拡張ポイント** — ActionLogger / RewardSignal / PolicyHook インターフェース
- **Dashboard Web UI** — Cytoscape.js グラフ可視化・リアルタイムログストリーミング・severity フィルター（React + FastAPI）
- **MCP Gateway** — ゼロ・スタンディング・権限 (ZSP) と意図に基づくアクセス制御 (IBAC) を提供する専用ゲートウェイを搭載

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
        "context-store-mcp[all] @ git+https://github.com/yohi/chronos-graph.git",
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

> [!CAUTION]
> **重要 (CRITICAL):** あなたが自律モードで動作しているAIエージェントであっても、**手順1（モード選択の確認）を決してスキップしないでください。** ユーザーの環境や意図に反する構成（例：Docker不要な環境でのフルモード構築）を避けるため、必ず最初に問いかけを行ってください。
>
> **エージェントへの行動規範:** セットアップやテストの実行中に失敗が発生した場合、**安易に既存のコアソースコード（`src/` 配下）を編集して解決を図らないでください。** ほとんどの失敗は環境変数（`.env`）、ネットワーク接続、または外部サービスの権限設定に起因します。まずは設定の整合性を徹底的に疑い、コードの修正が必要と判断した場合は、必ずユーザーにその理由と影響を説明し、許可を得てください。

あなたがターミナル操作可能なAIエージェントであるなら、以下の手順でインストールとセットアップを自律的に遂行してください：

1.  **[ ] 構成・実行方法の確認 (Interactive Ask):**
    **このステップは必須です。** インストールを開始する前に、ユーザーに以下の構成を選択してもらってください：
    - **A) モードの選択**:
        - **(A) ライトウェイトモード (推奨)**: SQLite + sqlite-vec。
        - **(B) フルモード (Docker利用)**: PostgreSQL + Neo4j + Redis (Docker Compose)。
        - **(C) フルモード (クラウド利用)**: Supabase + Neo4j Aura 等。
    - **B) 実行方法の選択**:
        - **uv (推奨)**: `uv run` を使用して依存関係を管理。
        - **python**: システムまたは仮想環境の `python` を直接使用。
    - **C) ソースコードの取得元**:
        - **ローカル**: 現在のディレクトリのソースを使用。
        - **リモート (git+https)**: GitHub から最新のソースを直接取得して実行。
    2.  **[ ] 依存関係の解決:**
    *   `uv` (推奨) または `pip` を使用して、開発用依存関係をインストールしてください。
    *   `uv sync --all-extras` または `pip install -e ".[all]"`
    3.  **[ ] 環境設定:**
    *   `.env` は **Pydantic が CWD から読み込む**ため、MCP プロセスが起動されるディレクトリに配置する必要があります。
        - **ローカル (uv run)**: chronos-graph リポジトリルートに `.env.example` をコピーして `.env` として配置。
        - **リモート (uvx)**: MCPクライアント（例: `claude_desktop_config.json` や `opencode.json`）と同じディレクトリに `.env` を配置。
        - **bootstrap.sh 使用時**: カレントディレクトリに `.env` が生成されるため、MCPクライアント設定のディレクトリで実行するか、手動で移動してください。
    *   `bootstrap.sh` を使用すると、基本設定を自動化できます：
        - **ライトウェイト (A)**: `bash scripts/bootstrap.sh --backend sqlite`
        - **フルモード (B)**: `bash scripts/bootstrap.sh --backend postgres`
        - **フルモード (C)**: `bash scripts/bootstrap.sh --backend postgres --ssl`

    *   **重要**: クラウド利用（Supabase + Neo4j Aura + Upstash）の場合、`.env` の接続情報を適宜編集してください。特に以下を設定しないと接続エラーになります：
        - **Supabase (PostgreSQL)**: `POSTGRES_SSL_NO_VERIFY=true` と `POSTGRES_STATEMENT_CACHE_SIZE=0`（pgBouncer transaction mode 対応）
        - **Upstash (Redis)**: `REDIS_SSL=true`
4.  **[ ] 動作確認:**
    *   DB/Redis/Neo4j を使用する構成の場合、各サービスへの疎通（Connectivity）が取れるか確認してください。
    *   ユニットテストを実行して、環境が正しく構築されているか確認してください。
    *   `uv run pytest tests/unit/ -v`
5.  **[ ] MCP設定の生成:**
    *   プロジェクトルートで `uv run python scripts/generate_config.py` を実行し、出力結果を **MCPクライアントの設定ファイルと同じディレクトリ**に `mcp_config.json` として保存してください。
    *   生成された `mcp_config.json` の `mcpServers` ブロックの内容を、ユーザーが使用しているAIエージェントのMCP設定に追加してください（設定方法は各AIエージェントのルールに従うこと）。エージェントごとに設定ファイルの場所は異なります（例: Claude Desktop の `claude_desktop_config.json`、OpenCode の `opencode.jsonc`、Cursor の `~/.cursor/mcp.json` 等）。
    *   **重要**: `mcp_config.json` はプロジェクトルートのリファレンス用です。各エージェントのMCP設定には直接読み込まれませんので、必ず各エージェントの設定に追加するようユーザーに説明してください。
6.  **[ ] エージェントへの指示の追加 (Personal/Global):**
    *   あなたがこの手順を実行しているAIエージェントそのものである場合、`docs/agent-prompts/memory-save-system-prompt.md` の内容をあなた自身の**グローバル設定**に追加してください。
    *   **注意**: プロジェクト内のファイルとして作成するのではなく、あなたの設定ファイル・ルールディレクトリに直接追加する必要があります（例: Gemini CLI は `~/.gemini/GEMINI.md`、Claude Code は `~/.clauderules/`、OpenCode は `AGENTS.md`、Cursor は `Rules for AI`）。設定方法は各エージェントのルールに従うこと。

上記の全手順（手順1を除く）を自律的に行うには、`bash scripts/bootstrap.sh` に適切なフラグを渡して実行してください。
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

### MCP Gateway の起動 (SSE Transport)

エージェントへの「権限の危機」（過剰権限・機密漏洩）のリスクを低減するため、HTTP/SSE 経由で接続可能な MCP Gateway を搭載しています。Gateway が通信をインフラレベルでフック（傍受）し、意図(Intent)に基づくアクセス制御（IBAC）と構造的な出力フィルタリングの適用を支援します。

#### 1. 宣言的な権限管理 (`intents.yaml`)
「AIエージェントに対する権限設定の最大効率」を図るため、コードを修正することなく YAML ファイルのみで権限を一元管理できます。Gateway はこの設定に基づき、未許可リクエストを拒否し、許可済み出力をフィルタリングすることを支援します。

さらに、**Semantic Guardrails** により、ツールの引数に対しても型、最大長、正規表現パターン、許容値のリストによる制限をかけることができ、不正な操作を未然に防ぎます。型チェックは厳密に行われ、指定した型（`string`, `integer`, `number`, `boolean`）と不一致の場合は即座に拒否（`DENY`）されます。また、ReDoS（正規表現DoS）攻撃を防ぐため、パターン文字数（最大200文字）や先行する長さ制限（`max_length`）が強制されます。

```yaml
version: 1
output_filters:
  recall_safe:
    type: structural_allowlist
    schemas:
      memory_search:
        results: [id, content, created_at] # embedding や internal_score などの機密フィールドは自動的にフック・除去される

intents:
  read_only_recall:
    description: "検索専用の権限"
    allowed_tools: [memory_search]
    output_filter: recall_safe
    guardrails:
      memory_search:
        params:
          query:
            type: string
            max_length: 512
            pattern: "^[^<>{};]*$" # スクリプトインジェクション等の簡易防止

  curate_memories:
    description: "記憶の管理権限"
    allowed_tools: [memory_delete]
    output_filter: none
    guardrails:
      memory_delete:
        requires_approval: true # 削除実行前に人間(HITL)の承認を必須にする
```

#### 2. HITL (Human-In-The-Loop) 承認
`requires_approval: true` が設定されたツールが呼び出されると、Gateway は承認通知を発行します。設定（`approval_blocking_mode`）に応じて以下の2つの挙動を選択可能です：
- **Immediate モード（デフォルト）**: 即座に `-32001` (`approval_required`) エラーを返し、クライアントに処理を委ねます。
- **Blocking モード**: ツール呼び出しを一時停止し、オペレーターからの `POST /approvals` エンドポイントへの承認応答を待ってから実行を再開/中断する「Suspend/Resume フロー」を実行します。これにより、破壊的な操作や機密性の高い操作を人間が安全に事前チェックできます。

#### 3. クライアント側の接続設定
エージェント側の設定（`mcp.json` や `claude_desktop_config.json` 等）には、環境変数ではなくヘッダを付与してエンドポイントを指定するだけです。これにより、エージェントごとに役割とアクセス権を安全に切り替えることができます。

```json
{
  "mcpServers": {
    "chronos-readonly": {
      "type": "sse",
      "url": "http://localhost:9100/sse",
      "headers": {
        "Authorization": "Bearer ck_super_secret_key",
        "X-MCP-Intent": "read_only_recall"
      }
    }
  }
}
```

#### 4. プロンプトの最大効率化
Gateway がツールの露出とペイロードを物理的にインターセプトするため、エージェントのシステムプロンプト（`AGENTS.md` 等）に「〇〇のツールは使わないで」「このフィールドは隠して」といった複雑な禁止事項を書く必要がなくなります。シンプルなプロンプトと Gateway の組み合わせにより、命令予算の浪費や LLM のハルシネーションを抑制することができます。

*(※ 今後のロードマップとして、Gateway が MCP の `prompts` 機能をフックし、接続時にエージェントへ役割や制約を自動注入する機能の実装を予定しています。)*

```bash
# サーバーの起動例
MCP_GATEWAY_POLICY_PATH=src/mcp_gateway/policies/intents.example.yaml \
MCP_GATEWAY_API_KEYS_JSON='{"my-agent":"ck_super_secret_key"}' \
uv run python -m mcp_gateway
```

---

## クライアント側のフック設定が不要な理由（ccgate 思想のサーバーサイド統合）

ChronosGraph の **MCP Gateway** は、LayerX社が提唱する「[ccgate (Server-defined Prompts / Permission Hook)](https://zenn.dev/layerx/articles/20260428-ccgate)」の設計思想を、**MCP プロトコル層（サーバー側）**に直接組み込んだものです。

Claude Code や Gemini CLI などのエージェントには、ツール実行前に介入するためのクライアントサイドのフック機能（`hooks` 設定など）が存在します。しかし、ChronosGraph を利用する場合、**エージェント側に複雑なフック設定や正規表現の決め打ちルールを記述する必要は一切ありません。**

### Gateway が「小さなゲート」として機能する仕組み

ccgate の「ツール実行前に必ず小さなゲート（Permission Hook）を通過させ、動的かつ安全に評価する」という哲学を、ChronosGraph は自らの Gateway 内で完結させています。

1. **インターセプト**: エージェントが MCP 経由で `tools/call` を要求した瞬間、Gateway がプロトコルレベルでこれを捕捉します。
2. **ポリシーエンジンによる決定論的評価**: 外部のバリデータ（LLMやクライアント側のccgateバイナリ）に問い合わせるのではなく、Gateway 内部の **Policy Engine** が `intents.yaml` と照合します。
    - インテント（用途）と権限の合致
    - 引数の型、文字列長、許容パターン（Semantic Guardrails）
    - 機密情報の混入チェック
3. **HITL (Human-In-The-Loop) による最終判断**: `requires_approval: true` のツール（`memory_delete` 等）が呼ばれた場合、Gateway 自身が実行を一時停止（Suspend）し、運用者からの承認を待機します。

このように、判断を下すのは外部ツールではなく **ChronosGraph 自身（の Gateway）** です。クライアント側の設定を肥大化させることなく、中央集権的で強固なガードレール（ZSP: Zero Standing Privileges / IBAC: Intent-Based Access Control）を実現しています。

---

## マイグレーション (Migration)

### ベクトル次元数の変更
埋め込みモデル（`EMBEDDING_PROVIDER`）を変更し、ベクトルの次元数が変わった場合、既存の記憶を新しいモデルで再埋め込みする必要があります。この操作を行わないと、検索時に次元不一致のエラーが発生します。

```bash
# 手動マイグレーションの実行
uv run python scripts/migrate_dimension.py
```

- このスクリプトは、既存のすべての記憶（Episodic / Semantic / Procedural）を現在の設定に基づいたモデルで再計算し、データベースを更新します。
- 大量の記憶がある場合は時間がかかる可能性があるため、事前にデータベースのバックアップを取ることを推奨します。

### スキーマの変更
SQLite および PostgreSQL ストレージを使用している場合、テーブル定義の変更は起動時に自動的に適用されます。手動での操作は通常不要です。新しいテーブルやカラムの追加は、SQL マイグレーションファイルとして管理されています。

---

## 設定リファレンス

| 環境変数 | デフォルト | 説明 |
|---|---|---|
| `STORAGE_BACKEND` | `sqlite` | ストレージバックエンド (`sqlite` / `postgres` / `supabase`) |
| `SUPABASE_URL` | `""` | **[Supabase用]** Supabase プロジェクト URL |
| `SUPABASE_KEY` | `""` | **[Supabase用]** Supabase Service Role Key |
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
| `POSTGRES_SSL` | `false` | PostgreSQL SSL 接続の有効化 |
| `POSTGRES_SSL_NO_VERIFY` | `false` | SSL証明書検証をスキップ（Supabase 等の自己署名チェーン対策） |
| `POSTGRES_STATEMENT_CACHE_SIZE` | `256` | asyncpg prepared statement キャッシュサイズ。pgBouncer transaction mode では `0` |
| `URL_FETCH_CONCURRENCY` | `3` | URL フェッチの同時実行数 |
| `ALLOW_PRIVATE_URLS` | `false` | プライベート URL の許可 (SSRF 対策) |
| `DASHBOARD_HOST` | `0.0.0.0` | Dashboard サーバーのバインドアドレス |
| `DASHBOARD_PORT` | `8000` | Dashboard サーバーのポート番号 |
| **`MCP_GATEWAY_POLICY_PATH`** | (必須) | **[MCP Gateway用]** 意図と出力フィルタを定義したポリシー(YAML)のパス |
| **`MCP_GATEWAY_API_KEYS_JSON`** | `None` | **[MCP Gateway用]** 認証用APIキーマップ (`{"agent_id": "raw_key"}`) |
| **`MCP_GATEWAY_HOST`** | `127.0.0.1` | **[MCP Gateway用]** サーバーのバインドアドレス |
| **`MCP_GATEWAY_PORT`** | `9100` | **[MCP Gateway用]** サーバーのポート番号 |

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
