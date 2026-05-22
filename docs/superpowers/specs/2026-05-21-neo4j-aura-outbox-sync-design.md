# Neo4j Aura Offloading — Transactional Outbox Sync 設計仕様書

| 項目 | 内容 |
| --- | --- |
| Spec ID | 2026-05-21-neo4j-aura-outbox-sync-design |
| Status | Approved (Design Phase) |
| 作成日 | 2026-05-21 |
| 関連 Spec | `2026-05-18-supabase-storage-adapter-design.md` (Supabase アダプタ) |
| 想定実装 | `src/context_store/sync/`, `src/context_store/storage/`, `scripts/` |

## 1. 背景と目的

### 1.1 課題

ChronosGraph は Polyglot Persistence 戦略により Storage Layer (PostgreSQL/SQLite/Supabase) と
Graph Layer (Neo4j) を分離しているが、現在の `sync` モードでは Ingestion Pipeline 内の
`GraphLinker` が Neo4j に直接同期書き込みを行う。この設計には以下の課題がある。

- **ファイアウォール制約**: 企業環境では DPI により Neo4j Bolt プロトコル (Port 7687) がブロック
  される場合がある。Neo4j Aura は `neo4j+s://` (WSS over Port 443) でこれを回避できるが、
  同期書き込みのレイテンシがエージェントの応答時間に直結する
- **トランザクション非分離**: メモリ保存とグラフ書き込みが別トランザクションであるため、
  メモリ保存成功後にグラフ書き込みが失敗すると Storage と Graph の不整合が発生する
- **Supabase + Neo4j の未対応**: `factory.py` で `supabase + graph_enabled` の組み合わせが
  バリデーションエラーとなり、SaaS フルオフロード構成への道が塞がれている

### 1.2 目的

**Transactional Outbox Pattern** を導入し、以下を達成する。

- Storage Layer のメモリ保存と同一トランザクションで Outbox テーブルにグラフ同期イベントを
  書き込み、Atomicity を保証する
- バックグラウンドワーカーが Outbox を polling し、バルク Cypher (UNWIND + MERGE) で
  Neo4j Aura に非同期同期する
- 全バックエンド (PostgreSQL / SQLite / Supabase) で Outbox をサポートする
- Supabase + Neo4j Aura の組み合わせを解禁し、HTTPS/WSS のみで完結する
  SaaS フルオフロード構成を実現する

### 1.3 非ゴール

- 既存の `sync` モードの動作変更（後方互換性を完全維持）
- 外部メッセージブローカー (Celery, RabbitMQ, Redis) の導入
- Neo4j への content body やベクトル配列の複製（Graph は Traversal Index に徹する）
- 既存の `GraphLinker` のエッジ推論ロジック自体の変更

## 2. アーキテクチャ概要

### 2.1 設定切替式 (Config-Switchable)

`GRAPH_SYNC_MODE` 環境変数により 2 つのモードを切り替える。

| モード | 動作 | ユースケース |
| --- | --- | --- |
| `sync` (デフォルト) | 既存動作を維持。GraphLinker が Neo4j に直接同期書き込み | ローカル環境、低レイテンシ環境 |
| `async_outbox` | Storage TX 内で Outbox に書き込み。Worker が非同期で Neo4j 同期 | ファイアウォール制約環境、SaaS オフロード |

### 2.2 データフロー

#### Write (async_outbox モード)

```text
IngestionPipeline
  ├─ Chunker → Classifier → Embedding → Deduplicator
  ├─ GraphLinker → Storage 側グラフテーブル (memory_nodes / memory_edges) のみ
  └─ StorageAdapter.save_memory()
       └─ 同一 TX: memories INSERT + graph_sync_outbox INSERT
                         ↓ (background polling, 5s interval)
                   OutboxWorker
                     ├─ fetch_pending(limit=100)
                     ├─ Storage から最新メモリをバッチフェッチ
                     ├─ GraphSyncService.bulk_merge_memories()
                     │     └─ UNWIND + MERGE via Neo4jGraphAdapter
                     └─ 成功: Outbox レコード削除 / 失敗: Exponential Backoff
```

#### Read (両モード共通)

```text
RetrievalPipeline.search()
  ├─ VectorSearch (Storage)          → results_v
  ├─ KeywordSearch (Storage)         → results_k
  ├─ GraphTraversal (Neo4j)          → results_g
  │     └─ 失敗/空: WARNING ログ → results_g = []
  └─ RRF Fusion (v + k + g)         → final results
```

既存のグレースフルデグラデーションにより、Neo4j 未反映のメモリも
VectorSearch / KeywordSearch で補完される。

### 2.3 コンポーネント責務

| コンポーネント | 責務 |
| --- | --- |
| **Storage Layer** | Source of Truth。メモリ永続化 + Outbox 書き込み（同一 TX） |
| **GraphSyncOutbox テーブル** | グラフ同期イベントの一時キュー |
| **OutboxWorker** | バックグラウンド polling + Neo4j バルク同期 |
| **GraphSyncService** | Storage → Neo4j の MERGE Cypher 変換（Worker + リカバリスクリプト共有） |
| **Neo4j Aura** | Traversal Index。最小プロパティ (id, memory_type, created_at, project, tags) のみ |

## 3. データモデル

### 3.1 GraphSyncOutbox テーブル

| カラム | PostgreSQL 型 | SQLite 型 | 説明 |
| --- | --- | --- | --- |
| `id` | UUID PK (gen_random_uuid()) | TEXT PK | イベント一意識別子 |
| `event_type` | VARCHAR(20) CHECK | TEXT CHECK | `SYNC_MEMORY` / `DELETE_MEMORY` |
| `memory_id` | UUID | TEXT | 対象メモリ ID (FK ではない) |
| `payload` | JSONB DEFAULT '{}' | TEXT DEFAULT '{}' | DELETE_MEMORY 時のメタデータ等 |
| `status` | VARCHAR(20) DEFAULT 'PENDING' | TEXT DEFAULT 'PENDING' | PENDING / PROCESSING / FAILED |
| `retry_count` | INT DEFAULT 0 | INTEGER DEFAULT 0 | リトライ回数 |
| `next_retry_at` | TIMESTAMPTZ DEFAULT NOW() | TEXT (ISO8601, DEFAULT now) | 次回リトライ可能時刻。Backoff を DB レベルで永続化 |
| `error_message` | TEXT NULL | TEXT NULL | 最後のエラー詳細 |
| `created_at` | TIMESTAMPTZ DEFAULT NOW() | TEXT (ISO8601) | イベント作成時刻 |
| `updated_at` | TIMESTAMPTZ DEFAULT NOW() | TEXT (ISO8601) | 最終更新時刻 |

**インデックス:**
- `(status, next_retry_at ASC)` — ワーカーの PENDING フェッチ用 (Backoff 対応)
- `(memory_id)` — 運用/障害調査クエリ用 (例: 特定メモリのイベント履歴を引く)。
  書き込み時の重複チェックには使用しない。詳細は §3.4 を参照

### 3.2 イベント粒度: 粗粒度モデル

| イベント | 意味 | ワーカーの動作 |
| --- | --- | --- |
| `SYNC_MEMORY` | メモリのノード + 関連エッジを同期 | Storage から最新状態フェッチ → MERGE |
| `DELETE_MEMORY` | ノード + 関連エッジを削除 | DETACH DELETE |

粗粒度を採用する理由:
- Graph は Index であり Event Store ではない。目的は「状態の同期」
- 順序性の罠を回避 (細粒度だと CREATE_NODE と CREATE_EDGE の処理順序逆転でクラッシュ)
- リカバリスクリプトとロジック完全共有 (MERGE ベースの冪等同期)

### 3.3 memory_id を FK にしない理由

`DELETE_MEMORY` イベントの処理時にメモリが既に削除されている。FK 制約があると
Outbox レコードが cascade 削除され、ワーカーが Neo4j 側のノード削除を実行できなくなる。

### 3.4 重複イベントの収束契約

#### 設計判断: 「dedup-at-convergence」を採用、「dedup-at-insert」は採用しない

同一 `memory_id` に対する複数の `SYNC_MEMORY` イベントが Outbox に並存することを
**意図的に許容する**。重複そのものを書き込み時に防ぐのではなく、ワーカー側で
最新状態を再フェッチして MERGE することにより収束させる。根拠は以下のとおり。

- **MERGE の冪等性**: §8.2 `bulk_merge_memories` は Cypher `MERGE` ベースで、
  同一ノードへの複数 MERGE は副作用を持たない
- **最新状態の再取得**: §7.3 ステップ2 のとおり、ワーカーはイベント処理時に
  `StorageAdapter.get_memories_batch()` で Storage から最新メモリを取得する。
  古い `SYNC_MEMORY` イベントを処理しても、結果は常に「現時点の Storage 状態」と一致する
- **Storage TX の単純化**: §1.2 の核心は「メモリ保存と Outbox 書き込みを同一 TX で
  Atomic に実行する」点にある。UNIQUE 制約や `SELECT FOR UPDATE` を Outbox に挿入する
  経路に持ち込むと、メモリ書き込み TX が Outbox 由来で失敗し得る経路を生み、
  Atomicity 保証の実効性が損なわれる

#### UNIQUE 制約 + UPSERT を採用しない理由

`UNIQUE (memory_id, event_type)` + `ON CONFLICT DO UPDATE` 案は以下の副作用を持つため
不採用とする。

- **PROCESSING との競合**: PROCESSING 中のレコードを UPSERT で上書きすると、
  ワーカーが保持している retry_count / next_retry_at の進行状態と DB 状態が乖離し、
  二重処理 or 古い状態への巻き戻しが発生する
- **FAILED 残骸との衝突**: 過去の FAILED が残存する間、新規 `SYNC_MEMORY` 書き込みが
  UPSERT パス上で待機 or 既存レコード書き換えとなり、メモリ書き込み TX のレイテンシと
  失敗確率が上昇する
- **DELETE_MEMORY との順序問題**: `SYNC_MEMORY` と `DELETE_MEMORY` を別行として
  保持しないと、削除イベントが UPSERT で打ち消される可能性がある（event_type を
  UNIQUE キーに含めれば回避できるが、書き込み経路の分岐が増える）

#### 重複時の正規動作

| ケース | 動作 |
|---|---|
| 同一 `memory_id` に複数の PENDING が並存 | `fetch_pending` で `next_retry_at` 昇順に取得し、それぞれ MERGE。最後に処理されたイベントの結果が最終状態と一致 |
| 同一 `memory_id` に PROCESSING + PENDING が並存 | PROCESSING はそのまま完走させ、PENDING は次サイクルで処理。MERGE 冪等性により問題なし |
| 同一 `memory_id` に FAILED + PENDING が並存 | PENDING を通常処理（FAILED は §7.6 によりスキップされ、`--catchup` で再処理） |
| `SYNC_MEMORY` と `DELETE_MEMORY` が並存 | `next_retry_at` 昇順、すなわち挿入順に処理。最終的に DELETE が反映されれば DETACH DELETE が後勝ち |

#### `(memory_id)` インデックスの実際の用途

`(memory_id)` インデックスは **書き込み時の重複制御には使わない**。実用途は以下に限定される。

- 運用/障害調査クエリ: `SELECT * FROM graph_sync_outbox WHERE memory_id = ?`
- リカバリスクリプト (`--catchup`) の追跡調査
- 将来追加候補の `--reconcile` モード (§10.1.1) における集合差分計算

#### 受け入れたトレードオフ

- ✅ Storage TX を単純な無条件 INSERT に保ち、Atomicity 保証の経路を最短化
- ✅ ワーカー側ロジックを変更せず水平スケール (`FOR UPDATE SKIP LOCKED`) と両立
- ⚠️ 同一メモリに対する冗長な MERGE が発生し得る。Neo4j への RTT が1回分余計に走るが、
  MERGE は冪等であり、性能上のオーバーヘッドのみ（数 ms 程度）。データ整合性への影響なし
- ⚠️ Outbox テーブル行数の短期的増加。`delete_completed` により処理成功イベントは
  即時削除されるため、定常状態では PENDING + FAILED + PROCESSING の合計のみが残る

## 4. マイグレーション

### 4.1 PostgreSQL

ファイル: `src/context_store/storage/migrations/postgres/0003_graph_sync_outbox.sql`

```sql
CREATE TABLE graph_sync_outbox (
    id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type    VARCHAR(20)  NOT NULL CHECK (event_type IN ('SYNC_MEMORY', 'DELETE_MEMORY')),
    memory_id     UUID         NOT NULL,
    payload       JSONB        NOT NULL DEFAULT '{}',
    status        VARCHAR(20)  NOT NULL DEFAULT 'PENDING'
                               CHECK (status IN ('PENDING', 'PROCESSING', 'FAILED')),
    retry_count   INT          NOT NULL DEFAULT 0,
    next_retry_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    error_message TEXT,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_outbox_status_retry ON graph_sync_outbox (status, next_retry_at ASC);
CREATE INDEX idx_outbox_memory_id ON graph_sync_outbox (memory_id);
```

### 4.2 SQLite

ファイル: `src/context_store/storage/migrations/sqlite/0003_graph_sync_outbox.sql`

```sql
CREATE TABLE graph_sync_outbox (
    id            TEXT PRIMARY KEY,
    event_type    TEXT NOT NULL CHECK (event_type IN ('SYNC_MEMORY', 'DELETE_MEMORY')),
    memory_id     TEXT NOT NULL,
    payload       TEXT NOT NULL DEFAULT '{}',
    status        TEXT NOT NULL DEFAULT 'PENDING'
                       CHECK (status IN ('PENDING', 'PROCESSING', 'FAILED')),
    retry_count   INTEGER NOT NULL DEFAULT 0,
    next_retry_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    error_message TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_outbox_status_retry ON graph_sync_outbox (status, next_retry_at);
CREATE INDEX idx_outbox_memory_id ON graph_sync_outbox (memory_id);
```

### 4.3 Supabase

ファイル: `supabase/migrations/20260521000001_graph_sync_outbox.sql`

テーブル定義は PostgreSQL と同一。加えて以下の RPC 関数を追加:

```sql
-- メモリ UPSERT + Outbox 書き込みをアトミックに実行
CREATE OR REPLACE FUNCTION upsert_memory_with_outbox(
    p_id            UUID,
    p_content       TEXT,
    p_memory_type   VARCHAR(20),
    p_source_type   VARCHAR(20),
    p_source_metadata JSONB,
    p_embedding     vector(768),
    p_semantic_relevance FLOAT,
    p_importance_score   FLOAT,
    p_tags          TEXT[],
    p_project       TEXT,
    p_content_hash  TEXT
)
RETURNS UUID
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
DECLARE
    v_memory_id UUID;
BEGIN
    INSERT INTO memories (
        id, content, memory_type, source_type, source_metadata,
        embedding, semantic_relevance, importance_score,
        tags, project, content_hash
    ) VALUES (
        p_id, p_content, p_memory_type, p_source_type, p_source_metadata,
        p_embedding, p_semantic_relevance, p_importance_score,
        p_tags, p_project, p_content_hash
    )
    ON CONFLICT (id) DO UPDATE SET
        content            = EXCLUDED.content,
        memory_type        = EXCLUDED.memory_type,
        source_type        = EXCLUDED.source_type,
        source_metadata    = EXCLUDED.source_metadata,
        embedding          = EXCLUDED.embedding,
        semantic_relevance = EXCLUDED.semantic_relevance,
        importance_score   = EXCLUDED.importance_score,
        tags               = EXCLUDED.tags,
        project            = EXCLUDED.project,
        content_hash       = EXCLUDED.content_hash,
        updated_at         = NOW()
    RETURNING id INTO v_memory_id;

    INSERT INTO graph_sync_outbox (event_type, memory_id)
    VALUES ('SYNC_MEMORY', v_memory_id);

    RETURN v_memory_id;
END;
$$;

-- メモリ削除 + Outbox 書き込みをアトミックに実行
CREATE OR REPLACE FUNCTION delete_memory_with_outbox(
    p_memory_id UUID
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
DECLARE
    v_meta JSONB;
    affected INTEGER;
BEGIN
    SELECT jsonb_build_object(
        'memory_type', memory_type,
        'tags', to_jsonb(tags),
        'project', project
    ) INTO v_meta
    FROM memories WHERE id = p_memory_id;

    DELETE FROM memories WHERE id = p_memory_id;
    GET DIAGNOSTICS affected = ROW_COUNT;

    IF affected > 0 THEN
        INSERT INTO graph_sync_outbox (event_type, memory_id, payload)
        VALUES ('DELETE_MEMORY', p_memory_id, COALESCE(v_meta, '{}'));
    END IF;

    RETURN affected > 0;
END;
$$;

GRANT EXECUTE ON FUNCTION upsert_memory_with_outbox(UUID, TEXT, VARCHAR, VARCHAR, JSONB, vector, FLOAT, FLOAT, TEXT[], TEXT, TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION delete_memory_with_outbox(UUID) TO service_role;

-- メモリ FK の無い Outbox に対するワーカー側操作は PostgREST + RPC を併用する。
-- 状態遷移を伴う fetch_pending と reset_stuck_processing は単一 TX が必要なため RPC、
-- それ以外（delete_completed / mark_failed / reset_to_pending / fetch_all_actionable）は
-- supabase-py の table().update()/delete()/select() で直接実行する。

CREATE OR REPLACE FUNCTION fetch_pending_outbox(p_limit INT)
RETURNS TABLE (
    id            UUID,
    event_type    VARCHAR(20),
    memory_id     UUID,
    payload       JSONB,
    status        VARCHAR(20),
    retry_count   INT,
    next_retry_at TIMESTAMPTZ,
    created_at    TIMESTAMPTZ,
    updated_at    TIMESTAMPTZ,
    error_message TEXT
)
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
BEGIN
    RETURN QUERY
    UPDATE graph_sync_outbox o
    SET status = 'PROCESSING', updated_at = NOW()
    WHERE o.id IN (
        SELECT inner_o.id FROM graph_sync_outbox inner_o
        WHERE inner_o.status = 'PENDING'
          AND inner_o.next_retry_at <= NOW()
        ORDER BY inner_o.next_retry_at ASC
        LIMIT p_limit
        FOR UPDATE SKIP LOCKED
    )
    RETURNING o.id, o.event_type, o.memory_id, o.payload, o.status,
              o.retry_count, o.next_retry_at, o.created_at, o.updated_at, o.error_message;
END;
$$;

CREATE OR REPLACE FUNCTION reset_stuck_processing_outbox(
    p_threshold_seconds INT,
    p_max_retries INT
)
RETURNS INT
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
DECLARE
    failed_count INT;
    pending_count INT;
BEGIN
    UPDATE graph_sync_outbox
    SET status = 'FAILED',
        error_message = 'Recovered from stuck PROCESSING (max retries)',
        updated_at = NOW()
    WHERE status = 'PROCESSING'
      AND updated_at < NOW() - (p_threshold_seconds || ' seconds')::interval
      AND retry_count + 1 > p_max_retries;
    GET DIAGNOSTICS failed_count = ROW_COUNT;

    UPDATE graph_sync_outbox
    SET status = 'PENDING',
        retry_count = retry_count + 1,
        updated_at = NOW()
    WHERE status = 'PROCESSING'
      AND updated_at < NOW() - (p_threshold_seconds || ' seconds')::interval;
    GET DIAGNOSTICS pending_count = ROW_COUNT;

    RETURN failed_count + pending_count;
END;
$$;

GRANT EXECUTE ON FUNCTION fetch_pending_outbox(INT) TO service_role;
GRANT EXECUTE ON FUNCTION reset_stuck_processing_outbox(INT, INT) TO service_role;
```

### 4.4 MigrationRunner への影響

`runner.py` の `_handle_baseline` 内 `requirements` マッピングに追加:

```python
"0003": ["graph_sync_outbox"],
```

それ以外の MigrationRunner 変更は不要。

## 5. Config 拡張

### 5.1 新規設定フィールド

`src/context_store/config.py` の `Settings` クラスに追加:

| フィールド | 型 | デフォルト | 環境変数 |
| --- | --- | --- | --- |
| `graph_sync_mode` | `Literal["sync", "async_outbox"]` | `"sync"` | `GRAPH_SYNC_MODE` |
| `outbox_poll_interval_seconds` | `float` | `5.0` | `OUTBOX_POLL_INTERVAL_SECONDS` |
| `outbox_batch_size` | `int` | `100` | `OUTBOX_BATCH_SIZE` |
| `outbox_max_retries` | `int` | `10` | `OUTBOX_MAX_RETRIES` |
| `outbox_backoff_base_seconds` | `float` | `1.0` | `OUTBOX_BACKOFF_BASE_SECONDS` |
| `outbox_backoff_max_seconds` | `float` | `60.0` | `OUTBOX_BACKOFF_MAX_SECONDS` |

### 5.2 バリデーションルール

```python
@model_validator(mode="after")
def _validate_graph_sync_mode(self) -> Self:
    if self.graph_sync_mode == "async_outbox" and not self.graph_enabled:
        raise ValueError("graph_sync_mode='async_outbox' requires graph_enabled=true")
    if (
        self.storage_backend == "supabase"
        and self.graph_enabled
        and self.graph_sync_mode != "async_outbox"
    ):
        raise ValueError(
            "Supabase + graph requires graph_sync_mode='async_outbox'"
        )
    return self
```

### 5.3 Factory ルーティング変更

| storage_backend | graph_enabled | graph_sync_mode | グラフアダプタ |
| --- | --- | --- | --- |
| `sqlite` | `true` | `sync` | SQLiteGraphAdapter (既存) |
| `sqlite` | `true` | `async_outbox` | SQLiteGraphAdapter (ローカル) + Neo4j (Worker)。Devcontainer テスト用途や、ローカル Storage + クラウド Graph のハイブリッド構成向け |
| `postgres` | `true` | `sync` | Neo4jGraphAdapter (直接) |
| `postgres` | `true` | `async_outbox` | PostgresGraphAdapter (ローカル) + Neo4j (Worker) |
| `supabase` | `true` | `async_outbox` | Neo4j (Worker 経由のみ) |
| `supabase` | `true` | `sync` | **バリデーションエラー** |

`async_outbox` モード時、Factory は追加で以下を生成:
- `OutboxWriter` インスタンス → StorageAdapter に注入
- `Neo4jGraphAdapter` インスタンス → Worker が使用

## 6. モジュール構成

### 6.1 新規モジュール

```text
src/context_store/sync/
├── __init__.py
├── models.py              # OutboxEvent / EventType / EventStatus データクラス
├── outbox_writer.py       # OutboxWriter Protocol + PostgresOutboxWriter / SqliteOutboxWriter
├── outbox_reader.py       # OutboxReader Protocol + Postgres / Sqlite / Supabase 各実装
├── outbox_worker.py       # ポーリングループ + バッチ処理 + Backoff
└── graph_sync.py          # GraphSyncService (MERGE Cypher 組み立て、Worker + スクリプト共有)
```

### 6.2 OutboxWriter (書き込み側)

各 StorageAdapter のトランザクション内で呼び出される。

```python
class OutboxWriter(Protocol):
    async def enqueue_sync(
        self,
        conn: Any,
        memory_id: str,
        event_type: str,
        payload: dict | None = None,
    ) -> None: ...
```

- **PostgresOutboxWriter**: `conn.execute()` で asyncpg コネクション内に INSERT
- **SqliteOutboxWriter**: `conn.execute()` で aiosqlite コネクション内に INSERT
- **Supabase**: OutboxWriter 不使用。RPC 関数 `upsert_memory_with_outbox` /
  `delete_memory_with_outbox` がサーバーサイドで Atomicity 保証

### 6.3 StorageAdapter への統合

各 StorageAdapter に `outbox_writer: OutboxWriter | None` を注入。

**PostgresStorageAdapter.save_memory() (async_outbox モード時):**

```python
async with self._pool.acquire() as conn:
    async with conn.transaction():
        row_id = await conn.fetchval(insert_sql, ...)
        if self._outbox_writer:
            await self._outbox_writer.enqueue_sync(conn, str(row_id), "SYNC_MEMORY")
```

**PostgresStorageAdapter.delete_memory() (async_outbox モード時):**

```python
async with self._pool.acquire() as conn:
    async with conn.transaction():
        meta = await conn.fetchrow(
            "SELECT memory_type, tags, project FROM memories WHERE id = $1", mid
        )
        await conn.execute("DELETE FROM memories WHERE id = $1", mid)
        if self._outbox_writer:
            await self._outbox_writer.enqueue_sync(
                conn, mid, "DELETE_MEMORY",
                payload=dict(meta) if meta else {},
            )
```

SQLiteStorageAdapter も同一パターン (BEGIN/COMMIT ブロック内)。

SupabaseStorageAdapter は `_outbox_enabled` フラグで RPC 呼び出しに切替:

```python
if self._outbox_enabled:
    result = await self._client.rpc("upsert_memory_with_outbox", {...}).execute()
else:
    # 既存の PostgREST INSERT ロジック
    ...
```

### 6.4 GraphLinker との関係

`async_outbox` モード時、IngestionPipeline は GraphLinker のステップを以下のように制御:

- GraphLinker は **Storage 側のグラフテーブル** (memory_nodes / memory_edges) にのみ書き込む
- Neo4j への直接書き込みはスキップ
- Worker が Storage 側グラフテーブルからエッジ情報を取得し、Neo4j に転写

## 7. OutboxWorker (バックグラウンドワーカー)

### 7.1 ライフサイクル

```text
Orchestrator.start()
  └─ if graph_sync_mode == "async_outbox":
       task_registry.register(outbox_worker.run())

Orchestrator.shutdown()
  └─ outbox_worker.stop()
       └─ asyncio.Event で graceful 停止
```

### 7.2 ポーリングループ

```python
async def run(self) -> None:
    while not self._stop_event.is_set():
        events = await self._reader.fetch_pending(limit=batch_size)
        if events:
            await self._process_batch(events)
        try:
            await asyncio.wait_for(
                self._stop_event.wait(),
                timeout=poll_interval_seconds,
            )
            break
        except asyncio.TimeoutError:
            pass
```

### 7.3 バッチ処理フロー

1. ステータスを `PENDING → PROCESSING` に一括更新
2. `SYNC_MEMORY` イベント: Storage から `get_memories_batch()` で最新メモリ取得
3. `GraphSyncService.bulk_merge_memories()` で Neo4j にバルク MERGE
4. `DELETE_MEMORY` イベント: `GraphSyncService.bulk_delete_nodes()` で DETACH DELETE
5. 成功: Outbox レコード削除
6. 失敗: Exponential Backoff + retry_count インクリメント

### 7.4 Exponential Backoff

- 対象: **Neo4j 接続失敗時のみ** (Outbox DB 読み取り失敗は別次元の問題)
- 計算: `min(base_seconds * 2^retry_count, max_seconds)`
- デフォルト: base=1s, max=60s
- リトライ上限: 10回。超過で `FAILED` ステータスに遷移 (Dead Letter)
- **DB レベルでの永続化**: 失敗時に `next_retry_at = NOW() + backoff_interval` を書き込み、
  `fetch_pending` が `WHERE next_retry_at <= NOW()` でフィルタする。これにより
  Worker のクラッシュ・再起動・水平スケール時にも Backoff 状態が保持される。
  Worker プロセス内のインメモリ待機 (`asyncio.wait_for`) は不要となり、
  ポーリングループは単純に次のサイクルで再チェックするだけでよい

### 7.5 PROCESSING スタックのリカバリ

Worker がステータスを `PROCESSING` に更新した後、Neo4j 同期完了前にクラッシュすると
レコードが `PROCESSING` のまま永久にスタックする。これを防ぐため以下のリカバリ機構を導入する。

**起動時リカバリ**: Worker 起動時（ポーリングループ開始前）に
`self._reader.reset_stuck_processing(threshold_seconds=300)` を呼び出す。
`updated_at` が閾値（デフォルト 300 秒）を超えた `PROCESSING` レコードを検出し、
`retry_count` をインクリメントして `PENDING` にリセットする。
`retry_count >= max_retries` の場合は `FAILED` に遷移させる。

```python
async def run(self) -> None:
    # 起動時: 前回クラッシュで放置された PROCESSING レコードをリカバリ
    recovered = await self._reader.reset_stuck_processing(
        threshold_seconds=300,
        max_retries=self._settings.outbox_max_retries,
    )
    if recovered:
        logger.info(
            "OutboxWorker: recovered stuck PROCESSING events",
            extra={"count": recovered},
        )
    # メインポーリングループ開始
    while not self._stop_event.is_set():
        ...
```

**OutboxReader への追加メソッド**:

```python
async def reset_stuck_processing(
    self, threshold_seconds: int = 300, max_retries: int = 10,
) -> int:
    """updated_at が閾値を超えた PROCESSING レコードをリカバリ。
    retry_count < max_retries → PENDING にリセット (retry_count++)
    retry_count >= max_retries → FAILED に遷移
    リカバリした件数を返す。"""
```

**スキーマへの影響**: 新規カラム不要。既存の `updated_at` を `mark_processing` 時に
`NOW()` に設定するため、これをスタック判定の基準として使用する。

**`fetch_all_actionable` の対象拡張**: リカバリスクリプト (`--catchup`) の
`fetch_all_actionable` は `PENDING` + `FAILED` に加えて `PROCESSING` も取得対象とする。
これにより、Worker クラッシュ後にスクリプトで手動リカバリも可能。

### 7.6 Head-of-Line Blocking 防止

`FAILED` イベントは自動スキップされ、後続イベントの処理を妨げない。
PostgreSQL では `FOR UPDATE SKIP LOCKED` により複数ワーカーの水平スケールにも対応。

### 7.7 OutboxReader Protocol

```python
class OutboxReader(Protocol):
    async def fetch_pending(self, limit: int) -> list[OutboxEvent]: ...
    async def delete_completed(self, event_ids: list[str]) -> None: ...
    async def mark_failed(self, event_id: str, error_message: str) -> None: ...
    async def reset_to_pending(
        self, event_id: str, retry_count: int,
        next_retry_at: datetime, error_message: str,
    ) -> None: ...
    async def fetch_all_actionable(self) -> list[OutboxEvent]: ...
    async def reset_stuck_processing(
        self, threshold_seconds: int = 300, max_retries: int = 10,
    ) -> int: ...
```

PostgreSQL `fetch_pending` 実装:

```sql
UPDATE graph_sync_outbox
SET status = 'PROCESSING', updated_at = NOW()
WHERE id IN (
    SELECT id FROM graph_sync_outbox
    WHERE status = 'PENDING'
      AND next_retry_at <= NOW()
    ORDER BY next_retry_at ASC
    LIMIT $1
    FOR UPDATE SKIP LOCKED
)
RETURNING id, event_type, memory_id, payload, status, retry_count,
          next_retry_at, created_at, updated_at, error_message;
```

`fetch_all_actionable` も同様に `SELECT` 句に `status` カラムを必ず含める。
ハードコードを避け、`OutboxEvent.status` は常に DB 上の実値を反映させる。

### 7.8 Supabase 向け OutboxReader 実装方針

Supabase はクライアントから直接 SQL を実行できず、`asyncpg` の `FOR UPDATE
SKIP LOCKED` を Python から発行できない。そのため `SupabaseOutboxReader` は
**状態遷移を伴う操作は §4.3 で定義した RPC、それ以外は supabase-py の
table API** で実装する。

| メソッド | 実装手段 | 備考 |
| --- | --- | --- |
| `fetch_pending` | RPC `fetch_pending_outbox(p_limit)` | UPDATE + RETURNING を 1 TX |
| `reset_stuck_processing` | RPC `reset_stuck_processing_outbox` | 2 段階 UPDATE を 1 TX |
| `delete_completed` | `client.table("graph_sync_outbox").delete().in_("id", ids)` |  |
| `mark_failed` | `client.table("graph_sync_outbox").update({status:FAILED,...}).eq("id", id)` |  |
| `reset_to_pending` | `client.table("graph_sync_outbox").update({...}).eq("id", id)` |  |
| `fetch_all_actionable` | `client.table("graph_sync_outbox").select("*").in_("status", [...])` | `status` カラムも取得 |

## 8. GraphSyncService (共有同期ロジック)

### 8.1 責務

Storage → Neo4j のノード/エッジ同期ロジック。Worker とリカバリスクリプトの両方から使用。

### 8.2 bulk_merge_memories

```python
async def bulk_merge_memories(self, memories: list[Memory]) -> int:
    # 1. ノードの MERGE (UNWIND バルク)
    cypher_nodes = """
        UNWIND $batch AS row
        MERGE (m:Memory {id: row.id})
        SET m.memory_type = row.memory_type,
            m.created_at  = row.created_at,
            m.project     = row.project,
            m.tags        = row.tags
    """

    # 2. エッジの同期 (Storage 側グラフテーブルから取得 → Neo4j に MERGE)
    #    エッジ種別ごとにグループ化して UNWIND MERGE
```

Neo4j に格納するプロパティは Traversal Index に必要な最小限:
`id`, `memory_type`, `created_at`, `project`, `tags`

content body やベクトル配列は **格納しない**。

### 8.3 bulk_delete_nodes

```python
cypher = """
    UNWIND $ids AS mid
    MATCH (m:Memory {id: mid})
    DETACH DELETE m
"""
```

### 8.4 full_sync_from_storage (リカバリ用)

Storage 全体から Neo4j を再構築。chunk_size=1000 のページネーションで
メモリ枯渇・トランザクションタイムアウトを防止。

冪等性保証: 全操作が MERGE / DETACH DELETE ベースのため、
クラッシュ後の再実行で重複やエラーは発生しない。

### 8.5 Neo4jGraphAdapter への追加

汎用的な書き込み Cypher 実行メソッドを追加:

```python
async def execute_write(self, cypher: str, parameters: dict) -> None:
    """任意の書き込み Cypher を実行。グレースフルデグラデーション付き。"""
```

既存のグレースフルデグラデーションパターン (例外 → WARNING ログ) を踏襲。

## 9. StorageAdapter プロトコルへの追加

### 9.1 get_memories_batch

Worker が SYNC_MEMORY イベントの対象メモリを一括取得するために追加:

```python
async def get_memories_batch(self, memory_ids: list[str]) -> list[Memory]:
    """複数 ID のメモリを一括取得。存在しない ID は結果に含めない。"""
```

| バックエンド | 実装 |
| --- | --- |
| PostgreSQL | `WHERE id = ANY($1::uuid[])` |
| SQLite | チャンク分割 + `WHERE id IN (...)` (変数上限対策) |
| Supabase | `self._client.table("memories").select("*").in_("id", memory_ids)` |

## 10. リカバリスクリプト

### 10.1 CLI インターフェース

ファイル: `scripts/sync_storage_to_neo4j.py`

```text
usage: sync_storage_to_neo4j.py [--full | --catchup] [--chunk-size N]
                                [--dry-run] [--yes]
```

| モード | 動作 |
| --- | --- |
| `--full` | Neo4j を完全パージし、Storage 全体から再構築 |
| `--catchup` | Outbox の PENDING + PROCESSING + FAILED イベントを再処理 |
| `--dry-run` | 実際の書き込みを行わず対象件数のみ出力 |
| `--chunk-size` | バッチサイズ (デフォルト 1000) |
| `--yes` | `--full` 実行時の対話確認をスキップする運用フラグ |

### 10.1.1 `--full` モードの制約とダウンタイム

`--full` は `MATCH (m:Memory) DETACH DELETE m` で全ノードを削除してから順次
MERGE するため、**実行中はグラフ traversal クエリが空結果を返す**。
以下の制約を必ず守る:

- **想定ユースケース**: スキーマ非互換変更後の再構築・データ破損からの災害復旧。
  通常運用での実行は禁止
- **メンテナンス窓口内での実行を必須とする**。ChronosGraph を利用する
  アプリケーション側でグラフ検索が一時的に空結果を返す前提のスケジュールを組む
- 実行前に `--dry-run` で対象件数を確認し、`--yes` 未指定時は対話プロンプトで
  オペレータの承認を要求する
- ジョブ実行ログに開始時刻・終了時刻・処理件数を必ず INFO レベルで残す

ダウンタイムレスな差分再同期が必要な場合は将来的に `--reconcile` モード（Storage 全 ID
と Neo4j 全 ID の集合差分を計算し、不足ノードを MERGE / 孤児ノードのみ
DETACH DELETE）を追加することを検討する。本リリースでは含まない。

### 10.2 冪等性

全操作が Cypher MERGE / DETACH DELETE ベースのため、クラッシュ・再実行・重複実行に安全。

### 10.3 FAILED イベントの運用フロー

1. `FAILED` イベントは Worker が自動スキップ
2. 管理者が `error_message` カラムで原因調査
3. 修正後 `--catchup` で FAILED イベントを再処理
4. あるいは `--full` で完全再構築

## 11. 読み取りフォールバック

### 11.1 既存メカニズムで十分

現在の RetrievalPipeline は GraphTraversal が失敗/空の場合でも
VectorSearch + KeywordSearch の RRF 合成で結果を返す。

`async_outbox` モードのラグ (数秒) で Neo4j 未反映のメモリは、
Storage 側の VectorSearch / KeywordSearch から即座に発見される。

### 11.2 追加ログ

`async_outbox` モード時にグラフ検索結果が 0 件の場合、INFO ログを出力:

```text
Graph traversal returned empty results; outbox sync lag may be a factor.
Falling back to vector+keyword fusion.
```

## 12. テスト戦略

### 12.1 テスト階層

```text
tests/
├── unit/
│   ├── sync/
│   │   ├── test_outbox_writer.py      # OutboxWriter の各バックエンド実装
│   │   ├── test_outbox_worker.py      # ポーリングループ・リトライ・Backoff
│   │   └── test_graph_sync.py         # Cypher 組み立て・バルク操作
│   ├── storage/
│   │   ├── test_postgres_outbox.py    # save_memory + Outbox の同一 TX 保証
│   │   ├── test_sqlite_outbox.py      # 同上 (SQLite)
│   │   └── test_supabase_outbox.py    # RPC 呼び出し検証
│   └── test_config_graph_sync.py      # バリデーションルール
└── integration/
    └── test_outbox_e2e.py             # SQLite で全サイクル結合テスト
```

### 12.2 ユニットテスト主要ケース

**OutboxWorker:**

| テストケース | 検証内容 |
| --- | --- |
| `test_worker_processes_pending_events` | PENDING → Neo4j 同期 → 削除 |
| `test_worker_skips_when_no_events` | 空キュー時にポーリング間隔待機 |
| `test_worker_retries_on_neo4j_failure` | Neo4j 例外 → retry_count++ → PENDING |
| `test_worker_marks_failed_after_max_retries` | retry >= 10 → FAILED |
| `test_worker_exponential_backoff` | base * 2^retry、max 超えない |
| `test_worker_graceful_shutdown` | stop() → バッチ完了後ループ終了 |
| `test_worker_orphaned_sync_event` | 削除済みメモリ → イベント削除して続行 |
| `test_worker_recovers_stuck_processing_on_startup` | 起動時に stale PROCESSING → PENDING リセット |
| `test_worker_fails_stuck_processing_at_max_retries` | stale PROCESSING + retry >= 10 → FAILED |

**Config バリデーション:**

| テストケース | 検証内容 |
| --- | --- |
| `test_async_outbox_requires_graph_enabled` | async_outbox + graph_enabled=false → ValueError |
| `test_supabase_graph_requires_async_outbox` | supabase + graph + sync → ValueError |
| `test_sync_mode_default` | デフォルトが sync |

### 12.3 結合テスト

SQLite + Mock Neo4j で Outbox サイクル全体を検証:
メモリ保存 → Outbox PENDING 確認 → Worker バッチ処理 → Neo4j モック呼び出し確認 → Outbox 空確認

### 12.4 テスト方針

- Neo4j は常にモック (実接続不要)
- SQLite はインメモリ (`:memory:`)
- 既存の conftest.py フィクスチャパターンを踏襲

## 13. 変更対象ファイル一覧

### 13.1 新規作成

| ファイル | 内容 |
| --- | --- |
| `src/context_store/sync/__init__.py` | パッケージ初期化 |
| `src/context_store/sync/outbox_writer.py` | OutboxWriter Protocol + Postgres/SQLite 実装 |
| `src/context_store/sync/outbox_worker.py` | ポーリングループ + バッチ処理 |
| `src/context_store/sync/graph_sync.py` | GraphSyncService |
| `src/context_store/storage/migrations/postgres/0003_graph_sync_outbox.sql` | PostgreSQL マイグレーション |
| `src/context_store/storage/migrations/sqlite/0003_graph_sync_outbox.sql` | SQLite マイグレーション |
| `supabase/migrations/20260521000001_graph_sync_outbox.sql` | Supabase マイグレーション + RPC |
| `scripts/sync_storage_to_neo4j.py` | リカバリ CLI |
| `tests/unit/sync/test_outbox_writer.py` | OutboxWriter テスト |
| `tests/unit/sync/test_outbox_worker.py` | OutboxWorker テスト |
| `tests/unit/sync/test_graph_sync.py` | GraphSyncService テスト |
| `tests/unit/storage/test_postgres_outbox.py` | PostgreSQL Outbox 統合テスト |
| `tests/unit/storage/test_sqlite_outbox.py` | SQLite Outbox 統合テスト |
| `tests/unit/storage/test_supabase_outbox.py` | Supabase RPC テスト |
| `tests/unit/test_config_graph_sync.py` | Config バリデーションテスト |
| `tests/integration/test_outbox_e2e.py` | 結合テスト |

### 13.2 既存ファイル変更

| ファイル | 変更内容 |
| --- | --- |
| `src/context_store/config.py` | graph_sync_mode + outbox_* 設定追加、バリデーション追加 |
| `src/context_store/storage/factory.py` | async_outbox 時の OutboxWriter 生成、Supabase+graph 解禁 |
| `src/context_store/storage/postgres.py` | OutboxWriter 注入、save_memory/delete_memory のトランザクション拡張 |
| `src/context_store/storage/sqlite.py` | 同上 (SQLite 版) |
| `src/context_store/storage/supabase.py` | RPC 呼び出し切替 (_outbox_enabled) |
| `src/context_store/storage/protocols.py` | get_memories_batch 追加 |
| `src/context_store/storage/neo4j.py` | execute_write メソッド追加 |
| `src/context_store/storage/migrations/runner.py` | baseline requirements に 0003 追加 |
| `src/context_store/orchestrator.py` | async_outbox 時の Worker 起動/停止 |
| `src/context_store/ingestion/pipeline.py` | async_outbox 時の GraphLinker 制御 |
