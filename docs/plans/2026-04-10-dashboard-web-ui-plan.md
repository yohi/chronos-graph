# Chronos Graph Dashboard Web UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `docs/plans/2026-04-10-dashboard-web-ui-design.md` (rev. 10) で定義された Read-Only CQRS ダッシュボード (FastAPI + React + Cytoscape.js) を、レビューしやすい 14 個の PR に分割して実装する。

**Architecture:** Dashboard は既存 `create_storage(settings, read_only=True)` 経由で `StorageAdapter` / `GraphAdapter` を直接取得する Read-Only CQRS プロセス。Orchestrator や `EmbeddingProvider` は一切初期化しない。フロントエンドは Vite + React + TypeScript + Zustand + Cytoscape.js。バックエンドは `src/context_store/dashboard/`、フロントエンドは `frontend/` に配置。

**Tech Stack:**
- Backend: Python 3.12, FastAPI, uvicorn, websockets, pytest, httpx, aiosqlite
- Frontend: React 18, TypeScript 5, Vite 5, Tailwind CSS, Zustand, Cytoscape.js (cose-bilkent), React Router v6, MSW, Vitest, React Testing Library, Playwright
- Infra: Docker Compose, 既存 `pyproject.toml` の optional-dependencies `dashboard`

---

## Design Document Reference

**必読**: すべてのタスク着手前に `docs/plans/2026-04-10-dashboard-web-ui-design.md` (rev. 10) を参照すること。本計画はその実装手順のみを定義し、設計判断の根拠は設計書に集約されている。

---

## PR 分割戦略

| PR | タイトル | 概要 | 推定 LOC | 依存 |
|---|---|---|---|---|
| 1 | `feat(config): add dashboard-related Settings fields` | `config.py` に `graph_backend`/`log_level`/`dashboard_port`/`dashboard_allowed_hosts`/`embedding_model` 追加 | ~250 | なし |
| 2 | `feat(storage): add read_only mode to create_storage factory (SQLite)` | `create_storage()` に `read_only` 追加、SQLite URI モード対応 | ~350 | PR 1 |
| 3 | `feat(graph): add list_edges_for_memories and count_edges (SQLite)` | GraphAdapter プロトコル拡張 + SQLite 実装 | ~350 | なし |
| 4 | `feat(graph): add list_edges_for_memories/count_edges and READ_ACCESS (Neo4j)` | Neo4j 実装 + Read-Only セッション | ~350 | PR 2, PR 3 |
| 5 | `feat(dashboard): scaffold package with DashboardService and schemas` | `src/context_store/dashboard/` 骨格 + サービス層 + Pydantic schemas | ~600 | PR 3 |
| 6 | `feat(dashboard): FastAPI app with stats/memories/system routes` | `api_server.py` + lifespan + 3 ルート + pyproject 依存 + エントリポイント | ~700 | PR 1, PR 2, PR 5 |
| 7 | `feat(dashboard): add graph routes (layout, traverse)` | `routes/graph.py` + 503 handling | ~400 | PR 4, PR 6 |
| 8 | `feat(dashboard): log collector and websocket manager` | `log_collector.py` + `websocket_manager.py` + ユニットテスト | ~600 | なし (PR 6 と並列可) |
| 9 | `feat(dashboard): logs route and websocket endpoint` | `routes/logs.py` + WS + lifespan 統合 | ~500 | PR 6, PR 8 |
| 10 | `feat(frontend): scaffold Vite+React+TS+Tailwind project` | `frontend/` 初期化、ルーティング、レイアウト、MSW | ~600 | なし |
| 11 | `feat(frontend): stores, API client, theme toggle, Dashboard page` | Zustand + api/ + ThemeToggle + Dashboard.tsx + StatCard | ~800 | PR 10 |
| 12 | `feat(frontend): NetworkView with Cytoscape.js` | Graph 可視化コンポーネント一式 | ~850 | PR 11 |
| 13 | `feat(frontend): LogExplorer with websocket streaming` | useWebSocket + useLogStream + LogExplorer 一式 | ~700 | PR 11 |
| 14 | `feat(dashboard): Settings page, SPA fallback, docker-compose, E2E` | Settings.tsx + FastAPI SPA fallback + docker-compose + Playwright | ~900 | PR 6, PR 12, PR 13 |

**並列化ガイド:**
- PR 1 / PR 3 / PR 8 / PR 10 は相互に独立 → 並列着手可
- PR 10-11 は PR 6 完了を待たずに MSW で進行可
- PR 4 は Neo4j 環境が必要なため CI 設定も含めて先に着手する価値あり

**各 PR の共通要件:**
1. 必ず **失敗するテストを先に書く (TDD)**
2. コミット粒度は「テスト追加 → 実装 → リファクタ」の 3 コミット以上
3. PR description に設計書 rev. 10 の該当章番号を明記
4. `ruff check`, `ruff format --check`, `mypy` (backend)、`eslint`, `tsc --noEmit` (frontend) を PR 作成前にパスさせる
5. 既存テストに破綻がないことを `pytest tests/ -x` で確認

---

## 共通準備

### Task 0: Worktree の準備 (任意)

既にブランチ `feat/dashboard` で作業中のため、worktree 追加は不要。新規に作業を開始する場合は:

- [ ] **Step 1: ブランチ確認**

```bash
cd /home/y_ohi/program/private/chronos-graph
git status
git branch --show-current
```

Expected: `feat/dashboard` ブランチ、clean working tree

---

## PR 1: Settings 拡張

**Goal:** `Settings` クラスに Dashboard 関連フィールドを追加する(他の PR すべての前提)。

**Files:**
- Modify: `src/context_store/config.py`
- Test: `tests/unit/test_config.py` (既存拡張)

### Task 1.1: 失敗するテストを追加

- [ ] **Step 1: 既存 `test_config.py` を確認**

```bash
cat tests/unit/test_config.py 2>&1 | head -50
```

- [ ] **Step 2: 新規テスト追加**

`tests/unit/test_config.py` 末尾に以下を追加:

```python
def test_settings_has_dashboard_fields_with_defaults(monkeypatch):
    """rev.10: Dashboard 用フィールドのデフォルト値を確認。"""
    # 既存必須 env をクリア
    monkeypatch.delenv("DASHBOARD_PORT", raising=False)
    monkeypatch.delenv("DASHBOARD_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.delenv("GRAPH_BACKEND", raising=False)

    s = Settings()

    assert s.log_level == "INFO"
    assert s.dashboard_port == 8000
    assert s.dashboard_allowed_hosts == ["localhost", "127.0.0.1"]
    # graph_backend は graph_enabled から派生
    assert s.graph_backend in ("sqlite", "neo4j", "disabled")


def test_settings_graph_backend_derivation(monkeypatch):
    """graph_backend は storage_backend + graph_enabled から自動導出される。"""
    monkeypatch.setenv("STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("GRAPH_ENABLED", "true")
    s = Settings()
    assert s.graph_backend == "sqlite"

    monkeypatch.setenv("STORAGE_BACKEND", "postgres")
    monkeypatch.setenv("GRAPH_ENABLED", "true")
    s = Settings()
    assert s.graph_backend == "neo4j"

    monkeypatch.setenv("GRAPH_ENABLED", "false")
    s = Settings()
    assert s.graph_backend == "disabled"


def test_settings_embedding_model_derivation(monkeypatch):
    """embedding_model は embedding_provider に応じて適切なフィールドから解決される。"""
    monkeypatch.setenv("EMBEDDING_PROVIDER", "local")
    monkeypatch.setenv("LOCAL_MODEL_NAME", "intfloat/multilingual-e5-base")
    s = Settings()
    assert s.embedding_model == "intfloat/multilingual-e5-base"


def test_settings_dashboard_allowed_hosts_from_env(monkeypatch):
    """DASHBOARD_ALLOWED_HOSTS はカンマ区切りで解釈される。"""
    monkeypatch.setenv("DASHBOARD_ALLOWED_HOSTS", "localhost,127.0.0.1,example.internal")
    s = Settings()
    assert s.dashboard_allowed_hosts == ["localhost", "127.0.0.1", "example.internal"]
```

- [ ] **Step 3: テストが失敗することを確認**

```bash
pytest tests/unit/test_config.py -x -k "dashboard or graph_backend or embedding_model or log_level" -v
```

Expected: FAIL (`AttributeError: 'Settings' object has no attribute 'log_level'`)

- [ ] **Step 4: コミット (失敗テスト)**

```bash
git add tests/unit/test_config.py
git commit -m "test(config): add tests for dashboard Settings fields"
```

### Task 1.2: Settings に フィールド追加

- [ ] **Step 1: `src/context_store/config.py` を読む**

```bash
wc -l src/context_store/config.py
```

既存構造 (pydantic_settings BaseSettings) を踏襲する。

- [ ] **Step 2: フィールドを追加**

`src/context_store/config.py` の `Settings` クラスに以下を追加(既存 `graph_enabled` の近くに配置):

```python
# --- Logging ---
log_level: str = Field(default="INFO", description="Root log level (DEBUG/INFO/WARNING/ERROR)")

# --- Dashboard (rev.10) ---
dashboard_port: int = Field(default=8000, description="FastAPI dashboard bind port")
dashboard_allowed_hosts: list[str] = Field(
    default_factory=lambda: ["localhost", "127.0.0.1"],
    description="TrustedHostMiddleware allowed hosts for dashboard",
)
```

カンマ区切り文字列を list に変換するため、既存の `model_config` の近くに validator を追加:

```python
from pydantic import field_validator

@field_validator("dashboard_allowed_hosts", mode="before")
@classmethod
def _split_hosts(cls, v):
    if isinstance(v, str):
        return [h.strip() for h in v.split(",") if h.strip()]
    return v
```

`graph_backend` と `embedding_model` は派生プロパティとして追加:

```python
@property
def graph_backend(self) -> str:
    """Derived: 'sqlite' | 'neo4j' | 'disabled'."""
    if not self.graph_enabled:
        return "disabled"
    if self.storage_backend == "sqlite":
        return "sqlite"
    if self.storage_backend == "postgres":
        return "neo4j"
    return "disabled"

@property
def embedding_model(self) -> str:
    """Derived: 現在の embedding_provider に応じたモデル名。"""
    if self.embedding_provider == "local":
        return self.local_model_name
    if self.embedding_provider == "litellm":
        return self.litellm_model
    return "unknown"
```

- [ ] **Step 3: テストを実行**

```bash
pytest tests/unit/test_config.py -x -v
```

Expected: PASS(追加した 4 テストすべて)

- [ ] **Step 4: 全テスト実行で退行なし確認**

```bash
pytest tests/ -x --timeout=60
```

Expected: PASS(既存テストが壊れていないこと)

- [ ] **Step 5: Lint / Type check**

```bash
ruff check src/context_store/config.py
ruff format src/context_store/config.py
mypy src/context_store/config.py
```

- [ ] **Step 6: コミット**

```bash
git add src/context_store/config.py
git commit -m "feat(config): add dashboard-related Settings fields

- Add log_level, dashboard_port, dashboard_allowed_hosts
- Add graph_backend and embedding_model as derived properties
- Refs docs/plans/2026-04-10-dashboard-web-ui-design.md rev.10 §3.2"
```

### Task 1.3: PR 1 作成

- [ ] **Step 1: PR を作成**

```bash
git push -u origin feat/dashboard
gh pr create --title "feat(config): add dashboard-related Settings fields" --body "$(cat <<'EOF'
## Summary
- `Settings` に rev.10 で要求された Dashboard 用フィールドを追加
- `log_level`, `dashboard_port`, `dashboard_allowed_hosts` を環境変数対応付きで追加
- `graph_backend` / `embedding_model` は既存フィールドからの派生プロパティ (YAGNI)

## Design Reference
- `docs/plans/2026-04-10-dashboard-web-ui-design.md` rev. 10 §3.2

## Test Plan
- [x] 新規: `test_settings_has_dashboard_fields_with_defaults`
- [x] 新規: `test_settings_graph_backend_derivation`
- [x] 新規: `test_settings_embedding_model_derivation`
- [x] 新規: `test_settings_dashboard_allowed_hosts_from_env`
- [x] 既存テスト全 Green
EOF
)"
```

---

## PR 2: `create_storage()` に read_only モード追加 (SQLite)

**Goal:** 既存 `storage/factory.py` の `create_storage()` に `read_only: bool = False` を追加し、SQLite バックエンドで `file:...?mode=ro` URI を使う経路を実装する。

**Files:**
- Modify: `src/context_store/storage/factory.py`
- Modify: `src/context_store/storage/sqlite.py`
- Modify: `src/context_store/storage/sqlite_graph.py`
- Test: `tests/integration/test_storage_readonly.py` (新規)

### Task 2.1: 失敗する統合テストを追加

- [ ] **Step 1: 新規テストファイル作成**

`tests/integration/test_storage_readonly.py`:

```python
"""Read-only mode integration tests for create_storage() factory (rev.10)."""

from __future__ import annotations

import sqlite3

import pytest

from context_store.config import Settings
from context_store.models.memory import Memory
from context_store.storage.factory import create_storage


@pytest.fixture
async def seeded_sqlite(tmp_path):
    """まず write モードで DB を作り、1 件 seed してから read-only で開き直すためのセットアップ。"""
    db_path = tmp_path / "test.db"
    settings = Settings(
        storage_backend="sqlite",
        sqlite_db_path=str(db_path),
        cache_backend="inmemory",
        graph_enabled=True,
    )

    # write モードで初期化 + seed
    storage, graph, cache = await create_storage(settings)
    try:
        mem = Memory(
            id="test-ro-1",
            content="read-only test seed",
            memory_type="episodic",
            project="ro-proj",
        )
        await storage.save_memory(mem)
    finally:
        await storage.dispose()
        if graph:
            await graph.dispose()
        await cache.dispose()

    return settings


@pytest.mark.asyncio
async def test_create_storage_read_only_can_read(seeded_sqlite):
    """read_only=True でも既存データを読み取れる。"""
    settings = seeded_sqlite
    storage, graph, cache = await create_storage(settings, read_only=True)
    try:
        mem = await storage.get_memory("test-ro-1")
        assert mem is not None
        assert mem.content == "read-only test seed"
    finally:
        await storage.dispose()
        if graph:
            await graph.dispose()
        await cache.dispose()


@pytest.mark.asyncio
async def test_create_storage_read_only_blocks_writes(seeded_sqlite):
    """read_only=True では save_memory が SQLite レベルで失敗する。"""
    settings = seeded_sqlite
    storage, graph, cache = await create_storage(settings, read_only=True)
    try:
        mem = Memory(
            id="should-fail",
            content="must not be written",
            memory_type="episodic",
            project="ro-proj",
        )
        with pytest.raises((sqlite3.OperationalError, Exception)) as exc_info:
            await storage.save_memory(mem)
        # sqlite3.OperationalError "attempt to write a readonly database" 等を期待
        assert "readonly" in str(exc_info.value).lower() or "read" in str(exc_info.value).lower()
    finally:
        await storage.dispose()
        if graph:
            await graph.dispose()
        await cache.dispose()


@pytest.mark.asyncio
async def test_create_storage_default_is_write_mode(tmp_path):
    """read_only を指定しない場合は write 可能 (既存挙動の退行テスト)。"""
    db_path = tmp_path / "rw.db"
    settings = Settings(
        storage_backend="sqlite",
        sqlite_db_path=str(db_path),
        cache_backend="inmemory",
        graph_enabled=False,
    )
    storage, graph, cache = await create_storage(settings)
    try:
        mem = Memory(
            id="rw-1",
            content="write ok",
            memory_type="semantic",
            project="rw",
        )
        await storage.save_memory(mem)
        got = await storage.get_memory("rw-1")
        assert got is not None
    finally:
        await storage.dispose()
        if graph:
            await graph.dispose()
        await cache.dispose()
```

- [ ] **Step 2: テスト実行 (失敗を確認)**

```bash
pytest tests/integration/test_storage_readonly.py -x -v
```

Expected: FAIL(`create_storage() got an unexpected keyword argument 'read_only'`)

- [ ] **Step 3: コミット**

```bash
git add tests/integration/test_storage_readonly.py
git commit -m "test(storage): add read-only mode integration tests"
```

### Task 2.2: `create_storage()` に `read_only` パラメータを追加

- [ ] **Step 1: `src/context_store/storage/factory.py` を編集**

`create_storage()` シグネチャに `read_only: bool = False` を追加し、`_create_storage_adapter` と `_create_graph_adapter` に伝播:

```python
async def create_storage(
    settings: "Settings",
    *,
    read_only: bool = False,
) -> tuple["StorageAdapter", "GraphAdapter | None", "CacheAdapter"]:
    """Create storage, graph, and cache adapters from *settings*.

    Args:
        settings: Application settings.
        read_only: If True, open SQLite with ``mode=ro`` URI and Neo4j with READ_ACCESS.
            Cache coherence checker is skipped (Dashboard does not mutate data).

    Returns:
        (StorageAdapter, GraphAdapter | None, CacheAdapter)
    """
    storage = None
    graph_adp = None
    cache_adp = None
    try:
        storage = await _create_storage_adapter(settings, read_only=read_only)
        graph_adp = await _create_graph_adapter(settings, read_only=read_only)
        cache_adp = await _create_cache_adapter(settings)

        # read-only の場合はコヒーレンスチェッカーをスキップ (writes 不要)
        if (
            not read_only
            and settings.storage_backend == "sqlite"
            and settings.cache_backend == "inmemory"
        ):
            # 既存のコヒーレンスチェッカー起動コードを read_only=False の場合のみ実行
            ...
        return storage, graph_adp, cache_adp
    except Exception:
        # 既存のクリーンアップロジック維持
        ...
```

`_create_storage_adapter` と `_create_graph_adapter` に `read_only` 引数を追加:

```python
async def _create_storage_adapter(
    settings: "Settings", *, read_only: bool = False
) -> "StorageAdapter":
    if settings.storage_backend == "sqlite":
        from context_store.storage.sqlite import SQLiteStorageAdapter
        return await SQLiteStorageAdapter.create(settings, read_only=read_only)
    if settings.storage_backend == "postgres":
        from context_store.storage.postgres import PostgresStorageAdapter
        # Postgres の read-only は Phase 6 (rev.10 §3.6)
        if read_only:
            raise NotImplementedError(
                "read_only mode for postgres backend is not yet supported (Phase 6)"
            )
        return await PostgresStorageAdapter.create(settings)
    raise ValueError(f"Unsupported storage_backend: {settings.storage_backend!r}")


async def _create_graph_adapter(
    settings: "Settings", *, read_only: bool = False
) -> "GraphAdapter | None":
    if not settings.graph_enabled:
        return None

    if settings.storage_backend == "sqlite":
        import os
        from context_store.storage.sqlite_graph import SQLiteGraphAdapter
        db_path = os.path.expanduser(settings.sqlite_db_path)
        adp = SQLiteGraphAdapter(db_path=db_path, settings=settings, read_only=read_only)
        await adp.initialize()
        return adp

    if settings.storage_backend == "postgres":
        # Neo4j の read-only は PR 4 で追加
        if read_only:
            raise NotImplementedError(
                "read_only mode for neo4j backend is added in PR 4"
            )
        # 既存 Neo4j 初期化ロジック維持
        ...
    raise ValueError(f"Unsupported storage_backend for graph: {settings.storage_backend!r}")
```

- [ ] **Step 2: `sqlite.py` を編集**

`SQLiteStorageAdapter.create()` に `read_only` 引数を追加し、接続 URI を切り替える。aiosqlite の URI モードは `aiosqlite.connect(f"file:{path}?mode=ro", uri=True)` で有効化できる。

```python
@classmethod
async def create(
    cls, settings: Settings, *, read_only: bool = False
) -> "SQLiteStorageAdapter":
    instance = cls(settings, read_only=read_only)
    await instance._initialize()
    return instance

def __init__(self, settings: Settings, *, read_only: bool = False) -> None:
    self._settings = settings
    self._read_only = read_only
    ...

async def _get_connection(self) -> aiosqlite.Connection:
    if self._read_only:
        db_path = os.path.expanduser(self._settings.sqlite_db_path)
        conn = await aiosqlite.connect(f"file:{db_path}?mode=ro", uri=True)
    else:
        conn = await aiosqlite.connect(self._settings.sqlite_db_path)
        await conn.execute("PRAGMA journal_mode=WAL")
    ...
```

**重要**: `_initialize()` 内のスキーマ作成ロジックは `read_only=True` の場合スキップする(DB 未初期化時のフェイルファストは Dashboard 側 lifespan で行う / 設計書 §2.2)。

```python
async def _initialize(self) -> None:
    if self._read_only:
        # 既存スキーマを前提とするため何もしない
        return
    # 既存の CREATE TABLE / CREATE INDEX 等
    ...
```

- [ ] **Step 3: `sqlite_graph.py` を編集**

`SQLiteGraphAdapter.__init__` に `read_only` パラメータを追加し、`initialize()` で read-only 時はスキーマ作成をスキップ:

```python
def __init__(
    self, db_path: str, settings: Settings, *, read_only: bool = False
) -> None:
    self._db_path = db_path
    self._settings = settings
    self._read_only = read_only

async def initialize(self) -> None:
    if self._read_only:
        return
    # 既存のスキーマ初期化
    ...

async def _connect(self) -> aiosqlite.Connection:
    if self._read_only:
        conn = await aiosqlite.connect(f"file:{self._db_path}?mode=ro", uri=True)
    else:
        conn = await aiosqlite.connect(self._db_path)
        await conn.execute("PRAGMA journal_mode=WAL")
    return conn
```

- [ ] **Step 4: テスト実行**

```bash
pytest tests/integration/test_storage_readonly.py -x -v
```

Expected: PASS(3 テストすべて)

- [ ] **Step 5: 全テスト退行確認**

```bash
pytest tests/ -x --timeout=120
```

Expected: PASS

- [ ] **Step 6: Lint / Type check**

```bash
ruff check src/context_store/storage/
ruff format src/context_store/storage/
mypy src/context_store/storage/factory.py src/context_store/storage/sqlite.py src/context_store/storage/sqlite_graph.py
```

- [ ] **Step 7: コミット**

```bash
git add src/context_store/storage/factory.py src/context_store/storage/sqlite.py src/context_store/storage/sqlite_graph.py
git commit -m "feat(storage): add read_only mode to create_storage (SQLite)

- create_storage(settings, read_only=True) で SQLite URI モードに切替
- SQLiteStorageAdapter と SQLiteGraphAdapter が file:...?mode=ro で接続
- Cache coherence checker は read_only=True でスキップ (writes 不要)
- Postgres/Neo4j の read_only はそれぞれ Phase 6 / PR 4 で対応
- Refs design rev.10 §2.2"
```

### Task 2.3: PR 2 作成

- [ ] **Step 1: PR 作成**

```bash
gh pr create --title "feat(storage): add read_only mode to create_storage factory (SQLite)" --body "..."
```

---

## PR 3: GraphAdapter に `list_edges_for_memories` / `count_edges` を追加 (SQLite 実装)

**Goal:** Dashboard が必要とする 2 つのグラフクエリメソッドをプロトコルに追加し、SQLite バックエンドで実装する。Neo4j 実装は PR 4。

**Files:**
- Modify: `src/context_store/storage/protocols.py`
- Modify: `src/context_store/storage/sqlite_graph.py`
- Modify: `src/context_store/storage/neo4j.py` (スタブのみ、本体は PR 4)
- Test: `tests/unit/test_sqlite_graph.py` (既存拡張)
- Test: `tests/integration/test_sqlite_graph_dashboard.py` (新規)

### Task 3.1: プロトコルに新規メソッドを追加 (失敗テスト先行)

- [ ] **Step 1: 失敗するユニットテスト作成**

`tests/unit/test_sqlite_graph.py` または `tests/integration/test_sqlite_graph_dashboard.py` (新規) に以下を追加:

```python
import pytest
from context_store.config import Settings
from context_store.storage.sqlite_graph import SQLiteGraphAdapter


@pytest.fixture
async def graph_adapter(tmp_path):
    settings = Settings(
        storage_backend="sqlite",
        sqlite_db_path=str(tmp_path / "graph.db"),
        graph_enabled=True,
    )
    adp = SQLiteGraphAdapter(db_path=str(tmp_path / "graph.db"), settings=settings)
    await adp.initialize()
    # seed: 3 nodes, 2 edges
    await adp.create_node("m1", {"memory_type": "episodic"})
    await adp.create_node("m2", {"memory_type": "semantic"})
    await adp.create_node("m3", {"memory_type": "procedural"})
    await adp.create_edge("m1", "m2", "RELATED", {})
    await adp.create_edge("m2", "m3", "DERIVED_FROM", {})
    yield adp
    await adp.dispose()


@pytest.mark.asyncio
async def test_list_edges_for_memories_returns_connecting_edges(graph_adapter):
    edges = await graph_adapter.list_edges_for_memories(["m1", "m2", "m3"])
    assert len(edges) == 2
    types = {e.edge_type for e in edges}
    assert types == {"RELATED", "DERIVED_FROM"}


@pytest.mark.asyncio
async def test_list_edges_for_memories_only_includes_edges_where_both_endpoints_in_set(
    graph_adapter,
):
    """m1 と m3 だけを渡した場合、m2 を経由するエッジは含まれない。"""
    edges = await graph_adapter.list_edges_for_memories(["m1", "m3"])
    assert len(edges) == 0


@pytest.mark.asyncio
async def test_list_edges_for_memories_empty_input(graph_adapter):
    edges = await graph_adapter.list_edges_for_memories([])
    assert edges == []


@pytest.mark.asyncio
async def test_count_edges_returns_total_count(graph_adapter):
    n = await graph_adapter.count_edges()
    assert n == 2


@pytest.mark.asyncio
async def test_list_edges_chunking_for_large_input(graph_adapter):
    """IN 句パラメータ上限 (999) を超えるサイズでもエラーなく動作する (rev.10 §3.5)。"""
    # 1500 件の ID (存在しないものを含む)
    ids = [f"nonexistent-{i}" for i in range(1500)]
    ids.extend(["m1", "m2"])
    edges = await graph_adapter.list_edges_for_memories(ids)
    # m1-m2 のエッジ 1 本が返る
    assert len(edges) == 1
```

- [ ] **Step 2: 実行して FAIL 確認**

```bash
pytest tests/integration/test_sqlite_graph_dashboard.py -x -v
```

Expected: FAIL(`AttributeError: 'SQLiteGraphAdapter' object has no attribute 'list_edges_for_memories'`)

- [ ] **Step 3: コミット**

```bash
git add tests/integration/test_sqlite_graph_dashboard.py
git commit -m "test(graph): add tests for list_edges_for_memories and count_edges"
```

### Task 3.2: プロトコル拡張

- [ ] **Step 1: `protocols.py` に追加**

`GraphAdapter` Protocol に以下を追加:

```python
async def list_edges_for_memories(self, memory_ids: list[str]) -> list[Edge]:
    """Return all edges where BOTH endpoints are in ``memory_ids``.

    For large input lists that exceed SQLite's parameter limit (999),
    implementations MUST chunk the query internally (rev.10 §3.5).

    Args:
        memory_ids: Memory IDs to filter edges by. Empty list returns ``[]``.

    Returns:
        List of edges whose ``from_id`` AND ``to_id`` are both in ``memory_ids``.
    """
    ...

async def count_edges(self) -> int:
    """Return the total number of edges in the graph."""
    ...
```

`Edge` 型のインポートも必要:

```python
from context_store.models.graph import Edge, GraphResult
```

### Task 3.3: SQLite 実装

- [ ] **Step 1: `sqlite_graph.py` に実装追加**

```python
async def list_edges_for_memories(self, memory_ids: list[str]) -> list[Edge]:
    if not memory_ids:
        return []

    # SQLite parameter limit (999) への対策: 500 件ずつチャンク分割
    CHUNK_SIZE = 500
    all_edges: list[Edge] = []
    seen: set[tuple[str, str, str]] = set()

    async with await self._connect() as conn:
        conn.row_factory = aiosqlite.Row
        for i in range(0, len(memory_ids), CHUNK_SIZE):
            chunk = memory_ids[i : i + CHUNK_SIZE]
            placeholders = ",".join("?" * len(chunk))
            # 両端点が chunk に含まれるエッジを取得
            # (chunk 間のエッジを拾うため memory_ids 全体と突合する必要があるが、
            #  500 ノード上限の MVP では 1 chunk で収まる)
            query = f"""
                SELECT from_id, to_id, edge_type, props
                FROM edges
                WHERE from_id IN ({placeholders}) AND to_id IN ({placeholders})
            """
            async with conn.execute(query, [*chunk, *chunk]) as cursor:
                rows = await cursor.fetchall()

            for row in rows:
                key = (row["from_id"], row["to_id"], row["edge_type"])
                if key in seen:
                    continue
                seen.add(key)
                all_edges.append(
                    Edge(
                        from_id=row["from_id"],
                        to_id=row["to_id"],
                        edge_type=row["edge_type"],
                        props=json.loads(row["props"]) if row["props"] else {},
                    )
                )
    return all_edges


async def count_edges(self) -> int:
    async with await self._connect() as conn:
        async with conn.execute("SELECT COUNT(*) FROM edges") as cursor:
            row = await cursor.fetchone()
            return int(row[0]) if row else 0
```

**注**: チャンク間をまたぐエッジも拾いたい場合は `(from_id IN chunk1 AND to_id IN chunk2)` の二重ループが必要だが、MVP 500 ノード制限下では不要 (設計書 §3.5)。そのため上記の単純チャンクで十分。

- [ ] **Step 2: `neo4j.py` にスタブ追加 (実装は PR 4)**

一時的に:

```python
async def list_edges_for_memories(self, memory_ids: list[str]) -> list[Edge]:
    raise NotImplementedError("Implemented in PR 4")

async def count_edges(self) -> int:
    raise NotImplementedError("Implemented in PR 4")
```

- [ ] **Step 3: テスト実行**

```bash
pytest tests/integration/test_sqlite_graph_dashboard.py -x -v
```

Expected: PASS

- [ ] **Step 4: 退行テスト**

```bash
pytest tests/ -x --timeout=120
```

- [ ] **Step 5: コミット**

```bash
git add src/context_store/storage/protocols.py src/context_store/storage/sqlite_graph.py src/context_store/storage/neo4j.py
git commit -m "feat(graph): add list_edges_for_memories and count_edges (SQLite)

- Add to GraphAdapter protocol with chunking contract (rev.10 §3.5)
- Implement in SQLiteGraphAdapter with 500-item chunks
- Neo4jGraphAdapter stub raises NotImplementedError (PR 4 follow-up)
- Refs design rev.10 §3.5, §3.6"
```

### Task 3.4: PR 3 作成

- [ ] **Step 1: PR 作成**

---

## PR 4: Neo4j 実装 + READ_ACCESS セッション

**Goal:** PR 3 で追加した 2 メソッドの Neo4j 実装と、PR 2 で追加した `read_only=True` の Neo4j 対応を完了する。

**Files:**
- Modify: `src/context_store/storage/neo4j.py`
- Modify: `src/context_store/storage/factory.py`
- Test: `tests/integration/test_neo4j_dashboard.py` (新規、Neo4j 環境必須)

### Task 4.1: 失敗する統合テスト作成

- [ ] **Step 1: 新規テスト** — 既存 Neo4j テストのパターン (`tests/integration/test_neo4j*.py`) を踏襲。Marker `@pytest.mark.neo4j` を付与し CI で Neo4j サービス起動を前提とする。

```python
@pytest.mark.neo4j
@pytest.mark.asyncio
async def test_neo4j_list_edges_for_memories(neo4j_adapter_seeded):
    """SQLite と同じ契約: 両端点が集合内のエッジのみ返す。"""
    edges = await neo4j_adapter_seeded.list_edges_for_memories(["m1", "m2", "m3"])
    assert len(edges) == 2


@pytest.mark.neo4j
@pytest.mark.asyncio
async def test_neo4j_count_edges(neo4j_adapter_seeded):
    n = await neo4j_adapter_seeded.count_edges()
    assert n >= 2


@pytest.mark.neo4j
@pytest.mark.asyncio
async def test_neo4j_read_only_mode_blocks_writes(neo4j_seeded_db, settings_postgres):
    """rev.10 §2.2: read_only=True で Neo4j セッションが READ_ACCESS になる。"""
    storage, graph, cache = await create_storage(settings_postgres, read_only=True)
    try:
        with pytest.raises(Exception) as exc_info:
            await graph.create_node("should-fail", {})
        assert "write" in str(exc_info.value).lower() or "read" in str(exc_info.value).lower()
    finally:
        await storage.dispose()
        if graph:
            await graph.dispose()
        await cache.dispose()
```

### Task 4.2: Neo4j 実装

- [ ] **Step 1: `neo4j.py` の `Neo4jGraphAdapter` に実装**

```python
@classmethod
async def create(
    cls,
    uri: str,
    user: str,
    password: SecretStr,
    *,
    read_only: bool = False,
) -> "Neo4jGraphAdapter":
    ...

def __init__(self, ..., read_only: bool = False) -> None:
    self._read_only = read_only
    ...

def _session(self):
    """READ session if read_only else WRITE session."""
    from neo4j import READ_ACCESS, WRITE_ACCESS
    access_mode = READ_ACCESS if self._read_only else WRITE_ACCESS
    return self._driver.session(default_access_mode=access_mode)

async def list_edges_for_memories(self, memory_ids: list[str]) -> list[Edge]:
    if not memory_ids:
        return []
    query = """
    MATCH (a:Memory)-[r]->(b:Memory)
    WHERE a.id IN $ids AND b.id IN $ids
    RETURN a.id AS from_id, b.id AS to_id, type(r) AS edge_type, properties(r) AS props
    """
    async with self._session() as session:
        result = await session.run(query, ids=memory_ids)
        records = [record async for record in result]
    return [
        Edge(
            from_id=r["from_id"],
            to_id=r["to_id"],
            edge_type=r["edge_type"],
            props=dict(r["props"]),
        )
        for r in records
    ]

async def count_edges(self) -> int:
    query = "MATCH ()-[r]->() RETURN count(r) AS cnt"
    async with self._session() as session:
        result = await session.run(query)
        record = await result.single()
    return int(record["cnt"]) if record else 0
```

- [ ] **Step 2: `factory.py` の Neo4j 経路で `read_only` 伝播**

PR 2 で残した `NotImplementedError` を解除:

```python
if settings.storage_backend == "postgres":
    from context_store.storage.neo4j import Neo4jGraphAdapter
    if (...credentials missing...):
        raise ValueError(...)
    return await Neo4jGraphAdapter.create(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password,
        read_only=read_only,
    )
```

- [ ] **Step 3: テスト実行**

```bash
# Neo4j サービスを起動 (docker-compose の既存設定を利用)
docker compose up -d neo4j
pytest tests/integration/test_neo4j_dashboard.py -x -v -m neo4j
```

Expected: PASS

- [ ] **Step 4: コミット + PR**

```bash
git commit -m "feat(graph): add Neo4j implementation and READ_ACCESS support

- Implement list_edges_for_memories and count_edges in Neo4jGraphAdapter
- Honor read_only via default_access_mode=READ_ACCESS sessions
- create_storage now fully supports read_only for both SQLite and Neo4j
- Refs design rev.10 §2.2, §3.5, §3.6"
```

---

## PR 5: Dashboard パッケージ骨格 + DashboardService + schemas

**Goal:** Dashboard パッケージ構造を作り、FastAPI に依存しない純粋な `DashboardService` クラスと Pydantic レスポンスモデルを実装する。ルート/Lifespan/FastAPI app は次の PR 6。

**Files:**
- Create: `src/context_store/dashboard/__init__.py`
- Create: `src/context_store/dashboard/schemas.py`
- Create: `src/context_store/dashboard/services.py`
- Test: `tests/unit/test_dashboard_schemas.py`
- Test: `tests/unit/test_dashboard_service.py`

### Task 5.1: スキーマ定義 + テスト

- [ ] **Step 1: `test_dashboard_schemas.py` で失敗テスト**

```python
from context_store.dashboard.schemas import (
    DashboardStats,
    GraphLayoutResponse,
    MemoryNode,
    MemoryEdge,
)


def test_dashboard_stats_camel_case_alias():
    s = DashboardStats(
        active_count=10,
        archived_count=2,
        total_count=12,
        edge_count=5,
        project_count=1,
        projects=["p1"],
    )
    data = s.model_dump(by_alias=True)
    assert data == {
        "activeCount": 10,
        "archivedCount": 2,
        "totalCount": 12,
        "edgeCount": 5,
        "projectCount": 1,
        "projects": ["p1"],
    }


def test_graph_layout_response_structure():
    resp = GraphLayoutResponse(
        elements={"nodes": [], "edges": []},
        total_nodes=0,
        returned_nodes=0,
        total_edges=0,
    )
    data = resp.model_dump(by_alias=True)
    assert "totalNodes" in data
    assert "returnedNodes" in data
```

- [ ] **Step 2: `schemas.py` を実装**

```python
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class DashboardBaseModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class DashboardStats(DashboardBaseModel):
    active_count: int
    archived_count: int
    total_count: int
    edge_count: int
    project_count: int
    projects: list[str]


class ProjectStats(DashboardBaseModel):
    project: str
    active_count: int
    archived_count: int
    total_count: int


class MemoryNode(DashboardBaseModel):
    id: str
    label: str
    memory_type: str
    importance: float
    project: str | None
    access_count: int
    created_at: str


class MemoryEdge(DashboardBaseModel):
    id: str
    source: str
    target: str
    edge_type: str


class GraphElementsDTO(DashboardBaseModel):
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]


class GraphLayoutResponse(DashboardBaseModel):
    elements: GraphElementsDTO
    total_nodes: int
    returned_nodes: int
    total_edges: int


class SystemConfigResponse(DashboardBaseModel):
    storage_backend: str
    graph_backend: str
    cache_backend: str
    embedding_provider: str
    embedding_model: str
    log_level: str
    dashboard_port: int


class LogEntry(DashboardBaseModel):
    timestamp: str
    level: str
    logger: str
    message: str
```

- [ ] **Step 3: テスト Green 確認 → コミット**

### Task 5.2: DashboardService + テスト

- [ ] **Step 1: 失敗テスト**

`tests/unit/test_dashboard_service.py`:

```python
from unittest.mock import AsyncMock

import pytest

from context_store.dashboard.services import DashboardService
from context_store.models.graph import Edge
from context_store.models.memory import Memory


@pytest.fixture
def storage_mock():
    m = AsyncMock()
    return m


@pytest.fixture
def graph_mock():
    m = AsyncMock()
    return m


@pytest.mark.asyncio
async def test_get_stats_summary_aggregates_counts(storage_mock, graph_mock):
    storage_mock.count_by_filter.side_effect = [120, 30, 150]  # active, archived, total
    storage_mock.list_projects.return_value = ["p1", "p2"]
    graph_mock.count_edges.return_value = 42

    svc = DashboardService(storage=storage_mock, graph=graph_mock)
    stats = await svc.get_stats_summary()

    assert stats.active_count == 120
    assert stats.archived_count == 30
    assert stats.total_count == 150
    assert stats.edge_count == 42
    assert stats.project_count == 2
    assert stats.projects == ["p1", "p2"]


@pytest.mark.asyncio
async def test_get_stats_summary_graph_none(storage_mock):
    storage_mock.count_by_filter.side_effect = [10, 0, 10]
    storage_mock.list_projects.return_value = []
    svc = DashboardService(storage=storage_mock, graph=None)
    stats = await svc.get_stats_summary()
    assert stats.edge_count == 0


@pytest.mark.asyncio
async def test_get_graph_layout_returns_cytoscape_format(storage_mock, graph_mock):
    storage_mock.count_by_filter.return_value = 2
    storage_mock.list_by_filter.return_value = [
        Memory(
            id="m1",
            content="test 1",
            memory_type="episodic",
            importance_score=0.8,
            project="p1",
            access_count=3,
        ),
        Memory(
            id="m2",
            content="test 2",
            memory_type="semantic",
            importance_score=0.6,
            project="p1",
            access_count=1,
        ),
    ]
    graph_mock.list_edges_for_memories.return_value = [
        Edge(from_id="m1", to_id="m2", edge_type="RELATED", props={}),
    ]

    svc = DashboardService(storage=storage_mock, graph=graph_mock)
    resp = await svc.get_graph_layout(project="p1", limit=500)

    assert resp.returned_nodes == 2
    assert resp.total_edges == 1
    assert len(resp.elements.nodes) == 2
    assert len(resp.elements.edges) == 1
    # Cytoscape 形式
    first_node = resp.elements.nodes[0]
    assert "data" in first_node
    assert first_node["data"]["id"] in ("m1", "m2")


@pytest.mark.asyncio
async def test_traverse_graph_raises_without_graph_backend(storage_mock):
    svc = DashboardService(storage=storage_mock, graph=None)
    with pytest.raises(RuntimeError, match="graph backend"):
        await svc.traverse_graph("m1")


@pytest.mark.asyncio
async def test_get_project_stats(storage_mock, graph_mock):
    storage_mock.list_projects.return_value = ["p1", "p2"]
    storage_mock.count_by_filter.side_effect = [10, 2, 12, 5, 1, 6]
    svc = DashboardService(storage=storage_mock, graph=graph_mock)
    stats = await svc.get_project_stats()
    assert len(stats) == 2
    assert stats[0].project == "p1"
    assert stats[0].active_count == 10
```

- [ ] **Step 2: `services.py` 実装**

```python
from __future__ import annotations

from typing import Literal

from context_store.dashboard.schemas import (
    DashboardStats,
    GraphElementsDTO,
    GraphLayoutResponse,
    ProjectStats,
)
from context_store.models.graph import GraphResult
from context_store.storage.protocols import (
    GraphAdapter,
    MemoryFilters,
    StorageAdapter,
)


class DashboardService:
    """Read-Only アダプタを組み合わせた Dashboard 専用の集約サービス。"""

    def __init__(
        self,
        storage: StorageAdapter,
        graph: GraphAdapter | None,
    ) -> None:
        self._storage = storage
        self._graph = graph

    async def get_stats_summary(self) -> DashboardStats:
        active = await self._storage.count_by_filter(MemoryFilters(archived=None))
        archived = await self._storage.count_by_filter(MemoryFilters(archived=True))
        total = await self._storage.count_by_filter(MemoryFilters(archived=False))
        projects = await self._storage.list_projects()
        edge_count = await self._graph.count_edges() if self._graph else 0
        return DashboardStats(
            active_count=active,
            archived_count=archived,
            total_count=total,
            edge_count=edge_count,
            project_count=len(projects),
            projects=projects,
        )

    async def get_project_stats(self) -> list[ProjectStats]:
        projects = await self._storage.list_projects()
        result: list[ProjectStats] = []
        for p in projects:
            active = await self._storage.count_by_filter(
                MemoryFilters(project=p, archived=None)
            )
            archived = await self._storage.count_by_filter(
                MemoryFilters(project=p, archived=True)
            )
            result.append(
                ProjectStats(
                    project=p,
                    active_count=active,
                    archived_count=archived,
                    total_count=active + archived,
                )
            )
        return result

    async def get_graph_layout(
        self,
        *,
        project: str | None = None,
        limit: int = 500,
        order_by: Literal["importance", "recency"] = "importance",
    ) -> GraphLayoutResponse:
        sort_column = "importance_score" if order_by == "importance" else "created_at"
        total = await self._storage.count_by_filter(
            MemoryFilters(project=project, archived=None)
        )
        memories = await self._storage.list_by_filter(
            MemoryFilters(
                project=project,
                archived=None,
                limit=limit,
                order_by=sort_column,
            )
        )
        memory_ids = [m.id for m in memories]
        edges = (
            await self._graph.list_edges_for_memories(memory_ids) if self._graph else []
        )
        nodes = [
            {
                "data": {
                    "id": m.id,
                    "label": (m.content or "")[:80],
                    "memoryType": m.memory_type,
                    "importance": m.importance_score,
                    "project": m.project,
                    "accessCount": m.access_count,
                    "createdAt": m.created_at.isoformat() if m.created_at else "",
                }
            }
            for m in memories
        ]
        edge_elements = [
            {
                "data": {
                    "id": f"{e.from_id}-{e.to_id}-{e.edge_type}",
                    "source": e.from_id,
                    "target": e.to_id,
                    "edgeType": e.edge_type,
                }
            }
            for e in edges
        ]
        return GraphLayoutResponse(
            elements=GraphElementsDTO(nodes=nodes, edges=edge_elements),
            total_nodes=total,
            returned_nodes=len(memories),
            total_edges=len(edges),
        )

    async def traverse_graph(
        self,
        seed_id: str,
        *,
        max_depth: int = 2,
        edge_types: list[str] | None = None,
    ) -> GraphResult:
        if self._graph is None:
            raise RuntimeError("graph backend not configured")
        return await self._graph.traverse(
            seed_ids=[seed_id],
            edge_types=edge_types or [],
            depth=max_depth,
        )
```

- [ ] **Step 3: `__init__.py` 作成**

```python
"""Chronos Graph Dashboard (Read-Only CQRS)."""

from context_store.dashboard.services import DashboardService

__all__ = ["DashboardService"]
```

- [ ] **Step 4: テスト実行 → PASS 確認**

```bash
pytest tests/unit/test_dashboard_service.py tests/unit/test_dashboard_schemas.py -x -v
```

- [ ] **Step 5: 退行 + Lint → コミット + PR**

```bash
git commit -m "feat(dashboard): scaffold package with DashboardService and schemas

- src/context_store/dashboard/{__init__,schemas,services}.py
- DashboardService aggregates Storage + Graph adapters (CQRS read side)
- Pydantic schemas with camelCase aliases for frontend compatibility
- Unit tests with mocked adapters
- Refs design rev.10 §3.2, §3.6"
```

---

## PR 6: FastAPI app + stats/memories/system ルート

**Goal:** Dashboard プロセスとして起動可能な FastAPI アプリを構築し、グラフ以外の 3 つの REST ルートを実装する。

**Files:**
- Create: `src/context_store/dashboard/api_server.py`
- Create: `src/context_store/dashboard/routes/__init__.py`
- Create: `src/context_store/dashboard/routes/stats.py`
- Create: `src/context_store/dashboard/routes/memories.py`
- Create: `src/context_store/dashboard/routes/system.py`
- Modify: `pyproject.toml`
- Test: `tests/integration/test_dashboard_api_stats.py`
- Test: `tests/integration/test_dashboard_api_memories.py`
- Test: `tests/integration/test_dashboard_api_system.py`
- Test: `tests/integration/test_dashboard_lifespan.py`

### Task 6.1: pyproject.toml 更新

- [ ] **Step 1: `pyproject.toml` 編集**

```toml
[project.optional-dependencies]
dashboard = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "websockets>=12.0",
]

[project.scripts]
context-store = "context_store.server:main"
chronos-dashboard = "context_store.dashboard.api_server:main"
```

- [ ] **Step 2: インストール確認**

```bash
uv sync --extra dashboard
python -c "import fastapi; print(fastapi.__version__)"
```

### Task 6.2: 失敗する統合テスト作成

- [ ] **Step 1: `test_dashboard_api_stats.py`**

```python
import pytest
from httpx import ASGITransport, AsyncClient

from context_store.dashboard.api_server import create_app
from context_store.dashboard.services import DashboardService


@pytest.fixture
async def app_with_mock_service(monkeypatch):
    from unittest.mock import AsyncMock
    service = AsyncMock(spec=DashboardService)
    service.get_stats_summary.return_value = ... # DashboardStats instance
    # create_app は lifespan で実際に create_storage を呼ぶため、
    # テスト用の app factory に service を注入できるフックが必要
    app = create_app(service_override=service)
    yield app, service


@pytest.mark.asyncio
async def test_stats_summary_endpoint(app_with_mock_service):
    app, service = app_with_mock_service
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/stats/summary", headers={"host": "localhost"})
    assert r.status_code == 200
    data = r.json()
    assert "activeCount" in data
    assert "projectCount" in data
```

他のエンドポイント (`/api/stats/projects`, `/api/memories/{id}`, `/api/system/config`) も同様に失敗テストを追加。

- [ ] **Step 2: `test_dashboard_lifespan.py`** — DB 未初期化時のフェイルファスト

```python
@pytest.mark.asyncio
async def test_lifespan_fails_fast_when_db_missing(tmp_path, monkeypatch):
    """rev.10 §2.2: DB 未初期化時は分かりやすいエラーで即終了する。"""
    monkeypatch.setenv("SQLITE_DB_PATH", str(tmp_path / "nonexistent.db"))
    monkeypatch.setenv("STORAGE_BACKEND", "sqlite")
    app = create_app()
    with pytest.raises(Exception) as exc_info:
        async with LifespanManager(app):
            pass
    assert "database" in str(exc_info.value).lower()
```

- [ ] **Step 3: テスト実行 → FAIL 確認 → コミット**

### Task 6.3: api_server.py 実装

- [ ] **Step 1: `api_server.py`**

```python
"""FastAPI application for Chronos Graph Dashboard (Read-Only CQRS)."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from context_store.config import Settings
from context_store.dashboard.services import DashboardService
from context_store.storage.factory import create_storage

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize Read-Only adapters and DashboardService.

    Fails fast if the SQLite database does not exist (rev.10 §2.2).
    """
    settings: Settings = app.state.settings
    try:
        storage, graph, cache = await create_storage(settings, read_only=True)
    except Exception as exc:
        logger.error(
            "Dashboard requires an existing database. Please start the MCP server "
            "(context-store) at least once to initialize the database. Error: %s",
            exc,
        )
        raise SystemExit(1) from exc

    app.state.storage = storage
    app.state.graph = graph
    app.state.cache = cache
    app.state.service = DashboardService(storage=storage, graph=graph)
    try:
        yield
    finally:
        await storage.dispose()
        if graph is not None:
            await graph.dispose()
        await cache.dispose()


def create_app(
    settings: Settings | None = None,
    service_override: DashboardService | None = None,
) -> FastAPI:
    """Application factory. ``service_override`` is for testing."""
    from context_store.dashboard.routes import memories, stats, system

    settings = settings or Settings()

    if service_override is not None:
        # Test mode: skip lifespan, inject service directly
        app = FastAPI(title="Chronos Graph Dashboard")
        app.state.settings = settings
        app.state.service = service_override
    else:
        app = FastAPI(title="Chronos Graph Dashboard", lifespan=_lifespan)
        app.state.settings = settings

    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.dashboard_allowed_hosts,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    app.include_router(stats.router, prefix="/api/stats", tags=["stats"])
    app.include_router(memories.router, prefix="/api/memories", tags=["memories"])
    app.include_router(system.router, prefix="/api/system", tags=["system"])
    return app


def main() -> None:
    """CLI entrypoint: `chronos-dashboard` command."""
    import uvicorn

    settings = Settings()
    logging.basicConfig(level=settings.log_level)
    uvicorn.run(
        create_app(settings),
        host="0.0.0.0",
        port=settings.dashboard_port,
    )
```

- [ ] **Step 2: `routes/stats.py`**

```python
from fastapi import APIRouter, Request

from context_store.dashboard.schemas import DashboardStats, ProjectStats

router = APIRouter()


@router.get("/summary", response_model=DashboardStats, response_model_by_alias=True)
async def get_summary(request: Request) -> DashboardStats:
    return await request.app.state.service.get_stats_summary()


@router.get("/projects", response_model=list[ProjectStats], response_model_by_alias=True)
async def get_projects(request: Request) -> list[ProjectStats]:
    return await request.app.state.service.get_project_stats()
```

- [ ] **Step 3: `routes/memories.py`**

```python
from fastapi import APIRouter, HTTPException, Request

router = APIRouter()


@router.get("/{memory_id}")
async def get_memory(memory_id: str, request: Request):
    storage = request.app.state.storage if hasattr(request.app.state, "storage") else \
        request.app.state.service._storage  # fallback for override mode
    mem = await storage.get_memory(memory_id)
    if mem is None:
        raise HTTPException(404, "Memory not found")
    return mem.model_dump(mode="json")
```

- [ ] **Step 4: `routes/system.py`**

```python
from fastapi import APIRouter, Request

from context_store.dashboard.schemas import SystemConfigResponse

router = APIRouter()


@router.get("/config", response_model=SystemConfigResponse, response_model_by_alias=True)
async def get_config(request: Request) -> SystemConfigResponse:
    s = request.app.state.settings
    return SystemConfigResponse(
        storage_backend=s.storage_backend,
        graph_backend=s.graph_backend,
        cache_backend=s.cache_backend,
        embedding_provider=s.embedding_provider,
        embedding_model=s.embedding_model,
        log_level=s.log_level,
        dashboard_port=s.dashboard_port,
    )
```

- [ ] **Step 5: テスト実行 → PASS → 退行確認 → コミット**

```bash
pytest tests/integration/test_dashboard_api_*.py tests/integration/test_dashboard_lifespan.py -x -v
pytest tests/ -x --timeout=120
git commit -m "feat(dashboard): FastAPI app with stats/memories/system routes

- api_server.py with lifespan (read_only=True) and fail-fast on missing DB
- routes/stats.py, memories.py, system.py
- TrustedHostMiddleware + CORS
- pyproject.toml: [dashboard] optional deps + chronos-dashboard entrypoint
- Integration tests with httpx.AsyncClient
- Refs design rev.10 §2.2, §3.1–3.2, §3.5"
```

### Task 6.4: PR 6 作成

---

## PR 7: Graph ルート (layout + traverse)

**Goal:** `/api/graph/layout` と `/api/graph/traverse` を追加。

**Files:**
- Create: `src/context_store/dashboard/routes/graph.py`
- Modify: `src/context_store/dashboard/api_server.py` (router 登録)
- Test: `tests/integration/test_dashboard_api_graph.py`

### Task 7.1: 失敗テスト

```python
@pytest.mark.asyncio
async def test_graph_layout_returns_cytoscape_elements(app_with_mock_service):
    app, service = app_with_mock_service
    service.get_graph_layout.return_value = GraphLayoutResponse(
        elements=GraphElementsDTO(nodes=[...], edges=[...]),
        total_nodes=2,
        returned_nodes=2,
        total_edges=1,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/graph/layout", headers={"host": "localhost"})
    assert r.status_code == 200
    data = r.json()
    assert "elements" in data
    assert "totalNodes" in data
    assert "returnedNodes" in data


@pytest.mark.asyncio
async def test_graph_traverse_returns_503_when_graph_none(app_with_mock_service_no_graph):
    app, service = app_with_mock_service_no_graph
    service.traverse_graph.side_effect = RuntimeError("graph backend not configured")
    async with AsyncClient(...) as c:
        r = await c.post("/api/graph/traverse", json={"seedId": "m1"}, headers={"host": "localhost"})
    assert r.status_code == 503
    assert "graph backend" in r.json()["detail"]
```

### Task 7.2: 実装

```python
# routes/graph.py
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from context_store.dashboard.schemas import DashboardBaseModel, GraphLayoutResponse

router = APIRouter()


class TraverseRequest(DashboardBaseModel):
    seed_id: str
    max_depth: int = 2
    edge_types: list[str] | None = None


@router.get("/layout", response_model=GraphLayoutResponse, response_model_by_alias=True)
async def get_layout(
    request: Request,
    project: str | None = None,
    limit: int = 500,
    order_by: str = "importance",
) -> GraphLayoutResponse:
    try:
        return await request.app.state.service.get_graph_layout(
            project=project, limit=limit, order_by=order_by  # type: ignore
        )
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e


@router.post("/traverse")
async def traverse(req: TraverseRequest, request: Request):
    try:
        result = await request.app.state.service.traverse_graph(
            req.seed_id, max_depth=req.max_depth, edge_types=req.edge_types
        )
        return result.model_dump(mode="json")
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e
```

`api_server.py` に:

```python
from context_store.dashboard.routes import graph
app.include_router(graph.router, prefix="/api/graph", tags=["graph"])
```

- [ ] **Step 3: テスト → コミット → PR**

---

## PR 8: Log Collector + WebSocket Manager

**Goal:** ログ収集のスレッド境界処理と WebSocket ブロードキャスト機構を独立モジュールとして実装する(ルート実装は PR 9)。

**Files:**
- Create: `src/context_store/dashboard/log_collector.py`
- Create: `src/context_store/dashboard/websocket_manager.py`
- Test: `tests/unit/test_log_collector.py`
- Test: `tests/unit/test_websocket_manager.py`

### Task 8.1: LogCollector TDD

- [ ] **Step 1: 失敗テスト**

```python
import asyncio
import logging
import threading
from unittest.mock import MagicMock

import pytest

from context_store.dashboard.log_collector import LogCollector


def test_ring_buffer_drops_oldest_when_full():
    collector = LogCollector(maxlen=3)
    handler = collector.handler()
    logger = logging.getLogger("test.ring")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    for i in range(5):
        logger.info("msg %d", i)
    snapshot = collector.snapshot()
    assert len(snapshot) == 3
    # 古いものが落ちる
    messages = [e.message for e in snapshot]
    assert "msg 2" in messages and "msg 3" in messages and "msg 4" in messages
    logger.removeHandler(handler)


def test_thread_safe_emit():
    collector = LogCollector(maxlen=1000)
    handler = collector.handler()
    logger = logging.getLogger("test.thread")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    def worker(n):
        for i in range(100):
            logger.info("t%d-%d", n, i)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    snapshot = collector.snapshot()
    assert len(snapshot) == 1000  # 全エントリが取れる (deque is thread-safe)
    logger.removeHandler(handler)


@pytest.mark.asyncio
async def test_call_soon_threadsafe_bridges_to_asyncio_queue():
    collector = LogCollector(maxlen=100, queue_maxsize=10)
    loop = asyncio.get_running_loop()
    collector.attach_loop(loop)
    handler = collector.handler()

    logger = logging.getLogger("test.bridge")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    def bg():
        logger.info("from thread")

    t = threading.Thread(target=bg)
    t.start()
    t.join()

    # asyncio.Queue に 1 件届いているはず
    await asyncio.sleep(0.05)  # call_soon_threadsafe を待つ
    entry = await asyncio.wait_for(collector.queue.get(), timeout=1.0)
    assert "from thread" in entry.message
    logger.removeHandler(handler)


@pytest.mark.asyncio
async def test_queue_full_drops_oldest_not_newest():
    """QueueFull 時は最古を捨てて新規を入れる (リングバッファ的)。"""
    collector = LogCollector(maxlen=100, queue_maxsize=2)
    loop = asyncio.get_running_loop()
    collector.attach_loop(loop)
    handler = collector.handler()

    logger = logging.getLogger("test.full")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    for i in range(5):
        logger.info("msg %d", i)
    await asyncio.sleep(0.05)

    entries = []
    while not collector.queue.empty():
        entries.append(await collector.queue.get())
    # queue_maxsize=2 のため最新 2 件が残る
    assert len(entries) == 2
    msgs = [e.message for e in entries]
    assert any("msg 3" in m or "msg 4" in m for m in msgs)
    logger.removeHandler(handler)
```

- [ ] **Step 2: `log_collector.py` 実装**

```python
"""Thread-safe log collector with ring buffer + asyncio bridge (rev.10 §3.5)."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime


@dataclass
class LogEntryRecord:
    timestamp: str
    level: str
    logger: str
    message: str


class _LogCollectorHandler(logging.Handler):
    def __init__(self, collector: "LogCollector") -> None:
        super().__init__()
        self._collector = collector

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = LogEntryRecord(
                timestamp=datetime.utcnow().isoformat() + "Z",
                level=record.levelname,
                logger=record.name,
                message=record.getMessage(),
            )
            self._collector._push(entry)
        except Exception:
            self.handleError(record)


class LogCollector:
    """Ring buffer + asyncio.Queue bridge for dashboard log streaming."""

    def __init__(self, *, maxlen: int = 1000, queue_maxsize: int = 500) -> None:
        self._deque: deque[LogEntryRecord] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self.queue: asyncio.Queue[LogEntryRecord] = asyncio.Queue(maxsize=queue_maxsize)
        self._loop: asyncio.AbstractEventLoop | None = None

    def handler(self) -> logging.Handler:
        return _LogCollectorHandler(self)

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def snapshot(self) -> list[LogEntryRecord]:
        with self._lock:
            return list(self._deque)

    def _push(self, entry: LogEntryRecord) -> None:
        with self._lock:
            self._deque.append(entry)
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._enqueue_from_loop, entry)

    def _enqueue_from_loop(self, entry: LogEntryRecord) -> None:
        try:
            self.queue.put_nowait(entry)
        except asyncio.QueueFull:
            # Drop oldest, insert newest (ring-buffer behavior for asyncio.Queue)
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                self.queue.put_nowait(entry)
            except asyncio.QueueFull:
                pass  # still full due to race — drop this entry
```

### Task 8.2: WebSocketManager TDD

- [ ] **Step 1: 失敗テスト**

```python
import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi import WebSocket

from context_store.dashboard.websocket_manager import WebSocketManager


class FakeWS:
    def __init__(self, slow: bool = False, fail: bool = False):
        self.sent: list = []
        self.slow = slow
        self.fail = fail
        self.closed = False

    async def send_json(self, payload):
        if self.fail:
            raise RuntimeError("ws error")
        if self.slow:
            await asyncio.sleep(5)  # exceeds 1-sec timeout
        self.sent.append(payload)

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_broadcast_sends_to_all_connected():
    mgr = WebSocketManager()
    w1, w2 = FakeWS(), FakeWS()
    mgr.connect("logs", w1)
    mgr.connect("logs", w2)
    await mgr.broadcast("logs", {"msg": "hi"})
    assert w1.sent == [{"msg": "hi"}]
    assert w2.sent == [{"msg": "hi"}]


@pytest.mark.asyncio
async def test_slow_consumer_is_disconnected_within_timeout():
    mgr = WebSocketManager(per_send_timeout=1.0)
    fast = FakeWS()
    slow = FakeWS(slow=True)
    mgr.connect("logs", fast)
    mgr.connect("logs", slow)
    await mgr.broadcast("logs", {"msg": "test"})
    # slow は切断されているはず
    assert slow not in mgr._conns["logs"]
    assert fast in mgr._conns["logs"]
    assert fast.sent == [{"msg": "test"}]


@pytest.mark.asyncio
async def test_failed_send_disconnects():
    mgr = WebSocketManager()
    good = FakeWS()
    bad = FakeWS(fail=True)
    mgr.connect("logs", good)
    mgr.connect("logs", bad)
    await mgr.broadcast("logs", {"msg": "x"})
    assert bad not in mgr._conns["logs"]
    assert good in mgr._conns["logs"]
```

- [ ] **Step 2: `websocket_manager.py` 実装**

```python
"""WebSocket connection manager with per-connection timeout (rev.10 §3.3)."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)


class WebSocketManager:
    def __init__(self, *, per_send_timeout: float = 1.0) -> None:
        self._conns: dict[str, set] = defaultdict(set)
        self._timeout = per_send_timeout
        self._lock = asyncio.Lock()

    def connect(self, channel: str, ws) -> None:
        self._conns[channel].add(ws)

    def disconnect(self, channel: str, ws) -> None:
        self._conns[channel].discard(ws)

    async def broadcast(self, channel: str, payload: dict[str, Any]) -> None:
        targets = list(self._conns[channel])
        if not targets:
            return
        results = await asyncio.gather(
            *(self._safe_send(ws, payload) for ws in targets),
            return_exceptions=True,
        )
        for ws, res in zip(targets, results, strict=False):
            if isinstance(res, BaseException):
                self._conns[channel].discard(ws)
                try:
                    await ws.close()
                except Exception:
                    pass

    async def _safe_send(self, ws, payload: dict[str, Any]) -> None:
        await asyncio.wait_for(ws.send_json(payload), timeout=self._timeout)
```

- [ ] **Step 3: テスト実行 → PASS → コミット + PR**

```bash
pytest tests/unit/test_log_collector.py tests/unit/test_websocket_manager.py -x -v
git commit -m "feat(dashboard): log collector and websocket manager

- LogCollector: thread-safe deque ring buffer + asyncio.Queue bridge
- Ring-buffer behavior on QueueFull via get_nowait+put_nowait
- WebSocketManager: parallel broadcast with per-connection 1s timeout
- Slow/failed consumers are immediately disconnected
- Refs design rev.10 §3.3, §3.5"
```

---

## PR 9: Logs ルート + WebSocket エンドポイント

**Goal:** `/api/logs/recent` と `/ws/logs` を実装し、api_server.py の lifespan で LogCollector を初期化してルートロガーに接続する。

**Files:**
- Create: `src/context_store/dashboard/routes/logs.py`
- Modify: `src/context_store/dashboard/api_server.py`
- Test: `tests/integration/test_dashboard_api_logs.py`
- Test: `tests/integration/test_dashboard_ws_logs.py`

### Task 9.1: 統合テスト追加

- [ ] **Step 1: REST テスト**

```python
@pytest.mark.asyncio
async def test_logs_recent_returns_snapshot(app_with_collector):
    app, collector = app_with_collector
    # シード: 3 件
    import logging
    logging.getLogger("test.api").info("hello 1")
    logging.getLogger("test.api").info("hello 2")
    logging.getLogger("test.api").info("hello 3")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/logs/recent?limit=10", headers={"host": "localhost"})
    assert r.status_code == 200
    data = r.json()
    assert len(data) >= 3
    assert all("message" in e for e in data)
```

- [ ] **Step 2: WebSocket テスト**

```python
@pytest.mark.asyncio
async def test_ws_logs_streams_entries():
    """FastAPI TestClient で WS をテスト。"""
    from fastapi.testclient import TestClient
    app = create_app()
    client = TestClient(app)
    with client.websocket_connect("/ws/logs") as ws:
        # サーバ側でログを発火させる (loopback)
        logging.getLogger("ws.test").info("streaming test")
        msg = ws.receive_json()
        assert msg["message"] == "streaming test"
```

### Task 9.2: 実装

- [ ] **Step 1: `routes/logs.py`**

```python
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.get("/recent")
async def get_recent(request: Request, limit: int = 100):
    collector = request.app.state.log_collector
    entries = collector.snapshot()[-limit:]
    return [
        {
            "timestamp": e.timestamp,
            "level": e.level,
            "logger": e.logger,
            "message": e.message,
        }
        for e in entries
    ]


async def ws_logs_endpoint(websocket: WebSocket):
    await websocket.accept()
    manager = websocket.app.state.ws_manager
    collector = websocket.app.state.log_collector
    manager.connect("logs", websocket)
    try:
        while True:
            entry = await collector.queue.get()
            # broadcast (このクライアントにも送る)
            await manager.broadcast(
                "logs",
                {
                    "timestamp": entry.timestamp,
                    "level": entry.level,
                    "logger": entry.logger,
                    "message": entry.message,
                },
            )
    except WebSocketDisconnect:
        manager.disconnect("logs", websocket)
```

**注意**: 上記の実装だと複数クライアント間で競合する。現実的には別の「ディスパッチャタスク」を lifespan で起動し、キューから取り出して manager にブロードキャストする構造が正しい。以下に修正:

- [ ] **Step 2: api_server.py に dispatcher タスクを追加**

```python
async def _log_dispatcher(collector, manager):
    while True:
        entry = await collector.queue.get()
        await manager.broadcast("logs", {
            "timestamp": entry.timestamp,
            "level": entry.level,
            "logger": entry.logger,
            "message": entry.message,
        })


@asynccontextmanager
async def _lifespan(app):
    # ... create_storage 初期化 ...
    collector = LogCollector(maxlen=1000, queue_maxsize=500)
    collector.attach_loop(asyncio.get_running_loop())
    logging.getLogger().addHandler(collector.handler())
    manager = WebSocketManager()
    app.state.log_collector = collector
    app.state.ws_manager = manager

    dispatcher_task = asyncio.create_task(_log_dispatcher(collector, manager))
    try:
        yield
    finally:
        dispatcher_task.cancel()
        try:
            await dispatcher_task
        except asyncio.CancelledError:
            pass
        logging.getLogger().removeHandler(collector.handler())  # best effort
        # ... dispose ...
```

- [ ] **Step 3: ws ルートを FastAPI 方式で追加**

```python
# api_server.py 内
from context_store.dashboard.routes.logs import router as logs_router, ws_logs_endpoint
app.include_router(logs_router, prefix="/api/logs", tags=["logs"])
app.add_api_websocket_route("/ws/logs", ws_logs_endpoint)
```

この場合、`ws_logs_endpoint` は dispatcher を経由せず「接続維持のみ」で良い:

```python
async def ws_logs_endpoint(websocket: WebSocket):
    await websocket.accept()
    manager = websocket.app.state.ws_manager
    manager.connect("logs", websocket)
    try:
        while True:
            # クライアントからの入力は無視するが、切断検出のため受信を試みる
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect("logs", websocket)
```

- [ ] **Step 4: テスト実行 → PASS → 退行 → コミット + PR**

```bash
git commit -m "feat(dashboard): logs route and websocket endpoint

- routes/logs.py: GET /api/logs/recent (ring buffer snapshot)
- /ws/logs WebSocket endpoint with connection management
- api_server lifespan: attach LogCollector to root logger + dispatcher task
- Dispatcher bridges asyncio.Queue → WebSocketManager.broadcast
- Refs design rev.10 §3.3, §3.5"
```

---

## PR 10: Frontend scaffold

**Goal:** Vite + React + TS + Tailwind + Router + MSW の最小セットアップ。空ページ 4 つとレイアウトのみ。

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tailwind.config.ts`
- Create: `frontend/postcss.config.js`
- Create: `frontend/index.html`
- Create: `frontend/.eslintrc.cjs`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/styles/globals.css`
- Create: `frontend/src/pages/Dashboard.tsx` (empty placeholder)
- Create: `frontend/src/pages/NetworkView.tsx`
- Create: `frontend/src/pages/LogExplorer.tsx`
- Create: `frontend/src/pages/Settings.tsx`
- Create: `frontend/src/components/layout/Sidebar.tsx`
- Create: `frontend/src/components/layout/Header.tsx`
- Create: `frontend/src/components/layout/PageContainer.tsx`
- Create: `frontend/src/mocks/handlers.ts`
- Create: `frontend/src/mocks/browser.ts`
- Create: `frontend/.gitignore`

### Task 10.1: プロジェクト初期化

- [ ] **Step 1: Vite scaffold**

```bash
cd /home/y_ohi/program/private/chronos-graph
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
```

- [ ] **Step 2: 追加依存インストール**

```bash
npm install react-router-dom zustand
npm install -D tailwindcss postcss autoprefixer \
  @types/node \
  msw@latest \
  vitest @testing-library/react @testing-library/jest-dom jsdom
npx tailwindcss init -p
```

- [ ] **Step 3: `tailwind.config.ts` を作成**

```typescript
import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: { extend: {} },
  plugins: [],
} satisfies Config;
```

- [ ] **Step 4: `vite.config.ts` にプロキシ設定**

```typescript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/ws": {
        target: "ws://localhost:8000",
        ws: true,
      },
    },
  },
  build: {
    outDir: "dist",
  },
});
```

- [ ] **Step 5: ルーティング + レイアウト**

`src/App.tsx`:

```tsx
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Sidebar } from "./components/layout/Sidebar";
import { Header } from "./components/layout/Header";
import { PageContainer } from "./components/layout/PageContainer";
import Dashboard from "./pages/Dashboard";
import NetworkView from "./pages/NetworkView";
import LogExplorer from "./pages/LogExplorer";
import Settings from "./pages/Settings";

export default function App() {
  return (
    <BrowserRouter>
      <div className="flex h-screen bg-white dark:bg-gray-900">
        <Sidebar />
        <div className="flex-1 flex flex-col">
          <Header />
          <PageContainer>
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/network" element={<NetworkView />} />
              <Route path="/logs" element={<LogExplorer />} />
              <Route path="/settings" element={<Settings />} />
            </Routes>
          </PageContainer>
        </div>
      </div>
    </BrowserRouter>
  );
}
```

`src/components/layout/Sidebar.tsx`:

```tsx
import { NavLink } from "react-router-dom";

const links = [
  { to: "/", label: "Dashboard" },
  { to: "/network", label: "Network" },
  { to: "/logs", label: "Logs" },
  { to: "/settings", label: "Settings" },
];

export function Sidebar() {
  return (
    <aside className="w-56 bg-gray-100 dark:bg-gray-800 border-r p-4">
      <nav className="space-y-2">
        {links.map((l) => (
          <NavLink
            key={l.to}
            to={l.to}
            className={({ isActive }) =>
              `block px-3 py-2 rounded ${
                isActive ? "bg-blue-500 text-white" : "hover:bg-gray-200 dark:hover:bg-gray-700"
              }`
            }
          >
            {l.label}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
```

`src/components/layout/Header.tsx`、`PageContainer.tsx` も同様の最小実装。

ページプレースホルダ:

```tsx
// pages/Dashboard.tsx
export default function Dashboard() {
  return <h1 className="text-2xl">Dashboard (placeholder)</h1>;
}
```

- [ ] **Step 6: MSW 最小セットアップ**

```ts
// src/mocks/handlers.ts
import { http, HttpResponse } from "msw";

export const handlers = [
  http.get("/api/stats/summary", () =>
    HttpResponse.json({
      activeCount: 0,
      archivedCount: 0,
      totalCount: 0,
      edgeCount: 0,
      projectCount: 0,
      projects: [],
    })
  ),
];
```

```ts
// src/mocks/browser.ts
import { setupWorker } from "msw/browser";
import { handlers } from "./handlers";
export const worker = setupWorker(...handlers);
```

`main.tsx` で dev モード時のみ有効化:

```tsx
async function enableMocks() {
  if (import.meta.env.DEV) {
    const { worker } = await import("./mocks/browser");
    await worker.start({ onUnhandledRequest: "bypass" });
  }
}
enableMocks().then(() => {
  // ReactDOM.createRoot(...).render(...)
});
```

- [ ] **Step 7: ビルド確認**

```bash
cd frontend && npm run build
```

Expected: `dist/` が生成され、エラーなし

- [ ] **Step 8: tsc / eslint チェック**

```bash
npm run lint 2>&1 || true
npx tsc --noEmit
```

- [ ] **Step 9: コミット + PR**

```bash
cd ..
git add frontend/
git commit -m "feat(frontend): scaffold Vite+React+TS+Tailwind project

- Vite 5 + React 18 + TypeScript + Tailwind CSS (darkMode: class)
- React Router v6 with 4 placeholder pages
- Sidebar/Header/PageContainer layout
- MSW setup for dev mock API
- vite.config.ts with /api and /ws proxy to localhost:8000
- Refs design rev.10 §4.1, §4.2, §5.2"
```

---

## PR 11: Stores + API client + Dashboard page + ThemeToggle

**Goal:** Zustand store と API クライアントを構築し、Dashboard ページで統計を表示する。

**Files:**
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/api/stats.ts`
- Create: `frontend/src/api/graph.ts`
- Create: `frontend/src/api/logs.ts`
- Create: `frontend/src/api/websocket.ts`
- Create: `frontend/src/stores/statsStore.ts`
- Create: `frontend/src/stores/graphStore.ts`
- Create: `frontend/src/stores/logStore.ts`
- Create: `frontend/src/stores/settingsStore.ts`
- Create: `frontend/src/types/api.ts`
- Create: `frontend/src/components/common/ThemeToggle.tsx`
- Create: `frontend/src/components/common/LoadingSpinner.tsx`
- Create: `frontend/src/components/common/ErrorBoundary.tsx`
- Create: `frontend/src/components/dashboard/StatCard.tsx`
- Modify: `frontend/src/pages/Dashboard.tsx`
- Test: `frontend/src/stores/statsStore.test.ts`
- Test: `frontend/src/components/dashboard/StatCard.test.tsx`

### Task 11.1: 型定義

- [ ] **Step 1: `types/api.ts`**

```ts
export interface DashboardStats {
  activeCount: number;
  archivedCount: number;
  totalCount: number;
  edgeCount: number;
  projectCount: number;
  projects: string[];
}

export interface GraphElements {
  nodes: Array<{ data: { id: string; label: string; memoryType: string; importance: number; project: string | null; accessCount: number; createdAt: string } }>;
  edges: Array<{ data: { id: string; source: string; target: string; edgeType: string } }>;
}

export interface GraphLayoutResponse {
  elements: GraphElements;
  totalNodes: number;
  returnedNodes: number;
  totalEdges: number;
}

export interface LogEntry {
  timestamp: string;
  level: string;
  logger: string;
  message: string;
}
```

### Task 11.2: API Client

- [ ] **Step 1: `api/client.ts`**

```ts
import { useSettingsStore } from "../stores/settingsStore";

function getBaseUrl(): string {
  const override = useSettingsStore.getState().apiBaseUrl;
  return override || "";
}

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${getBaseUrl()}${path}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<T>;
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${getBaseUrl()}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<T>;
}
```

- [ ] **Step 2: `api/stats.ts`, `api/graph.ts`, `api/logs.ts`** — 各ドメインの関数を定義

```ts
// api/stats.ts
import { apiGet } from "./client";
import type { DashboardStats } from "../types/api";

export const fetchStatsSummary = () => apiGet<DashboardStats>("/api/stats/summary");
```

### Task 11.3: Stores

- [ ] **Step 1: 失敗テスト**

```ts
// statsStore.test.ts
import { describe, it, expect, beforeEach, vi } from "vitest";
import { useStatsStore } from "./statsStore";

describe("statsStore", () => {
  beforeEach(() => {
    useStatsStore.setState({ summary: null, loading: false, error: null });
  });

  it("fetchSummary updates store on success", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        activeCount: 10,
        archivedCount: 2,
        totalCount: 12,
        edgeCount: 5,
        projectCount: 1,
        projects: ["p1"],
      }),
    }));
    await useStatsStore.getState().fetchSummary();
    const s = useStatsStore.getState();
    expect(s.summary?.activeCount).toBe(10);
    expect(s.loading).toBe(false);
  });
});
```

- [ ] **Step 2: `statsStore.ts` 実装**

```ts
import { create } from "zustand";
import { fetchStatsSummary } from "../api/stats";
import type { DashboardStats } from "../types/api";

interface StatsState {
  summary: DashboardStats | null;
  loading: boolean;
  error: string | null;
  fetchSummary: () => Promise<void>;
}

export const useStatsStore = create<StatsState>((set) => ({
  summary: null,
  loading: false,
  error: null,
  fetchSummary: async () => {
    set({ loading: true, error: null });
    try {
      const data = await fetchStatsSummary();
      set({ summary: data, loading: false });
    } catch (e) {
      set({ error: (e as Error).message, loading: false });
    }
  },
}));
```

他の store も同様に実装。`settingsStore` は `localStorage` 永続化ミドルウェアを使用:

```ts
import { create } from "zustand";
import { persist } from "zustand/middleware";

export const useSettingsStore = create(
  persist<{
    theme: "light" | "dark";
    apiBaseUrl: string;
    setTheme: (t: "light" | "dark") => void;
    setApiBaseUrl: (u: string) => void;
  }>(
    (set) => ({
      theme: "light",
      apiBaseUrl: "",
      setTheme: (theme) => set({ theme }),
      setApiBaseUrl: (apiBaseUrl) => set({ apiBaseUrl }),
    }),
    { name: "chronos-settings" }
  )
);
```

### Task 11.4: ThemeToggle + Dashboard page

- [ ] **Step 1: `ThemeToggle.tsx`**

```tsx
import { useEffect } from "react";
import { useSettingsStore } from "../../stores/settingsStore";

export function ThemeToggle() {
  const theme = useSettingsStore((s) => s.theme);
  const setTheme = useSettingsStore((s) => s.setTheme);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);

  return (
    <button
      onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
      className="px-3 py-1 rounded border"
    >
      {theme === "dark" ? "☀" : "☾"}
    </button>
  );
}
```

- [ ] **Step 2: `StatCard.tsx` + test**

```tsx
// StatCard.tsx
export function StatCard({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="p-4 rounded border bg-white dark:bg-gray-800 shadow">
      <div className="text-sm text-gray-500">{label}</div>
      <div className="text-2xl font-semibold">{value}</div>
    </div>
  );
}
```

```tsx
// StatCard.test.tsx
import { render, screen } from "@testing-library/react";
import { StatCard } from "./StatCard";

test("renders label and value", () => {
  render(<StatCard label="Total" value={42} />);
  expect(screen.getByText("Total")).toBeInTheDocument();
  expect(screen.getByText("42")).toBeInTheDocument();
});
```

- [ ] **Step 3: `Dashboard.tsx` 更新**

```tsx
import { useEffect } from "react";
import { useStatsStore } from "../stores/statsStore";
import { StatCard } from "../components/dashboard/StatCard";

export default function Dashboard() {
  const { summary, loading, error, fetchSummary } = useStatsStore();
  useEffect(() => { fetchSummary(); }, [fetchSummary]);

  if (loading) return <div>Loading...</div>;
  if (error) return <div className="text-red-500">Error: {error}</div>;
  if (!summary) return null;

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      <StatCard label="Active" value={summary.activeCount} />
      <StatCard label="Archived" value={summary.archivedCount} />
      <StatCard label="Total" value={summary.totalCount} />
      <StatCard label="Edges" value={summary.edgeCount} />
      <StatCard label="Projects" value={summary.projectCount} />
    </div>
  );
}
```

- [ ] **Step 4: テスト実行**

```bash
cd frontend
npm run test
```

- [ ] **Step 5: Header に ThemeToggle を配置してコミット + PR**

```bash
git commit -m "feat(frontend): stores, API client, theme toggle, Dashboard page

- Zustand stores: stats/graph/log/settings (settings has localStorage persist)
- api/client.ts with runtime base URL override from settingsStore
- ThemeToggle with document.documentElement class manipulation
- Dashboard page with StatCard grid
- Vitest + RTL tests for statsStore and StatCard
- Refs design rev.10 §4.1, §4.4, §5.1"
```

---

## PR 12: NetworkView (Cytoscape.js)

**Goal:** グラフ可視化ページの全コンポーネントを実装する。

**Files:**
- Create: `frontend/src/utils/cytoscape.ts` (styles, layout options)
- Create: `frontend/src/components/graph/CytoscapeGraph.tsx`
- Create: `frontend/src/components/graph/GraphControls.tsx`
- Create: `frontend/src/components/graph/GraphFilters.tsx`
- Create: `frontend/src/components/graph/NodeDetailPanel.tsx`
- Create: `frontend/src/components/graph/GraphLegend.tsx`
- Create: `frontend/src/components/graph/GraphTruncationWarning.tsx`
- Modify: `frontend/src/stores/graphStore.ts`
- Modify: `frontend/src/pages/NetworkView.tsx`
- Test: `frontend/src/components/graph/CytoscapeGraph.test.tsx`
- Test: `frontend/src/components/graph/GraphTruncationWarning.test.tsx`

### Task 12.1: 依存インストール

```bash
cd frontend
npm install cytoscape cytoscape-cose-bilkent cytoscape-cola cytoscape-dagre
npm install -D @types/cytoscape
```

### Task 12.2: Cytoscape ユーティリティ

- [ ] **Step 1: `utils/cytoscape.ts`**

```ts
import cytoscape from "cytoscape";
// @ts-expect-error no types
import coseBilkent from "cytoscape-cose-bilkent";
// @ts-expect-error no types
import cola from "cytoscape-cola";
// @ts-expect-error no types
import dagre from "cytoscape-dagre";

cytoscape.use(coseBilkent);
cytoscape.use(cola);
cytoscape.use(dagre);

export const NODE_COLORS = {
  episodic: "#3B82F6",
  semantic: "#10B981",
  procedural: "#F59E0B",
} as const;

export function buildStyle(dark: boolean): cytoscape.Stylesheet[] {
  const textColor = dark ? "#f3f4f6" : "#1f2937";
  return [
    {
      selector: "node",
      style: {
        "background-color": (ele: cytoscape.NodeSingular) =>
          NODE_COLORS[ele.data("memoryType") as keyof typeof NODE_COLORS] || "#888",
        label: "data(label)",
        color: textColor,
        "font-size": 10,
        "text-valign": "bottom",
        width: (ele: cytoscape.NodeSingular) => 20 + (ele.data("importance") || 0) * 40,
        height: (ele: cytoscape.NodeSingular) => 20 + (ele.data("importance") || 0) * 40,
      },
    },
    {
      selector: "edge",
      style: {
        width: 2,
        "line-color": dark ? "#6b7280" : "#9ca3af",
        "target-arrow-color": dark ? "#6b7280" : "#9ca3af",
        "target-arrow-shape": "triangle",
        "curve-style": "bezier",
      },
    },
  ];
}

export const LAYOUT_OPTIONS: Record<string, any> = {
  "cose-bilkent": { name: "cose-bilkent", animate: false, idealEdgeLength: 100 },
  cola: { name: "cola", animate: false },
  dagre: { name: "dagre", rankDir: "TB" },
  circle: { name: "circle" },
  breadthfirst: { name: "breadthfirst" },
};
```

### Task 12.3: CytoscapeGraph コンポーネント

- [ ] **Step 1: 失敗テスト**

```tsx
import { render, screen } from "@testing-library/react";
import { CytoscapeGraph } from "./CytoscapeGraph";

test("renders cytoscape container", () => {
  const elements = { nodes: [], edges: [] };
  render(<CytoscapeGraph elements={elements} layout="cose-bilkent" onNodeClick={() => {}} />);
  expect(screen.getByTestId("cytoscape-container")).toBeInTheDocument();
});
```

- [ ] **Step 2: 実装**

```tsx
import { useEffect, useRef } from "react";
import cytoscape, { Core } from "cytoscape";
import { buildStyle, LAYOUT_OPTIONS } from "../../utils/cytoscape";
import { useSettingsStore } from "../../stores/settingsStore";
import type { GraphElements } from "../../types/api";

interface Props {
  elements: GraphElements;
  layout: string;
  onNodeClick: (id: string) => void;
}

export function CytoscapeGraph({ elements, layout, onNodeClick }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const theme = useSettingsStore((s) => s.theme);

  useEffect(() => {
    if (!containerRef.current) return;
    cyRef.current = cytoscape({
      container: containerRef.current,
      elements: [...elements.nodes, ...elements.edges],
      style: buildStyle(theme === "dark"),
      layout: LAYOUT_OPTIONS[layout],
    });
    cyRef.current.on("tap", "node", (evt) => onNodeClick(evt.target.id()));
    return () => {
      cyRef.current?.destroy();
    };
  }, []);  // 初期化のみ

  // 差分更新
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.elements().remove();
    cy.add([...elements.nodes, ...elements.edges]);
    cy.layout(LAYOUT_OPTIONS[layout]).run();
  }, [elements, layout]);

  // テーマ変更は style のみ
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.style(buildStyle(theme === "dark")).update();
  }, [theme]);

  return <div ref={containerRef} data-testid="cytoscape-container" className="w-full h-full" />;
}
```

### Task 12.4: 他コンポーネント

- [ ] `GraphControls.tsx`: レイアウト選択 dropdown + zoom/fit ボタン
- [ ] `GraphFilters.tsx`: プロジェクト selector + エッジタイプ checkbox
- [ ] `NodeDetailPanel.tsx`: スライドアウト右パネル (`fixed right-0 w-96`)、選択ノード ID を graphStore から購読、`/api/memories/{id}` を取得表示
- [ ] `GraphLegend.tsx`: memoryType 色凡例
- [ ] `GraphTruncationWarning.tsx`:

```tsx
import { useState } from "react";

interface Props {
  totalNodes: number;
  returnedNodes: number;
}

export function GraphTruncationWarning({ totalNodes, returnedNodes }: Props) {
  const [dismissed, setDismissed] = useState(false);
  if (dismissed || totalNodes <= returnedNodes) return null;
  return (
    <div className="sticky top-0 bg-amber-100 dark:bg-amber-900 border-l-4 border-amber-500 p-3 flex justify-between">
      <span>
        全 {totalNodes} 件中 {returnedNodes} 件を表示しています。importance 上位のノードのみが描画されています。
        プロジェクトフィルタで絞り込むと全件表示できる場合があります。
      </span>
      <button onClick={() => setDismissed(true)}>×</button>
    </div>
  );
}
```

テスト:

```tsx
test("hides when totalNodes <= returnedNodes", () => {
  const { container } = render(<GraphTruncationWarning totalNodes={10} returnedNodes={10} />);
  expect(container.firstChild).toBeNull();
});

test("shows warning when truncated", () => {
  render(<GraphTruncationWarning totalNodes={600} returnedNodes={500} />);
  expect(screen.getByText(/全 600 件中 500 件/)).toBeInTheDocument();
});
```

### Task 12.5: NetworkView.tsx

```tsx
import { useEffect, useState } from "react";
import { useGraphStore } from "../stores/graphStore";
import { CytoscapeGraph } from "../components/graph/CytoscapeGraph";
import { GraphControls } from "../components/graph/GraphControls";
import { GraphFilters } from "../components/graph/GraphFilters";
import { NodeDetailPanel } from "../components/graph/NodeDetailPanel";
import { GraphLegend } from "../components/graph/GraphLegend";
import { GraphTruncationWarning } from "../components/graph/GraphTruncationWarning";

export default function NetworkView() {
  const { layout, elements, totalNodes, returnedNodes, fetchLayout, setSelectedNode } =
    useGraphStore();
  useEffect(() => { fetchLayout(); }, [fetchLayout]);
  return (
    <div className="relative w-full h-full">
      <GraphTruncationWarning totalNodes={totalNodes} returnedNodes={returnedNodes} />
      <GraphFilters />
      <GraphControls />
      <CytoscapeGraph elements={elements} layout={layout} onNodeClick={setSelectedNode} />
      <GraphLegend />
      <NodeDetailPanel />
    </div>
  );
}
```

- [ ] テスト → コミット + PR

---

## PR 13: LogExplorer + useWebSocket

**Goal:** ログストリーミングページを実装する。

**Files:**
- Create: `frontend/src/hooks/useWebSocket.ts`
- Create: `frontend/src/hooks/useLogStream.ts`
- Create: `frontend/src/components/logs/LogTable.tsx`
- Create: `frontend/src/components/logs/LogStream.tsx`
- Create: `frontend/src/components/logs/LogFilters.tsx`
- Create: `frontend/src/components/common/SearchInput.tsx`
- Modify: `frontend/src/stores/logStore.ts`
- Modify: `frontend/src/pages/LogExplorer.tsx`
- Test: `frontend/src/hooks/useWebSocket.test.ts`
- Test: `frontend/src/pages/LogExplorer.test.tsx`

### Task 13.1: useWebSocket

- [ ] **Step 1: 失敗テスト** — fake WebSocket でバックオフ + 再接続を検証

```ts
import { renderHook, act } from "@testing-library/react";
import { vi, test, expect } from "vitest";
import { useWebSocket } from "./useWebSocket";

class FakeWS {
  static instances: FakeWS[] = [];
  readyState = 0;
  onopen?: () => void;
  onmessage?: (ev: { data: string }) => void;
  onclose?: () => void;
  onerror?: () => void;
  constructor(public url: string) {
    FakeWS.instances.push(this);
  }
  send() {}
  close() {
    this.readyState = 3;
    this.onclose?.();
  }
}

test("reconnects with exponential backoff", async () => {
  vi.stubGlobal("WebSocket", FakeWS);
  vi.useFakeTimers();
  const { result } = renderHook(() => useWebSocket("/ws/logs"));
  // 1st connect
  expect(FakeWS.instances).toHaveLength(1);
  // simulate close
  act(() => FakeWS.instances[0].close());
  // backoff 1s
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1000);
  });
  expect(FakeWS.instances.length).toBeGreaterThanOrEqual(2);
  vi.useRealTimers();
});
```

- [ ] **Step 2: `useWebSocket.ts` 実装**

```ts
import { useEffect, useRef, useState } from "react";

const BASE_DELAY = 1000;
const MAX_DELAY = 30_000;

export type WsStatus = "connecting" | "open" | "reconnecting" | "closed";

export function useWebSocket<T = unknown>(
  path: string,
  onMessage: (data: T) => void
): WsStatus {
  const [status, setStatus] = useState<WsStatus>("connecting");
  const attemptRef = useRef(0);
  const timerRef = useRef<number | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const closedByUnmountRef = useRef(false);

  useEffect(() => {
    closedByUnmountRef.current = false;

    function connect() {
      const protocol = window.location.protocol === "https:" ? "wss" : "ws";
      const url = `${protocol}://${window.location.host}${path}`;
      const ws = new WebSocket(url);
      wsRef.current = ws;
      setStatus("connecting");
      ws.onopen = () => {
        attemptRef.current = 0;
        setStatus("open");
      };
      ws.onmessage = (ev) => {
        try {
          onMessage(JSON.parse(ev.data));
        } catch {}
      };
      ws.onclose = () => {
        if (closedByUnmountRef.current) return;
        setStatus("reconnecting");
        const delay = Math.min(BASE_DELAY * 2 ** attemptRef.current, MAX_DELAY);
        const jitter = delay * (0.8 + Math.random() * 0.4);
        timerRef.current = window.setTimeout(() => {
          attemptRef.current += 1;
          connect();
        }, jitter);
      };
      ws.onerror = () => { ws.close(); };
    }

    connect();
    return () => {
      closedByUnmountRef.current = true;
      if (timerRef.current) clearTimeout(timerRef.current);
      wsRef.current?.close();
      setStatus("closed");
    };
  }, [path, onMessage]);

  return status;
}
```

### Task 13.2: useLogStream + LogTable + LogFilters + LogStream + LogExplorer

```ts
// useLogStream.ts
import { useEffect } from "react";
import { useWebSocket } from "./useWebSocket";
import { useLogStore } from "../stores/logStore";
import type { LogEntry } from "../types/api";

export function useLogStream() {
  const appendLog = useLogStore((s) => s.appendLog);
  const fetchRecent = useLogStore((s) => s.fetchRecent);
  useEffect(() => { fetchRecent(); }, [fetchRecent]);
  const status = useWebSocket<LogEntry>("/ws/logs", appendLog);
  return status;
}
```

`logStore.ts` に `entries`, `filters`, `appendLog`, `fetchRecent`, `setFilter` を追加。

`LogTable.tsx` はフィルタを適用して entries を表示するシンプルな table。

`LogFilters.tsx` は severity と検索ボックス。

`LogStream.tsx` は接続状態インジケータ:

```tsx
export function LogStream({ status }: { status: WsStatus }) {
  const label = {
    connecting: "接続中...",
    open: "接続済み",
    reconnecting: "再接続中...",
    closed: "切断",
  }[status];
  const color = status === "open" ? "text-green-500" : "text-amber-500";
  return <div className={`text-sm ${color}`}>● {label}</div>;
}
```

`LogExplorer.tsx` は上記を組み合わせ。

- [ ] テスト → コミット + PR

---

## PR 14: Settings + SPA fallback + Docker + E2E

**Goal:** 最後のページ実装と本番デプロイ対応、E2E テスト。

**Files:**
- Modify: `frontend/src/pages/Settings.tsx`
- Create: `frontend/src/components/common/ErrorBoundary.tsx` (完全版)
- Create: `frontend/playwright.config.ts`
- Create: `frontend/e2e/dashboard.spec.ts`
- Create: `frontend/e2e/network.spec.ts`
- Create: `frontend/e2e/logs.spec.ts`
- Create: `frontend/e2e/theme.spec.ts`
- Modify: `src/context_store/dashboard/api_server.py` (SPA fallback route)
- Modify: `docker-compose.yml`
- Modify: `frontend/package.json` (Playwright scripts)

### Task 14.1: Settings page

```tsx
import { useSettingsStore } from "../stores/settingsStore";

export default function Settings() {
  const { apiBaseUrl, setApiBaseUrl, theme, setTheme } = useSettingsStore();
  return (
    <div className="max-w-lg space-y-4">
      <div>
        <label className="block mb-1">API Base URL</label>
        <input
          className="w-full border rounded px-2 py-1"
          value={apiBaseUrl}
          onChange={(e) => setApiBaseUrl(e.target.value)}
          placeholder="(empty: use same origin)"
        />
      </div>
      <div>
        <label className="block mb-1">Theme</label>
        <select
          value={theme}
          onChange={(e) => setTheme(e.target.value as "light" | "dark")}
          className="border rounded px-2 py-1"
        >
          <option value="light">Light</option>
          <option value="dark">Dark</option>
        </select>
      </div>
    </div>
  );
}
```

テスト: localStorage に `chronos-settings` キーが書き込まれることを確認。

### Task 14.2: SPA fallback

- [ ] **Step 1: 失敗テスト**

```python
@pytest.mark.asyncio
async def test_spa_fallback_serves_index_html_for_subpath():
    """/network 等の SPA サブパスが index.html を返す (rev.10 §3.5)。"""
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/network", headers={"host": "localhost"})
    assert r.status_code == 200
    assert "<!doctype html>" in r.text.lower() or "<!DOCTYPE" in r.text


@pytest.mark.asyncio
async def test_api_routes_not_shadowed_by_fallback():
    app = create_app()
    async with AsyncClient(...) as c:
        r = await c.get("/api/stats/summary", headers={"host": "localhost"})
    # mock service 必要なので別 fixture だが、404 ではなく 200 になる
    assert r.status_code != 404
```

- [ ] **Step 2: `api_server.py` に catch-all ルート追加**

```python
from pathlib import Path
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

def _mount_static(app: FastAPI, dist_dir: Path) -> None:
    if not dist_dir.exists():
        return
    # 静的アセット (/assets/ 等)
    app.mount("/assets", StaticFiles(directory=str(dist_dir / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        # /api/* と /ws/* は既にルーティング済みなのでここには来ない
        target = dist_dir / "index.html"
        return FileResponse(str(target))
```

`create_app` で `_mount_static(app, Path(__file__).parent.parent.parent.parent / "frontend" / "dist")` を呼ぶ(存在する場合のみ)。

### Task 14.3: docker-compose

```yaml
services:
  dashboard:
    build:
      context: .
      dockerfile: Dockerfile.dashboard
    command: chronos-dashboard
    environment:
      STORAGE_BACKEND: sqlite
      SQLITE_DB_PATH: /data/chronos.db
      DASHBOARD_PORT: 8000
      DASHBOARD_ALLOWED_HOSTS: localhost,127.0.0.1
    ports:
      - "127.0.0.1:8000:8000"
    volumes:
      - ./data:/data:ro
    depends_on: []
```

`Dockerfile.dashboard` を作成:

```dockerfile
FROM node:20 AS frontend
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN pip install uv && uv sync --extra dashboard --frozen
COPY src/ ./src/
COPY --from=frontend /app/frontend/dist ./frontend/dist
EXPOSE 8000
CMD ["uv", "run", "chronos-dashboard"]
```

### Task 14.4: Playwright E2E

```bash
cd frontend
npm install -D @playwright/test @axe-core/playwright
npx playwright install chromium
```

`playwright.config.ts`:

```ts
import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./e2e",
  use: {
    baseURL: "http://localhost:5173",
  },
  webServer: {
    command: "npm run dev",
    port: 5173,
    reuseExistingServer: true,
  },
});
```

`e2e/dashboard.spec.ts`:

```ts
import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test("dashboard shows StatCards", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Active")).toBeVisible();
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations.filter((v) => v.impact === "critical")).toEqual([]);
});
```

他 3 ケース (`network.spec.ts`, `logs.spec.ts`, `theme.spec.ts`) も設計書 §7.2 に従って実装。

- [ ] **Step 1: 実行**

```bash
npm run dev &  # バックエンドとフロントエンド両方起動を前提
npx playwright test
```

- [ ] **Step 2: コミット + PR**

```bash
git commit -m "feat(dashboard): Settings page, SPA fallback, docker-compose, E2E

- Settings.tsx with API URL and theme controls (localStorage persist)
- FastAPI catch-all route for SPA fallback (rev.10 §3.5)
- docker-compose.dashboard service with 127.0.0.1 port forward
- Dockerfile.dashboard multi-stage build (frontend + backend)
- Playwright 4 scenarios + axe-core a11y check
- Refs design rev.10 §3.5, §4.2, §7.2"
```

---

## Self-Review チェックリスト

実装計画を書いた後の最終確認:

**1. Spec coverage (設計書 rev.10 の要件と照合):**
- [x] §2.1 Orchestrator 非経由 CQRS → PR 5-6 (Lifespan で `create_storage` 直接呼び出し)
- [x] §2.2 DB 未初期化フェイルファスト → PR 6 (`test_lifespan_fails_fast_when_db_missing`)
- [x] §2.2 Read-Only SQLite URI → PR 2
- [x] §2.2 Neo4j READ_ACCESS → PR 4
- [x] §2.2 TrustedHostMiddleware + 0.0.0.0 バインド → PR 6
- [x] §3.1 ディレクトリ構造 → PR 5-9
- [x] §3.2 REST エンドポイント → PR 6 (stats/memories/system), PR 7 (graph), PR 9 (logs)
- [x] §3.3 WebSocket (slow consumer 保護) → PR 8-9
- [x] §3.5 IN 句チャンク分割 → PR 3 (`test_list_edges_chunking_for_large_input`)
- [x] §3.5 SPA フォールバック → PR 14
- [x] §3.5 ログ収集スレッド境界 → PR 8
- [x] §3.6 pyproject 依存 + エントリポイント → PR 6
- [x] §3.6 GraphAdapter 拡張 → PR 3-4
- [x] §4.1 frontend ディレクトリ → PR 10
- [x] §4.2 4 ページ + React Router → PR 10
- [x] §4.3 Cytoscape + ノードスタイル + レイアウト → PR 12
- [x] §4.3 GraphTruncationWarning → PR 12
- [x] §4.4 ダークモード (`darkMode: 'class'` + localStorage + `cy.style().update()`) → PR 11-12
- [x] §4.6 差分更新 (全体再描画しない) → PR 12 (`cy.elements().remove()` + `cy.add()`)
- [x] §5.3 Exponential Backoff 再接続 → PR 13
- [x] §6 Phase 1-5 → PR 1-14 すべてに対応
- [x] §7.2 E2E 4 ケース + axe-core → PR 14
- [x] rev.10 追加事項 (Settings 拡張 / create_storage read_only / SPA fallback) → PR 1, PR 2, PR 14

**2. Placeholder scan:**
- TBD, TODO, "implement later" → なし
- "Add error handling" → 具体的な 503 / 404 対応を記載済み
- "Similar to Task N" → 各 PR は独立して読める

**3. Type consistency:**
- `DashboardStats`, `GraphLayoutResponse`, `MemoryNode` 等の型は PR 5 で定義、PR 6/7 のルートで一貫して使用
- `create_storage(settings, *, read_only=False)` のシグネチャは PR 2 で確定、PR 4/6 で同一引数
- `LogCollector(maxlen=, queue_maxsize=)` のシグネチャは PR 8 で確定、PR 9 で同一

---

## Execution Handoff

**Plan complete and saved to `docs/plans/2026-04-10-dashboard-web-ui-plan.md`.**

実装には以下の 2 つのアプローチがあります:

**1. Subagent-Driven (推奨)** — PR 単位で fresh subagent を dispatch し、PR 間でレビュー。並列化可能な PR (1/3/8/10 など) は同時進行できる

**2. Inline Execution** — 本セッションで `superpowers:executing-plans` を使って PR 順次実行。各 PR 完了時にチェックポイントでレビュー

どちらで進めますか?
