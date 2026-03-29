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
> | Docker サービス名 | `postgres`, `neo4j` | (変更なし) |
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
| 多層記憶 | Episodic（経験）・Semantic（知識）・Procedural（手順）の自動分類 |
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

### 2.2 バックエンド構成

| コンポーネント | 役割 | 障害時の挙動 |
|---|---|---|
| PostgreSQL 16 + pgvector | マスターDB。記憶本体・メタデータ・ベクトル・FTS | 障害時は全機能停止 |
| Neo4j 5.x | グラフDB。記憶間のリレーションシップ | 障害時はグラフ検索をスキップして継続 |
| Redis 7.x | キャッシュ。検索結果・埋め込みベクトル | 障害時はキャッシュなしで継続 |

### 2.3 実装言語・フレームワーク

| カテゴリ | 技術 |
|---|---|
| 言語 | Python 3.12+ |
| MCP フレームワーク | FastMCP |
| PostgreSQL ドライバ | asyncpg |
| Neo4j ドライバ | neo4j-python-driver (async) |
| 日本語 FTS | pg_bigm または pgroonga |
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
| `project` | text? | プロジェクト識別子（ツール引数の `project` を直接保存） |

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
ルールベース（キーワード・構文パターン）+ 埋め込みプロトタイプ比較で分類する。

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

**トランザクション境界の設計原則:**
`EmbeddingProvider` によるベクトル化処理（外部API呼び出しや重いローカル推論）は、**必ず Storage Layer の書き込みトランザクション（`save_memory` 等）を開始する前**に完了させてください。
SQLite の `busy_timeout=5000` は強力ですが、トランザクション内でネットワークI/Oを待機すると、他のエージェント（プロセス）からの書き込みを長時間ブロックし、`SQLITE_BUSY` エラーを引き起こす原因となります。
この制約は実装コードおよびテスト内で明示的に保証する必要があります（例: モックを用いて、`EmbeddingProvider.embed_batch` の完了前に `StorageAdapter.save_memory` などのトランザクションメソッドが呼び出されるとテストが失敗するような呼び出し順序検証を実装すること）。

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

#### `memory_search_graph` — グラフトラバーサル検索

| 引数 | 型 | 必須 | デフォルト | 説明 |
|---|---|---|---|---|
| `query` | str | ✅ | — | 起点を見つけるためのクエリ |
| `edge_types` | list[str]? | — | None | 辿るエッジタイプの指定 |
| `depth` | int | — | 2 | トラバーサルの深さ |
| `project` | str? | — | None | プロジェクトフィルタ |

記憶のグラフ構造を辿って関連する記憶群を取得する。
返却値にはリレーションシップ情報も含む。

#### `memory_delete` — 記憶の削除

| 引数 | 型 | 必須 | 説明 |
|---|---|---|---|
| `memory_id` | str | ✅ | 削除対象の記憶 ID |

PostgreSQL・Neo4j 両方から削除する。

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
> **【重要な副作用と実装要件】**: 非同期タスクから単純に `interrupt()` を呼び出すと、クエリ完了後のアイドル状態のコネクションに割り込みフラグが残り、**後続の全く無関係なクエリが `OperationalError: interrupted` でクラッシュする**という深刻な副作用があります。これを防ぐため、実行中状態を管理するフラグやロックを用いたラッパークラス（コンテキストマネージャ等）を実装し、**「クエリが確実に実行中である期間のみ `interrupt()` を発火させる」**厳密な状態管理を行ってください。
> タイムアウト発生時は例外として処理を中断するのではなく、到達済みの部分グラフを返すか、安全に空結果を返す Graceful Degradation を行うサーキットブレーカー機構の実装を必須とします。タイムアウト発生時は警告ログも出力してください。
> Neo4jGraphAdapter においても、同様に `GRAPH_TRAVERSAL_TIMEOUT_SECONDS` を利用し、トランザクションのタイムアウト（例: `tx.run(..., timeout=GRAPH_TRAVERSAL_TIMEOUT_SECONDS)`）を設定して、同様の Graceful Degradation を行ってください。

**SQLite のバックプレッシャー制御:**
aiosqlite を用いた非同期実行において、FastMCP 側で大量の並行リクエストが発生した場合、スレッド枯渇やメモリ上のタスク滞留を防ぐため、以下のバックプレッシャー機構を実装すること：

1.  **同時接続制限**: `SQLiteStorageAdapter` 初期化時に `asyncio.Semaphore(sqlite_max_concurrent_connections)` を設定し、セマフォ (`self._semaphore`) は並行 DB 操作のために `asyncio.wait_for` と `try/finally` を使用し て取得・解放する。
2.  **待ち行列数制限 (Bounded Queueing)**: 待機リクエスト数を制限する機構を実装する。実装者は実装計画書 (docs/plans/...) に詳述されている通り、キュー・ワーカーパターン (例: `request_queue` と `maxsize=sqlite_max_queued_requests`) や明示的なカウンタ (例: `SQLiteStorageAdapter._pending_count` と `_pending_lock`) のいずれかを使用し、`asyncio.Semaphore` の内部状態への依存を避けること。制限を超過した場合は即座に `StorageError(code="STORAGE_BUSY", recoverable=True)` を送出してフェイルファストさせること。
3.  **取得タイムアウトと確実な解放**:  
    - すべての DB 操作を `asyncio.wait_for(self._semaphore.acquire(), timeout=Settings.sqlite_acquire_timeout)` でラップすること。
    - セマフォの確実な解放を保証するため、`try/finally` ブロックまたは `async with` コンテキストマネージャを必ず使用すること。
    - セマフォ取得時の `TimeoutError` および、DB 操作中に発生したロック関連の `aiosqlite.OperationalError` (捕捉対象: `"database is locked"`, `"locked"`, `"busy"` を含むメッセージ、およびエラーコード `SQLITE_BUSY` (5), `SQLITE_LOCKED` (6), `SQLITE_BUSY_SNAPSHOT` (517)) は、一律で `StorageError(code="STORAGE_BUSY", recoverable=True)` に変換して送出し、MCP クライアントにリトライを促すこと。ロック無関係のエラーは再スローすること。

これにより、イベントループ内での無制限なコルーチン滞留を防止し、システム全体の応答性を維持する。実装には上記のように `request_queue` や `self._pending_count` といった標準的なパブリック API のみを用いること。

**性能検証要件:**

- `memory_edges` に 10,000 件の現実的なエッジを投入した fixture を用意する
- depth=2 と depth=5 の再帰的 CTE トラバーサルについて、レイテンシとメモリ使用量を測定する
- from_id を複数パターン切り替えて tail percentile を取得する
- 結果は benchmark artifact として保存し、性能回帰の確認に使う

### 8.5 ストレージ選択ロジック

`config.py` の `STORAGE_BACKEND` / `CACHE_BACKEND` に応じて、
ファクトリ関数が適切なアダプターインスタンスを返す:

| 設定値 | StorageAdapter | GraphAdapter | CacheAdapter |
|---|---|---|---|
| `sqlite` (デフォルト) | SQLiteStorageAdapter | SQLiteGraphAdapter | InMemoryCacheAdapter |
| `postgres` | PostgresStorageAdapter | Neo4jGraphAdapter* | RedisCacheAdapter* |

\* `GRAPH_ENABLED=false` の場合は GraphAdapter を None に、Redis 未接続時は InMemoryCacheAdapter にフォールバック。

> **注意**: `sqlite` モードではグラフ機能は常に有効（`GRAPH_ENABLED` 設定は `postgres` モードのみに適用）。

---

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

```text
context-store-mcp/
├── pyproject.toml
├── docker-compose.yml
├── .env.example
├── SPEC.md                        # 本ドキュメント
│
├── src/
│   └── context_store/
│       ├── __init__.py
│       ├── server.py              # FastMCP サーバー（エントリーポイント）
│       ├── orchestrator.py        # パイプラインの統合・調整
│       ├── config.py              # pydantic-settings 設定
│       │
│       ├── ingestion/             # Ingestion Pipeline
│       │   ├── __init__.py
│       │   ├── pipeline.py
│       │   ├── adapters.py        # ConversationAdapter / ManualAdapter / URLAdapter
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
│       ├── storage/               # Storage Layer
│       │   ├── __init__.py
│       │   ├── protocols.py
│       │   ├── factory.py            # ストレージ選択ファクトリ
│       │   ├── postgres.py
│       │   ├── sqlite.py             # ライトウェイト版 (sqlite-vec + FTS5)
│       │   ├── sqlite_graph.py       # SQLite ローカルグラフ (再帰的 CTE)
│       │   ├── neo4j.py
│       │   ├── redis.py
│       │   └── inmemory.py           # InMemory Cache Adapter
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
│       └── extensions/            # RL 拡張ポイント
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

## 12. 環境変数

```bash
# === Storage Backend ===
STORAGE_BACKEND=sqlite              # sqlite | postgres
GRAPH_ENABLED=false                 # true | false (Neo4j の有効化)
CACHE_BACKEND=inmemory              # inmemory | redis
SQLITE_DB_PATH=~/.context-store/memories.db  # sqlite の場合

# === PostgreSQL (STORAGE_BACKEND=postgres の場合) ===
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=context_store
POSTGRES_USER=context_store
POSTGRES_PASSWORD=<secret>

# === Neo4j (GRAPH_ENABLED=true の場合) ===
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=<secret>

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

---

## 参考文献

- [sui-memory](https://zenn.dev/noprogllama/articles/7c24b2c2410213) — SQLite + FTS5 + Ruri v3 によるローカル長期記憶
- [engram](https://zenn.dev/kimmaru/articles/3dbd92dea9ede8) — sui-memory の MCP サーバー化
- [MAGMA](https://arxiv.org/html/2601.03236v1) — Multi-Graph based Agentic Memory Architecture
- [MCP 仕様](https://modelcontextprotocol.io/) — Model Context Protocol
- [CrewAI Memory](https://docs.crewai.com/en/concepts/memory) — 複合スコアリングの参照実装
- AIエージェントの長期記憶と強化学習プラグイン開発 — コグニティブアーキテクチャ / 複合スコアリング / RL

