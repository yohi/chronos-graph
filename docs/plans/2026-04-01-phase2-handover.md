# Phase 2 Storage Layer — 引き継ぎドキュメント

作成日: 2026-04-01  
ブランチ: `feature/phase-2-storage-layer`  
対象計画書: `docs/plans/2026-03-26-implementation-plan.md`

---

## 1. 完了済みタスク

| タスク | コミット | 状態 |
|---|---|---|
| Task 2.2: PostgreSQL Storage Adapter | `0ff8ee0` | ✅ 完了 |
| Task 2.3: Neo4j Graph Adapter | `2c16357` | ✅ 完了 |
| Task 2.4: Redis Cache Adapter | `d831fea` | ✅ 完了 |
| Task 2.5: SQLite Storage Adapter | `c082d64` | ✅ 完了 |

### 実装済みファイル一覧

```
src/context_store/storage/
├── protocols.py        # StorageAdapter / GraphAdapter / CacheAdapter Protocol
├── postgres.py         # PostgresStorageAdapter (asyncpg + pgvector + pg_bigm)
├── neo4j.py            # Neo4jGraphAdapter (neo4j.AsyncGraphDatabase)
├── redis.py            # RedisCacheAdapter (redis.asyncio)
└── sqlite.py           # SQLiteStorageAdapter (aiosqlite + sqlite-vec + FTS5)

tests/unit/
├── test_postgres_storage.py   # 31件
├── test_neo4j_storage.py      # 15件
├── test_redis_storage.py      # 13件
└── test_sqlite_storage.py     # 66件

tests/integration/
├── conftest.py                # postgres_pool / db_session fixture
├── test_postgres_schema.py    # 5件 (スキーマ検証)
└── test_postgres_integration.py # 14件 (CRUD + Search)
```

### Docker / インフラ変更点

- `docker-compose.yml`: PostgreSQL ポートを `5433` に変更（ホストの 5432 が既存コンテナで使用中）
- `docker/postgres/Dockerfile`: pg_bigm をコンテキスト内 tarball (`pg_bigm.tar.gz`) からビルドするよう修正
- `docker/postgres/`: `pg_bigm.tar.gz` を追加（ネットワーク不達対策）

---

## 2. 残りタスク（未着手）

### Task 2.5b: SQLite Graph Adapter
**計画書**: `docs/plans/2026-03-26-implementation-plan.md` L964〜L995

**作成ファイル:**
- `src/context_store/storage/sqlite_graph.py`
- `tests/unit/test_sqlite_graph.py`

**実装ポイント:**
- `memory_nodes` / `memory_edges` テーブルのスキーマ
- 再帰的 CTE によるグラフトラバーサル（depth パラメータ対応）
- `graph_max_logical_depth` / `graph_max_physical_hops` の制限
- **タイムアウト制御**: `settings.graph_traversal_timeout_seconds`
  - `src/context_store/utils/sqlite_interrupt.py` の `SafeSqliteInterruptCtx`（または `InterruptibleConnection`）を活用
  - タイムアウト発生時は部分/空結果を返す（Graceful Degradation）
- `SQLiteStorageAdapter` と同一の DB ファイルを共有
- GraphAdapter Protocol に完全準拠

---

### Task 2.6: InMemory Cache Adapter + Storage Factory
**計画書**: `docs/plans/2026-03-26-implementation-plan.md` L999〜L1027

**作成ファイル:**
- `src/context_store/storage/inmemory.py`
- `src/context_store/storage/factory.py`
- `tests/unit/test_inmemory_cache.py`
- `tests/unit/test_storage_factory.py`

**実装ポイント:**
- `InMemoryCacheAdapter`: `dict` + `asyncio.Lock` + TTL 管理
  - `invalidate_prefix`: batch_size ごとにロックを解放するか、スナップショット方式で O(N) ブロッキングを回避
  - `clear()` メソッドを実装
- `StorageFactory`:
  ```python
  async def create_storage(settings) -> tuple[StorageAdapter, GraphAdapter | None, CacheAdapter]:
  ```
  - `STORAGE_BACKEND=sqlite` → `SQLiteStorageAdapter` + `SQLiteGraphAdapter`
  - `STORAGE_BACKEND=postgres` → `PostgresStorageAdapter`
  - `GRAPH_ENABLED=false` → GraphAdapter = None
  - `CACHE_BACKEND=inmemory` → `InMemoryCacheAdapter`
  - `CACHE_BACKEND=redis` → `RedisCacheAdapter`
- **Cache Coherence Checker**: `system_metadata` テーブルの `last_cache_update` を
  `CACHE_COHERENCE_POLL_INTERVAL_SECONDS` 間隔でポーリングし、更新があれば `CacheAdapter.clear()` を呼ぶ

---

### PR ドラフト作成
全タスク完了後に `gh pr create --draft` で PR を作成する。

---

## 3. 環境セットアップ

```bash
# PostgreSQL（ポート 5433）を起動
cd /home/y_ohi/program/chronos-graph
docker compose up -d postgres

# テスト実行
uv run pytest tests/unit/ -v               # ユニットテスト
uv run pytest tests/integration/ -v       # 統合テスト（PostgreSQL 必須）
```

---

## 4. 既知の事項・注意点

- **`asyncio_mode = "auto"`**: `pyproject.toml` で設定済み。全テストは自動で async 対応
- **イベントループスコープ**: `pytest-asyncio` で `scope="session"` の async fixture はループ不一致エラーを起こす。`scope="function"` (デフォルト) を使うこと
- **pg_bigm**: ビルド時は `docker/postgres/pg_bigm.tar.gz` をコンテキストに置いておくこと。ネットワーク経由のダウンロードは Docker ビルド内で失敗する環境がある
- **統合テストの `pytest.mark.integration`**: `pyproject.toml` に未登録のため warning が出る。必要なら `[tool.pytest.ini_options] markers` に追加する
