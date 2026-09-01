# ChronosGraph (旧: Context Store MCP v2.0) — 設計・仕様書

> **名称について**: 本システムの正式プロジェクト名称は「**ChronosGraph**」です。開発・運用上の混乱を防ぐため、パッケージ名、モジュール名、データベース名、環境変数のプレフィックス等といった内部コンポーネント名としては引き続き `context_store` / `context-store-mcp` を使用するマッピングを採用しています。
> 
> **名称マッピング表と移行ガイダンス**:
> 
> | 項目 | 使用する名称 | 備考 |
> |---|---|---|
> | 正式プロジェクト名 | **ChronosGraph** | README.mdのタイトルや一般向けドキュメントで使用 |
> | PyPI パッケージ名 | `context-store-mcp` | `pyproject.toml` の `name` |
> | Python モジュール名 | `context_store` | `src/context_store/` など |
> | CLI コマンド | `context-store` | `python -m context_store` など |
> | データベース名 | `context_store` | PostgreSQL の DB名・ユーザー名 |
> | Docker サービス名 | `postgres`, `neo4j`, `redis` | 外部バックエンド利用時のみ |
> | 環境変数プレフィックス| (なし) | `POSTGRES_DB` など既存のまま |
> 
> **互換性の保証**:
> 名称変更に伴う破壊的変更はありません。既存の `.env` ファイル、MCP クライアント設定、データベースファイル（`memories.db`）はそのまま利用可能です。バージョンは `v2.0` として扱われます。
> **検索性の維持**: 古い名称で検索するユーザーのディスカバビリティを維持するため、README.md の冒頭等には旧名称（Context Store MCP）を併記することを推奨します。

> AIエージェント向け MCP ベース長期記憶システム

## 1. 製品概要

### 1.1 目的

AIエージェント（Claude Code / Gemini CLI / Cursor 等）にセッションを跨いだ永続的な
長期記憶を提供する Model Context Protocol (MCP) サーバー。

### 1.2 ターゲット

- 個人開発者によるセルフホスト運用
- 複数のAIエージェントからの共有利用

### 1.3 コア機能

| 機能 | 概要 |
|---|---|
| 多層記憶 | [📜 Episodic]（経験）・[🧠 Semantic]（知識）・[🕒 Procedural]（手順）の自動分類 |
| ハイブリッド検索 | ベクトル検索 + キーワード検索 + グラフ推論を RRF で統合 |
| 自動クリーンアップ | 時間減衰・重複排除・自動アーカイブによる記憶ライフサイクル管理 |
| 多様な入力ソース | 会話ログ自動取り込み・手動登録・URL ドキュメント取り込み |
| 埋め込みプロバイダー抽象化 | OpenAI / ローカルモデル / LiteLLM / カスタム API を設定で切り替え |
| RL 拡張ポイント | 将来の強化学習統合に向けたインターフェース設計 |

---

## 2. アーキテクチャ

### 2.1 アーキテクチャパターン

**パイプライン指向アーキテクチャ** を採用する。
処理を3つの独立したパイプラインに分離し、Orchestrator が統合・調整する。

```text
┌─────────────────────────────────────────────────────────────┐
│                    MCP Server (FastMCP)                       │
│                                                               │
│  ツール一覧:                                                   │
│  ├─ memory_save                 └─ session_flush              │
│  ├─ memory_search                                             │
│  ├─ memory_save_url                                           │
│  └─ ...                                                       │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │                    Orchestrator                          │ │
│  │                                                          │ │
│  │  ┌──────────────┐  ┌──────────────┐                     │ │
│  │  │  Ingestion   │  │   Batch      │                     │ │
│  │  │  Pipeline    │  │   Processor  │                     │ │
│  │  └──────┬───────┘  └──────┬───────┘                     │ │
│  │         │                 │                              │ │
│  │         │    ┌────────────┘                              │ │
│  │         │    │  ┌───────────────┐                        │ │
│  │         │    │  │ Task Registry │                        │ │
│  │         │    │  └───────────────┘                        │ │
│  │         │    │                                           │ │
│  │  ┌──────┴────┴──────────────────────────────────────┐   │ │
│  │  │            Storage Layer (抽象)                    │   │ │
│  │  └──────────────────────────────────────────────────┘   │ │
│  └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 バックエンド構成

| コンポーネント | 役割 | 障害時の挙動 | スキーマ管理 |
|---|---|---|---|
| SQLite + sqlite-vec | デフォルトの軽量DB。記憶本体・メタデータ・ベクトル・内部グラフ | 障害時は全機能停止 | 自動マイグレーション（SQLベース） |
| PostgreSQL 16 + pgvector | 本番向けDB。記憶本体・メタデータ・ベクトル・FTS | 障害時は全機能停止 | 自動マイグレーション（SQLベース） |
| Supabase (PostgREST) | HTTPS 経由のクラウド PostgreSQL バックエンド | 通信障害時はリトライ後 fail-soft/fail-fast を分類 | Supabase CLI 管理の SQL マイグレーション |
| Neo4j 5.x / Aura | PostgreSQL および Supabase 構成時の外部グラフDB。記憶間のリレーションシップ | 障害時はグラフ検索をスキップして継続。非同期モード時はワーカーがリトライ | (スキーマレス/Cypher初期化) |
| Redis 7.x | 任意のキャッシュ。検索結果・埋め込みベクトル | 障害時はキャッシュなしで継続 | (キーベース) |

### 2.3 実装言語・フレームワーク

| カテゴリ | 技術 |
|---|---|
| 言語 | Python 3.12+ |
| MCP フレームワーク | FastMCP |
| SQLite ドライバ | aiosqlite + sqlite-vec |
| PostgreSQL ドライバ | asyncpg |
| Supabase ドライバ | supabase-py / PostgREST |
| Neo4j ドライバ | neo4j-python-driver (async) |
| 日本語 FTS | PostgreSQL: pg_bigm または pgroonga / SQLite: LIKE・sqlite-vec 併用 |
| 埋め込み（ローカル） | sentence-transformers |
| 設定管理 | pydantic-settings |
| テスト | pytest + pytest-asyncio |
| コンテナ | Docker Compose |

---

## 3. データモデル

### 3.1 Memory エンティティ（PostgreSQL）

```python
class MemoryType(str, Enum):
    EPISODIC = "episodic"       # イベント・会話の記録
    SEMANTIC = "semantic"       # 事実・知識・定義
    PROCEDURAL = "procedural"   # 手順・ワークフロー・スキル

class SourceType(str, Enum):
    CONVERSATION = "conversation"
    MANUAL = "manual"
    URL = "url"
```

| フィールド | 型 | 説明 |
|---|---|---|
| `id` | UUID | 主キー |
| `content` | text | 記憶の本文 |
| `memory_type` | MemoryType | 自動分類された記憶の種別 |
| `source_type` | SourceType | 入力ソースの種別 |
| `source_metadata` | jsonb | ソース固有情報（agent名, URL, プロジェクトパス等） |
| `embedding` | vector | 埋め込みベクトル（次元数はプロバイダー依存） |
| `importance_score` | float | 重要度スコア（0.0 - 1.0） |
| `semantic_relevance` | float | 最終検索時の文脈的関連度スコア（0.0 - 1.0, 初期値: 0.5。初回検索前は中立値として扱う） |
| `access_count` | int | 検索で返却された回数 |
| `last_accessed_at` | timestamp | 最終アクセス日時 |
| `created_at` | timestamp | 作成日時 |
| `updated_at` | timestamp | 更新日時 |
| `archived_at` | timestamp? | アーカイブ日時（NULL = Active） |
| `tags` | text[] | プロジェクトタグ等 |
| `project` | text? | プロジェクト識別子。MCP ツール受け口で自動正規化される。入力が `.` の場合だけ、現在の Git リポジトリルートのディレクトリ名に解決する。それ以外の入力は filesystem や Git ルートへ解決せず、文字列上の basename を採用して前後の空白を除去、末尾の `/` を取り除き、小文字化する。区切り文字を含まない単純名はそのまま小文字化する。例: `.` → 現在の Git リポジトリ名、`/home/user/repo` → `repo`、`/path/to/chronos-graph` → `chronos-graph`、`  DotFiles-AI/ ` → `dotfiles-ai`、`sibyl` → `sibyl`。 |

### 3.2 インデックス

| インデックス | 種別 | 対象 |
|---|---|---|
| HNSW | ベクトル近傍探索 | `embedding` カラム |
| pg_bigm / pgroonga | 日本語全文検索 | `content` カラム |
| B-tree | フィルタ用 | `memory_type`, `source_type`, `archived_at`, `project` |
| GIN | 配列検索用 | `tags` カラム |

### 3.3 グラフモデル（Neo4j）

ノード:

```text
(:Memory {id: UUID, memory_type: string})
```

リレーションシップ（4カテゴリ）:

| カテゴリ | エッジタイプ | プロパティ | 説明 |
|---|---|---|---|
| 意味的 | `SEMANTICALLY_RELATED` | `score: float` | ベクトル類似度に基づく概念的関連 |
| 時間的 | `TEMPORAL_NEXT` | `time_delta_hours: int` | 同一セッション/プロジェクト内の時系列 |
| | `TEMPORAL_PREV` | `time_delta_hours: int` | |
| 因果的 | `CAUSED_BY` | `confidence: float` | 原因と結果（将来のRL拡張） |
| | `RESULTED_IN` | `confidence: float` | |
| 構造的 | `REFERENCES` | — | 明示的な参照（URL, ファイルパス） |
| | `DEPENDS_ON` | — | 依存関係 |
| | `CONTRADICTS` | `detected_at: timestamp` | 矛盾する情報（将来の概念ドリフト検出） |
| | `SUPERSEDES` | — | 新情報による旧情報の置換 |
| | `CHUNK_NEXT` | — | 同一ドキュメント内のチャンクの連続性（前→後） |
| | `CHUNK_PREV` | — | 同一ドキュメント内のチャンクの連続性（後→前） |

### 3.4 記憶の自動分類ルール

LLM は使用しない（トークン消費ゼロの原則）。
現行実装ではルールベース（キーワード・構文パターン）のスコアリングのみで分類する。埋め込みプロトタイプ比較は未実装の拡張候補とする。

| 種別 | 分類シグナル |
|---|---|
| Episodic | 過去形動詞（「〜した」「〜を決めた」）、会話ログ由来、タイムスタンプ参照 |
| Semantic | 定義表現（「〜とは」「〜の仕様は」）、ドキュメント/URL 由来、概念説明 |
| Procedural | 手順表現（「〜する方法」「手順：」「1. 2. 3.」）、コマンド列、ステップ構造 |

上記のいずれのルール・パターンにも合致しない曖昧な入力に対する**フォールバック（デフォルト）の MemoryType は `EPISODIC`** とする。
その際、フォールバックされた記憶ノードはノイズ（不要な相槌など）である可能性が高いため、デフォルトの `importance_score` に対してペナルティ（例: 0.5倍の係数を掛けるなど）を適用し、検索結果の上位に浮上するのを防ぐロジックを追加すること。

---

## 4. Ingestion Pipeline

### 4.1 処理フロー

```text
入力 → Source Adapter → Chunker → Classifier → Embedding → Deduplicator → Graph Linker → 永続化
```

**session_flush (バッチ保存):**
会話ログ全体をバックグラウンドで処理する機能。`Orchestrator` が `BatchProcessor` を介して `IngestionPipeline` へジョブを投入し、`TaskRegistry` でバックグラウンドタスクのライフサイクルを管理する。
- **Fire-and-forget**: ジョブを受理した時点で `{"status": "accepted", "estimated_chunks": n}` を即時返却する。`estimated_chunks` は `Chunker` による事前の概算であり、実際の永続化結果を保証するものではない。
- **並行制限**: 同時実行ジョブ数は `batch_max_concurrent_jobs` 設定により制限される。上限到達時は受理されずエラーを返す。
- **Shutdown Semantics**: システム終了時、`TaskRegistry` は未完了のバックグラウンドジョブの完了を待機せず、強制的にキャンセル（`cancel_all`）する。そのため、シャットダウン直前に投入されたジョブは永続化されない可能性がある。

**トランザクション境界の設計原則:**
`EmbeddingProvider` によるベクトル化処理（外部API呼び出しや重いローカル推論）は、**必ず Storage Layer の書き込みトランザクション（`save_memory` 等）を開始する前**に完了させてください。
SQLite の `busy_timeout=5000` は強力ですが、トランザクション内でネットワークI/Oを待機すると、他のエージェント（プロセス）からの書き込みを長時間ブロックし、`SQLITE_BUSY` エラーを引き起こす原因となります。
この制約は実装コードおよびテスト内で明示的に保証する必要があります（例: モックを用いて、`EmbeddingProvider.embed_batch` の完了前に `StorageAdapter.save_memory` などのトランザクションメソッドが呼び出されるとテストが失敗するような呼び出し順序検証を実装すること）。

### 4.1.1 Hybrid Ingestion Mode

記憶の保存運用として、エージェントの自主性に任せる「Selective モード」と、ターンごとに全ログを自動保存する「All モード」を切り替える機能を備える。
- **Selective モード**（デフォルト）: 従来通り、エージェントが自律的に `memory_save` ツールを呼び出す。
- **All モード**: クライアント側のフック（`scripts/agent_turn_hook.py` や OpenCode の `chronos-turn-end` プラグイン）からバックグラウンドで `tools/call memory_save` を直接叩き、ターン終了時にログを保存する。ツール実行前の安全評価は ChronosGate 側の責務として分離する。

**アーキテクチャ上の主要な設計:**
1. **設定のSSOT (Single Source of Truth) 化と伝播**: `CHRONOS_INGESTION_MODE` の型・デフォルト値・変数名は、クロスパッケージ参照を防ぐため独立した `src/chronos_shared/ingestion_mode.py` に集約する。ChronosGate を併用する場合は、Gateway 側からサブプロセスである context_store にこの環境変数を確実に継承させる。
2. **フックの切り詰めとフェイルソフト設計**: `agent_turn_hook.py` は送信前にログを **末尾保持 (最新情報優先)** で切り詰める（UTF-8 境界での不完全なシーケンスは破棄）。SSE ハンドシェイクと POST リクエスト全体に対して2段階の厳密なタイムアウトを適用し、いかなる通信障害時もエラーを握りつぶして `exit 0` で終了することで、メインプロセス（エージェント）をクラッシュさせない。
3. **ノイズ抑制 (Classifier 連携)**: `All` モードにおける低品質コンテンツの流入に対しては、既存の `Classifier` によるフォールバックペナルティ（`FALLBACK_PENALTY=0.5`）が適用され、検索結果のノイズ化を防ぐ。

**アーキテクチャ図 (トポロジ):**

```text
┌──────────────────────────────────────────────────────────────────┐
│  AI Agent (Claude Code / Codex / Cursor / Antigravity / OpenCode) │
│   ┌─────────────────────────────────────────────────────┐         │
│   │ ターン実行 → 終了時に Stop / session.idle 等が発火     │         │
│   └────────────────────┬────────────────────────────────┘         │
│                        │ stdin: 会話ログ or hook payload (JSON)    │
└────────────────────────┼─────────────────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────────────────┐
│  scripts/agent_turn_hook.py (フェイルソフトの薄い HTTP クライアント)│
│   1. extract_payload: --client 値に応じて payload から会話ログ抽出  │
│   2. truncate_log: 末尾保持で 8MB に切り詰め (UTF-8 境界対応)       │
│   3. POST /messages → tools/call memory_save (timeout=2.0s)      │
│   4. いかなるエラーも握りつぶし exit 0                              │
└────────────────────────┬─────────────────────────────────────────┘
                         │ HTTP (Bearer + x-mcp-intent: memory.ingest)
                         ▼
┌──────────────────────────────────────────────────────────────────┐
│  context_store (FastMCP サーバー)                                 │
│   - memory_save ツールが BatchProcessor で非同期処理              │
│   - Chunker → Classifier → Embedding → Deduplicator → Storage    │
│   - Fire-and-forget: 即座に {"status":"accepted"} を返す           │
└──────────────────────────────────────────────────────────────────┘
```

**フェイルソフト多層化設計:**

| 層 | 失敗対応 |
|---|---|
| クライアント hook | プロセス spawn 失敗は無視 (各クライアントの責務) |
| `agent_turn_hook.py` | 全例外 catch + `exit 0` でメインプロセスクラッシュ防止 |
| context_store ingestion | 分類失敗は EPISODIC + `FALLBACK_PENALTY=0.5` で救済 |
| シャットダウン | 進行中ジョブは `cancel_all` で強制終了 (ロス受容) |

**制限と注意:**

1. `MCP_GATEWAY_API_KEY` 未設定時はフックが no-op (stderr に ERROR ログのみ)。
2. シャットダウン中の取り込みは保証されない — 進行中ジョブは未保存のまま消える。
3. DB 容量が `selective` より明確に増加する。`purge_retention_days` で運用カバー。
4. Codex は新しい hook を初回 `/hooks` レビュー後にしか実行しない。

### 4.2 Source Adapter

入力ソースごとにアダプターを実装する:

```python
class SourceAdapter(Protocol):
    def extract(self, input_data: Any) -> list[RawContent]: ...
```

| アダプター | 入力 | 処理 |
|---|---|---|
| `ConversationAdapter` | 会話トランスクリプト（テキスト） | エージェント名・セッションID・プロジェクトパスをメタデータに付与 |
| `ManualAdapter` | 手動入力テキスト | タグ・重要度ヒントをメタデータに付与 |
| `URLAdapter` | URL 文字列 | HTML 取得 → Markdown 変換 → タイトル・URL・取得日時をメタデータに付与 |

### 4.3 Chunker

メモリフットプリントを最小化し、不要なガベージコレクションを防ぐため、Chunker は抽出結果全体を巨大なリストとして返すのではなく、Python のジェネレータ（`yield`）を利用した遅延評価（Streaming / Pipeline Processing）として実装する。

**スマートチャンキング（コードブロック保護）:**
Markdown 文書を分割する際、分割境界がコードブロック（```` ``` ````）の内部に該当する場合は、コードブロックの終了まで分割を遅延させる、または意味的ブロックを維持するスマートチャンキングロジックを実装し、コードの分断による検索精度低下を防止すること。

| ソース種別 | 分割方式 | チャンクサイズ |
|---|---|---|
| 会話ログ | Q&A ペア分割（ユーザー発言 + エージェント応答） | 1〜3ターン |
| 手動入力 | そのまま or セクション分割 | 〜1000 トークン |
| URL 文書 | Markdown 見出し（H1/H2）ベース + オーバーラップ | 500〜1000 トークン |

### 4.4 Deduplicator

| 条件 | アクション |
|---|---|
| 同一プロジェクト & コサイン類似度 ≥ 0.90 | **Append-only 置換**: 既存記憶を Archived 状態に遷移（論理削除）し、新ノードを INSERT。新ノードから旧ノードへ `SUPERSEDES` エッジを張る |
| 同一プロジェクト & 0.85 ≤ 類似度 < 0.90 | 統合候補としてマーク（バックグラウンドで処理） |
| その他 | 新規挿入 |

比較対象: 新チャンクのベクトルで既存メモリの Top 5 を検索。

> **設計根拠**: 物理的な UPDATE（上書き）ではなく追記型にすることで、
> (1) 旧情報の変更履歴をグラフ構造で追跡可能、
> (2) `SUPERSEDES` エッジが新旧ノード間に正しく作成される、
> (3) Archived 化された旧ノードは Lifecycle Manager の Purger フローで自然にクリーンアップされる。
> 
> **【アーキテクチャ上のトレードオフ（結果整合性）】**
> マルチプロセス環境において、同時に類似内容が書き込まれた場合、Ingestion Pipeline の排他制御はベストエフォートにとどまるため、類似度 ≥ 0.90 の重複がシステムに登録される可能性があります。すり抜けた重複についてはバックグラウンドの Consolidator によって事後修復される結果整合性のアプローチを採用します。詳細は Lifecycle Manager の Consolidator セクションを参照してください。

### 4.5 Graph Linker

新規記憶のNeo4j登録時に自動的にリレーションシップを推定する:

| エッジ | 推定条件 | 初期実装 |
|---|---|---|
| `SEMANTICALLY_RELATED` | ベクトル類似度 ≥ 0.70 | ✅ |
| `TEMPORAL_NEXT/PREV` | 同一セッション/プロジェクトの時系列順 | ✅ |
| `SUPERSEDES` | Deduplicator が Append-only 置換を実行（新→旧） | ✅ |
| `REFERENCES` | チャンク中の URL・ファイルパスの抽出 | ✅ |
| `CHUNK_NEXT/PREV` | 同一ドキュメント（URLや長文入力）から分割された連続するチャンク群の順序リンク | ✅ |
| `CAUSED_BY/RESULTED_IN` | 因果関係推定 | ❌（RL 拡張ポイント） |

**検索範囲とエッジ作成の上限およびバルク処理:**

パフォーマンスを維持するため、エッジ推定時の検索範囲と作成数に上限を設ける。
また、推定された複数のエッジは N+1 問題を防ぐため、`GraphAdapter.create_edges_batch` を用いて1回のバルク操作で一括登録する設計とする:

- 比較対象: 新チャンクのベクトルで既存メモリの **Top 10** を検索
- `SEMANTICALLY_RELATED` エッジは上位 **5 件**まで作成
- HNSW インデックスにより検索は O(log N) で実行される

---

## 5. Retrieval Pipeline

### 5.1 処理フロー

```text
クエリ → Query Analyzer → [Vector / Keyword / Graph] → Result Fusion → Post Processor → 結果返却
```

### 5.2 Query Analyzer

クエリの意図をルールベースで分析し、検索エンジンごとの重みを決定する。

```python
class SearchStrategy:
    vector_weight: float      # 0.0 - 1.0
    keyword_weight: float     # 0.0 - 1.0
    graph_weight: float       # 0.0 - 1.0
    graph_depth: int          # グラフトラバーサルの深さ
    time_decay_enabled: bool
```

戦略の決定パターン:

| クエリの特徴 | vector | keyword | graph | 備考 |
|---|---|---|---|---|
| 概念的・意味的クエリ | 0.5 | 0.2 | 0.3 | デフォルト |
| 固有名詞・コード片・エラーメッセージ | 0.2 | 0.6 | 0.2 | 完全一致重視 |
| 「なぜ」「原因」「経緯」 | 0.2 | 0.1 | 0.7 | 因果推論重視 |
| 時間表現（「先週」「以前」） | 0.4 | 0.2 | 0.4 | 時間フィルタ併用 |

### 5.3 検索エンジン

#### Vector Search（pgvector）

- コサイン類似度による HNSW 近似最近傍探索
- 閾値: `similarity ≥ 0.70`
- Active 状態の記憶のみ対象（`archived_at IS NULL`）

#### Keyword Search（PostgreSQL FTS）

- pg_bigm または pgroonga による日本語全文検索
- 固有名詞・コード片・エラーメッセージに有効

#### Graph Traversal（Neo4j）

- 起点ノード: Vector Search の上位結果から選定
- エッジタイプフィルタ: Query Analyzer が決定した戦略に基づく
- トラバーサル深さ: `SearchStrategy.graph_depth`（デフォルト 2）

### 5.4 Result Fusion

**RRF（Reciprocal Rank Fusion）** をベースとした複合スコアリング:

```text
rrf_score_raw = Σ (weight × 1/(K + rank + 1))    # K = 60
rrf_score = normalize_rrf(rrf_score_raw, weights_sum)  # 理論上の最大期待値に基づく正規化
time_decay = 0.5 ^ (days_since_access / 30)        # 半減期 30 日
final_score = 0.5 × rrf_score + 0.3 × time_decay + 0.2 × importance_score
```

**RRF スコアの正規化（必須）:**

RRF の生スコアは非常に小さな値（K=60, rank=1 の最大値でも約 0.016）となり、
time_decay（≈0.0〜1.0）や importance_score（0.0〜1.0）とスケールが大きく異なる。
Min-Max正規化を適用すると、結果が1件のみの場合や関連度が低い場合でも一律でスコアが1.0にインフレしてしまう問題があるため、
理論上の最大期待値（rank=1の時の値）を分母とした、静的なスケール引き伸ばしを適用する:

```python
def normalize_rrf(scores: list[float], weights_sum: float = 1.0, k: int = 60) -> list[float]:
    if not scores:
        return []
    # RRFの理論上の最大期待値 (全指標においてrank=1が並んだ場合)。
    # 公式: 1 / (K + rank + 1) -> 1 / (60 + 1 + 1) = 1 / 62
    # 最大期待値 = sum(weights) * (1.0 / (K + 2))
    max_possible_score = weights_sum * (1.0 / (k + 2))
    
    # スコアを最大期待値で割りスケールを合わせる（1.0を超える場合は1.0にクリップ）
    return [min(1.0, s / max_possible_score) for s in scores]
```

| パラメータ | デフォルト値 | 説明 |
|---|---|---|
| `K` | 60 | RRF 定数 |
| 半減期 | 30 日 | 時間減衰の半減期 |
| RRF 重み | 0.5 | 最終スコアにおける正規化済み検索スコアの重み |
| 直近性重み | 0.3 | 時間減衰の重み |
| 重要度重み | 0.2 | importance_score の重み |

### 5.5 Post Processor

- プロジェクトタグによるフィルタリング（オプション）
- 最大トークン制限によるコンテキスト消費の抑制
  - **完全オフライン対応**: トークン計算に利用する `tiktoken` はデフォルトでエンコーディング辞書をネットワークからフェッチするため、エアギャップ（完全オフライン）環境でのクラッシュリスクがあります。このため、以下の優先順位に基づくフォールバックチェーンと例外ハンドリングを必須要件とします。
    1. **`tiktoken.encoding_for_model(model)`**: 初期化時およびエンコード実行時に、ネットワーク関連エラー（`TimeoutError`, `ConnectionError`, `OSError`, `urllib.error.URLError` 等）を明示的にキャッチした場合は、即座にステップ 3 へジャンプします。
    2. **`TokenCounter` Protocol**: プロバイダー固有のフォールバック手段がある場合に試行します。
    3. **前述の言語別最適化（§5.5.1 の ASCII 比率ベースの動的マージン）を用いた文字数近似**: 最終手段として安全側過大推定による近似式（例: `token_count_approx = ceil(len(text) / 3.0 * safety_margin)`、日本語等の場合は `safety_margin = 1.2` または `3.0` 等）へフォールバックします。
    すべてのフォールバック発動時は、どの関数（`encoding_for_model` や `TokenCounter`）で失敗したかを含む明確なログを `INFO`/`WARNING` レベルで出力し、運用者が発生頻度を監視できるようにしてください。
- `last_accessed_at` と `access_count` の更新

---

## 6. Lifecycle Manager

### 6.1 記憶の状態遷移

```text
新規挿入 ──▶ Active ◀── アクセスで活性化
                │
     複合スコア ≤ 閾値 & 一定期間未アクセス
                │
                ▼
            Archived     (検索対象外、データ保持)
                │
         アーカイブ後 N 日経過
                │
                ▼
             Purged      (物理削除)
```

### 6.2 イベント駆動型クリーンアップ

MCP サーバーは `stdio` モードではクライアントに起動・停止される一時的なプロセスであり、
`APScheduler` 等の時間ベーススケジューラでは「実行予定時刻にプロセスが存在しない」
リスクが高い。そのため、**イベント駆動型のレイジー・クリーンアップ**を採用する。

**トリガー条件（いずれかを満たしたとき、非同期でクリーンアップタスクをキック）:**

| トリガー | 条件 |
|---|---|
| 初回起動 | 前回クリーンアップからの経過日数が 1 日以上（`last_cleanup_at` を DB に永続化） |
| 保存回数 | `memory_save` の累積呼び出し回数が閾値（デフォルト: 50）を超過 |
| 明示的実行 | `memory_prune` ツールの呼び出し |

**実行されるジョブ:**

| ジョブ | 処理 |
|---|---|
| Decay Scorer | 全 Active 記憶の複合スコア再計算。閾値以下をアーカイブ候補にマーク |
| Auto Archiver | マークされた記憶を Archived に遷移。グラフノードに `archived` フラグ付与 |
| Consolidator | Deduplicator がマークした統合候補（類似度 0.85〜0.89）のマージ、および**Deduplicator のレースコンディションをすり抜けて登録された重複記憶（類似度 ≥ 0.90）の自己修復（事後的な Append-only 置換と SUPERSEDES エッジの作成）**を行う |
| Purger | Archived 後 N 日経過した記憶を物理削除（Storage + Graph 連動）。Graph からノードを削除する際、そのノードが関与する全エッジ（`SUPERSEDES` などの依存エッジを含む）は確実にカスケード削除し（Neo4jの場合は `DETACH DELETE` などを利用）、データモデル上にダングリングエッジ（孤立した不正なエッジ）が残らないことを担保する。 |
| Stats Collector | DB 使用量・記憶数・平均スコア等の統計記録 |

**非同期タスクのエラーハンドリング**:

- クリーンアップタスクは `asyncio.create_task()` で生成されるが、サイレントフェイルを防ぐため、`Task.add_done_callback()` を使用してエラーハンドラを登録する。
- 例外が発生した場合は、標準エラー出力またはロガーに完全なトレースバックを出力し、異常を明示化する。
- ロック機構（`cleanup_running`）は `try...finally` ブロックを用いて、タスクが成功・失敗・キャンセルのいずれで終了しても確実に解放されるように実装する。

**実装上の注意:**

- `last_cleanup_at` と `save_count` はメモリではなく **DB に永続化** する（プロセス寿命が短いため）
- クリーンアップは `asyncio.create_task()` で非同期実行し、ツール応答をブロックしない
- `APScheduler` は不要（依存パッケージから除去）

**グレースフル・シャットダウン:**

`stdio` モードの MCP サーバーはエージェント側の判断で突然終了（Kill）される可能性がある。
進行中のクリーンアップタスクのデータ破損を防ぐため、以下を実装する:

- FastMCP の lifecycle / lifespan hook を優先し、そこで shutdown cleanup を実行する
- アプリケーション側で `SIGINT` / `SIGTERM` を扱う場合でも、既存の transport / サーバー実装がシグナルを所有しているときは無条件に上書きしない
- 進行中のクリーンアップタスクがあれば、タイムアウト付き（5秒）で完了を待機する
- タイムアウト時はタスクをキャンセルし、各アダプターの `dispose()` も 5 秒以内に収束させる
- `dispose()` 経路では未コミットトランザクションのロールバックと `cleanup_running` 状態の整合性回復を行う

**冪等性の要件:**

各クリーンアップジョブ（Archiver, Purger, Consolidator 等）は**冪等**に実装する:

- 中断されても次回再実行時に同じ結果に収束すること
- バッチ処理は小さなチャンク（例: 100件ずつ）でコミットし、単一の巨大トランザクションを避ける
- 処理済みレコードのスキップ条件を明示的にクエリに含める

**複数プロセス間の排他制御（SQLite モード）:**

複数エージェントが同一 SQLite DB に対して同時にクリーンアップを実行するリスク（SQLITE_BUSY等のロック競合）を防ぐため、Pythonの `filelock` ライブラリ等を利用したOSレベルのファイルロックを導入する。
DBファイルと同一ディレクトリに専用のロックファイル（例: `cleanup.lock`）を作成し、クリーンアップ開始前にこのファイルのロック取得を試行する。ロックが取得できない（他プロセスが実行中）場合は即座にスキップすることで、DBへの不要なアクセスを防ぎ安全な排他制御を実現する。

**Stale Lock 自動リカバリ基盤の必須実装**:
`filelock` をそのまま使用するだけでは、プロセスがSIGKILL等で強制終了された場合、環境やファイルシステムによってはロックファイルが残留し（Stale Lock）、以降のクリーンアップが永久に実行されなくなるデッドロックの危険性がある。これを防ぐため、`filelock` をラップした専用のロック管理基盤（例: `StaleAwareFileLock`）を実装すること。
ロック取得試行前にロックファイルの最終更新時刻（mtime）をチェックし、設定された有効期限（例: 10分、設定値 `STALE_LOCK_TIMEOUT_SECONDS` を導入）を超過している場合は、古いプロセスがクラッシュしたとみなして安全にロックファイルを強制削除・再取得する機構を備えなければならない。
この際、複数プロセスが同時に古いロックを検出し、削除と再取得を競合して実行する TOCTOU（Time-of-Check to Time-of-Use）のレースコンディションを防ぐため、以下のガード処理を必須とする：
1. ファイル削除時の `FileNotFoundError` を安全にハンドリングする（他プロセスが既に削除した場合は処理を継続）。
2. ファイル削除後からロック取得（`filelock.acquire()`）までの間に他プロセスがロックを取得する可能性を考慮し、ロック取得後に再度 `mtime` または作成されたファイルを検証して、自身が取得したロックが本当に新規の正当なものであることを確認するか、あるいは `filelock` の原子性を活用して削除後直ちに `acquire()` に委ねる堅牢なフローを構築すること。

OSレベルのロックを取得するコードは、後続のDBアクセス処理全体を `try...finally` ブロックでラップし、正常終了時だけでなくエラーやクラッシュ時（例外発生時）にも、最終的にOSレベルのファイルロックが確実に解放されるよう実装しなければならない。なお、OSレベルのファイルロック自体がプロセス異常終了時にもOSによって解放される性質（例: `fcntl` や `flock` ベースのファイルロック）を持つことが前提となる。

さらに、クライアントの再起動などによる状態のリセットやプロセスクラッシュ時の復旧、状態の永続化のため、ロック取得後にDB内の `lifecycle_state` テーブル（ID=1の単一行制約）に対しても状態を記録する。OSロック取得済みのプロセスが唯一の書き込みプロセスであることが保証されているため、DBの状態によらず強制的に上書き（無条件UPDATE）する。

```sql
-- OSロック取得後は無条件でDB状態を更新（OSロックが排他制御を保証するため）
UPDATE lifecycle_state
SET cleanup_running = 1, cleanup_started_at = datetime('now')
WHERE id = 1;
```

クリーンアップ完了時、または失敗時は、まずDBの `cleanup_running = 0` へのリセットとコミットを行い、その後、`finally` ブロック等の保証されたクリーンアップパスにてOSレベルのファイルロックを解放する。DBの更新に失敗した場合（例: I/Oエラー）であっても、OSレベルのロックは解放しなければならない。

**複数プロセス間の排他制御（PostgreSQL モード）:**

PostgreSQL では `lifecycle_state.cleanup_running` の論理フラグに加えて、
セッション単位の advisory lock を取得できた場合のみクリーンアップを実行する。

```sql
SELECT pg_try_advisory_lock(hashtext('cleanup_lock'));
-- false の場合は他プロセスが実行中のためスキップ
```

完了時は `pg_advisory_unlock(...)` を呼び出し、SQLite と同様に stale-lock timeout の考え方を維持する。

**Consolidator による自己修復（Self-healing）の実装・運用要件:**

- **検出戦略**: 
  - **問題**: 毎回対象ノードに対して全件のベクトル走査（フルスキャン）を行うのは計算量が膨大となり非効率である。
  - **解決策**: スライディングウィンドウ方式（例：直近 N 時間・あるいは前回クリーンアップ以降に `Active` で作成・更新された記憶ノード）をトリガーとして対象を絞り込む。
  - **実装（二段階フィルタリング）**:
    1. **HNSWインデックス活用**: DB側のHNSWインデックス機能（PostgreSQLの `ORDER BY embedding <=> $1 LIMIT $2` や sqlite-vec の `MATCH` クエリ）を活用した効率的なバッチクエリによって候補を絞り込む。
    2. **厳密フィルタリング**: その後アプリ側で閾値（≥ 0.90）による厳密なフィルタリングを行う。
- **パフォーマンスとスコープ**: データセットが大規模（1万〜10万件以上）な場合、Consolidator 1回あたりの処理件数（バッチサイズ）に上限（例: 100〜500件）を設け、超過分は次回のクリーンアップサイクルに持ち越す（バックオフ/スロットリング）。
- **優先順位**: 0.85〜0.89 の通常マージ処理よりも、類似度 ≥ 0.90 の自己修復（重複排除のすり抜け対応）を優先して実行する。
- **監視ログとメトリクス**:
  - 自己修復発動時は、`Self-healing: archived duplicate memory {id} due to similarity {score} (superseded by {new_id})` に相当する構造化ログを `INFO` または `WARNING` レベルで出力する。
  - 監視用メトリクスとして `self_healing_duplicate_count` を記録し、Stats Collector で集計・永続化する。

### 6.3 Decay Scorer 仕様

```python
composite_score = (
    0.5 × semantic_relevance +   # 最終検索時のスコア
    0.3 × recency +               # 0.5 ^ (経過日数 / HALF_LIFE_DAYS)
    0.2 × importance_score         # 重要度
)
```

`composite_score ≤ ARCHIVE_THRESHOLD` の記憶がアーカイブ候補となる。

### 6.4 設定パラメータ

| パラメータ | デフォルト値 | 説明 |
|---|---|---|
| `DECAY_HALF_LIFE_DAYS` | 30 | 時間減衰の半減期（日） |
| `ARCHIVE_THRESHOLD` | 0.05 | この複合スコア以下でアーカイブ候補 |
| `CONSOLIDATION_THRESHOLD` | 0.85 | 統合対象のコサイン類似度閾値 |
| `PURGE_RETENTION_DAYS` | 90 | アーカイブ後の保持日数 |

### 6.5 将来の拡張ポイント

初期実装には含めないが、アーキテクチャとして以下の拡張を想定:

- **概念ドリフト検出**: `CONTRADICTS` リレーションの自動検出
- **矛盾解決戦略**: 新情報を優先 / ユーザーに確認
- **重要度の動的再評価**: アクセスパターンに基づく昇格・降格

---

## 7. MCP インターフェース

### 7.1 サーバー初期化

FastMCP を使用. 重いモジュール（sentence-transformers 等）は**遅延ロード**する。

- 起動時: MCP ハンドシェイクのみ（軽量）
- 初回ツール呼び出し時: Orchestrator / Storage / Embedding の初期化
- 排他制御: 複数ツールの同時非同期呼び出しに備え、`asyncio.Lock` で初期化を排他制御する

### 7.1.1 トランスポート

初期実装は `stdio`（標準入出力）モードのみサポートする。

将来の拡張として以下を計画（v2.1 以降）:

- HTTP/SSE トランスポート（`uvicorn` ベース、`--transport sse` オプション）
- 認証層（Bearer Token / MCP 標準認証準拠）
- 複数PC間での記憶共有（クラウドネイティブ構成）

### 7.2 ツール一覧

#### `memory_save` — 記憶の保存

| 引数 | 型 | 必須 | デフォルト | 説明 |
|---|---|---|---|---|
| `content` | str | ✅ | — | 記憶する内容 |
| `source` | str | — | `"conversation"` | `"conversation"` / `"manual"` / `"url"` |
| `project` | str? | — | None | プロジェクトタグ |
| `tags` | list[str] | — | [] | 追加タグ（制約：要素最大長50、`^[a-zA-Z0-9_-]+$`） |
| `importance` | float? | — | None | 重要度ヒント（None なら自動） |

記憶種別（episodic/semantic/procedural）は自動分類される。
重複する記憶が存在する場合は自動的に統合される。

**互換性 / 移行への注意**: `source` フィールドの既定値が以前の値から `"conversation"` に変更されました。そのため、既存API利用時の既定挙動が変化する可能性があります。既存クライアントで明示的な挙動を維持したい場合は、明示的に `source: "manual"` などを設定して対処してください。

#### `memory_save_url` — URL からの取り込み

| 引数 | 型 | 必須 | デフォルト | 説明 |
|---|---|---|---|---|
| `url` | str | ✅ | — | 取り込む URL |
| `project` | str? | — | None | プロジェクトタグ |
| `tags` | list[str] | — | [] | 追加タグ（制約：要素最大長50、`^[a-zA-Z0-9_-]+$`） |

URL のコンテンツを取得し、Markdown 変換後にチャンク分割して記憶として保存する。

**セキュリティ制約（SSRF 対策）:**

`memory_save_url` は任意 URL への HTTP リクエストを発行するため、
SSRF（Server-Side Request Forgery）を防ぐ以下の制約を**必須**で適用する:

| 制約 | 値 |
|---|---|
| 許可スキーム | `http`, `https` のみ |
| プライベート IP | デフォルト拒否（`ALLOW_PRIVATE_URLS=true` で解除可） |
| リダイレクト | 最大 3 回 |
| レスポンスサイズ | 最大 10 MB（ストリーミング受信による到達時即時中断） |
| タイムアウト | 30 秒 |
| 許可 Content-Type | `text/*`, `application/json`, `application/pdf` |

プライベート IP の判定対象:

- `127.0.0.0/8`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`
- `::1`, `fc00::/7`
- `169.254.0.0/16`（リンクローカル / クラウドメタデータ）

> **設計根拠**: MCP サーバーはユーザーのローカルマシンで稼働するため、
> 悪意のある URL 指定によりクラウドメタデータエンドポイント（`169.254.169.254`）や
> ローカルサービスにアクセスされるリスクがある。

**DNS リバインディング対策:**

DNS リバインディング攻撃（初回は公開 IP → TTL 切れ後にプライベート IP へ再バインド）を
防ぐため、URLAdapter は以下の手順で HTTP リクエストを発行する:

1. URL のホスト名を DNS 解決し、解決された IP アドレスを取得
2. 取得した IP がプライベート IP 空間に該当しないことを検証
3. 検証済みの IP アドレスに対して直接接続する際、TLS ハンドシェイクにおいて `server_hostname` (SNI) に元のホスト名を設定し、かつ完全な証明書検証（ホスト名一致確認を含む）を強制する。証明書の不一致や検証失敗が発生した場合は接続を拒否する。
4. 検証済みの IP と TLS 設定を使用して HTTP リクエストを発行（`Host` ヘッダーは元のホスト名を設定）
5. レスポンスヘッダーの `Content-Type` が許可リスト（`text/*`, `application/json`, `application/pdf`）に含まれることを検証し、不一致の場合は接続を中断する（ボディのストリーミング開始前・ヘッダー受信直後に行うこと）
6. コネクション確立後、レスポンスボディを `httpx` のストリーミングリクエスト (`stream`) で受信し、チャンクごとに受信累積サイズを監視する。10MB を超過した時点で直ちに通信を中断 (Abort) すること。これにより巨大ファイルによるプロセス側の OOM (メモリ枯渇) やネットワーク帯域の浪費を防止する。
7. リダイレクト発生時は、遷移先 URL に対して手順 1-6 を再実行

> **実装注記**: `httpx` のカスタム Transport を使用し、
> DNS 解決、IP 検証、および IP 接続時のホスト名ベースの TLS 検証を強制的に実行する。
> これにより、IP アドレスに対する証明書受け入れやホスト名検証の無効化を防止する。
> **【重要な副作用と実装要件】**: 素朴にリクエストURLをIPアドレスに書き換えると、TLSのSNIやHTTPのHostヘッダまでがIPアドレスに切り替わり、証明書検証エラーやバイパスが発生する副作用があります。これを回避するため、`httpcore.AsyncNetworkBackend` をラップしたカスタムバックエンドを実装してください。このバックエンドの `connect_tcp` メソッドで検証済みのIPアドレスへルーティングを行うだけで、`httpcore` が後続で呼び出す `AsyncNetworkStream.start_tls(server_hostname=...)` により元のホスト名による厳格な証明書検証とSNIが自動的に維持されます。

**並行実行制限:**

複数の `memory_save_url` が同時に呼び出された場合、各リクエストが最大 30 秒の
HTTP タイムアウトを持つため、非同期ワーカーが枯渇し他の軽量ツール（`memory_search` 等）の
応答をブロックするリスクがある。これを防ぐため、`asyncio.Semaphore` による並行制限を適用する:

> **注意 (Semaphore のスコープとロギング要件)**:
> URLフェッチ用の `asyncio.Semaphore` はインスタンス（プロセス）レベルの排他制御です。
> MCPサーバーが複数プロセスで起動された場合（例: Claude と Cursor がそれぞれ独立したプロセスとして起動している場合）、この Semaphore の制限はプロセス単位となり、システム全体の真の制限にはなりません。この制約を運用者が明確に認識できるよう、サーバー初期化時（または `memory_save_url` の初回呼び出し時）に、「現在のURLフェッチ制限はプロセススコープであり、マルチプロセス実行時は制限を超過する可能性がある」旨の `DEBUG` または `INFO` レベルのログを出力するコードを実装してください。また、開発者向けの Docstring にもこの制約を明記してください。

| パラメータ | デフォルト値 | 説明 |
|---|---|---|
| `URL_FETCH_CONCURRENCY` | 3 | 同時 URL 取得数の上限 |

#### `memory_search` — ハイブリッド検索

| 引数 | 型 | 必須 | デフォルト | 説明 |
|---|---|---|---|---|
| `query` | str | ✅ | — | 検索クエリ |
| `project` | str? | — | None | プロジェクトフィルタ |
| `memory_type` | str? | — | None | 記憶種別フィルタ |
| `top_k` | int | — | 10 | 返却件数 |
| `max_tokens` | int? | — | None | 結果の最大トークン数 |

ベクトル検索・キーワード検索・グラフ検索をクエリ意図に基づいて自動重み付けし、
RRF + 時間減衰で統合して結果を返す。

> **現行実装の制限**: `memory_type` 引数は API 互換性のため受け取るが、RetrievalPipeline 側のフィルタにはまだ接続されていない。指定時は WARNING ログを出し、検索結果には反映しない。

#### `memory_search_graph` — グラフトラバーサル検索

| 引数 | 型 | 必須 | デフォルト | 説明 |
|---|---|---|---|---|
| `query` | str | ✅ | — | 起点を見つけるためのクエリ |
| `edge_types` | list[str]? | — | None | 辿るエッジタイプの指定 |
| `depth` | int | — | 2 | トラバーサルの深さ |
| `project` | str? | — | None | プロジェクトフィルタ |

記憶のグラフ構造を辿って関連する記憶群を取得する。
返却値にはリレーションシップ情報も含む設計とする。

> **現行実装の制限**: `memory_search_graph` は `GRAPH_ENABLED=true` のときのみ利用可能だが、`edge_types` と `depth` を GraphTraversal へ直接渡す専用経路は未実装。指定値がある場合は WARNING ログを出し、標準のハイブリッド検索（`top_k=5`）へフォールバックする。

#### `memory_delete` — 記憶の削除

| 引数 | 型 | 必須 | 説明 |
|---|---|---|---|
| `memory_id` | str | ✅ | 削除対象の記憶 ID |

有効な StorageAdapter から削除し、GraphAdapter が有効な場合は対応ノードもベストエフォートで削除する。

#### `memory_prune` — クリーンアップ

| 引数 | 型 | 必須 | デフォルト | 説明 |
|---|---|---|---|---|
| `older_than_days` | int | — | 90 | この日数以上未アクセスの記憶を対象 |
| `dry_run` | bool | — | True | true なら対象件数のみ返す |

#### `memory_stats` — 統計情報

| 引数 | 型 | 必須 | デフォルト | 説明 |
|---|---|---|---|---|
| `project` | str? | — | None | プロジェクトでフィルタ |

総記憶数、種別内訳、DB 使用量、平均スコア等を返す。

### 7.3 MCP Resources

| URI | 説明 |
|---|---|
| `memory://stats` | システム全体の統計情報 |
| `memory://projects` | 登録されているプロジェクト一覧 |

### 7.4 エラーハンドリング

統一されたエラーレスポンス:

```python
class StorageError:
    code: str           # "NOT_FOUND" | "STORAGE_ERROR" | "EMBEDDING_ERROR" 等
    message: str        # 人間が読めるエラーメッセージ
    recoverable: bool   # リトライ可能か
```

Graceful Degradation:

| 障害箇所 | 挙動 |
|---|---|
| Neo4j | グラフ検索をスキップ。ベクトル + キーワード検索のみで動作継続 |
| Redis | キャッシュなしで直接 DB 検索 |
| PostgreSQL | 全ツールがエラーを返す（マスター DB） |
| SQLite | WAL TRUNCATE中などのロック競合時（`SQLITE_BUSY`等）、`StorageError(code="STORAGE_BUSY", recoverable=True)`を返しMCPクライアントにリトライを促す |
| Supabase | 通信・接続エラーや `STORAGE_TIMEOUT`、500/502/503 (サーバー側エラー)、429 (Rate Limit) 等は Exponential Backoff リトライを前提とした Recoverable=True。一方、413 Payload Too Large、23505 (Unique Violation)、および 401/403 (認証・認可エラー) は Recoverable=False として直ちに fail-fast 停止 |

---

## 8. Storage Layer

### 8.1 Storage Adapter Protocol

```python
class StorageAdapter(Protocol):
    async def save_memory(self, memory: Memory) -> str: ...
    async def get_memory(self, memory_id: str) -> Memory | None: ...
    async def delete_memory(self, memory_id: str) -> bool: ...
    async def update_memory(self, memory_id: str, updates: dict) -> bool: ...
    async def vector_search(self, embedding: list[float], top_k: int) -> list[ScoredMemory]: ...
    async def keyword_search(self, query: str, top_k: int) -> list[ScoredMemory]: ...
    async def list_by_filter(self, filters: MemoryFilters) -> list[Memory]: ...
    async def get_vector_dimension(self) -> int | None: ...
    async def dispose(self) -> None: ...
```

### 8.2 Graph Adapter Protocol

```python
class EdgeParams(TypedDict):
    from_id: str
    to_id: str
    edge_type: str
    props: dict

class GraphAdapter(Protocol):
    async def create_node(self, memory_id: str, metadata: dict) -> None: ...
    async def create_edge(self, from_id: str, to_id: str, edge_type: str, props: dict) -> None: ...
    async def create_edges_batch(self, edges: list[EdgeParams]) -> None: ...
    async def traverse(self, seed_ids: list[str], edge_types: list[str], depth: int) -> GraphResult: ...
    async def delete_node(self, memory_id: str) -> None: ...
    async def dispose(self) -> None: ...
```

### 8.3 Cache Adapter Protocol

```python
class CacheAdapter(Protocol):
    async def get(self, key: str) -> Any | None: ...
    async def set(self, key: str, value: Any, ttl: int) -> None: ...
    async def invalidate(self, key: str) -> None: ...
    async def invalidate_prefix(self, prefix: str) -> None: ...
    async def clear(self) -> None: ...
    async def dispose(self) -> None: ...
```

#### キャッシュ無効化ルール

キャッシュキー命名規則:

- 検索結果: `search:{project}:{query_hash}`
- 個別記憶: `memory:{memory_id}`
- 統計情報: `stats:{project}`

データ変更時の無効化マッピング:

| 操作 | 無効化対象 |
|---|---|
| `save_memory` | `search:{project}:*`（プレフィックス一括）、`stats:{project}` |
| `update_memory` | `memory:{id}`、`search:{project}:*`、`stats:{project}` |
| `delete_memory` | `memory:{id}`、`search:{project}:*`、`stats:{project}` |
| `memory_prune` | 全キャッシュをクリア |

**プロセス間キャッシュの一貫性（SQLite + InMemoryCacheAdapter）:**
複数のエージェント（プロセス）が同一の SQLite DB を共有する場合、単一プロセス内のキャッシュでは他プロセスの更新を検知できず、古いデータ（Stale Cache）を返すリスクがある。
これを防ぐため、`StorageFactory` 内で `SQLiteCacheCoherenceChecker`（または同等の監視コンポーネント）を用いて、DB の `system_metadata` テーブルの `key = 'last_cache_update'` の `updated_at` をポーリングする。
パフォーマンス劣化を防ぐため、ポーリングは `get` の呼び出し毎ではなく、設定可能な一定間隔（例: `CACHE_COHERENCE_POLL_INTERVAL_SECONDS` = 5秒）でのみ実行する。インメモリの最終更新時刻より DB 側の時刻が新しいことが検知された場合は、`CacheAdapter.clear()` を呼び出してインメモリキャッシュを一括クリアする。

`invalidate_prefix(prefix)` の Redis 実装は `KEYS` を使わず、`SCAN` + batched `DELETE` を用いる。
疑似コード:

```python
cursor = 0
while True:
    cursor, keys = await redis.scan(cursor, match=f"{prefix}*", count=100)
    if keys:
        await redis.delete(*keys)
    if cursor == 0:
        break
```

InMemory 実装はプレフィックス一致での安全なループ削除を行い、意味論を揃える。
同時に、キーが膨大になった場合にイベントループをブロックせず、かつ `asyncio.Lock` の競合を長期化させないため、以下のいずれかのアプローチを必須とする:
(a) ロックの一時解放・再取得（ロック取得 → 最大N件のキーを取得・削除 → ロック解放 → `await asyncio.sleep(0.001)` で他タスクへ制御を譲り、再度ロック取得のループを繰り返す）。
(b) スナップショットベースの削除（ロックを短時間保持して削除対象キーのリストをスナップショットとして抽出し、ロックを解放した後に各対象キーを安全に削除する）。
※ `asyncio.Lock` でのロック中における `await asyncio.sleep(0)` 単体による制御委譲は、他タスクが同じロックを待っている場合に飢餓状態（Starvation）を引き起こすため不十分であり、必ず上記いずれかのロック管理手段と組み合わせて実装すること。

### 8.4 初期実装

**フルモード（PostgreSQL + Neo4j + Redis）:**

- `PostgresStorageAdapter` — asyncpg ベース
- `Neo4jGraphAdapter` — neo4j-python-driver (async) ベース
- `RedisCacheAdapter` — redis-py (async) ベース

**ライトウェイトモード（SQLite、ゼロコンフィグ）:**

- `SQLiteStorageAdapter` — `sqlite-vec`（ベクトル検索）+ `FTS5`（全文検索）、単一ファイルで完結
- `SQLiteGraphAdapter` — 同一 SQLite DB 内の `memory_edges` 結合テーブル + 再帰的 CTE によるグラフトラバーサル
- `InMemoryCacheAdapter` — Python `dict` + `asyncio.Lock` による TTL 付きインメモリキャッシュ

ライトウェイトモードは `pip install` のみで動作し、Docker / 外部サービスを必要としない。
`STORAGE_BACKEND` 環境変数で切り替える（デフォルト: `sqlite`）。

#### SQLite 初期化 PRAGMA

`SQLiteStorageAdapter` / `SQLiteGraphAdapter` は、接続確立直後に以下の PRAGMA を強制実行する:

```sql
PRAGMA journal_mode=WAL;          -- 読み取り/書き込みの並行実行を許可
PRAGMA busy_timeout=5000;          -- ロック競合時に最大5秒まで自動リトライ
PRAGMA foreign_keys=ON;            -- memory_edges の参照整合性を強制
PRAGMA synchronous=NORMAL;         -- WAL モードでは NORMAL で十分な耐久性
```

> **設計根拠**: 複数のエージェント（Claude Code + Gemini CLI 等）が同一 SQLite ファイルに
> 同時接続する運用が想定される。デフォルトの rollback journal モードでは `SQLITE_BUSY` エラーが
> 頻発するため、WAL モードへの切り替えは事実上必須。
> 
> **運用上の注意 (WAL 補助ファイル)**: WAL モードでは `memories.db-wal` と `memories.db-shm` が併せて生成される。
> 初期化ログや README では、この補助ファイルの存在と同一ディレクトリへの書き込み権限が必要であることを明示する。
> 
> **注意 (ファイルシステム制約)**: SQLite の WAL モードは同一マシン上のアクセスには対応しますが、NFS や CIFS などのネットワークファイルシステム上では正しく動作しません。
> 
> **保守運用**: 長時間運用で WAL が肥大化した場合に備え、Lifecycle Manager などのイベント駆動ジョブにて定期的に `PRAGMA wal_checkpoint(PASSIVE)` を実行する。ただし PASSIVE は非ブロッキングにチェックポイント処理を試行するものの即時の WAL ファイル縮小（truncation）を保証しない。
> **WAL肥大化の自動フェイルセーフ**: `PRAGMA wal_checkpoint(PASSIVE)` が継続的に失敗し、かつ WAL ファイルの物理サイズが閾値を超過した場合は、システムのIOパフォーマンス低下を防ぐため、警告ログ（`WARNING` または `ERROR` レベル）を出力した上で、**システムが自動的に**ロック競合のリスクを承知で `PRAGMA wal_checkpoint(TRUNCATE)` を試行する（または次回の安全な起動時まで待機する）自動リカバリ機構を実装すること。
> 判定ロジックは該当ジョブのステータス保持箇所に追加し、テスト用に環境変数やアプリケーションの Settings オブジェクトから以下のパラメータ（設定キーとデフォルト値）を注入・参照できるように構成すること。これらのパラメータは Lifecycle Manager ジョブのステータスおよび判定ロジックにて利用され、テスト時にも書き換え可能でなければならない:
> - `WAL_TRUNCATE_SIZE_BYTES` (デフォルト: 104857600 バイト / 100MB): 自動 TRUNCATE をトリガーする WAL ファイルの最大サイズ閾値
> - `WAL_PASSIVE_FAIL_CONSECUTIVE_THRESHOLD` (デフォルト: 3): 連続して PASSIVE チェックポイントに失敗した回数の閾値
> - `WAL_PASSIVE_FAIL_WINDOW_SECONDS` (デフォルト: 600 秒 / 10分): 失敗回数をカウントする時間枠（スライディングウィンドウの秒数）
> - `WAL_PASSIVE_FAIL_WINDOW_COUNT_THRESHOLD` (デフォルト: 5): 指定時間枠内（例: 10分間）でのチェックポイント失敗回数の閾値
> 
> **セキュリティ制約 (パーミッション)**: 記憶データ（会話ログ等）を含むため、DB ファイル（`~/.context-store/memories.db`）の作成時にパーミッションを `0600`（所有者のみ読み書き可）に設定することを必須とします。

#### SQLiteGraphAdapter のスキーマ

```sql
-- 実際の設定は src/context_store/storage/migrations/sqlite/*.sql を参照
CREATE TABLE IF NOT EXISTS memory_edges (
    from_id TEXT NOT NULL,
    to_id TEXT NOT NULL,
    edge_type TEXT NOT NULL,
    properties TEXT DEFAULT '{}',  -- JSON
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (from_id, to_id, edge_type)
);
CREATE INDEX IF NOT EXISTS idx_edges_from ON memory_edges(from_id);
CREATE INDEX IF NOT EXISTS idx_edges_to ON memory_edges(to_id);
```

トラバーサルは再帰的 CTE で実装（外部グラフ DB 不要）:

```sql
WITH RECURSIVE graph AS (
    SELECT to_id, edge_type, 1 AS depth
    FROM memory_edges WHERE from_id = ?
    UNION ALL
    SELECT e.to_id, e.edge_type, g.depth + 1
    FROM graph g JOIN memory_edges e ON g.to_id = e.from_id
    WHERE g.depth < ?  -- デフォルト: 2, ハードリミット: 5
)
SELECT DISTINCT to_id, edge_type, depth FROM graph;
```

設定ローダー（`config.py` 等の環境変数を読み込むモジュール）によって、環境変数 `GRAPH_MAX_LOGICAL_DEPTH` は `graph_max_logical_depth` に、`GRAPH_MAX_PHYSICAL_HOPS` は `graph_max_physical_hops` にマッピングされます。これらのロールとデフォルト値は以下の通りです。

| パラメータ | デフォルト値 | 役割・説明 |
|---|---|---|
| `max_depth` | 2 | クライアントからの要求によるトラバーサルの深さのデフォルト値。 |
| `graph_max_logical_depth` | 5 | クライアントが指定できる最大論理深さ（クライアント向けの制限。これを超える値は強制的に制限される）。 |
| `graph_max_physical_hops` | 50 | 透過的・SUPERSEDES解決時の無限ループを防止するための内部的な最大物理ホップ数制限。 |

> **特記事項 (`SUPERSEDES` チェーンの解決)**:
> Deduplicator による Append-only 置換で形成される `SUPERSEDES` エッジは新旧情報の論理的な同一性を示すため、この種のトラバーサルは論理的な「深さ」とみなさないこと。再帰的CTEやトラバーサルロジック内において、`SUPERSEDES` を辿る操作は `depth` のカウントを加算させない（透過的に最新ノードへ解決する）よう実装し、更新頻度の高いノードがハードリミットにより最新版へ到達できなくなる問題を回避する。
> ※ この透過解決を実装する際は、サイクル（閉路）発生時の無限ループ再帰を防止するため、訪問済みノードセット（`visited_supersedes_ids`）を保持して再訪時は打ち切るか、または物理的な最大ホップ数（例: 最大50ホップ。`graph_max_physical_hops`）のサブ上限を設ける設計を必須とする。また、制限に到達した場合はサイレントフェイルとせず、Pythonの `logging` モジュールを使用して明確な警告ログ（例: `logging.warning(f"Physical hops limit ({Settings.graph_max_physical_hops}) reached while resolving SUPERSEDES chain for node {node_id}. Returning last reachable node (may not be the latest active version).")`）を出力すること。Phase 5 / Phase 9 のテスト要件として以下の3ケースを必ず含めること: (1) Long SUPERSEDES chain: 同じメモリへの10回のSUPERSEDESチェーンを作成し、depth=2のトラバーサルが常に最新のActiveノードに到達することを検証、(2) Mixed-traversal: SUPERSEDESとSEMANTICALLY_RELATED等の他のエッジを混在させ、論理深さがSUPERSEDES以外のエッジでのみカウントされることを検証、(3) Hard-limit validation: SUPERSEDESを除外した論理深さが設定した論理ハードリミット（`graph_max_logical_depth`）を超えないこと、かつ物理深さのリミット（`graph_max_physical_hops`）により無限ループを防止し、警告ログが出力されることを検証。

> **サーキットブレーカー（CPU時間枯渇対策）**:
> 密なグラフにおける再帰的CTEの実行は、物理ホップ数の制限（`graph_max_physical_hops`）を満たしていても計算量が爆発し、CPU時間を枯渇させるリスクがあります。このため、SQLiteGraphAdapter におけるトラバーサルクエリ実行時には、明示的なクエリタイムアウトを導入してください。タイムアウト値は環境変数または設定ファイルから取得可能な `GRAPH_TRAVERSAL_TIMEOUT_SECONDS`（例: 1〜2秒）を使用します。
> 
> **注意**: `aiosqlite` を用いた場合、`asyncio.wait_for` によるタイムアウトでは Python 側のコルーチンがキャンセルされるだけで、バックグラウンドの SQLite スレッドでの CPU 消費は継続してしまいます。これを防ぐため、必ず `sqlite3.Connection.interrupt()` （プログレスハンドラ等を用いた経過時間の監視、または別タスクからの遅延呼び出し）を用いて SQLite 内部の実行を強制終了させる機構を実装してください。
> **【重要な副作用と実装要件（安全な SQLite Interrupt コンテキストマネージャ）】**: 非同期タスクから単純に `interrupt()` を呼び出すと、クエリ完了後のアイドル状態のコネクションに割り込みフラグが残り、**プール内の後続の無関係なクエリが `OperationalError: interrupted` でクラッシュする**という深刻な副作用があります。
> これを防ぐため、共通基盤として非同期コンテキストマネージャ（例: `SafeSqliteInterruptCtx`）を実装してください。このコンテキストマネージャは、「クエリが確実に実行中である期間」のみ割り込みフラグを有効化し、クエリ終了後やプール返却時には絶対に割り込みが波及しないよう厳密な状態管理を行わなければなりません。
> **実装における原子性要件**: タイマータスク内でのフラグチェックと `interrupt()` 呼び出しの間に `await` を挟んではなりません。asyncio は協調的マルチタスクであるため、`await` による制御の譲渡により、コンテキストマネージャの `__aexit__` がフラグを `False` に設定する隙が生まれます。
> 実装パターン例:
> 1. **単一ステップ実装**: フラグチェックと `interrupt()` を同期的に実行（`await` なし）
> 2. **asyncio.Lock ベース**: ロックを保持したままチェック→呼び出しを実行
> 3. **Task.cancel() ベース**: タイマーを `asyncio.Task` として管理し、コンテキスト終了時に `task.cancel()` で先制的にキャンセル
> タイムアウト発生時は例外として処理を中断するのではなく、到達済みの部分グラフを返すか、安全に空結果を返す Graceful Degradation を行うサーキットブレーカー機構の実装を必須とします。タイムアウト発生時は警告ログも出力してください。
> Neo4jGraphAdapter においても、同様に `GRAPH_TRAVERSAL_TIMEOUT_SECONDS` を利用し、トランザクションのタイムアウト（例: `tx.run(..., timeout=GRAPH_TRAVERSAL_TIMEOUT_SECONDS)`）を設定して、同様の Graceful Degradation を行ってください。

**SQLite のバックプレッシャー制御:**
aiosqlite を用いた非同期実行において、FastMCP 側で大量の並行リクエストが発生した場合、スレッド枯渇やメモリ上のタスク滞留を防ぐため、以下のバックプレッシャー機構を実装すること：

1.  **同時接続制限**: `SQLiteStorageAdapter` 初期化時に `asyncio.Semaphore(sqlite_max_concurrent_connections)` を設定し、セマフォ (`self._semaphore`) は並行 DB 操作のために `asyncio.wait_for` と `try/finally` を使用し て取得・解放する。
2.  **待ち行列数制限 (Bounded Queueing)**: 待機リクエスト数を制限する機構を実装する。キュー・ワーカーパターン (例: `request_queue` と `maxsize=sqlite_max_queued_requests`) や明示的なカウンタ (例: `SQLiteStorageAdapter._waiting_count` と `_waiting_lock`) のいずれかを使用し、`asyncio.Semaphore` の内部状態への依存を避けること。制限を超過した場合は即座に `StorageError(code="STORAGE_BUSY", recoverable=True)` を送出してフェイルファストさせること。
3.  **取得タイムアウトと確実な解放**:  
    - すべての DB 操作を `asyncio.wait_for(self._semaphore.acquire(), timeout=Settings.sqlite_acquire_timeout)` でラップすること。
    - セマフォの確実な解放を保証するため、`try/finally` ブロックまたは `async with` コンテキストマネージャを必ず使用すること。
    - セマフォ取得時の `TimeoutError` および、DB 操作中に発生したロック関連の `aiosqlite.OperationalError` (捕捉対象: `"database is locked"`, `"locked"`, `"busy"` を含むメッセージ、およびエラーコード `SQLITE_BUSY` (5), `SQLITE_LOCKED` (6), `SQLITE_BUSY_SNAPSHOT` (517)) は、一律で `StorageError(code="STORAGE_BUSY", recoverable=True)` に変換して送出し、MCP クライアントにリトライを促すこと。ロック無関係のエラーは再スローすること。

これにより、イベントループ内での無制限なコルーチン滞留を防止し、システム全体の応答性を維持する。実装には上記のように `request_queue` や `self._waiting_count` といった標準的なパブリック API のみを用いること。

**性能検証要件:**

- `memory_edges` に 10,000 件の現実的なエッジを投入した fixture を用意する
- depth=2 と depth=5 の再帰的 CTE トラバーサルについて、レイテンシとメモリ使用量を測定する
- from_id を複数パターン切り替えて tail percentile を取得する
- 結果は benchmark artifact として保存し、性能回帰の確認に使う

### 8.5 マイグレーションシステム

SQLファイルベースの軽量なマイグレーションシステムを備え、スキーマ変更を自動的に適用する。

- **MigrationRunner**: SQLite および PostgreSQL の両方に対応した非同期実行コア。
- **格納場所**: `src/context_store/storage/migrations/{sqlite,postgres}/*.sql`
- **バージョン管理**: `schema_migrations` テーブルに適用済みのバージョン（SQLファイル名）を記録。
- **ベースライン検知**: マイグレーション導入前の既存データベースを検知し、初期マイグレーションをスキップして現状を「適用済み」として記録する。
- **原子性の保証**: スキーマ変更とバージョン記録を同一トランザクション内（SQLite/PostgreSQL）で実行し、不整合を防止。
- **Supabase の例外**: `STORAGE_BACKEND=supabase` の場合、内蔵のランナーは使用せず、Supabase CLI を用いて `supabase/migrations/` 配下の SQL ファイルでスキーマがデプロイ・管理されます。

### 8.6 ストレージ選択ロジック

`config.py` の `STORAGE_BACKEND` / `CACHE_BACKEND` / `GRAPH_SYNC_MODE` に応じて、
ファクトリ関数が適切なアダプターインスタンスを返す:

| 設定値 | StorageAdapter | GraphAdapter | CacheAdapter |
|---|---|---|---|
| `sqlite` (デフォルト) | SQLiteStorageAdapter | `GRAPH_ENABLED=true` の場合 SQLiteGraphAdapter | `CACHE_BACKEND` に応じて InMemoryCacheAdapter または RedisCacheAdapter |
| `postgres` | PostgresStorageAdapter | `GRAPH_ENABLED=true` の場合 Neo4jGraphAdapter* | `CACHE_BACKEND` に応じて InMemoryCacheAdapter または RedisCacheAdapter |
| `supabase` | SupabaseStorageAdapter | `graph_sync_mode=async_outbox` かつ `GRAPH_ENABLED=true` の場合 Neo4jGraphAdapter*。それ以外は非対応・バリデーションエラー | `CACHE_BACKEND` に応じて InMemoryCacheAdapter または RedisCacheAdapter |

\* `GRAPH_ENABLED=false` の場合は GraphAdapter を None にする。Redis は `CACHE_BACKEND=redis` のときのみ使用し、接続失敗時の暗黙フォールバックは行わない。
\* `supabase` バックエンドは `graph_sync_mode=async_outbox` の場合のみグラフ機能（Neo4j Aura への非同期同期）をサポートします（同期の `sync` モードは Neo4j Bolt を HTTPS 経由でカプセル化できないため非対応）。

> **注意**: `sqlite` モードでも `GRAPH_ENABLED=false` の場合は GraphAdapter を None にする。`GRAPH_ENABLED=true` の場合のみ SQLiteGraphAdapter を使用する。

---

### 8.7 Supabase Storage Adapter 設計

`STORAGE_BACKEND=supabase` は、Supabase Data API (PostgREST) を HTTPS (port 443) 経由で利用するストレージアダプタである。Prisma Accelerate ベースの旧実装 (`storage-backend=prisma`) からの置き換えとして設計された。

**コンポーネント構成:**

```text
Application (Python 3.12+)
  └── SupabaseStorageAdapter (storage/supabase.py)
        |   - supabase-py v2.4+ AsyncClient
        |   - postgres_helpers 再利用
        | HTTPS (port 443)
        v
Supabase Project (managed PostgreSQL)
  +-- PostgREST (/rest/v1/memories, /rest/v1/rpc/*)
  +-- PostgreSQL + pgvector + pg_trgm
  +-- memories テーブル (vector(768))
```

**主要設計判断:**

| 決定 | 採用案 | 根拠 |
|---|---|---|
| クライアント初期化 | `classmethod .create(settings)` | Prisma 実装と一貫、factory が同期コードのまま |
| ベクトル検索 | Postgres RPC `vector_search` | PostgREST 経由で pgvector `<=>` 演算子を利用 |
| 起動時検証 | 薄い probe (初回呼出時に検知) | Supabase CLI で事前適用が前提 |
| アトミック increment | RPC `increment_memory_access_count` | HTTP RMW 競合の根本回避 |
| 入力順保持 | `dict[uuid -> Memory]` + 入力順走査 | Prisma 実装踏襲 |

**SQL 設計の要点:**

- `supabase/migrations/` でスキーマ管理 (Supabase CLI 規約 `YYYYMMDDHHMMSS_<description>.sql`)。
- `memories` テーブル: `vector(768)`, HNSW インデックス (`idx_memories_embedding_hnsw`), pg_trgm FTS。
- RPC `vector_search`: `1 - (m.embedding <=> query_embedding)` でコサイン類似度。`LANGUAGE sql STABLE`, `SECURITY INVOKER`, `SET search_path = public`。
- RPC `list_projects`: サーバサイド DISTINCT (PostgREST 単独では表現不可)。
- RPC `increment_memory_access_count`: PL/pgSQL でアトミック increment + 時刻更新。
- RPC `get_embedding_dimension`: 既存 embedding がない場合にスキーマ上の vector 次元を取得。

**エラーマッピング:**

| 条件 | StorageError コード | recoverable |
|---|---|---|
| PostgreSQL unique_violation (23505) | `DUPLICATE_CONTENT` | false |
| 不正入力 (22P02, 22023) | `INVALID_INPUT` | false |
| リソース未検出 (PGRST116) | `NOT_FOUND` | false |
| タイムアウト・504・503・ConnectionError | `STORAGE_TIMEOUT` | true |
| 413 Payload Too Large | `STORAGE_PAYLOAD_TOO_LARGE` | false (入力分割が必要) |

**実装上の重要な注意点:**

1. **UPDATE 列ホワイトリスト**: Prisma 実装と同じ許可セット。`content` 更新時は `content_hash` を再計算。
2. **カーソルページング**: `or_` で `(created_at, id)` 複合比較。日時は `isoformat(timespec=microseconds)` の完全表現が必要。
3. **`archived` セマンティクス**: `None=active only`, `True=archived only`, `False=両方`。
4. **`top_k` clamp**: `SUPABASE_MAX_TOP_K=200` で頭打ち。
5. **`keyword_search` ワイルドカード**: `%`/`_` を意図的にエスケープしない (Prisma 互換)。サニタイズは呼出側の責務。
6. **`count_by_filter`**: `head=True` で行データを返さず count のみ取得。
7. **機密情報保護**: `SUPABASE_KEY` を例外メッセージ・ログ・スタックトレースに含めない。
8. **次元検証**: `create()` で DB 実次元と `settings.embedding_dimension` を照合。不一致なら `StorageError(code=INVALID_STATE, recoverable=False)` で fail-fast。

## 9. Embedding Provider

### 9.1 Protocol

```python
class EmbeddingProvider(Protocol):
    async def embed(self, text: str) -> list[float]: ...
    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...
    @property
    def dimension(self) -> int: ...
```

**レートリミット対策:**
`memory_save_url` 等で巨大なMarkdown文書を取り込み、多数のチャンクに分割して `embed_batch` に渡した場合、OpenAI等の外部APIのレートリミット（TPM/RPM）やペイロードサイズ上限に抵触する可能性があります。
`EmbeddingProvider` の実装（特に外部通信を伴う `openai.py`、`litellm.py`、`custom_api.py`）においては、内部で固定サイズ（例: 100件ごと）のバッチページネーション処理を行い、透過的に複数回のリクエストへ分割するロジックを実装してください。この際、**`embed_batch` が返すベクトルの順序は、入力された `texts` の順序と完全に一致すること**を厳密に保証する必要があります。具体的には、入力時に各テキストへ元のインデックスを付与して追跡状態を維持し、分割リクエスト完了後に元のインデックス順に再構築（ソート）してから返すように実装してください。さらに `tenacity` ライブラリ等を用いて Exponential Backoff にジッター (Jitter) を加えたリトライ機構を組み込むことが必須です。具体的な制約として、最大試行回数（`stop_after_attempt` 等）または最大経過時間（`stop_after_delay` 等）を明示し、リトライ対象とする例外（HTTP 429 Rate Limit、ネットワークタイムアウト、5xx系のサーバーサイドエラー等）を厳密に列挙指定してください。また、リトライが発生した場合でも前述のインデックス追跡が失われず、最終的な順序が常に保持されることを確保してください。

#### ベクトル次元数の整合性チェック（フェイルファスト）

Embedding Provider の切り替え（例: OpenAI 1536次元 → ローカルモデル 768次元）により
ベクトル次元数が変更された場合、既存の DB スキーマとの不整合が発生する。
これを防ぐため、Orchestrator 初期化時にフェイルファストチェックを行う:

```python
stored_dim = await storage.get_vector_dimension()
current_dim = embedding_provider.dimension
if stored_dim is not None and stored_dim != current_dim:
    raise ConfigurationError(
        f"ベクトル次元数の不一致: DB={stored_dim}, Provider={current_dim}.\\n"
        f"現行バージョンでは自動マイグレーションはサポートされていません。\\n"
        f"以下のいずれかの方法でデッドロック状態を回避してください:\\n"
        f"1. 環境変数 SQLITE_DB_PATH や Postgres の DB 名を変更して別環境として開始する\\n"
        f"2. 既存データを退避する場合、付属の退避スクリプト (`python scripts/migrate_dimension.py`) を実行する\\n"
        f"3. 全データを初期化する場合、DBファイルの手動削除（SQLite）やスキーマの再構築（PostgreSQL）を行う"
    )
```

> **注意**: 既存ベクトルの自動マイグレーション（再埋め込み）は v2.1 ロードマップとして計画。
> v2.0 では不一致検知時の安全な停止（フェイルファスト）のみを実装する。

### 9.2 実装一覧

| プロバイダー | クラス | 設定値 |
|---|---|---|
| OpenAI API | `OpenAIEmbeddingProvider` | `EMBEDDING_PROVIDER=openai` |
| ローカルモデル | `LocalModelEmbeddingProvider` | `EMBEDDING_PROVIDER=local-model` |
| LiteLLM Proxy | `LiteLLMEmbeddingProvider` | `EMBEDDING_PROVIDER=litellm` |
| カスタム API | `CustomAPIEmbeddingProvider` | `EMBEDDING_PROVIDER=custom-api` |

ローカルモデルは `sentence-transformers` を使用。推奨モデル: `cl-nagoya/ruri-v3-310m`（日本語特化, 768 次元）。

---

## 10. RL 拡張ポイント

初期実装は行わない。Orchestrator に以下のフックインターフェースを配置し、
NoOp 実装をデフォルトとして注入する。

```python
class ActionLogger(Protocol):
    """エージェントの行動ログを記録（将来の RL 学習データ源）"""
    async def log_action(self, action: AgentAction) -> None: ...

class RewardSignal(Protocol):
    """報酬シグナルの収集"""
    async def record_reward(self, memory_id: str, signal: float, context: dict) -> None: ...

class PolicyHook(Protocol):
    """検索戦略の決定に介入するフック（将来のプランナー用）"""
    async def adjust_strategy(self, query: str, base_strategy: SearchStrategy) -> SearchStrategy: ...
```

---

## 11. プロジェクト構成

**💡 ChronosGate 分離について**: ツール実行前の安全評価 Gateway は ChronosGraph 本体から分離され、独立リポジトリ ChronosGate として提供されます。ChronosGraph は `context_store` と共有プリミティブ `chronos_shared` を保持し、ChronosGate へ直接依存しません。

```text
context-store-mcp/
├── pyproject.toml
├── docker-compose.yml
├── .env.example
├── SPEC.md                        # 本ドキュメント
│
├── supabase/
│   └── migrations/                # Supabase 管理の SQL マイグレーションファイル（supabase CLI を使用）
│
├── src/
│   ├── context_store/
│   │   ├── __init__.py
│   │   ├── server.py              # FastMCP サーバー（エントリーポイント）
│   │   ├── orchestrator.py        # パイプラインの統合・調整
│   │   ├── config.py              # pydantic-settings 設定
│   │   │
│   │   ├── ingestion/             # Ingestion Pipeline
│   │   │   ├── __init__.py
│   │   │   ├── pipeline.py
│   │   │   ├── adapters.py        # ConversationAdapter / ManualAdapter / URLAdapter
│   │   │   ├── chunker.py
│   │   │   ├── classifier.py      # 記憶種別の自動分類
│   │   │   ├── deduplicator.py
│   │   │   └── graph_linker.py
│   │   │
│   │   ├── retrieval/             # Retrieval Pipeline
│   │   │   ├── __init__.py
│   │   │   ├── pipeline.py
│   │   │   ├── query_analyzer.py
│   │   │   ├── vector_search.py
│   │   │   ├── keyword_search.py
│   │   │   ├── graph_traversal.py
│   │   │   ├── result_fusion.py
│   │   │   └── post_processor.py
│   │   │
│   │   ├── lifecycle/             # Lifecycle Manager
│   │   │   ├── __init__.py
│   │   │   ├── manager.py
│   │   │   ├── decay_scorer.py
│   │   │   ├── archiver.py
│   │   │   ├── consolidator.py
│   │   │   └── purger.py
│   │   │
│   │   ├── storage/               # Storage Layer
│   │   │   ├── __init__.py
│   │   │   ├── protocols.py
│   │   │   ├── factory.py            # ストレージ選択ファクトリ
│   │   │   ├── postgres.py
│   │   │   ├── sqlite.py             # ライトウェイト版 (sqlite-vec + FTS5)
│   │   │   ├── sqlite_graph.py       # SQLite ローカルグラフ (再帰的 CTE)
│   │   │   ├── neo4j.py
│   │   │   ├── redis.py
│   │   │   └── inmemory.py           # InMemory Cache Adapter
│   │   │
│   │   ├── embedding/             # Embedding Provider
│   │   │   ├── __init__.py
│   │   │   ├── protocols.py
│   │   │   ├── openai.py
│   │   │   ├── local_model.py
│   │   │   ├── litellm.py
│   │   │   └── custom_api.py
│   │   │
│   │   ├── models/                # データモデル
│   │   │   ├── __init__.py
│   │   │   ├── memory.py
│   │   │   ├── search.py
│   │   │   └── graph.py
│   │   │
│   │   └── extensions/            # RL 拡張ポイント
│   │       ├── __init__.py
│   │       ├── protocols.py
│   │       └── noop.py
│   │
│   └── chronos_shared/            # ChronosGraph / ChronosGate shared primitives
│       ├── __init__.py
│       ├── ingestion_mode.py
│       └── py.typed
│
├── frontend/                      # Dashboard Web UI (React + Vite)
│   ├── src/
│   │   ├── api/                   # API クライアント（stats/graph/logs/websocket）
│   │   ├── stores/                # Zustand ストア（statsStore/graphStore/logStore）
│   │   ├── pages/                 # ページ（Dashboard/NetworkView/LogExplorer/Settings）
│   │   ├── components/            # 共有コンポーネント（layout/common）
│   │   ├── types/                 # TypeScript 型定義
│   │   └── utils/                 # ユーティリティ（apiUtils/logUtils）
│   ├── e2e/                       # Playwright E2E テスト
│   └── playwright.config.ts
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── conftest.py
│
└── docs/
    └── (設計資料は SPEC.md に統合済み)
```

---

## 12. 環境変数

```bash
# === Storage Backend ===
STORAGE_BACKEND=sqlite              # sqlite | postgres | supabase
GRAPH_ENABLED=false                 # true | false (Neo4j の有効化)
CACHE_BACKEND=inmemory              # inmemory | redis
SQLITE_DB_PATH=~/.context-store/memories.db  # sqlite の場合

# === PostgreSQL (STORAGE_BACKEND=postgres の場合) ===
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=context_store
POSTGRES_USER=context_store
POSTGRES_PASSWORD=<secret>
POSTGRES_SSL=false
POSTGRES_SSL_NO_VERIFY=false   # true で証明書検証をスキップ (Supabase 等)
POSTGRES_STATEMENT_CACHE_SIZE=256  # 0 で prepared statement キャッシュ無効化 (pgBouncer)

# === Supabase (STORAGE_BACKEND=supabase の場合) ===
SUPABASE_URL=https://xxxxx.supabase.co
SUPABASE_KEY=<secret>
SUPABASE_REQUEST_TIMEOUT_SECONDS=10.0   # Supabase Data API呼び出しのタイムアウト秒数

# === Neo4j (GRAPH_ENABLED=true の場合) ===
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=<secret>

# === Graph Sync Mode (rev.11 Transactional Outbox) ===
GRAPH_SYNC_MODE=sync                   # sync | async_outbox
OUTBOX_POLL_INTERVAL_SECONDS=5.0
OUTBOX_BATCH_SIZE=100
OUTBOX_MAX_RETRIES=10
OUTBOX_BACKOFF_BASE_SECONDS=1.0
OUTBOX_BACKOFF_MAX_SECONDS=60.0

# === Redis (CACHE_BACKEND=redis の場合) ===
REDIS_URL=redis://localhost:6379

# === Embedding ===
EMBEDDING_PROVIDER=openai           # openai | local-model | litellm | custom-api
OPENAI_API_KEY=sk-...               # openai の場合
LOCAL_MODEL_NAME=cl-nagoya/ruri-v3-310m  # local-model の場合
LITELLM_API_BASE=http://localhost:4000   # litellm の場合
CUSTOM_API_ENDPOINT=http://...           # custom-api の場合

# === Lifecycle ===
DECAY_HALF_LIFE_DAYS=30
ARCHIVE_THRESHOLD=0.05
CONSOLIDATION_THRESHOLD=0.85
PURGE_RETENTION_DAYS=90
STALE_LOCK_TIMEOUT_SECONDS=600  # 10 minutes; stale filelock auto-recovery threshold

# === Ingestion & Hook ===
CHRONOS_INGESTION_MODE=selective    # selective | all
MCP_HOOK_TIMEOUT_SECONDS=2.0
MCP_HOOK_SSE_TIMEOUT_SECONDS=1.0
MCP_HOOK_MAX_LOG_BYTES=8388608

# === Search ===
DEFAULT_TOP_K=10
SIMILARITY_THRESHOLD=0.70
DEDUP_THRESHOLD=0.90
GRAPH_MAX_LOGICAL_DEPTH=5
GRAPH_MAX_PHYSICAL_HOPS=50
GRAPH_TRAVERSAL_TIMEOUT_SECONDS=2.0
SQLITE_MAX_CONCURRENT_CONNECTIONS=5
SQLITE_MAX_QUEUED_REQUESTS=20        # セマフォ取得待ちの最大キュー数 (超過時は即時拒否)
SQLITE_ACQUIRE_TIMEOUT=2.0           # seconds (セマフォ取得待ちタイムアウト)
```

---

## 13. パフォーマンス目標

| メトリクス | 目標値 |
|---|---|
| 検索レイテンシ（P95） | < 2,000 ms |
| 記憶保存レイテンシ | < 1,000 ms |
| MCP サーバー起動（ハンドシェイク） | < 500 ms |
| 対応記憶数 | 100,000+ |

### 13.1 パフォーマンス最適化仕様 (Phase 1 実装完了)

リモートDB（Supabase Data API）使用時のp95レイテンシおよびタイムアウト頻度を大幅に削減するため、以下の最適化が実装されています。

1. **Supabase 射影最適化（ペイロード削減）**
   - **`vector_search_brief` RPC の導入**: ベクトル検索（`vector_search`）時、768次元の `embedding` カラム（1レコードあたり約10KBのJSON表現）の転送コストを排除するため、`embedding` カラムを除外した結果を返す専用RPC `vector_search_brief` を呼び出す。
   - **SELECT 射影の制限**: `get_memory`, `get_memories_batch`, `keyword_search`, `list_by_filter` の読込系クエリについて、`select("*")` を廃止し、`embedding` カラムを除外した `_MEMORY_BRIEF_COLUMNS` 射影を強制。これにより、検索結果返却時のHTTPS通信ペイロードが劇的に削減されます。

2. **N+1クエリ問題の解消（アクセス数の一括更新）**
   - **`increment_memory_access_counts` RPC / メソッド of StorageAdapter の追加**: 検索結果として返された複数のメモリに対するアクセスカウント更新（N回のHTTPS呼び出し）を廃止し、UUIDの配列を受け取って1回のクエリで一括更新するバルクAPIを新設。
   - Postgresアダプターは `WHERE id = ANY($1::uuid[])`、SQLiteアダプターはプレースホルダー上限を考慮した `chunk_size = 997` でのバッチ処理により一括更新を保証。後処理層 `PostProcessor` では本バルクAPIへ一本化。

3. **インジェストパイプラインの事前バッチ埋め込み化**
   - **ユニークチャンクの重複排除と事前一括埋め込み**: インジェスト対象のテキストをチャンク分割した後、`_compute_memo_key` に基づいてユニークなチャンクを特定（重複排除）。これらを1回の `embed_batch` で一括して埋め込みベクトルに変換し、各チャンクコア処理（`_process_chunk`）にパイプライン伝播させる。
   - トランザクション開始前の一括埋め込み生成を徹底し、SQLite等のロック競合を防ぐとともに、無駄な個別 HTTP/推論レイテンシを削減。

4. **ローカル埋め込みスレッドプールの長寿命化とライフサイクル統合**
   - **ThreadPoolExecutor の再利用**: `LocalModelEmbeddingProvider` の `ThreadPoolExecutor` を `__init__` で一度だけ生成して使い回す。これにより、呼び出しのたびに発生していたスレッドプール生成のオーバーヘッドをゼロに抑える。
   - **Orchestrator の `dispose` カスケード**: プロセス終了時やエラー時のスレッドリークを防止するため、Orchestrator のシャットダウンシーケンスで `IngestionPipeline` および `EmbeddingProvider.close()` が確実に呼ばれ、スレッドプールが `shutdown` されるライフサイクル管理を実装。

5. **二重スタートアッププローブのキャッシュ排除**
   - **get_vector_dimension の結果キャッシュ**: 起動時に Orchestrator が行うベクトル次元チェック時の二重のデータベース問い合わせを防止するため、`SupabaseStorageAdapter.get_vector_dimension()` の初回実行結果をメンバ変数にキャッシュし、2回目以降のHTTPSラウンドトリップを即座にショートサーキットする。

6. **クライアントレベルのタイムアウト制御**
   - **`supabase_request_timeout_seconds` 設定の追加**: Supabase AsyncClientOptions に対して `postgrest_client_timeout` を明示的に設定可能とし、接続ハング時の速やかなフェイルファストと Exponential Backoff リトライを保証。

---

## 14. Dashboard Web UI

> **実装状態**: 実装済み（2026-04-14 完了）

### 14.1 概要

MCP サーバーとは独立した Read-Only 可視化ダッシュボード。記憶グラフの可視化・リアルタイムイベント監視・システム状態把握を Web UI で提供する。

**プロセス分離**: `python -m context_store.dashboard.api_server` で起動。既存 MCP サーバー（`context_store`）には影響なし。

### 14.2 アーキテクチャ

```text
┌──────────────────┐     HTTP/WS      ┌─────────────────────────┐
│  React Frontend  │ <─────────────> │  FastAPI Bridge          │
│  (Vite + TS)     │  REST + WebSocket│  (api_server.py)         │
│  frontend/       │                  │  src/.../dashboard/      │
└──────────────────┘                  └────────┬────────────────┘
                                               │ Direct import (CQRS)
                                    ┌──────────┴──────────┐
                              ┌─────▼──────┐     ┌───────▼────────┐
                              │ Storage     │     │ Graph          │
                              │ Adapter     │     │ Adapter        │
                              │ (Read-Only) │     │ (Read-Only)    │
                              └────────────┘     └────────────────┘
```

**CQRS 設計方針**: Orchestrator を経由せず、`create_storage(settings, read_only=True)` で StorageAdapter と GraphAdapter を直接取得する。Dashboard 用検索経路では必要に応じて RetrievalPipeline と EmbeddingProvider を初期化するが、IngestionPipeline は初期化しない。

**Read-Only 保証**:
- SQLite: `file:{path}?mode=ro` URI モードで接続（OS レベルで書き込み不可）
- Neo4j: `default_access_mode=READ_ACCESS` セッションのみ発行
- PostgreSQL / Supabase: read-only StorageAdapter は未実装のため、Dashboard 起動時は限定機能用の `ReadOnlyNoOpStorageAdapter` にフォールバックする。

**セキュリティ（二層）**:
1. Docker ポートフォワード: `127.0.0.1:8000:8000` でホスト外アクセスを遮断
2. アプリケーション層: `TrustedHostMiddleware` で `localhost` / `127.0.0.1` 以外を拒否

**DB 未初期化時のフェイルファスト**: MCP サーバーが一度も起動していない場合、Lifespan 内で `create_storage()` が失敗しエラーメッセージを出力して即時シャットダウンする。

### 14.3 技術スタック

| 分類 | 技術 |
|------|------|
| フロントエンド | React 18 + TypeScript + Vite |
| グラフ描画 | Cytoscape.js + cose-bilkent レイアウト |
| 状態管理 | Zustand |
| スタイリング | Tailwind CSS（ダークモード対応） |
| バックエンド API | FastAPI |
| E2E テスト | Playwright + @axe-core/playwright |

### 14.4 バックエンド API

| Method | Path | 機能 |
|--------|------|------|
| GET | `/api/stats/summary` | 統計サマリ（アクティブ/アーカイブ/総数/エッジ数/プロジェクト数） |
| GET | `/api/stats/projects` | プロジェクト別統計 |
| GET | `/api/graph/layout` | Cytoscape 形式グラフレイアウト（`limit` デフォルト 500） |
| POST | `/api/graph/{id}/traverse` | グラフトラバーサル（seed ID からの探索） |
| GET | `/api/memories/{id}` | 単一メモリ取得 |
| POST | `/api/memories/search` | メモリ検索 |
| GET | `/api/system/config` | 設定サマリ（ホワイトリスト方式） |
| GET | `/api/logs/recent` | 直近ログ取得（リングバッファ） |
| WebSocket | `/api/logs/ws` | リアルタイムログストリーミング |

### 14.5 フロントエンドページ構成

| ページ | パス | 機能 |
|--------|------|------|
| Dashboard | `/` | 統計カード（アクティブ数・エッジ数・プロジェクト等）、プロジェクト一覧 |
| NetworkView | `/network` | Cytoscape.js グラフ可視化、ノードクリック詳細パネル、上限到達警告 |
| LogExplorer | `/logs` | リアルタイムログストリーミング、severity/テキストフィルター |
| Settings | `/settings` | テーマ設定、API Base URL カスタマイズ（localStorage 永続化） |

### 14.6 グラフ表示の設計

- **ノード上限**: 500（importance スコア上位）。超過時は `GraphTruncationWarning` バナーを表示
- **ノードクリック**: `NodeDetailPanel` がスライドアウト表示（content / memoryType / importance / project）
- **色分け**: [📜 Episodic]=青（`#3B82F6`）、[🧠 Semantic]=緑（`#10B981`）、[🕒 Procedural]=黄（`#F59E0B`）
- **レイアウト**: cose-bilkent（物理ベース自動レイアウト）

### 14.7 ダークモード

- Tailwind `darkMode: 'class'` 方式
- `ThemeToggle` コンポーネントで `<html>` の `dark` クラスを切替
- `localStorage('theme')` で永続化、App.tsx の mount 時に初期化

### 14.8 E2E テスト（Playwright）

`frontend/e2e/dashboard.spec.ts` に以下のテストグループが実装済み:

| テストグループ | 内容 |
|--------------|------|
| Dashboard page | StatCard が `/api/stats/summary` のモック値を正しく描画 |
| NetworkView page | Cytoscape コンテナ表示・truncation warning 動作 |
| SPA routing | `/network`, `/logs`, `/settings` への直接アクセスが 200 を返す |
| ThemeToggle | ダークモード切替が localStorage に永続化・別ページに伝播 |
| LogExplorer | severity フィルター UI・テキスト検索フィルターの動作確認 |
| Accessibility | axe-core WCAG2A/2AA による主要 3 ページの critical 違反ゼロ確認 |

## 15. ChronosGate 連携

ChronosGate は、ChronosGraph から分離された独立リポジトリで、AI エージェントのツール実行前にセキュリティ評価（IBAC / Guardrails / LLM Evaluator）を行います。ChronosGraph 本体は ChronosGate からの記憶検索リクエストに応答する長期記憶サーバーとして振る舞います。

詳細な仕様・構築手順は [ChronosGate リポジトリ](https://github.com/yohi/chronos-gate)（※プライベートリポジトリ）を参照してください。

### 15.1 連携インターフェース

- **HTTP API**: `POST /evaluate` でツール実行前評価を受け付けます。
- **CLI**: `chronos-gate evaluate --json-io` で stdin から JSON を受け取り、stdout に Decision を返します。
- **Decision**: `"allow"`, `"deny"` (reason 必須), `"ask"` (ask_message 必須) のいずれか。

### 15.2 必要な環境変数（ChronosGraph 側）

| 変数 | デフォルト | 説明 |
|---|---|---|
| `MCP_GATEWAY_URL` | `http://127.0.0.1:9100` | ChronosGate の HTTP エンドポイント |
| `MCP_GATEWAY_API_KEY` | 未設定 | `agent_turn_hook.py` が ChronosGate へ送る API キー |
---

## 16. ロードマップ

### 16.1 実装済み（2026-05-10 時点）

| 機能 | 備考 |
|------|------|
| SQLite バックエンド（Read-Only 対応含む） | `file:...?mode=ro` URI モード実装済み |
| PostgreSQL + pgvector バックエンド | |
| Supabase (PostgREST) バックエンド | HTTPS (443) 経由、Supabase Data API 経由で動作 |
| Neo4j グラフアダプタ（READ_ACCESS 対応） | |
| Ingestion Pipeline（全 Source Adapter） | ConversationAdapter / ManualAdapter / URLAdapter |
| Retrieval Pipeline（ハイブリッド検索・RRF） | |
| Lifecycle Manager（衰退・アーカイブ・パージ） | 明示的な `memory_prune` は現行実装では SQLite バックエンドのみ実行し、PostgreSQL / Supabase ではスキップ |
| MCP 7 ツール + 2 リソース | FastMCP ベース |
| グラフトラバーサル（timeout・depth 制限） | RetrievalPipeline 内の GraphTraversal は対応。`memory_search_graph` 専用 API の `edge_types` / `depth` 反映は未実装 |
| Dashboard Web UI（バックエンド + フロントエンド） | SQLite read-only 中心。PostgreSQL / Supabase read-only は限定機能にフォールバック。§14 参照 |
| Docker Compose 統合（chronos-dashboard サービス） | `127.0.0.1:8000:8000` バインド |
| pre-commit フック（ruff / mypy / shellcheck） | |
| Playwright E2E テスト（6 テストグループ + axe-core） | |
| ChronosGate 分離 | Universal Evaluator / Permission Hook を独立リポジトリへ移管 |

### 16.2 近期予定（1-2 ヶ月）

| 機能 | 優先度 | 概要 |
|------|--------|------|
| ChronosGate: Server-defined Prompts (Hook) | High | サーバー側からエージェントのコンテキストにプロンプト（役割と利用可能ツール）を動的注入する `prompts/list`, `prompts/get` の実装。エージェント側の手動プロンプト設定の手間をゼロにし、権限設定の「最大効率」を実現する。 |
| Dashboard: 統計クエリキャッシング | Medium | `cachetools.TTLCache` 等による短 TTL（5-30 秒）インメモリキャッシュ。100k+ ノード規模での SLO 維持が目的 |
| Dashboard: メモリ検索 UI | Medium | Settings または NetworkView にメモリ検索フォームを追加（`/api/memories/search` 利用） |
| 埋め込みベクトル自動マイグレーション | Medium | プロバイダー切替時の次元数変更に対応する再埋め込みスクリプト（`scripts/migrate_dimension.py`）。現状はフェイルファスト停止のみ（v2.1 ロードマップ） |
| ベンチマーク artifact 自動化 | Low | `memory_edges` 10,000 件での depth=2/5 トラバーサルレイテンシを CI で記録 |

### 16.3 中期予定（2-4 ヶ月）

| 機能 | 概要 |
|------|------|
| Dashboard: グラフ分析 | 次数分布・クラスタ検出・Community Detection の可視化 |
| Dashboard: 時系列再生 | `created_at` フィルター × スライダー UI でグラフの時間変化を再生 |
| Dashboard: エクスポート | グラフスナップショットの PDF/画像エクスポート |
| Dashboard: 統合運用モード | `context_store --with-dashboard` で MCP + Dashboard を同居起動 |
| 概念ドリフト検出 | `CONTRADICTS` エッジの自動検出・ユーザー通知・自動統合ロジック |
| マルチプロバイダー統合強化 | LiteLLM / Custom API エンドポイントの本番安定化・テスト拡充 |

### 16.4 長期予定（6 ヶ月以上）

| 機能 | 概要 |
|------|------|
| RL 統合 | ActionLogger / RewardSignal / PolicyHook の実装。エージェントの行動ログから報酬シグナルを収集し検索戦略を強化学習で最適化 |
| マルチテナント対応 | Project isolation の強化（テナント間データ分離・権限管理） |
| 大規模最適化 | 100k+ ノード規模での Cytoscape WebWorker 化・グラフレンダリング最適化 |
| Neo4j フル統合 | Dashboard での Neo4j バックエンド接続と高度なグラフクエリ（Cypher）対応 |

### 16.5 改善課題：MCP メモリ操作タイムアウト対策（Phase 2 以降）

2026-05-26 のリモート DB（Supabase Data API）前提のボトルネック監査で抽出された改善候補のうち、Phase 1 最適化（実装完了）のスコープ外として後回しになった項目をここにトラッキングする。Phase 1 で対処済みの項目（A-1/A-2/A-3 前半/B-1/C-1/C-2/C-4）は本表からは除外している。

#### D. ChronosGate 層の改善（タイムアウト・評価レイテンシ）

| ID | 改善項目 | 影響 | 優先度 | 主要箇所 |
|----|---------|------|--------|---------|
| D-1 | `UpstreamClient.call_tool` への明示タイムアウト導入 | ChronosGate で `mcp.ClientSession.call_tool` を `asyncio.wait_for` でラップし、ツール単位のタイムアウトと `UpstreamError` への正規化を行う。 | High (実装済) | ChronosGate `src/chronos_gate/upstream/context_store_client.py` |
| D-2 | Universal Evaluator (LiteLLM) のレイテンシ最適化 | `CHRONOS_EVALUATOR_API_KEY` 設定時、read 系ツールの評価バイパス、評価結果の短 TTL キャッシュ、LLM / memory retrieve のタイムアウト管理を ChronosGate 側で行う。 | High (実装済) | ChronosGate `src/chronos_gate/policy/` |
| D-3 | 承認モードのタイムアウト調整とバイパス分類 | ChronosGate の Blocking 承認モードで read-only ツールの承認バイパスと `GatewaySettings` による承認待機タイムアウト調整を行う。 | Medium (実装済) | ChronosGate `src/chronos_gate/server.py` |

#### E. ストレージ・取り込みパイプライン層の追加改善（中〜低影響）

| ID | 改善項目 | 影響 | 優先度 | 主要箇所 |
|----|---------|------|--------|---------|
| E-1 | `IngestionPipeline._process_chunk` の並列化 (A-3 後半) | Phase 1 で全チャンクの埋め込みは `embed_batch` で一括化したが、`_process_chunk` 自体は依然として逐次。`graph_enabled=false`（Supabase 等）の場合は CHUNK 系エッジ依存が無いので `asyncio.gather` + Semaphore でチャンク間を並列化できる。grand-enabled 構成では document_id 単位での順序保証が必要。 | High (実装済) | `src/context_store/ingestion/pipeline.py:218-263` |
| E-2 | OpenAI / LiteLLM 埋め込みプロバイダのリトライ調整 (B-2) | 現在は `stop_after_attempt(5)` × `wait_exponential(min=1, max=60)` で最悪 5×60s=300s。`max=10` 程度への縮小、per-attempt timeout の短縮（10s 程度）、`Retry-After` ヘッダ尊重を導入し、Embedding バックエンドの 429/5xx でクライアント側 MCP タイムアウトを大幅超過しないようにする。 | High (実装済) | `src/context_store/embedding/openai.py:101-117`, `src/context_store/embedding/litellm.py:107-117` |
| E-3 | Supabase `keyword_search` の検索戦略改善 (C-3) | 現状は `ilike("content", "%X%")` でトリグラム索引を前提。短いクエリ（CJK 1 文字など）では planner がシーケンシャルスキャンへフォールバックする。短すぎる query の早期 return、または `to_tsvector` + GIN(tsvector) ベースの全文検索 RPC へ移行することで大規模化に備える。 | Medium | `src/context_store/storage/supabase.py:291-316`, `supabase/migrations/20260518000001_initial_schema.sql:45-46` |
| E-4 | `GraphLinker._build_semantic_edges` の `vector_search` 重複呼び出し解消 | `Postgres + Neo4j` 構成で 1 件保存ごとに dedup 用 `vector_search` と SEMANTICALLY_RELATED 用 `vector_search` が 2 回発行される。Deduplicator の結果（`similar_memories` リスト）を `GraphLinker.link()` にパススルーするか、`IngestionPipeline` 側でキャッシュして再利用する。Supabase バックエンドでは `graph_enabled=false` のため影響なし。 | Medium | `src/context_store/ingestion/graph_linker.py:106-131`, `src/context_store/ingestion/deduplicator.py:60-86`, `src/context_store/ingestion/pipeline.py:362-364` |
| E-5 | `Orchestrator.stats()` の `count_by_filter` 2 本を 1 RPC に統合 | active/archived のカウントで HTTPS 2 本発生。Supabase に `count_active_and_archived(p_project text)` RPC を追加し 1 ラウンドトリップに集約する。`head=True` で軽いが、ダッシュボード等で頻繁に呼ばれるケースで効く。 | Low | `src/context_store/orchestrator.py:394-414`, `src/context_store/storage/supabase.py:371-382` |
| E-6 | InMemoryCacheAdapter の再起動時コールドスタート解消 | `cache_backend=inmemory` だとプロセスごとに分離・再起動でキャッシュ消失。マルチプロセス・再起動耐性が必要な本番では `cache_backend=redis` を既定推奨に格上げ、または起動時の warm-up（よく使われる project の `memory_search` を 1 度実行）を導入する。 | Low | `src/context_store/storage/inmemory.py`, `src/context_store/storage/factory.py:251-269` |
| E-7 | ローカル埋め込みモデルの eager preload（MCP lifespan 連携） | Phase 1 では `LocalModelEmbeddingProvider.start()` を追加したが、Orchestrator は lazy 初期化のため auto-invoke しても初回ツール呼び出しの cold-start を実質削減できない。FastMCP の `lifespan` 起動フックで `EmbeddingProvider` を eager 構築・`start()` し、`ChronosServer._do_initialize` が再構築せず既存インスタンスを再利用する設計に切り替えれば、初回呼び出しのレイテンシからモデルロード時間（ruri-v3-310m で 5-10 秒）を完全に外せる。 | Medium | `src/context_store/server.py`, `src/context_store/orchestrator.py:474-611`, `src/context_store/embedding/local_model.py` |

---

## 17. Transactional Outbox Sync (非同期グラフ同期)

### 17.1 目的とアプローチ

ChronosGraph では、エージェントの応答レイテンシ向上と、Storage Layer (PostgreSQL/SQLite/Supabase) と Graph Layer (Neo4j) 間のトランザクション原子性（Atomicity）を保証するため、**Transactional Outbox Pattern** を採用する。

`GRAPH_SYNC_MODE` 環境変数に `"async_outbox"` を指定した場合、Storage Layer への書き込みと同一トランザクション内で Outbox テーブル (`graph_sync_outbox`) にイベントを記録し、バックグラウンドの `OutboxWorker` が非同期に Neo4j へバルク同期する。

#### Config 拡張とバリデーション

`Settings` クラス（`src/context_store/config.py`）に以下の設定が追加され、相関バリデーションが行われる。

- `graph_sync_mode`: グラフ同期モード (`"sync"` または `"async_outbox"`)。デフォルトは `"sync"`。
- `outbox_poll_interval_seconds`: ポーリング間隔（デフォルト: 5.0秒）
- `outbox_batch_size`: 1バッチの処理イベント数（デフォルト: 100）
- `outbox_max_retries`: 最大リトライ回数（デフォルト: 10）
- `outbox_backoff_base_seconds`: Exponential Backoff のベース待機秒数（デフォルト: 1.0秒）
- `outbox_backoff_max_seconds`: Exponential Backoff の最大待機秒数（デフォルト: 60.0秒）

**相関バリデーションルール:**
1. `graph_sync_mode == "async_outbox"` の場合、`graph_enabled == true` が必須。
2. `storage_backend == "supabase"` かつ `graph_enabled == true` の場合、`graph_sync_mode == "async_outbox"` が必須（Supabase 環境では Neo4j Bolt プロトコルの直接接続をブロックするファイアウォール制約を回避するため）。

### 17.2 データモデル

`graph_sync_outbox` テーブル構造:

| カラム | PostgreSQL / Supabase 型 | SQLite 型 | 説明 |
|---|---|---|---|
| `id` | UUID PK | TEXT PK | イベント一意識別子 |
| `event_type` | VARCHAR(20) CHECK | TEXT CHECK | `SYNC_MEMORY` / `DELETE_MEMORY` |
| `memory_id` | UUID | TEXT | 対象メモリ ID（外部キー制約は不適用） |
| `payload` | JSONB DEFAULT '{}' | TEXT DEFAULT '{}' | `DELETE_MEMORY` 時のメタデータなど |
| `status` | VARCHAR(20) DEFAULT 'PENDING' | TEXT DEFAULT 'PENDING' | `PENDING` / `PROCESSING` / `FAILED` |
| `retry_count` | INT DEFAULT 0 | INTEGER DEFAULT 0 | リトライ回数 |
| `next_retry_at` | TIMESTAMPTZ | TEXT (ISO8601) | 次回リトライ可能時刻（Backoff 永続化） |
| `error_message` | TEXT NULL | TEXT NULL | 最後のエラーメッセージ |
| `created_at` | TIMESTAMPTZ | TEXT (ISO8601) | 作成日時 |
| `updated_at` | TIMESTAMPTZ | TEXT (ISO8601) | 最終更新日時 |

**インデックス:**
- `idx_outbox_status_retry`: `(status, next_retry_at ASC)` — ワーカーの PENDING フェッチ高速化用
- `idx_outbox_memory_id`: `(memory_id)` — 運用/調査クエリ用

#### 外部キー（FK）制約を適用しない理由
`DELETE_MEMORY` イベント処理時に、すでに Storage 上のメモリは削除されている。FK制約があると `memories` 削除に伴い Outbox レコードもカスケード削除され、ワーカーが Neo4j 側のノード削除（`DETACH DELETE`）を実行できなくなるため、あえて FK 制約は適用しない。

#### OutboxWriter / OutboxReader プロトコル

同期処理の結合度を下げるため、書き込み用および読み込み用のインターフェースを Protocol として定義する。

**OutboxWriter (`src/context_store/sync/outbox_writer.py`):**
```python
class OutboxWriter(Protocol):
    async def enqueue_sync(
        self,
        conn: Any,
        memory_id: str,
        event_type: str,
        payload: dict | None = None,
    ) -> None:
        """Storage の同一トランザクション内で Outbox イベントをエンキューする"""
        ...
```

**OutboxReader (`src/context_store/sync/outbox_reader.py`):**
```python
class OutboxReader(Protocol):
    async def fetch_pending(self, limit: int) -> list[OutboxEvent]:
        """PENDING 状態のイベントを limit 件フェッチし、PROCESSING に遷移させる"""
        ...

    async def delete_completed(self, event_ids: list[str]) -> None:
        """処理完了したイベントを物理削除する"""
        ...

    async def mark_failed(self, event_id: str, error_message: str) -> None:
        """リトライ上限に達したイベントを FAILED 状態にし、エラーログを記録する"""
        ...

    async def reset_to_pending(
        self,
        event_id: str,
        retry_count: int,
        next_retry_at: datetime,
        error_message: str,
    ) -> None:
        """リトライ対象のイベントを PENDING に戻し、次回リトライ時刻と Backoff カウントを更新する"""
        ...

    async def fetch_all_actionable(self) -> list[OutboxEvent]:
        """リカバリスクリプト向けに、PENDING / FAILED / PROCESSING の全イベントをフェッチする"""
        ...

    async def reset_stuck_processing(
        self,
        threshold_seconds: int = 300,
        max_retries: int = 10,
    ) -> int:
        """スタックした PROCESSING イベントを検出し、リセットまたは FAILED 遷移を行う"""
        ...
```

### 17.3 状態の収束契約（Deduplication at Convergence）
同一 `memory_id` に対する複数の `SYNC_MEMORY` イベントが Outbox に並存することを許容する。ワーカーはイベント処理時に Storage から**現時点の最新レコード**をバッチ取得し、Neo4j 側に `UNWIND + MERGE` することによって状態を収束させる。UNIQUE 制約 + UPSERT は PROCESSING との競合や FAILED の残骸との衝突による副作用があるため採用しない。

### 17.4 ワーカーの動作仕様と対障害性

1. **フェッチとアトミックな状態遷移**:
   - `OutboxReader.fetch_pending` により、`next_retry_at <= NOW()` である `PENDING` レコードを取得。
   - 二重処理を防ぐため、フェッチと同時にステータスを `PROCESSING` に更新する（Postgres/Supabase は `FOR UPDATE SKIP LOCKED`、SQLite は `BEGIN IMMEDIATE` + ループ内 UPDATE を使用）。
2. **バルク同期**:
   - `SYNC_MEMORY` イベント: `StorageAdapter.get_memories_batch()` で最新メモリ状態を取得。存在しないものは "orphan"（孤児）として扱い同期せず Outbox から削除。存在するメモリを `GraphSyncService.bulk_merge_memories()` により Neo4j に一括 MERGE。
   - `DELETE_MEMORY` イベント: `GraphSyncService.bulk_delete_nodes()` により Neo4j 側のノードを `DETACH DELETE`。
   - 成功したイベントは `delete_completed()` により Outbox から物理削除。
3. **Exponential Backoff**:
   - Neo4j 接続失敗時、`min(base * (2^retry_count), max)` 秒のバックオフを計算し、`next_retry_at` に設定して status を `PENDING` に戻す。
   - `retry_count` が上限（デフォルト: 10）を超過した場合は `FAILED` に移行。
4. **クラッシュからのリカバリ**:
   - ワーカー起動時、`reset_stuck_processing(threshold_seconds=300)` を実行し、`updated_at` が閾値を超えて `PROCESSING` のままスタックしているレコードを `PENDING`（リトライ回数上限を超えている場合は `FAILED`）に復旧させる。

#### 読み取りフォールバックとログ出力仕様

`async_outbox` モードの特性上、メモリ保存からグラフ反映までに数秒の遅延（ラグ）が生じる。このラグの間、`RetrievalPipeline.search()` における `GraphTraversal` が空（0件）の結果を返した場合、システムは以下の INFO ログを出力して、VectorSearch + KeywordSearch の RRF 融合で結果を補完する。

```text
Graph traversal returned empty results; outbox sync lag may be a factor.
Falling back to vector+keyword fusion.
```

### 17.5 Supabase 向け RPC 制御と DDL

Supabase（PostgREST）を使用する場合、アプリケーションクライアントからトランザクションの直接制御（`BEGIN/COMMIT` などのアドホックなトランザクション境界）を行うことができない。そのため、データベースの原子性（Atomicity）を保証する以下のPL/pgSQL RPC関数を定義・利用する。

#### RPC 1: `upsert_memory_with_outbox`
- **目的**: メモリのインサート（衝突時は `UPDATE`）と、同一トランザクション内での `SYNC_MEMORY` イベントの Outbox 挿入をアトミックに実行する。
- **引数**:
  - `p_id` UUID, `p_content` TEXT, `p_memory_type` VARCHAR, `p_source_type` VARCHAR, `p_source_metadata` JSONB, `p_embedding` vector(768), `p_semantic_relevance` FLOAT, `p_importance_score` FLOAT, `p_tags` TEXT[], `p_project` TEXT, `p_content_hash` TEXT
- **戻り値**: 挿入された `UUID`。

#### RPC 2: `delete_memory_with_outbox`
- **目的**: メモリレコードを削除し、削除したレコードのメタデータ（`memory_type`, `tags`, `project`）を payload に含む `DELETE_MEMORY` イベントを Outbox にアトミックに記録する。
- **引数**: `p_memory_id` UUID
- **戻り値**: 削除に成功したか（`BOOLEAN`）。

#### RPC 3: `fetch_pending_outbox`
- **目的**: `PENDING` 状態のイベントを安全に一括フェッチしつつ、他ワーカーとの多重処理を避けるため、アトミックに `PROCESSING` に状態遷移させる。内部で `FOR UPDATE SKIP LOCKED` を含む `UPDATE ... RETURNING` クエリを使用する。
- **引数**: `p_limit` INT
- **戻り値**: 状態更新された `graph_sync_outbox` レコードのセット。

#### RPC 4: `reset_stuck_processing_outbox`
- **目的**: 起動時リカバリ用。一定時間 `PROCESSING` のまま更新がないスタックしたイベントを抽出し、リトライ上限超過なら `FAILED`、未満なら `retry_count` をインクリメントした上で `PENDING` にリセットする。
- **引数**: `p_threshold_seconds` INT, `p_max_retries` INT
- **戻り値**: 復旧処理したレコード件数（`INT`）。

### 17.6 リカバリ・管理コマンドラインツール

データベースと Neo4j Aura の不整合を手動で解消・修復するため、以下の管理コマンドラインツールを配置する。

- **ファイル**: `scripts/sync_storage_to_neo4j.py`
- **インターフェース**:
  ```bash
  uv run python scripts/sync_storage_to_neo4j.py [--full | --catchup] [--chunk-size N] [--dry-run] [--yes]
  ```
- **実行モード**:
  - `--full`: Storage Layer に存在するすべてのメモリ・関係性情報をフルスキャンし、Neo4j 側に一括再構築（UNWIND + MERGE）する。メモリ枯渇・タイムアウト防止のため、`--chunk-size`（デフォルト 1000）でページネーションを行う。
  - `--catchup`: `OutboxWorker` がポーリングするのと同じロジックで、Outbox 内のすべての未完了イベント（`PENDING`/`FAILED`、およびスタックしている `PROCESSING` イベント）を1回限り同期実行し、残存イベントを回収・クリーンアップする。
  - `--dry-run`: 実際に Neo4j や Outbox に変更を適用せず、同期対象となる件数のみを出力する。

#### `--full` モードの制約とダウンタイム

`--full` モードは `MATCH (m:Memory) DETACH DELETE m` で Neo4j 側の全ノードをパージしてから再構築するため、実行中は一時的にグラフ検索が空の結果を返す状態が発生する。これに伴い、以下の運用制約を厳守すること。

- **通常運用中の実行禁止**: データ破損からの復旧やスキーマ変更など、メンテナンス窓口内での実行を必須とする。
- **事前承認プロンプト**: `--dry-run` で事前に処理件数を確認した上で実行する。`--yes`（非対話フラグ）が指定されていない場合は、オペレータに確認プロンプトを提示して承認を得ること。
- **実行ログ記録**: 処理の開始時刻、終了時刻、処理件数を必ず `INFO` レベルのログに残すこと。
- **差分再同期の将来計画**: ダウンタイムのない再同期（Storage と Neo4j の ID 集合の差分を取り、差分のみを MERGE/DELETE する機能）として、将来的に `--reconcile` モードの追加を検討する（本リリースには含まない）。

### 17.7 マイグレーションベースラインへの統合

SQLite および PostgreSQL でマイグレーションを適用する `MigrationRunner`（`src/context_store/storage/migrations/runner.py`）において、既存のデータベースに Outbox テーブルを適用するために、ベースライン要件マッピングに `0003` を追加している。

```python
"0003": ["graph_sync_outbox"]
```

これによって、移行前の既存 DB は安全にスキップされつつ、テーブルが存在しない場合は `0003_graph_sync_outbox.sql` が自動的に適用される。

---

## 18. 開発・テストサンドボックス (OpenSandbox)

> **実装状態**: 実装済み（Phase 1 & 2 完了、2026-06-07）

### 18.1 概要

[OpenSandbox](https://github.com/opensandbox-group/OpenSandbox) を導入し、AIエージェント（Gemini / OpenCode 等）がテスト・静的解析を実行する際に、セキュアで使い捨て（Ephemeral）なサンドボックス環境を利用できるようにする。テスト・Lint は人間の Devcontainer 内では実行せず、必ず OpenSandbox 上で実行する。

| 項目 | 内容 |
|---|---|
| フェーズ1 | 静的解析（ruff / mypy / tsc / eslint）と DB 非依存の単体テストを `lite` サンドボックスで実行 |
| フェーズ2 | 結合テスト（Postgres / Neo4j / Redis 依存）を `integration` サンドボックスから Devcontainer の DB サービスへ接続して実行 |
| スコープ外 | Phase 3（E2E / Heavy Dockerfile / Headless Chrome）、MCP Gateway へのサンドボックスツール統合、Kubernetes ランタイム、CI/CD パイプライン統合 |

**設計判断:**

| 決定事項 | 選択 | 理由 |
|---|---|---|
| アプローチ | 薄いラッパースクリプト + 宣言的プロファイル | シンプル・段階的拡張が可能 |
| Python | 3.12 | `pyproject.toml` の `requires-python = ">=3.12"` に準拠 |
| フロントエンド PM | pnpm | npm → pnpm 移行を含む |
| ランタイム | Docker（ローカル） | Kubernetes は将来スコープ |
| 利用者 | AIエージェント | OpenSandbox Python SDK 経由でプログラマティックに操作 |

### 18.2 実行フロー

```text
(Host) AI Agent
  └─ scripts/sandbox_runner.py
       └─ OpenSandbox Python SDK (SandboxSync)
            └─ OpenSandbox Server (Docker Runtime, 127.0.0.1:8090)
                 └─ Lite Pool (warm standby): python:3.12 + uv + pnpm
```

1. AIエージェントが lint / テスト実行を指示する
2. `sandbox_runner.py` がコマンド文字列からプロファイルを判定（lite / integration）
3. SDK で Lite Pool からサンドボックスを取得（または新規作成）
4. 依存インストール（`uv sync` / `pnpm install`）後にコマンドを実行
5. 標準出力 / 標準エラーをホストへ転送し、終了コードを伝播（None → 1 のフェイルセーフ）
6. サンドボックスを破棄（Stateless 原則）

### 18.3 プロファイルルーティング

`scripts/sandbox_runner.py` の `resolve_profile()` がコマンド文字列からプロファイルを自動選択する。

| Task | Profile | DB 接続 | Egress |
|---|---|---|---|
| `ruff` / `mypy` / `tsc` / `eslint` | `lite` | なし | pypi.org, npmjs.org |
| `pytest tests/unit/` | `lite` | In-memory SQLite | pypi.org |
| `pytest tests/integration/` | `integration` | Postgres / Neo4j / Redis | pypi.org + DB ホスト |

ルーティング規則（先頭一致優先、未一致時は `lite`。`--profile` 明示指定は正規表現より優先）:

```python
ROUTING_RULES = [
    (r"tests/integration", "integration"),
    (r"\btest_postgres\b", "integration"),
    (r"\btest_neo4j\b",    "integration"),
    (r"\btest_redis\b",    "integration"),
]
DEFAULT_PROFILE = "lite"
```

### 18.4 サンドボックスインフラ

| ファイル | 役割 |
|---|---|
| `.devcontainer/opensandbox/lite.Dockerfile` | Lite イメージ定義 |
| `.devcontainer/opensandbox/sandbox.yaml` | プロファイル定義（lite / integration） |
| `docker-compose.yml` の `opensandbox` サービス | OpenSandbox サーバー（`sandbox` プロファイル） |

**Lite イメージ（`lite.Dockerfile`）の要点:**

- ベース: `python:3.12-slim` + マルチステージ `node:22.11.0-slim`（`curl | bash` を排除）
- バージョン固定: `uv 0.5.0`、Node.js 22 LTS、`pnpm 9.15.4`（corepack 経由）
- ビルドツール非搭載（`build-essential` / `git` / `gcc` なし）
- 非 root ユーザー `sandbox`（UID 1000）
- venv: `UV_PROJECT_ENVIRONMENT=/tmp/.venv`（Ephemeral、権限問題を回避）
- `USER sandbox` 切替の前後で `uv / uvx / node / npm / pnpm` のバージョン検証を二重実行

**`sandbox.yaml` プロファイル定義の要点:**

- `lite`: リソース上限 `cpu: 2` / `memory: 2Gi`、`timeout: 300`（5 分でサーバーが強制回収）、プール設定 `min_ready: 1` / `max_instances: 3` / `idle_timeout: 600`、egress 許可 `pypi.org` / `files.pythonhosted.org` / `registry.npmjs.org`
- `integration`: `lite` を継承（`extends: lite`。コンテナイメージも `lite` を再利用する）。egress に DB ホスト（既定 `host.docker.internal`）を追加し、`POSTGRES_*` / `NEO4J_USER` / `NEO4J_PASSWORD` / `REDIS_URL` を環境変数として定義
- NEO4J は本体 Settings（`src/context_store/config.py`）が `NEO4J_USER` / `NEO4J_PASSWORD` を個別に読むため、結合形式の `NEO4J_AUTH` ではなく分割して渡す
- フォールバック既定値（`dev_password` 等）はローカル開発専用。CI / 本番環境では `TEST_DB_PASSWORD` 等を必ずオーバーライドする

**docker-compose `opensandbox` サービス:**

- `image: opensandbox/opensandbox-server:latest`、`profiles: [sandbox]`（`docker compose --profile sandbox up opensandbox` が必要）
- `/var/run/docker.sock` をマウント（DinD によるコンテナ管理）
- `127.0.0.1:8090:8080` バインド（ローカルアクセスのみ）

> **二重定義の注意（sandbox.yaml ⇔ sandbox_runner.py）**: `sandbox_runner.py` は egress ルールと DB 環境変数を SDK パラメータ（`build_network_policy()` / `build_profile_env()`）として直接渡し、`SandboxSync.create()` 時にサーバー側プロファイルを実行時オーバーライドする。`sandbox.yaml` の値は直接 API 利用や手動 `docker compose` 起動時のサーバー側デフォルトとして機能する。DB 接続・egress 設定を変更する際は `sandbox.yaml` と `sandbox_runner.py` の両方を更新して同期を保つこと。

### 18.5 サンドボックスランナー (`scripts/sandbox_runner.py`)

Gateway 実装に依存しない ChronosGraph 用スタンドアロンスクリプト。プロファイル自動選択・依存インストール・コマンド実行・破棄のライフサイクルを一元管理する。

```bash
# プロファイル自動判定
python scripts/sandbox_runner.py -- uv run ruff check src/ tests/
python scripts/sandbox_runner.py -- uv run pytest tests/unit/ -v
python scripts/sandbox_runner.py -- uv run pytest tests/integration/ -v

# 明示指定
python scripts/sandbox_runner.py --profile integration -- uv run pytest tests/integration/ -v

# フロントエンド
python scripts/sandbox_runner.py -- bash -c "cd frontend && pnpm install && pnpm lint"
```

**主要関数:**

| 関数 | 役割 |
|---|---|
| `resolve_profile()` | `--profile` 明示 > `ROUTING_RULES` 正規表現 > `lite` の順でプロファイル決定 |
| `normalize_command()` | bare ツール（`ruff` / `mypy` / `pytest`）を `uv run` 前置で仮想環境解決 |
| `install_dependencies()` | コマンドに応じ `uv sync --frozen --all-extras` / `pnpm install --frozen-lockfile` を実行。失敗時は `RuntimeError` |
| `build_profile_env()` | `OPENSANDBOX=1` を常時設定。`integration` 時は DB 接続環境変数を追加し `_validate_db_host_consistency()` を実行 |
| `build_network_policy()` | egress allowlist を構築。`integration` 時は DB ホストを追加 |
| `_validate_db_host_consistency()` | `integration` の全 DB ホスト（Postgres / Neo4j / Redis）が単一ホストを指すことを検証。不一致時は `ValueError` |
| `setup_sandbox()` | プール枯渇時に指数バックオフで最大 2 回リトライしてサンドボックス取得 |
| `execute_in_sandbox()` | `RunCommandOpts(envs={"OPENSANDBOX": "1"})` でコマンド実行・出力転送・終了コード伝播 |
| `teardown_sandbox()` | `sandbox.kill()` で破棄（失敗してもエラーを握りつぶす） |

**OPENSANDBOX=1 の二重設定（belt-and-suspenders）**: ランナーは全実行（lite / integration 両方）で `OPENSANDBOX=1` を保証する。設定箇所は 2 点 — (1) コンテナ生成時 `build_profile_env()` → `SandboxSync.create(env=...)`、(2) コマンド実行時 `RunCommandOpts(envs=...)`。これによりコンテナの entrypoint の環境変数継承方法に依存せず、Phase 2 のテストフック（§18.6）が確実に発火する。

**エラーハンドリング**: プール枯渇は指数バックオフ（最大 2 回）／タイムアウトは `sandbox.yaml` の `timeout: 300`（5 分でサーバーが強制回収）／`SIGTERM`・`SIGINT` で `teardown_sandbox` 実行／`finally` で破棄を保証。

### 18.6 Phase 2: 結合テストの標準化

**SQLite 一時パス切替（`tests/conftest.py`）:**
`_sandbox_aware_sqlite`（autouse fixture）が `OPENSANDBOX=1` のときのみ `SQLITE_DB_PATH` を一時ディレクトリへ切り替える。

```python
@pytest.fixture(autouse=True)
def _sandbox_aware_sqlite(tmp_path, monkeypatch, sandbox_aware_sqlite_env):
    if os.environ.get("OPENSANDBOX") == "1":
        monkeypatch.setenv("SQLITE_DB_PATH", str(tmp_path / "test.db"))
```

- SQLite バックエンドは記憶・内部グラフを単一ファイル（`Settings.sqlite_db_path`）に保存するため、`SQLITE_DB_PATH` のみ設定する（`SQLITE_GRAPH_PATH` は存在せず no-op のため設定しない）。
- `tests/unit/conftest.py::clean_env` は `OPENSANDBOX=1` のとき `sqlite_db_path` の削除をスキップし、autouse fixture の実行順序に依存せずパス切替が保持される。

**DB 接続（`integration` プロファイル）:**
サンドボックスは `host.docker.internal`（Docker ブリッジゲートウェイ）経由で Devcontainer の DB へ接続する。Devcontainer 側は既にホストへポート公開済み（Postgres `5435:5432` / Neo4j `7474`,`7687` / Redis `6379`）。`build_profile_env()` が `POSTGRES_*` / `NEO4J_*` / `REDIS_URL` を設定し、`Settings`（`env_prefix=""`）が直接読み取る。

**テスト DB 分離（`docker/postgres/`）:**
開発 DB（`context_store`）の汚染を防ぐため、テスト専用 DB `context_store_test` を用意する。静的 SQL（`init.sql`）は `TEST_DB_NAME` 環境変数を読めないため、`init.sql` は拡張作成のみに留め、DB 作成 + スキーマ適用は `docker/postgres/zz-apply-schema.sh`（`zz-` 接頭辞で初期化時に最後に実行）へ委譲する。

```bash
# zz-apply-schema.sh（抜粋）
apply_schema "${POSTGRES_DB:-context_store}"
ensure_database "${TEST_DB_NAME:-context_store_test}"   # CREATE DATABASE + GRANT
apply_schema "${TEST_DB_NAME:-context_store_test}"
```

- Neo4j: Community Edition の単一 DB のため、テストの setup/teardown でクリーンアップ（既存パターン）。
- Redis: `SELECT 1`（DB 番号 1）で開発データ（DB 番号 0）から分離。

**Egress 制御（`integration`）:** `pypi.org` / `files.pythonhosted.org` / `host.docker.internal` のみ許可し、それ以外の外向き通信はすべてブロックする。

### 18.7 pnpm 移行

フロントエンドのパッケージマネージャを npm から pnpm へ移行済み:

- `frontend/package-lock.json` を削除し `frontend/pnpm-lock.yaml` を生成（`pnpm import`）
- `frontend/.npmrc` に `shamefully-hoist=true`（React / Vite 互換性）
- `frontend/playwright.config.ts` の `command: 'npm run dev'` → `'pnpm dev'`
- `package.json` の scripts は変更不要（pnpm は npm scripts をネイティブ実行）

### 18.8 制約

1. **実行隔離**: テスト・Lint は人間の Devcontainer 内で実行しない。常に OpenSandbox を使用する。
2. **依存管理**: バックエンドは `uv` 専用（`pip` は使わない）。フロントエンドは `pnpm`。
3. **Statelessness**: Lite コンテナは状態を持たない。破棄は `finally` + シグナルハンドラ + サーバータイムアウトで保証する。
4. **依存の分離**: ChronosGraph は ChronosGate に依存しない。ランナーは `scripts/` 配下のスタンドアロンスクリプト。
5. **Docker socket セキュリティ**: `/var/run/docker.sock` マウントは Docker API への完全アクセスを許可しホスト権限昇格リスクがあるため、`sandbox` プロファイル + `127.0.0.1` バインドに限定する。ローカル開発専用で、本番・共有環境では有効化しない。
6. **単一 DB ホスト**: 結合テストの全 DB サービス（Postgres / Neo4j / Redis）は単一ホスト（既定 `host.docker.internal`）経由で到達可能であること。複数ホストへ分割する場合は `sandbox.yaml` の `egress.allow` 更新が必要（§18.6）。

**関連ファイル一覧:**

| ファイル | 役割 |
|---|---|
| `.devcontainer/opensandbox/lite.Dockerfile` | Lite サンドボックスイメージ |
| `.devcontainer/opensandbox/sandbox.yaml` | プロファイル定義（lite / integration） |
| `docker-compose.yml`（`opensandbox` サービス） | OpenSandbox サーバー（sandbox profile） |
| `docker/postgres/init.sql` / `zz-apply-schema.sh` | テスト DB `context_store_test` 作成 |
| `scripts/sandbox_runner.py` | サンドボックスランナー（ルーティング + ライフサイクル） |
| `tests/conftest.py` / `tests/unit/conftest.py` | `OPENSANDBOX` 対応 SQLite パス切替 |
| `tests/unit/test_sandbox_runner.py` / `test_conftest_sandbox.py` | ユニットテスト |
| `pyproject.toml` | `opensandbox>=0.1.0`（dev 依存） |

---

## 19. Agent Skills Distribution (Agent 資産同期)

### 19.1 目的

Save / Recall の記憶運用ルールを、常時 context を消費する system prompt の手動コピーから、必要時にロードする global Agent Skills へ一本化する。リポジトリ内の `agent-assets/` を SSOT とし、`scripts/bootstrap.sh` が内部 CLI `scripts/sync_agent_assets.py` に委譲して導入・同期・検証・ロールバックまでを完結させる。

- 対応 Agent: `claudecode` / `codex` / `opencode`（公式の global 設置経路が確立した Agent のみ）
- 対象外: Cursor CLI / Antigravity への配布、ユーザー管理資産の自動削除・自動 migration（非破壊検出と warning は対象）
- 非破壊契約: 既存 instructions の marker 外は byte-for-byte 保持、他 Skills は変更しない
- 詳細な運用規則は各 `SKILL.md` が唯一の SSOT とする。Recall は task start / prior-work 参照 / 既知解決があり得る error / convention decision での project-scoped 検索、結果の可視化、current state への grounding を維持する。Save は `selective` での完了・failure-to-success trigger、Semantic / Procedural 形式、自律的な `memory_save`、8,000 文字時の `session_flush` を維持する。
- この配布レイヤーは `memory_save`、`memory_search`、`session_flush` の API・発火 semantics、`CHRONOS_INGESTION_MODE` の意味、turn-end ingestion の payload / 送信処理、storage / retrieval engine、既存の Cursor / Antigravity payload parser を変更しない。

### 19.2 Repository SSOT (`agent-assets/`)

```text
agent-assets/
├── minimal-instructions.md          # render token テンプレート
└── skills/
    ├── chronos-memory-recall/
    │   ├── SKILL.md
    │   └── .chronosgraph-managed    # 所有 sentinel
    └── chronos-memory-save/
        ├── SKILL.md
        └── .chronosgraph-managed
```

- sentinel は正確に `owner=chronosgraph\nformat=1\n`（28 bytes）。形式不一致は所有と推定せず collision として扱う。
- `minimal-instructions.md` は render token `{{BUNDLE_SHA256}}` / `{{INGESTION_MODE}}` / `{{SAVE_MODE_RULE}}` を保持し、同期時にすべて置換する。token のまま対象へ配置しない。
- 旧 `docs/agent-prompts/` 配下の system prompt template は削除済み。legacy 検出器の regression 用 fixture のみ `tests/fixtures/agent_assets/` に保持し、runtime は読まない。

### 19.3 対応 Agent と配置先

| Agent ID | Global Skills root | Global instructions | Approved instructions root |
|---|---|---|---|
| `claudecode` | `~/.claude/skills/` | `~/.claude/CLAUDE.md` | `~/.claude/` |
| `codex` | `~/.agents/skills/` | `${CODEX_HOME:-~/.codex}/AGENTS.md` | `${CODEX_HOME:-~/.codex}/` |
| `opencode` | `~/.config/opencode/skills/` | `~/.config/opencode/AGENTS.md` | `~/.config/opencode/` |

配置先は `scripts/agent_assets/models.py` の adapter table が唯一の定義源。Codex のみ `CODEX_HOME` 環境変数で instructions root を上書きできる（Skills root は常に `~/.agents/skills/`）。正式対応外 Agent への fallback prompt / asset 配布は行わない。将来 Agent は公式 global paths と自動検証方法が確定してから adapter に追加する。

### 19.4 Bundle digest と managed block render

- SSOT 配下の全 regular file を relative POSIX path 昇順でソートし、各 file について `8-byte big-endian path 長 + path bytes + 8-byte big-endian content 長 + content bytes` を順に SHA-256 へ入力する（長さプレフィックス方式）。SSOT 内の symlink と未定義 file type は validation error。
- digest と期待 block は毎回 SSOT から再計算し、利用者側コピーを入力にしない。digest は SSOT 整合判定専用で、外部互換性を持たない。
- render 済み block は `chronosgraph-bundle` metadata comment に bundle SHA-256 と ingestion mode を記録する。render token は対象へ残してはならない。
- `SAVE_MODE_RULE` は mode 固定文言:

```text
selective: In selective mode, load and follow `chronos-memory-save` when its save trigger applies.
all: In all mode, do not call `memory_save` or `session_flush`; turn-end ingestion owns saving.
```

### 19.5 所有境界

- instructions は marker pair（`<!-- BEGIN CHRONOSGRAPH MANAGED: agent-memory -->` 〜 `<!-- END CHRONOSGRAPH MANAGED: agent-memory -->`）で囲まれた範囲のみ所有する。0 組（新規作成）または 1 組のみ許可し、重複・片側欠損・順序逆転は write 前 error。新 target bytes は常に `prefix + rendered block + suffix` として構築する。
- Skill は同名 directory が正確な sentinel を含む regular file を持つ場合のみ所有。未存在なら create、sentinel 無し・非 regular・内容不一致は collision として拒否。
- Skills root 配下の非所有 entry（他のユーザー管理 Skills を含む）は relative path / `lstat` type / fingerprint（regular file は content SHA-256、symlink は link target bytes、directory は構造的存在）で snapshot し、apply 前後で一致を要求する。unsupported special file は preflight collision。所有 Skill 配下の非 SSOT entry は staging 複製によって保持され、snapshot 検証対象外である（§19.8）。

### 19.6 Preflight（write 前に全対象を検証し、部分更新を許さない）

1. **instructions symlink**: 既存親 directory の symlink、broken、cyclic（ELOOP）、解決先が承認 root 外、non-regular target はすべて preflight error。root 内 leaf symlink は symlink 自体を保持したまま、解決先の regular file を更新対象とする。shared instructions symlink は初期実装では未サポートであり、検出時は collision とする。shared root を許可する将来変更には明示的な opt-in と承認済み root の指定を要する。
2. **legacy prompt 検出**: 安定 heading + versioned byte 長 + SHA-256 の fingerprint をメモリ内で照合し、prompt 本文は出力しない。
   - `selective`: Save / Recall とも手動削除を促す warning のみで継続。
   - `all`: legacy Save は preflight collision として全 write・hook setup 前に拒否（Recall は warning のみ）。legacy Save が残る `selective` → `all` 切替は必ず拒否され、手動削除後の再実行でのみ進行する。
3. **OpenCode `all` hook config**: `opencode.jsonc` / `oh-my-opencode.jsonc` が存在する場合は collision（strict JSON writer は書き換えない）。`opencode.json` 未存在なら plugin のみの minimal JSON を作成、存在すれば `plugin` 配列へ `@yohi/opencode-plugin-chronos-turn-end` を一度だけ追加し、他 key を保持する。

1 対象でも失敗した場合（marker 重複・SSOT 破損・collision 等）は全対象を無変更のまま終了する。

### 19.7 OpenCode `all` モードの registry 前提条件（production のみ）

- 前提: ユーザー所有の `~/.npmrc` が `@yohi:registry=https://npm.pkg.github.com` マッピングと非空の `//npm.pkg.github.com/:_authToken`（`${ENV_VAR}` 参照可）を持つこと。`.npmrc` / `bunfig.toml` / token を create・rewrite・log・persist しない。
- GitHub Packages の package metadata を read-only probe し、401/403 は `registry-probe-access`、その他のネットワーク系 failure は `registry-probe-network`、credential 不備は `registry-probe-credential` として `PluginRegistryPrerequisiteError` で preflight 拒否する。diagnostic に token 値・response body・credential path は含めない。
- dry-run では probe を実行しない（オフライン dry-run を可能にする意図的な例外。network I/O は同期対象の状態検証に含めない）。
- 現行実装の credential 解決源は `~/.npmrc` のみ。Bun 固有の `bunfig.toml` precedence 解決は将来拡張とする。

### 19.8 Transaction（production apply）

適用順序: journal 生成（private temp directory）→ preflight 状態の再検証（TOCTIU 対策）→ Skills / instructions の適用 → hook artifacts（wrapper / `opencode.json`）→ post-write verification → commit。

- **wrapper**: canonical set が `claudecode` または `codex` を含む `all` モードでのみ `scripts/chronos-turn-hook.sh`（Windows は `.cmd`）を作成。2 行目に管理 marker（`# chronosgraph-managed: turn-hook-wrapper format=1` / Windows は `rem ...`）を要求し、marker 無き同名 wrapper は hook collision。interpreter は local `.venv` → `uv` → `python` の順で `scripts/agent_turn_hook.py` を呼ぶ。`scripts/agent_turn_hook.py` 自体は変更しない。
- **Skill**: 対象 parent 内の staging に既存 target を snapshot どおり複製し、`SKILL.md` と `.chronosgraph-managed` のみ SSOT から置換してから atomic swap。
- **instructions**: 同一 directory の temporary file へ permission 保持で書き atomic replace。未存在なら作成する。
- journal 生成後の全例外は rollback を 1 回実行してから `ApplyError` として報告。`build_bundle` / preflight 失敗は journal 生成前に発生するため rollback しない。
- rollback は逆順で実行し、preflight snapshot と現在値が一致する owned path のみ復元。外部変更があった path は触れず backup artifact を保持して報告する。今回作成した path は transaction が作成したことを確認できる場合のみ除去。rollback 自体の失敗も別 category で報告し非ゼロ終了。
- bootstrap は `set -e` により helper 失敗時に `Bootstrap complete!` を表示しない。

### 19.9 Post-write verification

- SSOT bundle digest を**再計算**して preflight 値と照合する（preflight 値を信用しない）。
- 全 target: Skill は SSOT と byte 一致かつ非所有 snapshot 一致、instructions は期待 content と byte 一致（marker 外保持を包含）。

### 19.10 Dry-run

- production と同一の parse / validation / render / 比較を行い、bundle digest と target ごとの `create` / `update` / `unchanged` / diagnostics を出力する。
- staging・temporary file・directory 作成を含む filesystem write を一切行わない。production で失敗する preflight 状態は dry-run も非ゼロ終了する（§19.7 の registry probe のみ例外）。

### 19.11 内部 CLI 契約

```bash
# CSV を受け付ける唯一の口。canonical Agent ID を 1 行 1 件で出力
python scripts/sync_agent_assets.py canonicalize --agents "opencode,claudecode,codex,opencode"

# sync は繰り返し --agent のみ受け付ける（CSV 再分割なし）
python scripts/sync_agent_assets.py sync \
  --repo-root . --mode production --ingestion-mode all \
  --agent claudecode --agent opencode
```

- `--agents` は必須かつ 1 回のみ。空値・空要素・未知 ID（`notcodex` のような substring も含む）を拒否し、canonical order へ正規化して重複除去する。環境変数からの暗黙補完・substring 判定は禁止。
- bootstrap は canonicalize を依存 install・`.env` 作成・MCP 設定生成など全 filesystem side effect より前に 1 回実行し、得た canonical set を dry-run 表示と helper 呼び出しの唯一の入力とする。hook 側は canonical set の厳密な membership のみを使用する。
- 各 selected Agent には `selective` / `all` のいずれでも両 Skills と managed instruction block を同期する。`all` では同じ canonical set に含まれる Agent の hook artifact だけを同一 transaction で同期する。
- `--source=local|remote` は MCP server の実行方式だけを選ぶ。Agent asset は常に実行中 bootstrap と同じ checkout または release tarball の `agent-assets/` から同期し、`--source` で切り替わらない。`--non-interactive` でも Agent は暗黙選択せず、`--agents` を必須とする。
- error / warning 出力は Agent ID・path・phase・action・不一致 category・digest・復旧 artifact 識別子のみ。instructions 本文・他 Skill 本文・prompt 本文・credential は出力しない。preflight 拒否は exit 2、apply / rollback 失敗は exit 1。

### 19.12 コンポーネント構成

| ファイル | 役割 |
|---|---|
| `agent-assets/` | Agent 資産 SSOT（§19.2） |
| `scripts/sync_agent_assets.py` | 内部 CLI エントリポイント（`canonicalize` / `sync`） |
| `scripts/agent_assets/models.py` | Agent ID・mode・adapter・plan 等の型と `parse_agent_csv` |
| `scripts/agent_assets/bundle.py` | SSOT 検証・digest 計算・block render |
| `scripts/agent_assets/preflight.py` | marker 解析・legacy 検出・plan 生成 |
| `scripts/agent_assets/preflight_files.py` | instructions symlink containment・Skill 所有判定・snapshot |
| `scripts/agent_assets/hooks.py` | wrapper / OpenCode plugin 設定の plan と registry probe |
| `scripts/agent_assets/transaction.py` | apply / verify / rollback のファサード |
| `scripts/agent_assets/transaction_*.py` | staging・journal・rollback・post-write verification |
| `scripts/agent_assets/cli.py` | CLI 境界・決定論的 plan 出力・redacted diagnostics |
| `scripts/bootstrap.sh` | `--agents` の 1 回 parse と helper 委譲 |

各新規 Python module は pure 250 行以下を維持し、runtime 依存は標準ライブラリと既存の pyyaml（SKILL.md frontmatter 検証のみに使用）に限る。

### 19.13 テスト

- Unit: `tests/unit/test_agent_asset_sources.py`（SSOT 構造・frontmatter・sentinel）、`tests/unit/test_sync_agent_assets.py`（parser・digest・marker・所有・symlink・legacy・transaction・diagnostics）、`tests/unit/test_bootstrap_agent_assets.py`（CLI 契約・委譲・dry-run・完了メッセージ抑止）、`tests/unit/test_bootstrap_messages.py`（旧案内削除の regression）
- Integration: `tests/integration/test_sync_agent_assets.py`（temporary HOME での e2e・rollback・symlink 分類）、`tests/integration/test_opencode_turn_end_plugin.cjs`（`session.idle` → `scripts/agent_turn_hook.py` の plugin 契約）
- 必須 regression matrix: SSOT の missing / malformed template・Skill layout・sentinel・render token、3 Agent の clean install、同一 SSOT の no-op re-sync、marker 外 instructions と他 Skills の保持、SSOT 更新時の所有範囲だけの更新、mode switch、multi-Agent preflight failure 時の部分更新なし、I/O / post-write verification / hook setup / rollback failure、in-root / shared / root-external / broken / cyclic / parent symlink、legacy Save / Recall の mode guard、dry-run 前後の filesystem snapshot、OpenCode plugin の `session.idle` dispatch を検証する。3 Agent × 2 ingestion mode の clean install・再同期・mode switch・hook artifact は一時 HOME で manual QA も行う。
- fixtures: `tests/fixtures/agent_assets/legacy-save-v1.md` / `legacy-recall-v1.md`（legacy fingerprint 検出の pinned 入力）

---

## 参考文献

- [sui-memory](https://zenn.dev/noprogllama/articles/7c24b2c2410213) — SQLite + FTS5 + Ruri v3 によるローカル長期記憶
- [engram](https://zenn.dev/kimmaru/articles/3dbd92dea9ede8) — sui-memory の MCP サーバー化
- [MAGMA](https://arxiv.org/html/2601.03236v1) — Multi-Graph based Agentic Memory Architecture
- [MCP 仕様](https://modelcontextprotocol.io/) — Model Context Protocol
- [CrewAI Memory](https://docs.crewai.com/en/concepts/memory) — 複合スコアリングの参照実装
- AIエージェントの長期記憶と強化学習プラグイン開発 — コグニティブアーキテクチャ / 複合スコアリング / RL
- [LayerX ccgate (Zenn)](https://zenn.dev/layerx/articles/20260428-ccgate) — Server-defined Prompts / Permission Hook 概念の基礎
- [tak848/ccgate (GitHub)](https://github.com/tak848/ccgate) — ccgate 参照実装
