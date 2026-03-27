# Context Store MCP v2.0 — フルアーキテクチャ再設計

## 概要

AIエージェント（Claude Code / Gemini CLI / Cursor等）向けの永続的な長期記憶システムを、
パイプライン指向アーキテクチャで全面的に再設計する。

### 設計の背景

- 既存実装（TypeScript, Phase 2まで完了）を破棄し、Pythonで全面書き直し
- Zenn記事（sui-memory / engram）の実践的知見を反映
- 設計ドキュメント「AIエージェントの長期記憶と強化学習プラグイン開発」の理論的基盤に基づく

### 設計決定サマリー

| 項目 | 決定 |
|---|---|
| スコープ | フルアーキテクチャ再設計 |
| ターゲット | 個人開発者、セルフホスト |
| 入力ソース | 会話ログ自動取り込み + 手動登録 + URL取り込み |
| 検索 | ハイブリッド検索 + グラフ推論、両方を第一級市民 |
| RL | 拡張ポイント（インターフェース）のみ設計 |
| 記憶管理 | 自動クリーンアップ（時間減衰 + 重複排除 + 自動アーカイブ） |
| 埋め込み | プロバイダー抽象化（プラグイン方式） |
| MCPツール | 中程度の粒度（7ツール） |
| 実装言語 | Python 3.12+ |

---

## 1. 全体アーキテクチャ

### 1.1 システム構成図

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

**アプローチ: パイプライン指向アーキテクチャ**

処理をIngestion（取り込み）/ Retrieval（検索）/ Lifecycle（管理）の3パイプラインに
明確に分離。各パイプラインは独立してテスト・拡張可能。

選定理由:

- レイヤードモノリスの密結合リスクを回避
- マイクロサービスの過度な分割・運用コストを回避
- RL拡張ポイントをOrchestratorレベルに自然に配置可能

---

## 2. データモデル

### 2.1 記憶データモデル（PostgreSQL）

```python
class MemoryType(str, Enum):
    EPISODIC = "episodic"       # イベント・会話の記録
    SEMANTIC = "semantic"       # 事実・知識・定義
    PROCEDURAL = "procedural"   # 手順・ワークフロー・スキル

class SourceType(str, Enum):
    CONVERSATION = "conversation"  # AIエージェントとの会話ログ
    MANUAL = "manual"              # 手動入力
    URL = "url"                    # URLからの取り込み

class Memory:
    id: UUID
    content: str                    # 記憶の本文
    memory_type: MemoryType         # 自動分類
    source_type: SourceType
    source_metadata: dict           # ソース固有情報 (agent名, URL, プロジェクトパス等)
    embedding: Vector               # 埋め込みベクトル (次元数はプロバイダー依存)
    semantic_relevance: float       # 文脈的関連度スコア (0.0 - 1.0)
    importance_score: float         # 重要度スコア (0.0 - 1.0)
    access_count: int               # アクセス回数
    last_accessed_at: datetime      # 最終アクセス日時
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None    # アーカイブ日時 (NoneならActive)
    tags: list[str]                 # プロジェクトタグ等
    project: str | None = None      # プロジェクト識別子
```

### 2.2 グラフモデル（Neo4j）

MAGMAアーキテクチャに基づく4種類のリレーションシップ:

```text
(:Memory {id, memory_type})

// 意味的関係: 概念的な関連
-[:SEMANTICALLY_RELATED {score: 0.85}]->

// 時間的関係: 時系列の前後
-[:TEMPORAL_NEXT {time_delta_hours: 24}]->
-[:TEMPORAL_PREV]->

// 因果的関係: 原因と結果
-[:CAUSED_BY {confidence: 0.9}]->
-[:RESULTED_IN]->

// 構造的関係: 依存・参照・矛盾
-[:REFERENCES]->
-[:DEPENDS_ON]->
-[:CONTRADICTS {detected_at}]->
-[:SUPERSEDES]->
```

### 2.3 記憶の自動分類

| 種別 | 定義 | 分類シグナル例 |
|---|---|---|
| Episodic | 特定のイベント・会話の記録 | 「〜した」「〜を決めた」、タイムスタンプ付き、会話ログ由来 |
| Semantic | 事実・知識・定義 | 「〜とは」「〜の仕様は」、ドキュメント/URL由来 |
| Procedural | 手順・ワークフロー・スキル | 「〜する方法」「手順：」、コマンド列、ステップ構造 |

分類はルールベース（キーワード・構文パターン）+ 埋め込みベクトルの類似度を併用。
LLMは使用しない（トークン消費ゼロの原則）。

---

## 3. Ingestion Pipeline（取り込みパイプライン）

### 3.1 パイプラインフロー

```text
入力ソース
    │
    ▼
┌─────────────┐
│  Source      │  会話ログ / 手動入力 / URL → 生テキスト取得
│  Adapter     │
└──────┬──────┘
       ▼
┌─────────────┐
│  Chunker    │  Q&A形式 / セクション分割 / スライディングウィンドウ
└──────┬──────┘
       ▼
┌─────────────┐
│  Classifier │  記憶種別の自動判定 (episodic/semantic/procedural)
└──────┬──────┘
       ▼
┌─────────────┐
│  Embedding  │  プロバイダー抽象化経由でベクトル化
│  Provider   │
└──────┬──────┘
       ▼
┌──────────────┐
│ Deduplicator │  既存記憶との重複チェック → 統合 or 新規挿入
└──────┬───────┘
       ▼
┌──────────────┐
│ Graph        │  Neo4jにノード作成 + リレーションシップ推定
│ Linker       │
└──────┬───────┘
       ▼
   Storage Layer へ永続化
```

### 3.2 Source Adapter

```python
class SourceAdapter(Protocol):
    """入力ソースごとのアダプター抽象"""
    def extract(self, input_data: Any) -> list[RawContent]:
        """生テキストとメタデータを抽出"""
        ...

# 実装:
# - ConversationAdapter: 会話トランスクリプト処理
# - ManualAdapter: 手動入力されたナレッジ処理
# - URLAdapter: URLからHTML取得 → Markdown変換
```

### 3.3 Chunker（チャンク分割戦略）

| ソース | 分割方式 | チャンクサイズ目安 |
|---|---|---|
| 会話ログ | Q&A ペア分割（ユーザー発言 + エージェント応答を1チャンクに） | 1〜3ターン |
| 手動入力 | そのまま1チャンク（短い場合）/ セクション分割（長い場合） | 〜1000トークン |
| URL文書 | Markdown見出し（H1/H2）ベースのセクション分割 + オーバーラップ | 500〜1000トークン |

### 3.4 Deduplicator（重複排除と統合）

```python
class Deduplicator:
    SIMILARITY_THRESHOLD = 0.90   # コサイン類似度がこれ以上なら重複 → Append-only 置換
    CONSOLIDATION_THRESHOLD = 0.85  # 統合候補の閾値

    def check(self, new_memory: Memory) -> DeduplicationResult:
        # 1. 新チャンクのベクトルで既存Top5を検索
        # 2. 同一プロジェクト & 類似度 >= 0.90 → Append-only 置換（旧記憶をArchive、新規 INSERT、SUPERSEDESエッジ作成）
        # 3. 同一プロジェクト & 0.85 <= 類似度 < 0.90 → 統合候補としてマーク
        # 4. それ以外 → 新規挿入
```

統合（Consolidation）は非同期バックグラウンドジョブで実行。

### 3.5 Graph Linker（リレーションシップ自動推定）

- **SEMANTICALLY_RELATED**: ベクトル類似度 >= 0.70 の既存ノードとリンク
- **TEMPORAL_NEXT/PREV**: 同一セッション・プロジェクトの記憶を時系列順にリンク
- **SUPERSEDES**: DeduplicatorがAppend-only 置換を行った場合にリンク
- **REFERENCES**: チャンク中の明示的参照（URL・ファイルパス等）からリンク
- **CAUSED_BY/RESULTED_IN**: 将来のRL拡張ポイント（初期実装ではスキップ）

---

## 4. Retrieval Pipeline（検索パイプライン）

### 4.1 パイプラインフロー

```text
ユーザークエリ
    │
    ▼
┌──────────────┐
│ Query        │  クエリの意図を分析し、最適な検索戦略を決定
│ Analyzer     │
└──────┬───────┘
       │
       ├──────────────────┬──────────────────┐
       ▼                  ▼                  ▼
┌─────────────┐  ┌──────────────┐  ┌──────────────┐
│ Vector      │  │ Keyword      │  │ Graph        │
│ Search      │  │ Search       │  │ Traversal    │
│ (pgvector)  │  │ (PostgreSQL  │  │ (Neo4j)      │
│             │  │  FTS)        │  │              │
└──────┬──────┘  └──────┬───────┘  └──────┬───────┘
       │                │                  │
       └────────────────┼──────────────────┘
                        ▼
               ┌──────────────┐
               │ Result       │  RRF + 時間減衰 + 複合スコアリング
               │ Fusion       │
               └──────┬───────┘
                      ▼
               ┌──────────────┐
               │ Post         │  フィルタリング・ランキング・アクセス記録
               │ Processor    │
               └──────┬───────┘
                      ▼
                検索結果を返却
```

### 4.2 Query Analyzer（意図解析と戦略選択）

```python
class SearchStrategy:
    vector_weight: float    # ベクトル検索の重み (0.0 - 1.0)
    keyword_weight: float   # キーワード検索の重み
    graph_weight: float     # グラフ検索の重み
    graph_depth: int        # グラフトラバーサルの深さ
    time_decay_enabled: bool
```

| クエリパターン | 戦略 |
|---|---|
| `"JWT認証の実装方針"` | vector重視 (0.5 / 0.2 / 0.3) |
| `"TypeORMのエラー ER_PARSE_ERROR"` | keyword重視 (0.2 / 0.6 / 0.2) |
| `"なぜReactからSvelteに移行した？"` | graph重視 (0.2 / 0.1 / 0.7), depth=3 |
| `"先週決めたAPI設計"` | vector + 時間フィルタ |

意図解析はルールベース（キーワードパターン）で実装。LLMは使用しない。

### 4.3 検索エンジン

**Vector Search (pgvector):**

- コサイン類似度によるANN検索
- HNSWインデックスで高速近似最近傍探索
- 閾値: similarity >= 0.70

**Keyword Search (PostgreSQL FTS):**

- pg_bigm または pgroonga による日本語全文検索
- 固有名詞・コード片・エラーメッセージに強い

**Graph Traversal (Neo4j):**

- 起点ノードをベクトル検索で特定し、そこからグラフを辿る
- MAGMAの適応型トラバーサル: クエリ意図に応じてエッジタイプをフィルタ

### 4.4 Result Fusion（結果統合）

RRF (Reciprocal Rank Fusion) + 時間減衰 + 重要度の複合スコアリング:

```python
class ResultFusion:
    K = 60  # RRF定数

    def fuse(self, results, strategy) -> list[ScoredMemory]:
        # 1. RRFスコア算出
        #    rrf_score = Σ weight × 1/(K + rank + 1)
        #
        # 2. 複合スコア算出
        #    time_decay = 0.5^(days_since_access / 30)
        #    final_score = 0.5 × rrf_score + 0.3 × time_decay + 0.2 × importance_score
```

### 4.5 Post Processor

- プロジェクトフィルタ（オプション）
- 最大トークン制限（エージェントのコンテキスト消費を抑制）
- アクセス記録更新（last_accessed_at, access_count）

---

## 5. Lifecycle Manager（記憶ライフサイクル管理）

### 5.1 記憶の状態遷移

```text
      新規挿入 ──▶ Active ◀── アクセスで活性化
                      │
           スコアが閾値以下 & 一定期間未アクセス
                      │
                      ▼
                  Archived    (検索対象外、データは保持)
                      │
               アーカイブ後90日経過
                      │
                      ▼
                   Purged     (物理削除)
```

### 5.2 イベント駆動型クリーンアップ

| ジョブ | トリガー条件 | 処理内容 |
|---|---|---|
| Decay Scorer | 初回起動時、または記憶保存時（条件付き） | 全Active記憶の複合スコアを再計算、閾値以下をマーク |
| Auto Archiver | 同上 | マークされた記憶をArchived状態に遷移 |
| Consolidator | 同上 | 統合候補の記憶群をマージ処理 |
| Purger | 同上 | Archived後N日経過した記憶を物理削除 |
| Stats Collector | 同上 | DB使用量・記憶数・平均スコアの統計記録 |

※時間ベースではなく、`memory_save` 呼び出し回数（例: 50回）の超過や、前回実行から一定時間経過（例: 1日）などを条件に非同期にジョブがトリガーされる。

Lifecycle Manager は、`memory_save` 累積回数が **50 回** に達した場合、または前回クリーンアップから **1 日** 以上経過した場合に起動する。これらの閾値は実装計画ではなく `SPEC.md` を正本とし、保存回数ベース・経過時間ベースの両トリガーを併用する。

### 5.3 Decay Scorer

```python
class DecayScorer:
    HALF_LIFE_DAYS = 30
    ARCHIVE_THRESHOLD = 0.05

    def compute_composite_score(self, memory: Memory) -> float:
        days_elapsed = (now() - memory.last_accessed_at).days
        recency = 0.5 ** (days_elapsed / self.HALF_LIFE_DAYS)
        composite = (
            0.5 * memory.semantic_relevance +
            0.3 * recency +
            0.2 * memory.importance_score
        )
        return composite
```

### 5.4 設定パラメータ

```yaml
lifecycle:
  decay:
    half_life_days: 30
    archive_threshold: 0.05
  consolidation:
    similarity_threshold: 0.85
  purge:
    retention_days: 90
  # 将来の拡張: 概念ドリフト検出
  # concept_drift:
  #   enabled: false
  #   contradiction_threshold: 0.80
```

---

## 6. MCP インターフェース

### 6.1 MCPサーバー基盤

FastMCPを使用。重いモジュール（sentence-transformers等）は遅延ロード。
初期化時はMCPハンドシェイクのみ、初回ツール呼び出し時にOrchestrator/Storageを初期化。

### 6.2 ツール一覧

| ツール | 用途 |
|---|---|
| `memory_save` | 記憶の保存（種類は自動分類） |
| `memory_save_url` | URLからコンテンツを取り込んで記憶化 |
| `memory_search` | ハイブリッド検索（ベクトル + キーワード + グラフを自動統合） |
| `memory_search_graph` | グラフトラバーサル特化（因果関係・依存関係の探索） |
| `memory_delete` | 記憶の削除 |
| `memory_prune` | 古い/低スコアの記憶のクリーンアップ |
| `memory_stats` | 統計情報 |

### 6.3 ツール仕様

```python
@server.tool()
async def memory_save(
    content: str,
    source: str = "manual",       # "conversation" | "manual" | "url"
    project: str | None = None,
    tags: list[str] | None = None,
    importance: float | None = None,
) -> SaveResult:
    tags = tags or []
    ...

@server.tool()
async def memory_save_url(
    url: str,
    project: str | None = None,
    tags: list[str] | None = None,
) -> SaveResult:
    tags = tags or []
    ...

@server.tool()
async def memory_search(
    query: str,
    project: str | None = None,
    memory_type: str | None = None,
    top_k: int = 10,
    max_tokens: int | None = None,
) -> list[SearchResult]: ...

@server.tool()
async def memory_search_graph(
    query: str,
    edge_types: list[str] | None = None,
    depth: int = 2,
    project: str | None = None,
) -> GraphSearchResult: ...

@server.tool()
async def memory_delete(memory_id: str) -> DeleteResult: ...

@server.tool()
async def memory_prune(
    older_than_days: int = 90,
    dry_run: bool = True,
) -> PruneResult: ...

@server.tool()
async def memory_stats(project: str | None = None) -> StatsResult: ...
```

### 6.4 MCP Resources

```python
@server.resource("memory://stats")
async def stats_resource() -> str: ...

@server.resource("memory://projects")
async def projects_resource() -> str: ...
```

### 6.5 エラーハンドリングとGraceful Degradation

- Neo4j障害 → グラフ検索をスキップ、ベクトル + キーワード検索のみで動作継続
- Redis障害 → キャッシュなしで直接DB検索
- PostgreSQL障害 → 全ツールがエラーを返す（マスターDB）

---

## 7. Storage Layer と Embedding Provider

### 7.1 Storage Protocol

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

class GraphAdapter(Protocol):
    async def create_node(self, memory_id: str, metadata: dict) -> None: ...
    async def create_edge(self, from_id: str, to_id: str, edge_type: str, props: dict) -> None: ...
    async def traverse(self, seed_ids: list[str], edge_types: list[str], depth: int) -> GraphResult: ...
    async def delete_node(self, memory_id: str) -> None: ...
    async def dispose(self) -> None: ...

class CacheAdapter(Protocol):
    async def get(self, key: str) -> Any | None: ...
    async def set(self, key: str, value: Any, ttl: int) -> None: ...
    async def invalidate(self, key: str) -> None: ...
    async def invalidate_prefix(self, prefix: str) -> None: ...
    async def dispose(self) -> None: ...
```

#### invalidate_prefix 実装注記

- Redis: `KEYS` コマンドは使用禁止。`SCAN` + batched `DELETE` でブロッキング回避（SPEC.md §8.3 参照）
- InMemory: プレフィックス一致での安全なループ削除（`asyncio.Lock` で排他制御）
- 原子性: 個別キー削除はベストエフォート。全削除完了までに一貫性違反が発生する可能性あり
- 計算量: O(n)（n = プレフィックス一致キー数）

#### get_vector_dimension() のバックエンド別実装方針

**PostgreSQL:**
- `pg_typeof(embedding)` で列型を確認し、`array_length(embedding, 1)` で次元数を取得
- 例: `SELECT array_length(embedding, 1) FROM memories LIMIT 1`
- 列が存在しない、または NULL のみの場合は `None` を返す

**SQLite:**
- 専用メタデータテーブル `vectors_metadata` を参照
- 例: `SELECT dimension FROM vectors_metadata WHERE table_name = 'memories'`
- メタテーブル未存在・不整合の場合は `None` を返す（初期化時に警告ログ）

**Orchestrator フェイルファスト:**
- 初期化時に `storage.get_vector_dimension()` と `embedding_provider.dimension` を比較
- `stored_dim is not None and stored_dim != current_dim` の場合 `ConfigurationError` を発生
- 詳細は SPEC.md §9.1 参照

初期実装: PostgresStorageAdapter, Neo4jGraphAdapter, RedisCacheAdapter

### 7.2 Embedding Provider Protocol

```python
class EmbeddingProvider(Protocol):
    async def embed(self, text: str) -> list[float]: ...
    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...
    @property
    def dimension(self) -> int: ...

# 初期実装:
# - OpenAIEmbeddingProvider
# - LocalModelEmbeddingProvider (sentence-transformers / Ruri v3等)
# - LiteLLMEmbeddingProvider
# - CustomAPIEmbeddingProvider
```

---

## 8. RL拡張ポイント

初期実装はしないが、Orchestratorにフックポイントを配置:

```python
class ActionLogger(Protocol):
    """エージェントの行動ログを記録"""
    async def log_action(self, action: AgentAction) -> None: ...

class RewardSignal(Protocol):
    """報酬シグナルの収集"""
    async def record_reward(self, memory_id: str, signal: float, context: dict) -> None: ...

class PolicyHook(Protocol):
    """検索戦略への介入フック"""
    async def adjust_strategy(self, query: str, base_strategy: SearchStrategy) -> SearchStrategy: ...

class Orchestrator:
    def __init__(
        self,
        ingestion: IngestionPipeline,
        retrieval: RetrievalPipeline,
        lifecycle: LifecycleManager,
        action_logger: ActionLogger | None = None,
        reward_signal: RewardSignal | None = None,
        policy_hook: PolicyHook | None = None,
    ):
        self.ingestion = ingestion
        self.retrieval = retrieval
        self.lifecycle = lifecycle
        self.action_logger = action_logger or NoOpActionLogger()
        self.reward_signal = reward_signal or NoOpRewardSignal()
        self.policy_hook = policy_hook or NoOpPolicyHook()
```

---

## 9. 技術スタック

| カテゴリ | 技術 | 理由 |
|---|---|---|
| 言語 | Python 3.12+ | ML/埋め込みモデルとの親和性 |
| MCPフレームワーク | FastMCP | Python MCP実装のデファクト |
| ストレージ | PostgreSQL 16 + pgvector | ベクトル検索 + メタデータ + FTS の統合 |
| グラフDB | Neo4j 5.x | Cypherクエリ、リレーションシップモデリング |
| キャッシュ | Redis 7.x | 検索結果・埋め込みのキャッシュ |
| ORM/クエリ | asyncpg | 非同期・高パフォーマンス |
| Neo4jドライバ | neo4j-python-driver (async) | 公式非同期ドライバ |
| 日本語FTS | pg_bigm or pgroonga | PostgreSQLの日本語全文検索拡張 |
| 埋め込み(ローカル) | sentence-transformers | Ruri v3-310m等のローカルモデル |
| ストレージ（ライトウェイト） | aiosqlite + sqlite-vec + FTS5 | ゼロコンフィグモード（デフォルト） |
| 設定管理 | pydantic-settings | 型安全な設定 + .env サポート |
| テスト | pytest + pytest-asyncio | 非同期テスト対応 |
| コンテナ | Docker Compose | PostgreSQL / Neo4j / Redis の一括管理 |

---

## 10. プロジェクト構成

```text
context-store-mcp/
├── pyproject.toml
├── docker-compose.yml
├── .env.example
├── src/
│   └── context_store/
│       ├── __init__.py
│       ├── server.py              # FastMCP サーバー (エントリーポイント)
│       ├── orchestrator.py        # 全パイプラインの統合・調整
│       ├── config.py              # pydantic-settings による設定
│       │
│       ├── ingestion/             # Ingestion Pipeline
│       │   ├── __init__.py
│       │   ├── pipeline.py
│       │   ├── adapters.py        # SourceAdapter (conversation/manual/url)
│       │   ├── chunker.py
│       │   ├── classifier.py      # 記憶種別の自動分類
│       │   ├── deduplicator.py
│       │   └── graph_linker.py
│       │
│       ├── retrieval/             # Retrieval Pipeline
│       │   ├── __init__.py
│       │   ├── pipeline.py
│       │   ├── query_analyzer.py
│       │   ├── vector_search.py
│       │   ├── keyword_search.py
│       │   ├── graph_traversal.py
│       │   ├── result_fusion.py
│       │   └── post_processor.py
│       │
│       ├── lifecycle/             # Lifecycle Manager
│       │   ├── __init__.py
│       │   ├── manager.py
│       │   ├── decay_scorer.py
│       │   ├── archiver.py
│       │   ├── consolidator.py
│       │   └── purger.py
│       │
│       ├── storage/               # Storage Layer (SQLite default)
│       │   ├── __init__.py
│       │   ├── protocols.py
│       │   ├── factory.py
│       │   ├── inmemory.py
│       │   ├── sqlite.py
│       │   ├── sqlite_graph.py
│       │   ├── postgres.py
│       │   ├── neo4j.py
│       │   └── redis.py
│       │
│       ├── embedding/             # Embedding Provider
│       │   ├── __init__.py
│       │   ├── protocols.py
│       │   ├── openai.py
│       │   ├── local_model.py
│       │   ├── litellm.py
│       │   └── custom_api.py
│       │
│       ├── models/                # データモデル
│       │   ├── __init__.py
│       │   ├── memory.py
│       │   ├── search.py
│       │   └── graph.py
│       │
│       └── extensions/            # RL拡張ポイント
│           ├── __init__.py
│           ├── protocols.py
│           └── noop.py
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── conftest.py
│
└── docs/
    └── plans/
```

---

## 11. 設定ファイル

```bash
# .env
# --- Core ---
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=context_store
POSTGRES_USER=context_store
POSTGRES_PASSWORD=your_password

NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password

REDIS_URL=redis://localhost:6379

# --- Embedding ---
EMBEDDING_PROVIDER=openai
OPENAI_API_KEY=sk-...
LOCAL_MODEL_NAME=cl-nagoya/ruri-v3-310m

# --- Lifecycle ---
DECAY_HALF_LIFE_DAYS=30
ARCHIVE_THRESHOLD=0.05
PURGE_RETENTION_DAYS=90

# --- Search ---
DEFAULT_TOP_K=10
SIMILARITY_THRESHOLD=0.70
DEDUP_THRESHOLD=0.90
```

---

## 参考文献

- [sui-memory (noprogllama)](https://zenn.dev/noprogllama/articles/7c24b2c2410213) — SQLite + FTS5 + Ruri v3 によるローカル長期記憶
- [engram (kimmaru)](https://zenn.dev/kimmaru/articles/3dbd92dea9ede8) — sui-memoryのMCPサーバー化
- AIエージェントの長期記憶と強化学習プラグイン開発 — コグニティブアーキテクチャ / MAGMA / 複合スコアリング / RL
- [MAGMA (arXiv)](https://arxiv.org/html/2601.03236v1) — Multi-Graph based Agentic Memory Architecture
- [MCP仕様](https://modelcontextprotocol.io/)
- [CrewAI Memory](https://docs.crewai.com/en/concepts/memory) — 複合スコアリングの参照実装
