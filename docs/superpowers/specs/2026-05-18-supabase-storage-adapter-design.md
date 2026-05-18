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
    async def create(cls, settings: Settings) -> "SupabaseStorageAdapter": ...

    async def dispose(self) -> None: ...

    def _map_to_storage_error(self, exc: Exception) -> StorageError: ...
```

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
```

`_validate_storage_config` に `supabase` 分岐を追加し、`graph_enabled=true` との併用を拒否。`graph_backend` computed_field も `supabase → "disabled"` を返すよう修正。

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

主要ケース (抜粋):
- `test_save_memory_inserts_with_content_hash`
- `test_save_memory_raises_duplicate_on_23505`
- `test_get_memory_returns_none_when_not_found`
- `test_get_memory_invalid_uuid_returns_none`
- `test_get_memories_batch_preserves_input_order`
- `test_get_memories_batch_chunks_at_200`
- `test_get_memories_batch_skips_invalid_uuid`
- `test_delete_memory_returns_false_when_not_found`
- `test_update_memory_recomputes_content_hash`
- `test_update_memory_rejects_disallowed_columns`
- `test_vector_search_invokes_rpc`
- `test_vector_search_clamps_top_k`
- `test_vector_search_with_project_filter`
- `test_keyword_search_uses_ilike`
- `test_keyword_search_does_not_escape_like_wildcards`
- `test_list_by_filter_archived_logic`
- `test_list_by_filter_cursor_pagination`
- `test_count_by_filter_uses_head_true`
- `test_increment_access_count_invokes_rpc`
- `test_list_projects_distinct`
- `test_get_vector_dimension_returns_length`
- `test_dispose_closes_client`
- `test_timeout_maps_to_storage_timeout`
- `test_no_secret_in_exception_message`

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
| `Settings.embedding_dimension` デフォルト値 1024 と SQL の `vector(768)` の不整合 | 起動時にミスマッチを誤検知 | 別 issue として記録。本スコープでは `vector(768)` を採用 |
| `Prisma schema.prisma` の `vector(1024)` 表記の歴史的経緯不明 | 既存環境で次元 1024 で運用中の可能性 | 移行前にユーザーが既存データの埋め込み次元を確認する案内を README に追加 |
| Supabase RPC 関数の戻り値型と `_record_to_memory` の互換性 | テスト時点で発覚 | 単体テストで `dict[str, Any]` 形式の応答をモックして検証 |
| PostgREST `or_` フィルタの構文の表記揺れ | カーソルページングが動かない | 実装時に supabase-py のドキュメント/ソースで確認 |
| `dispose()` で参照する `client.postgrest.aclose()` の属性名がバージョン差で異なる可能性 | リソースリーク | 実装時に `hasattr` ガードで安全に呼出し、テストでクローズ呼出を検証 |

## 11. 受け入れ基準

1. `pytest tests/storage/test_supabase_adapter.py` がすべて成功
2. `mypy --strict src/context_store/storage/supabase.py` がエラーゼロ
3. `ruff check` / `ruff format --check` がパス
4. `storage_backend=supabase` で `factory.create_storage()` が正常に `SupabaseStorageAdapter` を返す
5. Prisma 関連ファイル・依存・テストが削除済み
6. `supabase/migrations/*.sql` を Supabase プロジェクトに適用後、本アダプタが期待通り動作する手順が README に明記

## 12. 次フェーズ

設計承認後、`superpowers/writing-plans` スキルでステップ単位の実装計画を作成する。
