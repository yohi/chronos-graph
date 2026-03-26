# Context Store MCP v2.0 — 設計・仕様書

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
| `semantic_relevance` | float | 最終検索時の文脈的関連度スコア（0.0 - 1.0, 初期値: 0.0） |
| `access_count` | int | 検索で返却された回数 |
| `last_accessed_at` | timestamp | 最終アクセス日時 |
| `created_at` | timestamp | 作成日時 |
| `updated_at` | timestamp | 更新日時 |
| `archived_at` | timestamp? | アーカイブ日時（NULL = Active） |
| `tags` | text[] | プロジェクトタグ等 |

### 3.2 インデックス

| インデックス | 種別 | 対象 |
|---|---|---|
| HNSW | ベクトル近傍探索 | `embedding` カラム |
| pg_bigm / pgroonga | 日本語全文検索 | `content` カラム |
| B-tree | フィルタ用 | `memory_type`, `source_type`, `archived_at`, `tags` |

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

### 3.4 記憶の自動分類ルール

LLM は使用しない（トークン消費ゼロの原則）。
ルールベース（キーワード・構文パターン）+ 埋め込みプロトタイプ比較で分類する。

| 種別 | 分類シグナル |
|---|---|
| Episodic | 過去形動詞（「〜した」「〜を決めた」）、会話ログ由来、タイムスタンプ参照 |
| Semantic | 定義表現（「〜とは」「〜の仕様は」）、ドキュメント/URL 由来、概念説明 |
| Procedural | 手順表現（「〜する方法」「手順：」「1. 2. 3.」）、コマンド列、ステップ構造 |

---

## 4. Ingestion Pipeline

### 4.1 処理フロー

```text
入力 → Source Adapter → Chunker → Classifier → Embedding → Deduplicator → Graph Linker → 永続化
```

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

### 4.5 Graph Linker

新規記憶のNeo4j登録時に自動的にリレーションシップを推定する:

| エッジ | 推定条件 | 初期実装 |
|---|---|---|
| `SEMANTICALLY_RELATED` | ベクトル類似度 ≥ 0.70 | ✅ |
| `TEMPORAL_NEXT/PREV` | 同一セッション/プロジェクトの時系列順 | ✅ |
| `SUPERSEDES` | Deduplicator が Append-only 置換を実行（新→旧） | ✅ |
| `REFERENCES` | チャンク中の URL・ファイルパスの抽出 | ✅ |
| `CAUSED_BY/RESULTED_IN` | 因果関係推定 | ❌（RL 拡張ポイント） |

**検索範囲とエッジ作成の上限:**

パフォーマンスを維持するため、エッジ推定時の検索範囲と作成数に上限を設ける:

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
rrf_score = min_max_normalize(rrf_score_raw)       # 結果セット内で 0.0〜1.0 に正規化
time_decay = 0.5 ^ (days_since_access / 30)        # 半減期 30 日
final_score = 0.5 × rrf_score + 0.3 × time_decay + 0.2 × importance_score
```

**RRF スコアの正規化（必須）:**

RRF の生スコアは非常に小さな値（K=60, top_k=10 の場合、典型的に 0.001〜0.016）となり、
time_decay（≈0.0〜1.0）や importance_score（0.0〜1.0）とスケールが大きく異なる。
正規化しないと RRF の寄与率が設計意図の 50% ではなく実質 2% 未満になるため、
結果セット内の Min-Max 正規化を適用する:

```python
def normalize_rrf(scores: list[float]) -> list[float]:
    min_s, max_s = min(scores), max(scores)
    if max_s - min_s < 1e-8:  # 結果が1件 or 全同スコア
        return [1.0] * len(scores)
    return [(s - min_s) / (max_s - min_s) for s in scores]
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
| Consolidator | Deduplicator がマークした統合候補をマージ |
| Purger | Archived 後 N 日経過した記憶を物理削除（Storage + Graph 連動） |
| Stats Collector | DB 使用量・記憶数・平均スコア等の統計記録 |

**実装上の注意:**

- `last_cleanup_at` と `save_count` はメモリではなく **DB に永続化** する（プロセス寿命が短いため）
- クリーンアップは `asyncio.create_task()` で非同期実行し、ツール応答をブロックしない
- `APScheduler` は不要（依存パッケージから除去）

**グレースフル・シャットダウン:**

`stdio` モードの MCP サーバーはエージェント側の判断で突然終了（Kill）される可能性がある。
進行中のクリーンアップタスクのデータ破損を防ぐため、以下を実装する:

- `SIGINT` / `SIGTERM` シグナルをキャッチするシグナルハンドラを登録
- 進行中のクリーンアップタスクがあれば、タイムアウト付き（5秒）で完了を待機
- タイムアウト時はタスクをキャンセルし、各アダプターの `dispose()` でトランザクションをロールバック

**冪等性の要件:**

各クリーンアップジョブ（Archiver, Purger, Consolidator 等）は**冪等**に実装する:

- 中断されても次回再実行時に同じ結果に収束すること
- バッチ処理は小さなチャンク（例: 100件ずつ）でコミットし、単一の巨大トランザクションを避ける
- 処理済みレコードのスキップ条件を明示的にクエリに含める

**複数プロセス間の排他制御（SQLite モード）:**

複数エージェントが同一 SQLite DB に対して同時にクリーンアップを実行するリスクを防ぐため、
`lifecycle_state` テーブルにロック機構を組み込む:

```sql
UPDATE lifecycle_state
SET cleanup_running = 1, cleanup_started_at = datetime('now')
WHERE cleanup_running = 0
   OR cleanup_started_at < datetime('now', '-10 minutes');  -- スタルロック自動解放
-- affected_rows == 0 → 他プロセスが実行中のためスキップ
```

クリーンアップ完了時は `cleanup_running = 0` にリセットする。
10分間のタイムアウトにより、プロセスクラッシュ時のデッドロックを防止する。

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

FastMCP を使用。重いモジュール（sentence-transformers 等）は**遅延ロード**する。

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
| `source` | str | — | `"manual"` | `"conversation"` / `"manual"` / `"url"` |
| `project` | str? | — | None | プロジェクトタグ |
| `tags` | list[str] | — | [] | 追加タグ |
| `importance` | float? | — | None | 重要度ヒント（None なら自動） |

記憶種別（episodic/semantic/procedural）は自動分類される。
重複する記憶が存在する場合は自動的に統合される。

#### `memory_save_url` — URL からの取り込み

| 引数 | 型 | 必須 | デフォルト | 説明 |
|---|---|---|---|---|
| `url` | str | ✅ | — | 取り込む URL |
| `project` | str? | — | None | プロジェクトタグ |
| `tags` | list[str] | — | [] | 追加タグ |

URL のコンテンツを取得し、Markdown 変換後にチャンク分割して記憶として保存する。

**セキュリティ制約（SSRF 対策）:**

`memory_save_url` は任意 URL への HTTP リクエストを発行するため、
SSRF（Server-Side Request Forgery）を防ぐ以下の制約を**必須**で適用する:

| 制約 | 値 |
|---|---|
| 許可スキーム | `http`, `https` のみ |
| プライベート IP | デフォルト拒否（`ALLOW_PRIVATE_URLS=true` で解除可） |
| リダイレクト | 最大 3 回 |
| レスポンスサイズ | 最大 10 MB |
| タイムアウト | 30 秒 |
| 許可 Content-Type | `text/*`, `application/json`, `application/pdf` |

プライベート IP の判定対象:

- `127.0.0.0/8`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`
- `::1`, `fc00::/7`
- `169.254.0.0/16`（リンクローカル / クラウドメタデータ）

> **設計根拠**: MCP サーバーはユーザーのローカルマシンで稼働するため、
> 悪意のある URL 指定によりクラウドメタデータエンドポイント（`169.254.169.254`）や
> ローカルサービスにアクセスされるリスクがある。

**並行実行制限:**

複数の `memory_save_url` が同時に呼び出された場合、各リクエストが最大 30 秒の
HTTP タイムアウトを持つため、非同期ワーカーが枯渇し他の軽量ツール（`memory_search` 等）の
応答をブロックするリスクがある。これを防ぐため、`asyncio.Semaphore` による並行制限を適用する:

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
class MemoryError:
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
    async def dispose(self) -> None: ...
```

### 8.2 Graph Adapter Protocol

```python
class GraphAdapter(Protocol):
    async def create_node(self, memory_id: str, metadata: dict) -> None: ...
    async def create_edge(self, from_id: str, to_id: str, edge_type: str, props: dict) -> None: ...
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
    WHERE g.depth < ?  -- デフォルト: 3, ハードリミット: 5
)
SELECT DISTINCT to_id, edge_type, depth FROM graph;
```

| パラメータ | デフォルト値 | 説明 |
|---|---|---|
| `max_depth` | 3 | トラバーサルの深さ |
| ハードリミット | 5 | クライアントが指定できる最大深さ（これを超える値は強制的に 5 に制限） |

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

#### ベクトル次元数の整合性チェック（フェイルファスト）

Embedding Provider の切り替え（例: OpenAI 1536次元 → ローカルモデル 768次元）により
ベクトル次元数が変更された場合、既存の DB スキーマとの不整合が発生する。
これを防ぐため、Orchestrator 初期化時にフェイルファストチェックを行う:

```python
stored_dim = await storage.get_vector_dimension()
current_dim = embedding_provider.dimension
if stored_dim is not None and stored_dim != current_dim:
    raise ConfigurationError(
        f"ベクトル次元数の不一致: DB={stored_dim}, Provider={current_dim}. "
        f"`context-store migrate-embeddings` を実行して既存ベクトルを再計算してください。"
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
