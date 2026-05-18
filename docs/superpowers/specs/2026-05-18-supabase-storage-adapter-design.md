# Supabase Storage Adapter — 設計仕様書

| 項目 | 内容 |
| --- | --- |
| Spec ID | 2026-05-18-supabase-storage-adapter-design |
| Status | Approved (Design Phase) |
| 作成日 | 2026-05-18 |
| 関連 Spec | `2026-05-12-prisma-adapter-design.md` (置換対象) |
| 想定実装 | `src/context_store/storage/supabase.py` (新規) |

## 1. 背景と目的

### 1.1 課題
社内ネットワークポリシーにより PostgreSQL の直接接続 (TCP port 5432) が完全に遮断されている。現行の Prisma Accelerate (`prisma-client-py`) ベースのストレージバックエンドは HTTPS 経由で動作するが、Prisma ランタイム同梱の Rust エンジン・スキーマ二重管理・Accelerate 固有のサイズ/タイムアウト制約 (P6004/P6009 等) によりメンテナンスコストが高い。

### 1.2 目的
Supabase Data API (PostgREST) を利用したストレージアダプタへ置き換え、以下を達成する。
- **接続**: HTTPS (port 443) のみで全操作を完結
- **クライアント**: `supabase>=2.4.0` の公式 async クライアント (`create_async_client`) を採用
- **既存プロトコル互換**: `StorageAdapter` Protocol (`src/context_store/storage/protocols.py`) に完全準拠
- **アトミック性**: HTTP の Read-Modify-Write 競合を Postgres 関数 (RPC) で回避

## 2. スコープ

### 2.1 対象
- 新規ファイル: `src/context_store/storage/supabase.py` (`SupabaseStorageAdapter`)
- 新規 SQL: `supabase/migrations/20260518000001_initial_schema.sql`、`supabase/migrations/20260518000002_rpc_functions.sql`
- 変更: `pyproject.toml`、`src/context_store/config.py`、`src/context_store/storage/factory.py`
- 削除: `src/context_store/storage/prisma.py`、`prisma/schema.prisma`、関連テスト

### 2.2 対象外
- 既存データの Prisma Accelerate → Supabase 移行（手動 `pg_dump`/`pg_restore`）
- Supabase RLS (Row Level Security) ポリシーの定義（後続スコープ）
- `STORAGE_BACKEND=prisma` の後方互換維持 (clean break)
- ライブ統合テストの CI 組み込み (オプションのみ提供)

## 3. アーキテクチャ

### 3.1 コンポーネント図

```
┌────────────────────────────────────────────────────────────┐
│                    Application (Python 3.12+)              │
│  Orchestrator / MCP Server                                 │
│      │                                                     │
│  factory.py: _create_storage_adapter()                     │
│      │   storage_backend == "supabase"                     │
│  SupabaseStorageAdapter (storage/supabase.py)              │
│      │   - AsyncClient (supabase-py v2.4+)                 │
│      │   - postgres_helpers 再利用                          │
└──────┼─────────────────────────────────────────────────────┘
       │ HTTPS (port 443)
       ▼
┌────────────────────────────────────────────────────────────┐
│           Supabase Project (managed PostgreSQL)            │
│  PostgREST  (/rest/v1/memories, /rest/v1/rpc/*)            │
│  PostgreSQL + pgvector + pg_trgm                           │
│      - memories テーブル (vector(768))                       │
│      - RPC: vector_search, increment_memory_access_count   │
└────────────────────────────────────────────────────────────┘
```

### 3.2 主要決定事項
| 決定 | 採用案 | 根拠 |
| --- | --- | --- |
| クライアント初期化 | `classmethod .create(settings)` パターン | 既存 `PrismaStorageAdapter` と一貫、factory が同期コードのまま |
| ベクトル検索 | Postgres RPC `vector_search` | PostgREST 経由で pgvector の `<=>` 演算子を利用 |
| 起動時検証 | 薄い probe (初回呼出時に検知) | シンプル、Supabase CLI で事前適用が前提 |
| 入力順保持 | `dict[uuid -> Memory]` + 入力順走査 | Prisma 実装踏襲 |
| アトミック increment | RPC 関数 + `UPDATE ... + 1` | HTTP RMW 競合の根本回避 |
| エラー分類 | Prisma 実装と同等カテゴリ | サービスレイヤ互換 |
| 埋め込み次元 | `vector(768)` 固定 | 現行 `0001_initial.sql` と一致 |

## 4. データベース層 (SQL)

### 4.1 配置
プロジェクトルートに `supabase/migrations/` を新設。Supabase CLI 規約 `YYYYMMDDHHMMSS_<description>.sql`。

```
supabase/
└── migrations/
    ├── 20260518000001_initial_schema.sql
    └── 20260518000002_rpc_functions.sql
```

### 4.2 `20260518000001_initial_schema.sql`

```sql
-- pgvector + pg_trgm 拡張
CREATE EXTENSION IF NOT EXISTS "vector";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- memories テーブル
CREATE TABLE IF NOT EXISTS memories (
    id                 UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    content            TEXT         NOT NULL,
    memory_type        VARCHAR(20)  NOT NULL CHECK (
        memory_type IN ('episodic', 'semantic', 'procedural')
    ),
    source_type        VARCHAR(20)  NOT NULL CHECK (
        source_type IN ('conversation', 'manual', 'url')
    ),
    source_metadata    JSONB        DEFAULT '{}',
    embedding          vector(768),
    semantic_relevance FLOAT        NOT NULL DEFAULT 0.5
                       CHECK (semantic_relevance >= 0 AND semantic_relevance <= 1),
    importance_score   FLOAT        NOT NULL DEFAULT 0.5
                       CHECK (importance_score >= 0 AND importance_score <= 1),
    access_count       INT          NOT NULL DEFAULT 0 CHECK (access_count >= 0),
    last_accessed_at   TIMESTAMPTZ  DEFAULT NOW(),
    created_at         TIMESTAMPTZ  DEFAULT NOW(),
    updated_at         TIMESTAMPTZ  DEFAULT NOW(),
    archived_at        TIMESTAMPTZ,
    tags               TEXT[]       DEFAULT '{}',
    project            TEXT,
    content_hash       TEXT         NOT NULL UNIQUE
);

-- B-tree indexes
CREATE INDEX IF NOT EXISTS idx_memories_memory_type    ON memories (memory_type);
CREATE INDEX IF NOT EXISTS idx_memories_source_type    ON memories (source_type);
CREATE INDEX IF NOT EXISTS idx_memories_archived_at    ON memories (archived_at);
CREATE INDEX IF NOT EXISTS idx_memories_project        ON memories (project);
CREATE INDEX IF NOT EXISTS idx_memories_created_at     ON memories (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_created_at_id  ON memories (created_at ASC, id ASC);
CREATE INDEX IF NOT EXISTS idx_memories_tags_gin       ON memories USING gin (tags);

-- HNSW vector index
CREATE INDEX IF NOT EXISTS idx_memories_embedding_hnsw
    ON memories USING hnsw (embedding vector_cosine_ops);

-- Full-text search (pg_trgm)
CREATE INDEX IF NOT EXISTS idx_memories_content_fts
    ON memories USING gin (content gin_trgm_ops);
```

### 4.3 `20260518000002_rpc_functions.sql`

```sql
-- ============================================================
-- vector_search: pgvector の <=> (cosine distance) を使って
-- 上位 K 件取得。score = 1 - distance でコサイン類似度を返す。
-- p_project が NULL なら全プロジェクト対象。
-- ============================================================
CREATE OR REPLACE FUNCTION vector_search(
    query_embedding vector(768),
    match_count     integer,
    p_project       text DEFAULT NULL
)
RETURNS TABLE (
    id                 uuid,
    content            text,
    memory_type        varchar,
    source_type        varchar,
    source_metadata    jsonb,
    embedding          vector(768),
    semantic_relevance float,
    importance_score   float,
    access_count       integer,
    last_accessed_at   timestamptz,
    created_at         timestamptz,
    updated_at         timestamptz,
    archived_at        timestamptz,
    tags               text[],
    project            text,
    content_hash       text,
    score              float
)
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path = public
AS $$
    SELECT
        m.id, m.content, m.memory_type, m.source_type, m.source_metadata,
        m.embedding, m.semantic_relevance, m.importance_score, m.access_count,
        m.last_accessed_at, m.created_at, m.updated_at, m.archived_at,
        m.tags, m.project, m.content_hash,
        (1 - (m.embedding <=> query_embedding))::float AS score
    FROM memories m
    WHERE m.archived_at IS NULL
      AND m.embedding IS NOT NULL
      AND (p_project IS NULL OR m.project = p_project)
    ORDER BY m.embedding <=> query_embedding
    LIMIT match_count;
$$;

-- ============================================================
-- increment_memory_access_count: アトミック increment + 時刻更新
-- ============================================================
CREATE OR REPLACE FUNCTION increment_memory_access_count(
    p_memory_id uuid
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
DECLARE
    affected integer;
BEGIN
    UPDATE memories
       SET access_count     = access_count + 1,
           last_accessed_at = NOW(),
           updated_at       = NOW()
     WHERE id = p_memory_id;

    GET DIAGNOSTICS affected = ROW_COUNT;
    RETURN affected > 0;
END;
$$;

-- 権限付与
GRANT EXECUTE ON FUNCTION vector_search(vector, integer, text)
    TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION increment_memory_access_count(uuid)
    TO anon, authenticated, service_role;
```

### 4.4 設計上の SQL ノート
- `vector_search` は `LANGUAGE sql STABLE` で副作用なし宣言（プランナ最適化）
- `SECURITY INVOKER` で RLS 適用時に呼出元権限で実行
- `SET search_path = public` で関数経由のスキーマ汚染攻撃を防止 (Supabase 公式推奨)
- `keyword_search` は専用 RPC を作らず、PostgREST の `ilike` フィルタで対応

## 5. Python 実装

### 5.1 モジュール構造 (`src/context_store/storage/supabase.py`)

```python
from __future__ import annotations
import logging
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

try:
    from supabase import AsyncClient, create_async_client
    from postgrest.exceptions import APIError as PostgrestAPIError
    _supabase_available = True
except ImportError:
    AsyncClient = Any   # type: ignore
    PostgrestAPIError = Exception  # type: ignore
    _supabase_available = False

from context_store.config import Settings
from context_store.storage.postgres_helpers import (
    _content_hash, _embedding_to_pg, _record_to_memory,
)
from context_store.storage.protocols import (
    ALLOWED_SORT_COLUMNS, MemoryFilters, StorageError,
)

if TYPE_CHECKING:
    from context_store.models.memory import Memory, ScoredMemory

logger = logging.getLogger(__name__)

SUPABASE_BATCH_FETCH_CHUNK_SIZE: Final[int] = 200
SUPABASE_MAX_TOP_K: Final[int] = 200
```

### 5.2 クラスシグネチャ

```python
class SupabaseStorageAdapter:
    def __init__(self, client: AsyncClient) -> None: ...

    @classmethod
    async def create(cls, settings: Settings) -> "SupabaseStorageAdapter":
        """
        起動時責務:
          1. supabase ライブラリ存在チェック → ImportError
          2. URL/KEY 検証は Settings 側の validator で済んでいる前提
          3. create_async_client(url, key) で AsyncClient 生成
          4. オプション: get_vector_dimension() で DB 実次元を取得し
             settings.embedding_dimension と照合。不一致なら StorageError(
             code='INVALID_STATE', recoverable=False) で fail-fast。
             ただしテーブル未投入時 (= 既存 embedding がない) は None が返るので
             スキップ。
        """
        ...

    async def dispose(self) -> None: ...

    def _map_to_storage_error(self, exc: Exception) -> StorageError: ...
```

`create()` での次元検証ロジック（擬似コード）:

```python
@classmethod
async def create(cls, settings: Settings) -> "SupabaseStorageAdapter":
    if not _supabase_available:
        raise ImportError("supabase is not installed. ...")
    client = await create_async_client(
        settings.supabase_url, settings.supabase_key.get_secret_value()
    )
    adapter = cls(client)
    try:
        actual_dim = await adapter.get_vector_dimension()
    except Exception as exc:
        # 起動時に DB 接続不能 → 致命的
        await adapter.dispose()
        raise adapter._map_to_storage_error(exc) from exc

    if actual_dim is not None and actual_dim != settings.embedding_dimension:
        await adapter.dispose()
        raise StorageError(
            f"Supabase memories.embedding dimension ({actual_dim}) does not match "
            f"settings.embedding_dimension ({settings.embedding_dimension}). "
            "Apply the matching supabase/migrations SQL or reconcile EMBEDDING_DIMENSION.",
            code="INVALID_STATE",
            recoverable=False,
        )
    return adapter
```

これにより **Settings レベル（次元定数チェック）と DB レベル（実次元チェック）の二重防御** を構築する。

### 5.3 メソッドマッピング

| Protocol メソッド | 実装方式 | 主な API |
| --- | --- | --- |
| `save_memory(memory)` | INSERT 単一行 | `client.table("memories").insert(row).execute()` |
| `get_memory(memory_id)` | UUID 検証後 SELECT | `.select("*").eq("id", uid).maybe_single().execute()` |
| `get_memories_batch(ids)` | 200件チャンクで `in_` | `.select("*").in_("id", chunk).execute()` |
| `delete_memory(memory_id)` | DELETE returning | `.delete(returning="representation").eq("id", uid).execute()` |
| `update_memory(memory_id, updates)` | 列ホワイトリスト → UPDATE | `.update(filtered).eq("id", uid).execute()` |
| `vector_search(...)` | **RPC** `vector_search` | `client.rpc("vector_search", {...}).execute()` |
| `keyword_search(query, top_k, project)` | `ilike` フィルタ | `.ilike("content", f"%{q}%").is_("archived_at","null").limit(k).execute()` |
| `list_by_filter(filters)` | クエリビルダ複合条件 | チェーン構築 → `.execute()` |
| `count_by_filter(filters)` | `count="exact", head=True` | `.select("*", count="exact", head=True)...` |
| `list_projects()` | DISTINCT 相当 | Python 側で `set()` 重複除去 |
| `increment_memory_access_count(id)` | **RPC** | `client.rpc("increment_memory_access_count", ...)` |
| `get_vector_dimension()` | LIMIT 1 で `embedding` 長算出 | `_parse_embedding` 利用 |
| `dispose()` | PostgREST httpx クローズ | `client.postgrest.aclose()` |

### 5.4 エラーマッピング

```python
def _map_to_storage_error(self, exc: Exception) -> StorageError:
    code = getattr(exc, "code", None) or ""
    message = getattr(exc, "message", "") or str(exc)

    if code == "23505":  # unique_violation
        return StorageError(message, code="DUPLICATE_CONTENT", recoverable=False)
    if code in ("22P02", "22023"):
        return StorageError(message, code="INVALID_INPUT", recoverable=False)
    if code == "PGRST116":
        return StorageError(message, code="NOT_FOUND", recoverable=False)

    exc_str = str(exc).lower()
    if any(kw in exc_str for kw in ("timeout", "408", "504", "503", "connecterror")):
        return StorageError(message, code="STORAGE_TIMEOUT", recoverable=True)
    if "413" in exc_str or "payload too large" in exc_str:
        return StorageError(message, code="STORAGE_PAYLOAD_TOO_LARGE", recoverable=True)

    return StorageError(message, code="STORAGE_ERROR", recoverable=True)
```

### 5.5 重要な実装ノート
- **入力順保持** (`get_memories_batch`): `dict[str(UUID), Memory]` 経由で元順序を復元
- **UPDATE 列ホワイトリスト**: Prisma 実装と同じセット。`content` 更新時は `content_hash` 再計算
- **`list_by_filter` カーソル**: `or_("created_at.lt.X,and(created_at.eq.X,id.lt.Y)")` で `(ts, id)` 比較を表現
- **`top_k` clamp**: `SUPABASE_MAX_TOP_K=200` で頭打ち、`logger.warning` 出力
- **`count_by_filter`**: `head=True` で行データを返さず count のみ取得
- **PostgREST URL 長制限**: バッチサイズ 200 件で URL 長 < 8KB
- **機密情報保護**: `SUPABASE_KEY` を例外メッセージ・ログ・スタックトレースに含めない

## 6. 設定・依存関係の変更

### 6.1 `pyproject.toml`

```toml
[project.optional-dependencies]
storage-postgres = [
    "asyncpg>=0.29.0",
    "neo4j>=5.0.0",
    "redis>=5.0.0",
]
# DELETE: storage-prisma
# ADD:
storage-supabase = [
    "supabase>=2.4.0",
]
all = [
    "context-store-mcp[storage-postgres,storage-supabase,embedding-local,embedding-openai,embedding-litellm,dashboard,evaluator]",
]
```

### 6.2 `src/context_store/config.py`

```python
# Literal 変更
storage_backend: Literal["sqlite", "postgres", "supabase"] = "sqlite"

# DELETE: prisma_database_url: SecretStr = SecretStr("")

# ADD:
supabase_url: str = Field(
    default="",
    description="Supabase Project URL (例: https://xxxxx.supabase.co)",
)
supabase_key: SecretStr = Field(
    default=SecretStr(""),
    description="Service Role Key または Anon Key",
)

# CHANGE: embedding_dimension のデフォルト値を 1024 → 768 に修正
# 理由:
#   1. supabase/migrations/20260518000001_initial_schema.sql で vector(768) を定義
#   2. 既存 migrations/postgres/0001_initial.sql も vector(768)
#   3. 現行ローカルモデル cl-nagoya/ruri-v3-310m は 768 次元
# 旧 Prisma schema.prisma の vector(1024) は誤設定（削除対象）。
embedding_dimension: int = Field(default=768, ge=1)
```

`_validate_storage_config` に `supabase` 分岐を追加し、`graph_enabled=true` との併用を拒否。`graph_backend` computed_field も `supabase → "disabled"` を返すよう修正。

加えて、**`embedding_dimension` と Supabase スキーマの不一致を起動前に検出する**ためのバリデーションを追加する:

```python
# Supabase スキーマが期待する次元数 (supabase/migrations と同期)
SUPABASE_VECTOR_DIMENSION: Final[int] = 768

@model_validator(mode="after")
def _validate_storage_config(self) -> "Settings":
    # ... 既存の postgres 分岐 ...
    if self.storage_backend == "supabase":
        if not self.supabase_url.strip():
            raise ValueError("SUPABASE_URL は storage_backend=supabase の場合に必須です。")
        if not self.supabase_key.get_secret_value().strip():
            raise ValueError("SUPABASE_KEY は storage_backend=supabase の場合に必須です。")
        if not self.supabase_url.startswith("https://"):
            raise ValueError("SUPABASE_URL は https:// で始まる必要があります。")
        if self.graph_enabled:
            raise ValueError(
                "storage_backend=supabase は graph_enabled=true をサポートしません "
                "(Neo4j Bolt は HTTPS にカプセル化できないため)。"
            )
        # 次元数の起動前検証 (本番障害防止)
        if self.embedding_dimension != SUPABASE_VECTOR_DIMENSION:
            raise ValueError(
                f"EMBEDDING_DIMENSION={self.embedding_dimension} は "
                f"storage_backend=supabase のスキーマ vector({SUPABASE_VECTOR_DIMENSION}) "
                "と一致しません。次元数を変更する場合は "
                "supabase/migrations/ の SQL とこの定数を同時に更新してください。"
            )
    return self
```

この validator は **Pydantic Settings の初期化時 = アプリ起動時に評価される**ため、設定ミスを fail-fast で検知できる。

### 6.3 `src/context_store/storage/factory.py`

`_create_storage_adapter` から `prisma` 分岐を削除し、`supabase` 分岐を追加:

```python
if settings.storage_backend == "supabase":
    from context_store.storage.supabase import SupabaseStorageAdapter
    if read_only:
        raise NotImplementedError(
            "read_only mode for supabase backend is not yet supported"
        )
    return await SupabaseStorageAdapter.create(settings)
```

`_create_graph_adapter` も `prisma → supabase` リネーム＋エラーメッセージ更新。ファイル冒頭 docstring も同様更新。

### 6.4 削除対象

| パス | 削除理由 |
| --- | --- |
| `src/context_store/storage/prisma.py` | Prisma 依存実装を Supabase に置換 |
| `prisma/schema.prisma` | Prisma スキーマ定義 |
| `prisma/` ディレクトリ全体 | 上記のみのため空に |
| `tests/storage/test_prisma_*.py` (存在分) | Prisma 専用テスト |
| `.env.example` 内の `PRISMA_DATABASE_URL` | 環境変数置換 |

`src/context_store/storage/migrations/postgres/` の SQL ファイルは `storage-postgres` バックエンドが引き続き利用するため**残置**する。

## 7. テスト戦略

### 7.1 単体テスト (`tests/storage/test_supabase_adapter.py`)

`AsyncClient` 全体を `unittest.mock.AsyncMock` で差し替え。HTTP 経由なしでアダプタロジックを検証。

#### 7.1.1 モックの基本構造

supabase-py の `client.table(name).select(...).eq(...).execute()` チェーンは fluent インターフェースなので、各メソッドが自分自身（または別の Mock）を返すよう設定する。`execute()` の戻り値は `APIResponse(data=[...], count=...)` 相当の `MagicMock` を返す。

```python
# 共通ヘルパ (conftest.py)
def make_mock_response(data, count=None):
    resp = MagicMock()
    resp.data = data
    resp.count = count
    return resp

def make_mock_client():
    client = MagicMock()
    client.table = MagicMock()
    client.rpc = MagicMock()
    client.postgrest = AsyncMock()
    return client
```

#### 7.1.2 代表ケースの具体仕様

##### `test_save_memory_inserts_with_content_hash`
**入力:** `Memory(content="hello world", memory_type=SEMANTIC, source_type=MANUAL, ...)`
**モック設定:**
```python
mock_client.table.return_value.insert.return_value.execute = AsyncMock(
    return_value=make_mock_response(
        data=[{"id": "550e8400-e29b-41d4-a716-446655440000"}]
    )
)
```
**期待出力:** `await adapter.save_memory(memory)` が `"550e8400-e29b-41d4-a716-446655440000"` を返す
**検証点:**
- `insert()` の呼出引数 dict 内の `content_hash` が `hashlib.sha256(b"hello world").hexdigest()` と一致
- `embedding` が `_embedding_to_pg(memory.embedding)` で文字列化されている
- `source_metadata` が JSON 互換 dict として渡されている

##### `test_save_memory_raises_duplicate_on_23505`
**モック設定:** `execute()` が `PostgrestAPIError` をスロー (`code="23505"`, `message="duplicate key value"`)
**期待出力:** `StorageError(code="DUPLICATE_CONTENT", recoverable=False)` が raise される

##### `test_get_memory_returns_none_when_not_found`
**入力:** 任意の有効 UUID
**モック設定:**
```python
mock_client.table.return_value.select.return_value.eq.return_value\
    .maybe_single.return_value.execute = AsyncMock(
        return_value=make_mock_response(data=None)
    )
```
**期待出力:** `None`

##### `test_get_memory_invalid_uuid_returns_none`
**入力:** `"not-a-uuid"`
**期待出力:** `None` （PostgREST 呼出は発生しない＝`table.return_value.select` が呼ばれない）

##### `test_get_memories_batch_preserves_input_order`
**入力:** `["id-3", "id-1", "id-2"]` （いずれも有効 UUID 文字列）
**モック設定:** `in_()` の戻りで `data=[{"id": "id-1", ...}, {"id": "id-2", ...}, {"id": "id-3", ...}]`（順不同）を返す
**期待出力:** 返却 list の順序は `[memory_3, memory_1, memory_2]` （入力順）

##### `test_get_memories_batch_chunks_at_200`
**入力:** 有効 UUID 250 個
**モック設定:** `in_()` を MagicMock として呼出回数記録
**期待出力:** `in_()` が **2 回** 呼ばれる（200 + 50 のチャンクで分割）

##### `test_update_memory_recomputes_content_hash`
**入力:** `updates={"content": "new content"}`
**モック設定:** `update().eq().execute()` を AsyncMock
**期待出力:**
- `update()` の引数 dict が `{"content": "new content", "content_hash": sha256("new content")}` を含む
- 戻り値は `True` (data に 1 行あった場合)

##### `test_update_memory_rejects_disallowed_columns`
**入力:** `updates={"id": "999", "secret_field": "x", "content": "ok"}`
**期待出力:**
- `update()` の引数 dict には `"content"` と `"content_hash"` のみ含まれ、`id` と `secret_field` は除外

##### `test_vector_search_invokes_rpc`
**入力:** `embedding=[0.1]*768`, `top_k=10`, `project=None`
**モック設定:**
```python
mock_client.rpc.return_value.execute = AsyncMock(
    return_value=make_mock_response(data=[
        {"id": "uuid1", "content": "...", "memory_type": "semantic",
         "source_type": "manual", "source_metadata": {}, "embedding": "[0.1,...]",
         "semantic_relevance": 0.5, "importance_score": 0.5, "access_count": 0,
         "last_accessed_at": "2026-05-18T00:00:00Z",
         "created_at": "2026-05-18T00:00:00Z", "updated_at": "2026-05-18T00:00:00Z",
         "archived_at": None, "tags": [], "project": None, "content_hash": "abc",
         "score": 0.95}
    ])
)
```
**期待出力:**
- `client.rpc("vector_search", {"query_embedding": [0.1]*768, "match_count": 10, "p_project": None})` で呼ばれる
- 戻り値は `[ScoredMemory(memory=..., score=0.95, source=MemorySource.VECTOR)]`

##### `test_vector_search_clamps_top_k`
**入力:** `top_k=300`
**期待出力:** `rpc()` への `match_count` 引数が **200** (`SUPABASE_MAX_TOP_K`)
**追加検証:** `logger.warning` が呼ばれている (`caplog` フィクスチャで捕捉)

##### `test_keyword_search_uses_ilike`
**入力:** `query="hello"`, `top_k=5`, `project=None`
**期待出力:**
- `ilike("content", "%hello%")` で呼ばれる
- `is_("archived_at", "null")` で archived 除外
- `limit(5)` が呼ばれる

##### `test_keyword_search_does_not_escape_like_wildcards`
**入力:** `query="%hack_"`
**期待出力:** `ilike()` の第 2 引数は `"%%hack_%"` （`%` / `_` はエスケープされない）

##### `test_list_by_filter_cursor_pagination`
**入力:** `MemoryFilters(created_after=datetime(2026,5,1), id_after="uuid-X", order_by="created_at DESC")`
**期待出力:** `or_("created_at.lt.2026-05-01T00:00:00,and(created_at.eq.2026-05-01T00:00:00,id.lt.uuid-X)")` 相当の文字列が `or_()` に渡される

##### `test_count_by_filter_uses_head_true`
**期待出力:** `client.table("memories").select("*", count="exact", head=True)` で呼ばれ、戻り値は `response.count` を int 化

##### `test_increment_access_count_invokes_rpc`
**入力:** UUID 文字列
**モック設定:** `rpc().execute()` が `make_mock_response(data=True)` を返す
**期待出力:** `client.rpc("increment_memory_access_count", {"p_memory_id": "<uuid>"})` で呼ばれ、戻り値は `True`

##### `test_get_vector_dimension_returns_length`
**モック設定:** `select("embedding").not_.is_().limit(1).execute()` が `data=[{"embedding": "[0.1,0.2,0.3,...(768個)...]"}]` を返す
**期待出力:** `768`

##### `test_get_vector_dimension_returns_none_when_empty`
**モック設定:** `data=[]`
**期待出力:** `None`

##### `test_create_fails_when_dimension_mismatch`
**前提:** Settings.embedding_dimension=768
**モック設定:** `get_vector_dimension()` が `1024` を返す
**期待出力:** `StorageError(code="INVALID_STATE", recoverable=False)` が raise され、メッセージに `768` と `1024` の両方が含まれる。`dispose()` が呼ばれている。

##### `test_dispose_closes_client`
**期待出力:** `client.postgrest.aclose()` が呼ばれている (hasattr ガードあり)

##### `test_timeout_maps_to_storage_timeout`
**モック設定:** `execute()` が `httpx.ReadTimeout("504 Gateway Timeout")` をスロー
**期待出力:** `StorageError(code="STORAGE_TIMEOUT", recoverable=True)`

##### `test_no_secret_in_exception_message`
**前提:** Settings.supabase_key=`"super-secret-jwt-token"`
**モック設定:** 任意の操作で例外をスロー
**期待出力:** raise された `StorageError` の `str()` および `repr()` に `"super-secret-jwt-token"` が含まれない（PostgREST のエラーメッセージ仕様に依存するが、wrapper では Authorization ヘッダを露出させないことを保証）

#### 7.1.3 残るテストケース（簡易仕様）

以下は上記パターンの応用で網羅:
- `test_get_memories_batch_skips_invalid_uuid` — 不正 UUID 含む入力 → 除外して `in_()` を呼ぶ
- `test_delete_memory_returns_false_when_not_found` — `delete()` 戻りの `data=[]` → `False`
- `test_list_by_filter_archived_logic` — `archived=None/True/False` の各ケースで WHERE 句相当の呼出が変わる
- `test_list_projects_distinct` — 重複あり `data=[{"project":"a"},{"project":"a"},{"project":"b"}]` → `["a","b"]` (set 化)

### 7.2 静的検証
- `mypy --strict` を `src/context_store/storage/supabase.py` で実行
- `ruff check` および `ruff format --check`

### 7.3 統合テスト (任意)
`tests/storage/integration/test_supabase_live.py` を環境変数 `SUPABASE_LIVE_TEST=1` 限定で提供。本フェーズの合格条件には含めない。

## 8. 実行手順 (devcontainer 必須)

### 8.1 ローカル開発・テスト

**全てのテスト・型チェック・lint は `.devcontainer` 環境内で実行する**。社内ネットワークから外部 PyPI/Supabase への HTTPS アクセスが必要なため、devcontainer 外での動作は保証しない。

```bash
# devcontainer 内で:
uv sync --extra storage-supabase --extra dashboard --extra embedding-local

pytest tests/storage/test_supabase_adapter.py -v
mypy src/context_store/storage/supabase.py
ruff check src/context_store/storage/supabase.py
ruff format --check src/context_store/storage/supabase.py
```

### 8.2 Supabase スキーマ適用

```bash
# Supabase CLI で適用
supabase link --project-ref <YOUR_PROJECT_REF>
supabase db push

# あるいは Supabase Studio の SQL Editor で
# supabase/migrations/*.sql を順に手動実行
```

### 8.3 環境変数 (`.env`)

```bash
STORAGE_BACKEND=supabase
GRAPH_ENABLED=false
CACHE_BACKEND=inmemory
SUPABASE_URL=https://xxxxxxxxxxxx.supabase.co
SUPABASE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...   # Service Role Key
EMBEDDING_DIMENSION=768
EMBEDDING_PROVIDER=local-model
LOCAL_MODEL_NAME=cl-nagoya/ruri-v3-310m
```

## 9. 既存ユーザー向け移行手順

旧 `STORAGE_BACKEND=prisma` ユーザー向けの移行案内:
1. `.env` で `STORAGE_BACKEND=prisma` → `supabase` に変更
2. `PRISMA_DATABASE_URL` を削除し、`SUPABASE_URL`/`SUPABASE_KEY` を設定
3. Supabase プロジェクトに `supabase/migrations/*.sql` を適用
4. データ移行が必要な場合は `pg_dump`/`pg_restore` 等で手動移行（本スコープ外）

## 10. リスクと未確定事項

| リスク | 影響 | 対応 |
| --- | --- | --- |
| ~~`Settings.embedding_dimension` デフォルト値 1024 と SQL の `vector(768)` の不整合~~ | ~~起動時にミスマッチを誤検知~~ | **解決済み (Section 6.2 / 5.2)**: デフォルトを 768 に修正し、Settings validator と adapter.create() の二重防御を導入 |
| `Prisma schema.prisma` の `vector(1024)` 表記の歴史的経緯不明 | 既存環境で次元 1024 で運用中の可能性 | 移行前にユーザーが既存データの埋め込み次元を確認する案内を README に追加。adapter.create() の起動時 probe で実次元と Settings の不一致を fail-fast 検知 |
| Supabase RPC 関数の戻り値型と `_record_to_memory` の互換性 | テスト時点で発覚 | 単体テストで `dict[str, Any]` 形式の応答をモックして検証 (Section 7.1.2 参照) |
| PostgREST `or_` フィルタの構文の表記揺れ | カーソルページングが動かない | 実装時に supabase-py のドキュメント/ソースで確認 |
| `dispose()` で参照する `client.postgrest.aclose()` の属性名がバージョン差で異なる可能性 | リソースリーク | 実装時に `hasattr` ガードで安全に呼出し、テストでクローズ呼出を検証 |
| 将来 `EMBEDDING_DIMENSION` を変更したい場合の運用負荷 | SQL と Python 定数の二重更新が必要 | `SUPABASE_VECTOR_DIMENSION` 定数を `config.py` 内で集中管理し、変更時の対応箇所を 2 つ (定数 + supabase/migrations) に限定。手順を README に記載 |

## 11. 受け入れ基準

1. `pytest tests/storage/test_supabase_adapter.py` がすべて成功 (Section 7.1.2 の各テストを含む)
2. `mypy --strict src/context_store/storage/supabase.py` および変更後の `config.py` / `factory.py` がエラーゼロ
3. `ruff check` / `ruff format --check` がパス
4. `storage_backend=supabase` で `factory.create_storage()` が正常に `SupabaseStorageAdapter` を返す
5. Prisma 関連ファイル・依存・テストが削除済み
6. `Settings.embedding_dimension` デフォルトが 768 で、`SUPABASE_VECTOR_DIMENSION` と一致するバリデータが動作する (`test_create_fails_when_dimension_mismatch` で検証)
7. `supabase/migrations/*.sql` を Supabase プロジェクトに適用後、本アダプタが期待通り動作する手順が README に明記

## 12. 次フェーズ

設計承認後、`superpowers/writing-plans` スキルでステップ単位の実装計画を作成する。
