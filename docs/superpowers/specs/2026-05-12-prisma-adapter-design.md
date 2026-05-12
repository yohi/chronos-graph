# PrismaAdapter 設計仕様書

- 作成日: 2026-05-12
- 対象ブランチ: master
- 関連ドキュメント: `docs/future/2026-05-11-network-restriction-bypass-strategy.md`

## 1. 目的と背景

社内ネットワーク (Fortinet 等の UTM/次世代ファイアウォール) における
PostgreSQL 標準ポート (5432, 6543 等) の遮断、および DPI によるバイナリ
プロトコル切断を回避するため、HTTPS (443) にカプセル化された通信で
PostgreSQL へアクセスする経路を提供する。

実証された事実 (2026-05-11):
- 直接接続 (ポート 5432 / asyncpg) は Fortinet DPI により切断される。
- 標準 HTTPS (443) 経由の Prisma Accelerate エンドポイントは通過可能。

本仕様は、既存の `StorageAdapter` プロトコルに準拠した
`PrismaStorageAdapter` を追加し、環境変数 `STORAGE_BACKEND=prisma` で
切り替え可能にすることを目的とする。

## 2. スコープ

### 含むもの

- `StorageAdapter` プロトコル準拠の Prisma 実装 (memories テーブル)。
- `schema.prisma` (接続定義と Prisma Client 生成のため、`memories` のみ)。
- 既存 SQL マイグレーション (`migrations/postgres/*.sql`) を
  Prisma 経由で実行するマイグレーションランナー。
- 設定 (`Settings`) およびファクトリ (`factory.create_storage`) の拡張。
- Devcontainer 内で完結する `prisma generate` 等の実行手順。

### 含まないもの

- `GraphAdapter` 実装 (Neo4j Bolt は HTTPS でカプセル化できないため対象外)。
  `STORAGE_BACKEND=prisma` かつ `graph_enabled=true` の組合せは
  ファクトリ層で明示エラーとする。
- `CacheAdapter` の変更 (Redis は本設計の対象外)。
- 既存 `PostgresStorageAdapter` の挙動変更。
- Prisma Migrate (`prisma migrate dev/deploy`) の導入。スキーマの
  真実は引き続き SQL ファイル側に置き、`schema.prisma` は接続定義と
  型表現のみに用いる。

## 3. アーキテクチャ概要

```
┌────────────────────────────────────────────────────────────────┐
│  Application (Orchestrator / Dashboard / MCP Gateway)          │
└────────────────────┬───────────────────────────────────────────┘
                     │ StorageAdapter Protocol
        ┌────────────┼────────────┬───────────────┐
        ▼            ▼            ▼               ▼
  SQLiteAdapter  PostgresAdapter  PrismaAdapter   ...
                                        │
                       prisma.Prisma() (async client)
                                        │
                       prisma.query_raw / execute_raw
                                        │ HTTPS (443)
                                        ▼
                       prisma://accelerate.prisma-data.net
                                        │
                                        ▼
                              PostgreSQL + pgvector + pg_trgm
```

### 3.1 設計原則

- `PrismaStorageAdapter` は既存 `PostgresStorageAdapter` の SQL を
  ほぼそのまま再利用する。`$1, $2, ...` プレースホルダ表現は
  Prisma Client Python の Postgres プレースホルダ規約と互換。
- pgvector の値は文字列 `"[x,y,z]"` 形式でバインドし、SQL 内で
  `::vector` キャストする (既存実装と同一)。
- スキーマの真実は SQL マイグレーションファイル側に保持する。
  Prisma 側では DDL を Prisma Migrate ではなく `execute_raw` で発行する。
- `prisma.Prisma` インスタンスのライフサイクル (connect / disconnect) は
  アダプターが所有し、`dispose()` で確実に切断する。

### 3.2 コンポーネントと責務

| コンポーネント | パス | 責務 |
|---|---|---|
| `PrismaStorageAdapter` | `src/context_store/storage/prisma.py` | `StorageAdapter` プロトコル準拠。全クエリ実装。 |
| `_PrismaMigrationRunner` (private) | 同上 | 既存 SQL ファイルを `execute_raw` で順次適用。 |
| `schema.prisma` | `prisma/schema.prisma` | Prisma Client 生成のためのスキーマ定義 (memories のみ)。 |
| Factory 分岐 | `src/context_store/storage/factory.py` | `STORAGE_BACKEND=prisma` のディスパッチ。`graph_enabled=true` のとき明示エラー。 |
| 設定追加 | `src/context_store/config.py` | `storage_backend` の `Literal` に `"prisma"` を追加、`prisma_database_url` 等を追加、バリデーション。 |
| 依存関係 | `pyproject.toml` | `storage-prisma = ["prisma>=0.15.0"]` を optional-dependencies に追加。 |
| Devcontainer 拡張 | `.devcontainer/setup.sh`, `.devcontainer/devcontainer.json` | Node.js のインストールと `prisma generate` の自動実行。 |

## 4. データフローと Raw SQL クエリ戦略

### 4.1 API マッピング

| 既存 (`asyncpg`) | Prisma 等価 |
|---|---|
| `pool.acquire() / conn.fetchrow(sql, *params)` | `await prisma.query_first_raw(sql, *params)` |
| `conn.fetch(sql, *params)` | `await prisma.query_raw(sql, *params)` |
| `conn.fetchval(sql, *params)` | `await prisma.query_first_raw(...)` で単一カラム抽出 |
| `conn.execute(sql, *params)` (DML/DDL) | `await prisma.execute_raw(sql, *params)` |
| トランザクション | `async with prisma.tx() as tx:` |

### 4.2 差異と対処

1. **戻り値の型**: Prisma の `query_raw` は `list[dict[str, Any]]` を
   返す (asyncpg は `Record`)。既存の `_record_to_memory(dict(record))`
   関数はそのまま再利用可能。
2. **`execute_raw` の戻り値**: `affected rows: int`。
   `UPDATE 1` / `DELETE 1` の文字列マッチではなく `>= 1` で判定する。
3. **`RETURNING` 句**: `query_first_raw` で取得 (`save_memory`)。
4. **配列バインド** (`get_memories_batch` の `WHERE id = ANY($1::uuid[])`):
   Prisma Client Python では `list` をそのまま渡せる。
   型キャスト `::uuid[]` は明示する。
5. **pgvector**: 文字列 `"[0.1,0.2]"` を渡して `$N::vector` でキャスト。
6. **Accelerate の制約**:
   - クエリ結果サイズ上限 5 MB。
   - クエリタイムアウト 10s。
   - `get_memories_batch` で大量取得時は 500 件単位で分割する。

### 4.3 SQL 再利用ルール

YAGNI の観点で、本設計の段階では SQL 文を `PrismaStorageAdapter` 内に
直接書き写す。`PostgresStorageAdapter` との重複削減のための SQL 共有
モジュール抽出は別タスクとし、本仕様の範囲外とする。

## 5. エラーハンドリング/例外マッピング

| Prisma 例外 | StorageError code | recoverable |
|---|---|---|
| `prisma.errors.UniqueViolationError` | `DUPLICATE_CONTENT` | False |
| `prisma.errors.RawQueryError` (構文/型エラー等) | `STORAGE_ERROR` | False |
| `prisma.errors.PrismaError` (接続/タイムアウト) | `STORAGE_ERROR` | True |
| HTTP 4xx/5xx (Accelerate 由来) | `STORAGE_ERROR` | True |

接続障害 (Fortinet 切断, Accelerate サービス障害) は `recoverable=True`
でマークし、上位の retry 層 (`tenacity`) で再試行可能とする。

## 6. `schema.prisma` の表現

```prisma
generator client {
  provider             = "prisma-client-py"
  interface            = "asyncio"
  recursive_type_depth = 5
}

datasource db {
  provider = "postgresql"
  url      = env("PRISMA_DATABASE_URL")
}

model memories {
  id                 String   @id @default(dbgenerated("gen_random_uuid()")) @db.Uuid
  content            String
  memory_type        String   @db.VarChar(20)
  source_type        String   @db.VarChar(20)
  source_metadata    Json     @default("{}")
  embedding          Unsupported("vector(768)")?
  semantic_relevance Float    @default(0.5)
  importance_score   Float    @default(0.5)
  access_count       Int      @default(0)
  last_accessed_at   DateTime @default(now()) @db.Timestamptz
  created_at         DateTime @default(now()) @db.Timestamptz
  updated_at         DateTime @default(now()) @db.Timestamptz
  archived_at        DateTime? @db.Timestamptz
  tags               String[] @default([])
  project            String?
  content_hash       String   @unique
}
```

- `Unsupported(...)` カラムは Prisma Client から直接読み書きできないが、
  本実装は全クエリで `query_raw` を用いるため問題にならない。
- HNSW インデックス、GIN インデックス等は `schema.prisma` で表現できない。
  これらは引き続き SQL マイグレーションファイル側で作成する。

## 7. Devcontainer 実行手順

### 7.1 設計要件

`prisma generate`, `pytest`, `ruff`, `mypy` は**必ず Devcontainer 内で
実行する**。ホスト Python では実行しない。

### 7.2 `.devcontainer/setup.sh` への追加 (差分)

```bash
# Node.js (Prisma CLI 用)
if ! command -v node >/dev/null 2>&1; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
  sudo apt-get install -y nodejs
fi

# Prisma extras を含めて Python 依存をインストール
uv pip install -e ".[dev,storage-postgres,storage-prisma]"

# Prisma Client Python の生成 (schema.prisma → ./prisma/ パッケージ生成)
prisma generate --schema=./prisma/schema.prisma
```

### 7.3 `.devcontainer/devcontainer.json` の `Install Dependencies` タスク

`pip install -e ".[dev,storage-postgres]"` を
`pip install -e ".[dev,storage-postgres,storage-prisma]"` に変更し、
`prisma generate --schema=./prisma/schema.prisma` を後段に追加した
新規タスク `Prisma Generate` を加える。

### 7.4 開発者向け実行コマンド (Devcontainer 内)

```bash
# 1. Prisma Client 生成 (schema.prisma 変更時のみ)
prisma generate --schema=./prisma/schema.prisma

# 2. テスト
pytest tests/unit/storage/test_prisma_adapter.py -v

# 3. 静的解析
ruff check src/context_store/storage/prisma.py
mypy src/context_store/storage/prisma.py
```

## 8. テスト戦略

| 層 | 対象 | 手段 |
|---|---|---|
| Unit | 型変換ヘルパ (`_embedding_to_pg`, `_parse_embedding`, `_record_to_memory`) | 純粋関数として直接テスト |
| Mock 統合 | `PrismaStorageAdapter` の各メソッド | `prisma.Prisma` を `AsyncMock` で差し替え、`query_raw` / `execute_raw` が期待 SQL/params で呼ばれることを検証 |
| Live (opt-in) | 実 Accelerate エンドポイント | `PRISMA_DATABASE_URL` が `prisma://` で始まる場合のみ実行 (`pytest.mark.live_prisma`、デフォルトスキップ) |

## 9. 設定 (`Settings`) 拡張仕様

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `storage_backend` | `Literal["sqlite","postgres","prisma"]` | `"sqlite"` | バックエンド選択。`"prisma"` を追加。 |
| `prisma_database_url` | `SecretStr` | `SecretStr("")` | `prisma://accelerate.prisma-data.net/?api_key=...` 形式。 |

### バリデーション規則 (`_validate_storage_config` を拡張)

- `storage_backend == "prisma"` のとき:
  - `prisma_database_url` が空でないこと。
  - `prisma_database_url` の値が `prisma://` または `prismas://` で
    始まること (Accelerate スキーム)。違反時はエラー。
  - `graph_enabled is True` の場合はエラー
    (`PrismaAdapter` は graph をサポートしない)。

## 10. ファクトリ (`factory.py`) 拡張仕様

`_create_storage_adapter` に分岐を追加:

```python
if settings.storage_backend == "prisma":
    from context_store.storage.prisma import PrismaStorageAdapter

    if read_only:
        raise NotImplementedError(
            "read_only mode for prisma backend is not yet supported"
        )
    return await PrismaStorageAdapter.create(settings)
```

`_create_graph_adapter` で `storage_backend == "prisma"` かつ
`graph_enabled` の場合は `ValueError` を送出する
(Settings バリデーションと二重化することで安全性を確保)。

## 11. ファイル変更サマリと実装順序

| # | アクション | ファイル |
|---|---|---|
| 1 | 新規 | `prisma/schema.prisma` |
| 2 | 編集 | `pyproject.toml` (optional-deps + mypy override) |
| 3 | 編集 | `src/context_store/config.py` (`Literal` 拡張, `prisma_database_url`, validator) |
| 4 | 新規 | `src/context_store/storage/prisma.py` (アダプター本体 + マイグレーションランナー) |
| 5 | 編集 | `src/context_store/storage/factory.py` (`prisma` ブランチ追加) |
| 6 | 編集 | `.devcontainer/setup.sh` (Node.js + `prisma generate`) |
| 7 | 編集 | `.devcontainer/devcontainer.json` (`Install Dependencies` タスク更新 + `Prisma Generate` タスク) |
| 8 | 新規 | `tests/unit/storage/test_prisma_adapter.py` (mock-based テスト) |

実装順序は上記の番号順とする。`schema.prisma` を最初に確定させ、
そこから生成される Prisma Client の型シグネチャを前提に Adapter を
実装する。

## 12. 非機能要件

- **セキュリティ**: API キーを含む `PRISMA_DATABASE_URL` はログ・例外
  メッセージに含めない。`SecretStr` 化し、`get_secret_value()` は
  Prisma クライアント初期化時のみ呼び出す。
- **可観測性**: 既存の `logging.getLogger(__name__)` を踏襲。
  Accelerate 由来の HTTP エラーは DEBUG レベルで記録する。
- **後方互換性**: 既存の `STORAGE_BACKEND=sqlite|postgres` 利用者には
  影響しない。`storage-prisma` extras は opt-in。

## 13. リスクと未解決事項

- Prisma Client Python (v0.15.x) は活発な開発中。`Unsupported(...)`
  カラム + `query_raw` の組合せが将来のメジャーアップデートで
  挙動変更となる可能性がある。CI で extras 込みのスモークテストを
  Devcontainer 内で実行することで早期検知を行う。
- Accelerate のクエリタイムアウト 10s は `vector_search` の `top_k`
  が大きい場合や HNSW インデックス未構築時に超過する可能性がある。
  運用時に observe して、必要なら `top_k` 上限または事前 RPC 化を検討。
- 組織のコンプライアンス承認は前提条件 (`docs/future/2026-05-11-...`
  に記載)。本仕様は技術設計のみを対象とする。
