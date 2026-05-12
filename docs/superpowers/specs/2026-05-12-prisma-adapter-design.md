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
- `read_only=True` モードでの動作 (Dashboard の読み取り専用起動)。
  既存 `factory._create_storage_adapter` は `postgres` バックエンド
  において `read_only=True` のとき `NotImplementedError` を送出する
  実装となっており (`factory.py` 内 `if read_only: raise NotImplementedError`)、
  `prisma` バックエンドも同様に **`NotImplementedError` を送出する**
  ものとする。読み取り専用 Dashboard 起動時は `ReadOnlyNoOpStorageAdapter`
  にフォールバックされる既存挙動を踏襲する。

## 3. アーキテクチャ概要

```text
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
6. **Accelerate の制約**: クエリ結果サイズ上限 5 MB、クエリタイムアウト 10s。
   これらへのフェールセーフは 4.3 にて定義する。

### 4.3 Accelerate 制約に対するフェールセーフ仕様

運用時の事後対応ではなく、設計段階で以下のフェールセーフを組み込む。
すべて `PrismaStorageAdapter` の内部で完結し、上位 (Orchestrator 等)
から見たインターフェースは `PostgresStorageAdapter` と等価に保つ。

#### (a) `top_k` ハードリミット

- 定数 `PRISMA_MAX_TOP_K = 200` を `prisma.py` 内に定義する。
  - 根拠: 1 件あたり embedding 768 次元 × 8 byte ≒ 6 KB に、
    本文・メタデータを加味して安全側に 1 件 ≒ 20 KB と見積もる。
    200 件 × 20 KB ≒ 4 MB であり、5 MB 上限に対して 20% の安全マージンを残す。
- `vector_search(embedding, top_k, ...)` および
  `keyword_search(query, top_k, ...)` の冒頭で `top_k` をクランプする:
  - `top_k <= 0` → `StorageError("top_k must be >= 1", code="INVALID_PARAMETER")` を送出。
  - `top_k > PRISMA_MAX_TOP_K` → `PRISMA_MAX_TOP_K` にクランプし、
    `logger.warning` で「クランプした旨 / 元の値 / 適用値」を出力する。
    サイレント切り捨てではなく必ずログに記録する。

#### (b) `get_memories_batch` のチャンク分割

- 定数 `PRISMA_BATCH_FETCH_CHUNK_SIZE = 250` を定義する。
  - 根拠 (計算例):
    - 最悪ケース: 1 件 ≒ 20 KB (embedding 768 次元の JSON 文字列 ≒ 8.5 KB
      + content + メタデータ) × 250 件 = **5 MB ちょうど** → 上限超過の
      リスクがあるため、後述の典型ケース見積りと (c) フォールバックで
      補完する。
    - 典型ケース: 1 件 ≒ 15 KB × 250 件 = **3.75 MB** (安全マージン 25%)。
    - `PRISMA_MAX_TOP_K = 200` と整合: 200 × 20 KB = 4 MB と同等オーダーで
      あり、`top_k` (similarity スコア演算を伴うクエリ) より単純 SELECT の
      batch fetch をやや大きく取ることでスループットを確保しつつ、上限を
      超えるリスクは (c) で吸収する。
- `len(memory_ids) > PRISMA_BATCH_FETCH_CHUNK_SIZE` の場合は
  250 件単位で `query_raw` を分割実行し、結果をマージして
  入力順を維持して返す。

#### (c) タイムアウト / 応答サイズ超過時のフォールバック

`prisma.errors.PrismaError` の `code` が以下のいずれかに該当する、
または HTTP 408/504 相当を補足したときに発火する。

- **タイムアウト系**: `P2024` / `P2028` (Engine 側タイムアウト) /
  `P6004` (Accelerate `QueryTimeout`) → 最終 `StorageError` コードは
  `STORAGE_TIMEOUT`。
- **応答サイズ超過系**: `P6009` (Accelerate
  `ResponseSizeLimitExceeded`) → 最終 `StorageError` コードは
  `STORAGE_PAYLOAD_TOO_LARGE`。

実装上は両者を同一のフォールバック関数で扱い、最終送出時の
`StorageError.code` のみを Prisma 例外コードから派生させる。

| 発生箇所 | フォールバック |
|---|---|
| `vector_search` / `keyword_search` | `top_k` を半分 (整数除算、最低 1) に縮小して **1 回だけ** リトライ。それでも失敗時は対応する `StorageError(code=<上記マッピング>, recoverable=True)` を送出。 |
| `get_memories_batch` (チャンク内) | 該当チャンクのみチャンクサイズを半分に分割して **1 回だけ** リトライ。それでも失敗時は対応する `StorageError(code=<上記マッピング>, recoverable=True)` を送出。 |
| `list_by_filter` / `count_by_filter` | リトライしない。対応する `StorageError(recoverable=True)` を即座に送出する (これらは `limit` を呼出側が指定するため、内部で勝手に縮小しない)。 |
| `save_memory` / `update_memory` / `delete_memory` / `increment_memory_access_count` | リトライしない (idempotency を保証できないため)。対応する `StorageError(recoverable=True)` を送出。 |

`recoverable=True` を上位 retry 層 (`tenacity`) が認識して全体リトライを
行うことを許容する。アダプター内の自動リトライは上記の **1 回のみ** に
限定し、二重リトライによる増幅を防ぐ。

### 4.4 SQL 再利用ルール

YAGNI の観点で、本設計の段階では SQL 文を `PrismaStorageAdapter` 内に
直接書き写す。`PostgresStorageAdapter` との重複削減のための SQL 共有
モジュール抽出は別タスクとし、本仕様の範囲外とする。

## 5. エラーハンドリング/例外マッピング

| Prisma 例外 | StorageError code | recoverable |
|---|---|---|
| `prisma.errors.UniqueViolationError` | `DUPLICATE_CONTENT` | False |
| `prisma.errors.RawQueryError` (構文/型エラー等) | `STORAGE_ERROR` | False |
| `prisma.errors.PrismaError` (code `P2024`/`P2028`, Engine タイムアウト) | `STORAGE_TIMEOUT` | True |
| `prisma.errors.PrismaError` (code `P6004`, Accelerate タイムアウト) | `STORAGE_TIMEOUT` | True |
| `prisma.errors.PrismaError` (code `P6009`, Accelerate 応答サイズ超過) | `STORAGE_PAYLOAD_TOO_LARGE` | True |
| `prisma.errors.PrismaError` (その他接続障害) | `STORAGE_ERROR` | True |
| HTTP 408 / 504 (Accelerate タイムアウト相当) | `STORAGE_TIMEOUT` | True |
| HTTP 4xx/5xx (上記以外, Accelerate 由来) | `STORAGE_ERROR` | True |

例外クラスは Prisma Client Python (`prisma-client-py`) が
`prisma.errors` 配下にエクスポートしているもの (`UniqueViolationError`,
`RawQueryError`, `PrismaError` 等) を直接使用する。Prisma 固有エラーコード
(`P2024`, `P2028`, `P6004`, `P6009`) は `PrismaError.code` 属性で
判定する。`STORAGE_TIMEOUT` および `STORAGE_PAYLOAD_TOO_LARGE` に分類される
例外は 4.3 (c) のフォールバック処理を経た上で送出される。
`recoverable=True` を上位 retry 層 (`tenacity`) が認識して全体リトライを
行うことを許容する。

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

### 8.1 テスト層

| 層 | 対象 | 手段 |
|---|---|---|
| Unit | 型変換ヘルパ (`_embedding_to_pg`, `_parse_embedding`, `_record_to_memory`) | 純粋関数として直接テスト |
| Mock 統合 | `PrismaStorageAdapter` の各メソッド | `prisma.Prisma` を `AsyncMock` で差し替え、`query_raw` / `execute_raw` が期待 SQL/params で呼ばれることを検証 |
| Live (opt-in) | 実 Accelerate エンドポイント | `PRISMA_DATABASE_URL` が `prisma://` で始まる場合のみ実行 (`pytest.mark.live_prisma`、デフォルトスキップ) |

### 8.2 Accelerate 制約に関するエッジケーステスト (必須)

4.3 で定義したフェールセーフを検証するための具体的なテストケース。
すべて Mock 統合層 (8.1) に追加し、`AsyncMock` で `query_raw` の挙動を
制御する。

#### (a) `top_k` ハードリミット

| ケース | 入力 | モック挙動 | 期待される出力/動作 |
|---|---|---|---|
| 通常範囲 | `top_k=10` | `query_raw` は 10 件返却 | クランプなし。`top_k=10` が SQL の `LIMIT $N` パラメータに渡される。`logger.warning` は呼ばれない。 |
| 上限ちょうど | `top_k=200` | `query_raw` は 200 件返却 | クランプなし。`top_k=200` が渡される。 |
| 上限超過 | `top_k=500` | `query_raw` は 200 件返却 | `top_k=200` にクランプされ、SQL パラメータも 200。`logger.warning` が "clamped 500 -> 200" 相当のメッセージで 1 回呼ばれる。 |
| 不正値 | `top_k=0` | (呼ばれない) | `StorageError(code="INVALID_PARAMETER")` が送出される。`query_raw` は呼ばれない。 |
| 不正値 | `top_k=-1` | (呼ばれない) | 同上。 |

#### (b) `get_memories_batch` のチャンク分割境界

`PRISMA_BATCH_FETCH_CHUNK_SIZE = 250` を前提とする。

| ケース | 入力 (件数) | 期待される `query_raw` 呼び出し回数 / 各回の `len(ids)` |
|---|---|---|
| 単一チャンク内 | 249 | 1 回 / `[249]` |
| チャンクサイズちょうど | 250 | 1 回 / `[250]` |
| 1 件超過 | 251 | 2 回 / `[250, 1]` |
| 2 チャンク未満 | 499 | 2 回 / `[250, 249]` |
| 2 チャンク満杯 | 500 | 2 回 / `[250, 250]` |
| 3 チャンク開始 | 501 | 3 回 / `[250, 250, 1]` |

加えて以下を検証する:
- 各チャンクの結果をマージした際、戻り値の順序が **入力 `memory_ids`
  の順序と完全に一致**すること (既存 `PostgresStorageAdapter`
  の挙動と互換)。
- 重複 ID が含まれる場合、`PostgresStorageAdapter` と同じ挙動
  (重複行は 1 回のみ返す) を再現すること。
- 不正な UUID 文字列は呼び出し前にスキップされ、`query_raw` の
  パラメータには含まれないこと。

#### (c) タイムアウト時のフォールバック

`prisma.errors.PrismaError` (code=`"P2024"`) を `AsyncMock.side_effect`
で発生させる。

| 対象メソッド | 初回呼び出し | フォールバック呼び出し | 期待される結果 |
|---|---|---|---|
| `vector_search(top_k=100)` | timeout を送出 | `top_k=50` で正常 (10 件返却) | 10 件の `ScoredMemory` が返る。`query_raw` は 2 回呼ばれ、2 回目のパラメータは `top_k=50`。 |
| `vector_search(top_k=100)` | timeout を送出 | `top_k=50` でも timeout | `StorageError(code="STORAGE_TIMEOUT", recoverable=True)` が送出される。`query_raw` は 2 回呼ばれる。 |
| `vector_search(top_k=1)` | timeout を送出 | `top_k=1` (= max(1, 1//2)) でも timeout | `StorageError(code="STORAGE_TIMEOUT")` が送出される。3 回目のリトライは行われない。 |
| `keyword_search(top_k=100)` | timeout を送出 | `top_k=50` で正常 | (上記 `vector_search` と同様) |
| `get_memories_batch(ids=600件)` | チャンク 1 (250 件) で timeout | 250 件を 125 件 × 2 に分割し正常完了。チャンク 2 (250 件)、チャンク 3 (100 件) は通常実行 | 600 件 (※実存分) が返る。`query_raw` 呼び出しは 5 回 (250 失敗 → 125 成功 → 125 成功 → 250 成功 → 100 成功)。 |
| `get_memories_batch(ids=600件)` | チャンク 1 で timeout | 125 件分割でも timeout | `StorageError(code="STORAGE_TIMEOUT")` が送出される。 |
| `list_by_filter(filters)` | timeout を送出 | (リトライしない) | `StorageError(code="STORAGE_TIMEOUT", recoverable=True)` が即座に送出。`query_raw` は 1 回のみ呼ばれる。 |
| `save_memory(memory)` | timeout を送出 | (リトライしない) | `StorageError(code="STORAGE_TIMEOUT", recoverable=True)` が即座に送出。`query_first_raw` は 1 回のみ呼ばれる。 |

#### (d) 5MB 上限到達のシミュレーション

Prisma Accelerate は応答サイズ上限超過時に **`P6009`
(`ResponseSizeLimitExceeded`)** を、サーバー側クエリタイムアウトには
**`P6004` (`QueryTimeout`)** を返す (Prisma Accelerate エラーコード体系)。
本テストでは以下を検証する。

| ケース | モック挙動 | 期待される結果 |
|---|---|---|
| `vector_search` が応答サイズ超過 | `PrismaError(code="P6009")` を送出 | `top_k` を半分にしてリトライ。`StorageError(code="STORAGE_PAYLOAD_TOO_LARGE", recoverable=True)` を経由するパスを通る。 |
| `get_memories_batch` (250 件チャンク) が応答サイズ超過 | `PrismaError(code="P6009")` を送出 | チャンクを 125 件に分割してリトライ。同様に `STORAGE_PAYLOAD_TOO_LARGE` 経路。 |
| `vector_search` が Accelerate タイムアウト | `PrismaError(code="P6004")` を送出 | `top_k` を半分にしてリトライ。`STORAGE_TIMEOUT` 経路。 |

**内部コードマッピング (実装要件)**:

| Prisma エラーコード | 内部 `StorageError.code` | フォールバック挙動 |
|---|---|---|
| `P2024` / `P2028` (Engine 側タイムアウト) | `STORAGE_TIMEOUT` | 4.3 (c) の縮小リトライ |
| `P6004` (Accelerate `QueryTimeout`) | `STORAGE_TIMEOUT` | 同上 |
| `P6009` (Accelerate `ResponseSizeLimitExceeded`) | `STORAGE_PAYLOAD_TOO_LARGE` | 同じ縮小リトライパスを共用 (実装上は分岐させず、内部コードのみ区別) |

`STORAGE_TIMEOUT` と `STORAGE_PAYLOAD_TOO_LARGE` は別コードとして
区別するが、リトライ縮小ロジックは共通とする。これにより
オペレーター側で原因識別を可能にしつつ、コードパスの重複を避ける。

> Note: 上記コード (`P6004`, `P6009`) は Prisma Accelerate の現行仕様に
> 基づくが、Prisma 側で将来変更される可能性がある。実装時には
> 使用する `prisma` パッケージ (>= 0.15.0) のバージョンで実際に
> スローされる例外の `code` 属性をログから確認し、必要に応じて
> 定数 `PRISMA_TIMEOUT_CODES = {"P2024", "P2028", "P6004"}` /
> `PRISMA_PAYLOAD_TOO_LARGE_CODES = {"P6009"}` を更新する。

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
- Accelerate のクエリタイムアウト 10s および結果サイズ 5MB 上限への
  対応は、運用時の事後対応ではなく 4.3 のフェールセーフ仕様として
  設計に組み込み済み (`top_k` ハードリミット / チャンク分割 /
  縮小リトライ)。HNSW インデックスが未構築のまま大規模データに
  到達した場合は本フェールセーフでも救えないため、初期化時に
  インデックス存在をチェックする責務は SQL マイグレーション側に
  委ねる (既存 `0001_initial.sql` で HNSW を作成済み)。
- 組織のコンプライアンス承認は前提条件 (`docs/future/2026-05-11-...`
  に記載)。本仕様は技術設計のみを対象とする。
