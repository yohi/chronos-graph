# Neo4j Aura Transactional Outbox Sync 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Storage Layer のメモリ書き込みと同一トランザクション内で Outbox テーブルにグラフ同期イベントを記録し、バックグラウンドワーカーが非同期に Neo4j Aura へバルク MERGE 同期する Transactional Outbox Pattern を実装する。

**Architecture:** PostgreSQL/SQLite/Supabase の各 Storage Adapter は `save_memory`/`delete_memory` 時に同一 TX で `graph_sync_outbox` テーブルへ無条件 INSERT する（Supabase は RPC で Atomicity 保証）。同一 `memory_id` に対する重複 `SYNC_MEMORY` は意図的に許容し、ワーカー側の「最新状態フェッチ + MERGE」によって収束させる（dedup-at-convergence。詳細は設計 §3.4 を参照）。`OutboxWorker` が `next_retry_at` に基づき PENDING/FAILED イベントを polling し、`GraphSyncService` 経由で Neo4j に UNWIND+MERGE する。失敗時は DB レベルで Exponential Backoff を永続化、Worker クラッシュは起動時 `reset_stuck_processing` でリカバリする。

**Tech Stack:** Python 3.12 / asyncio / asyncpg / aiosqlite / supabase-py / neo4j-python-driver / pydantic-settings / pytest / Devcontainer (Ubuntu slim, uv)

---

## 参考ドキュメント

- 設計仕様書: [`docs/superpowers/specs/2026-05-21-neo4j-aura-outbox-sync-design.md`](../specs/2026-05-21-neo4j-aura-outbox-sync-design.md)
- Gitブランチ運用フロー: [AI-Native Stacked PR Workflow](https://different-sunday-448.notion.site/AI-Native-Stacked-PR-Workflow-3611669a4c16802eb032eb4ab05a8adb)

---

## エージェント向け実行ルール（厳守）

### 1. 実行環境

- **すべてのテスト・静的解析・ブランチ検証は Devcontainer 内で実行する** こと。ホスト側の `python`/`pytest`/`mypy` を直接呼び出してはならない。
- Devcontainer 起動コマンド: `code --folder-uri vscode-remote://dev-container+<path>/workspaces/chronos-graph` あるいは VS Code から `Reopen in Container`。
- CLI 起動: `docker compose -f .devcontainer/docker-compose.yml run --rm app bash`（CI 環境では `uv run` で代替可）。
- 以下のすべての `Run:` コマンドは Devcontainer 内シェル前提とする。

### 2. 並列実行制御

| 実行モード | 意味 | エージェント挙動 |
| --- | --- | --- |
| **直列必須 (Wait for Task X)** | 直前 Task の Draft PR が存在しないと開始不可 | 前提条件 Draft PR URL が記録されるまでブロック |
| **並列可能** | Base ブランチからの独立タスク。並列実行可 | 派生元ブランチが master/Phase Root のうちに着手可 |

### 3. ブランチ整合性チェック（ポカヨケ）

各 Task の **Step 1** で必ず以下の検証スクリプトを Devcontainer 内で実行し、派生元ブランチが正しいことを確認する。`exit 1` した場合は **絶対に作業を継続せず、人間に報告する** こと。

```bash
EXPECTED_BASE="<タスクごとに指定>"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git merge-base --is-ancestor "$EXPECTED_BASE" "$CURRENT_BRANCH" || {
    echo "ERROR: 派生元ブランチが $EXPECTED_BASE ではありません。スタック構造が壊れています。"
    exit 1
}
```

### 4. Draft PR 作成義務

各 Task の最終ステップで、**派生元ブランチ**を target に Draft PR を作成し、URL を本計画書の「Draft PR 一覧」セクションに記録する。

```bash
gh pr create --draft --base "<派生元ブランチ>" --title "<タイトル>" --body "<本文>"
```

---

## ファイル構成マップ

### 新規作成

| パス | 責務 |
| --- | --- |
| `src/context_store/sync/__init__.py` | パッケージ初期化 |
| `src/context_store/sync/outbox_writer.py` | `OutboxWriter` Protocol + Postgres/SQLite 実装 |
| `src/context_store/sync/outbox_reader.py` | `OutboxReader` Protocol + 各バックエンド実装 |
| `src/context_store/sync/outbox_worker.py` | Polling ループ + バッチ処理 + リカバリ |
| `src/context_store/sync/graph_sync.py` | `GraphSyncService` (Worker + リカバリスクリプト共有) |
| `src/context_store/sync/models.py` | `OutboxEvent` データクラス |
| `src/context_store/storage/migrations/postgres/0003_graph_sync_outbox.sql` | PG マイグレーション |
| `src/context_store/storage/migrations/sqlite/0003_graph_sync_outbox.sql` | SQLite マイグレーション |
| `supabase/migrations/20260521000001_graph_sync_outbox.sql` | Supabase マイグレーション + RPC |
| `scripts/sync_storage_to_neo4j.py` | リカバリ CLI |
| `tests/unit/sync/__init__.py` |  |
| `tests/unit/sync/test_outbox_writer.py` | OutboxWriter テスト |
| `tests/unit/sync/test_outbox_reader.py` | OutboxReader テスト |
| `tests/unit/sync/test_outbox_worker.py` | OutboxWorker テスト |
| `tests/unit/sync/test_graph_sync.py` | GraphSyncService テスト |
| `tests/unit/storage/test_postgres_outbox.py` | PG Storage Outbox 統合 |
| `tests/unit/storage/test_sqlite_outbox.py` | SQLite Storage Outbox 統合 |
| `tests/unit/storage/test_supabase_outbox.py` | Supabase RPC 検証 |
| `tests/unit/test_config_graph_sync.py` | Config バリデーション |
| `tests/integration/test_outbox_e2e.py` | E2E 結合テスト |

### 既存ファイル変更

| パス | 変更内容 |
| --- | --- |
| `.env.example` | Outbox 関連の環境変数追加 |
| `src/context_store/config.py` | `graph_sync_mode` + `outbox_*` フィールド + バリデーション |
| `src/context_store/storage/protocols.py` | (既存) `get_memories_batch` は既に存在 - 確認のみ |
| `src/context_store/storage/migrations/runner.py` | baseline `requirements` に `"0003"` 追加 |
| `src/context_store/storage/neo4j.py` | `execute_write` メソッド追加 |
| `src/context_store/storage/postgres.py` | OutboxWriter 注入、save/delete_memory TX 拡張 |
| `src/context_store/storage/sqlite.py` | OutboxWriter 注入、save/delete_memory TX 拡張 |
| `src/context_store/storage/supabase.py` | `_outbox_enabled` フラグで RPC 切替 |
| `src/context_store/storage/factory.py` | async_outbox 時の OutboxWriter/Worker 生成、Supabase+graph 解禁 |
| `src/context_store/orchestrator.py` | async_outbox 時の Worker 起動/停止 |
| `src/context_store/ingestion/pipeline.py` | async_outbox 時の GraphLinker 制御 |

---

## ブランチ構造図

```text
master
└── feat/outbox-base (Task 0.1)
    ├── feat/outbox-config (Task 1.1) ─────────── 並列可能
    ├── feat/outbox-storage-migrations (Task 1.2) 並列可能
    ├── feat/outbox-supabase-migrations (Task 1.3) 並列可能
    ├── feat/outbox-neo4j-execute-write (Task 2.2) 並列可能
    │
    │ -- Phase 1 完了 --
    │
    ├── feat/outbox-writer (Task 2.1)  ←── Task 1.2 Draft PR 必須
    │   ├── feat/outbox-postgres-integration (Task 3.1) 並列可能 (Task 3.2と)
    │   └── feat/outbox-sqlite-integration (Task 3.2)
    │
    ├── feat/outbox-graph-sync (Task 2.3) ←── Task 2.2 Draft PR 必須
    │   └── feat/outbox-worker-loop (Task 4.2) ←── Task 4.1 Draft PR も必須
    │       └── feat/outbox-factory (Task 5.1)
    │           └── feat/outbox-orchestrator (Task 5.2)
    │               └── feat/outbox-pipeline (Task 5.3)
    │                   └── feat/outbox-e2e (Task 6.2)
    │
    ├── feat/outbox-reader (Task 4.1)  ←── Task 1.2 Draft PR 必須
    │
    ├── feat/outbox-supabase-integration (Task 3.3) ←── Task 1.3 Draft PR 必須
    │
    └── feat/outbox-recovery-script (Task 6.1) ←── Task 2.3 Draft PR 必須
```

---

## Draft PR 一覧（エージェント記入欄）

| Task | ブランチ | Draft PR URL | ステータス |
| --- | --- | --- | --- |
| 0.1 | feat/outbox-base |  |  |
| 1.1 | feat/outbox-config |  |  |
| 1.2 | feat/outbox-storage-migrations |  |  |
| 1.3 | feat/outbox-supabase-migrations |  |  |
| 2.1 | feat/outbox-writer |  |  |
| 2.2 | feat/outbox-neo4j-execute-write |  |  |
| 2.3 | feat/outbox-graph-sync |  |  |
| 3.1 | feat/outbox-postgres-integration |  |  |
| 3.2 | feat/outbox-sqlite-integration |  |  |
| 3.3 | feat/outbox-supabase-integration |  |  |
| 4.1 | feat/outbox-reader |  |  |
| 4.2 | feat/outbox-worker-loop |  |  |
| 5.1 | feat/outbox-factory |  |  |
| 5.2 | feat/outbox-orchestrator |  |  |
| 5.3 | feat/outbox-pipeline |  |  |
| 6.1 | feat/outbox-recovery-script |  |  |
| 6.2 | feat/outbox-e2e |  |  |

---

# Phase 0: 基盤準備

## Task 0.1: Phase Root ブランチ作成と環境変数追加

- **派生元ブランチ:** `master`
- **実行モード:** 直列必須（後続全Taskの前提）
- **前提条件:** なし
- **作成ブランチ:** `feat/outbox-base`

**Files:**
- Modify: `.env.example`
- Create: `src/context_store/sync/__init__.py`
- Create: `src/context_store/sync/models.py`
- Create: `tests/unit/sync/__init__.py`

- [ ] **Step 1: ブランチ作成と派生元検証**

```bash
EXPECTED_BASE="master"
git fetch origin master
git checkout -b feat/outbox-base origin/master
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git merge-base --is-ancestor "$EXPECTED_BASE" "$CURRENT_BRANCH" || {
    echo "ERROR: 派生元ブランチが $EXPECTED_BASE ではありません。スタック構造が壊れています。"
    exit 1
}
```

- [ ] **Step 2: Devcontainer baseline テスト実行（クリーン状態確認）**

```bash
uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && uv run mypy src/ && uv run pytest tests/unit -q
```

Expected: PASS（既存テストすべて通る）

- [ ] **Step 3: `.env.example` に Outbox 関連環境変数追加**

`.env.example` の末尾に追記:

```env
# --- Graph Sync Mode (rev.11 Transactional Outbox) ---
# sync: GraphLinker が Neo4j に直接同期書き込み (デフォルト)
# async_outbox: Storage TX 内で Outbox に書き込み、Worker が非同期で Neo4j 同期
GRAPH_SYNC_MODE=sync
OUTBOX_POLL_INTERVAL_SECONDS=5.0
OUTBOX_BATCH_SIZE=100
OUTBOX_MAX_RETRIES=10
OUTBOX_BACKOFF_BASE_SECONDS=1.0
OUTBOX_BACKOFF_MAX_SECONDS=60.0
```

- [ ] **Step 4: sync パッケージの空モジュール作成**

`src/context_store/sync/__init__.py`:

```python
"""Transactional Outbox Sync package.

Provides:
- OutboxWriter: Storage TX 内で Outbox レコードを書き込む
- OutboxReader: Outbox からイベントを取得・更新する
- OutboxWorker: ポーリングループでイベントを処理する
- GraphSyncService: Storage → Neo4j の MERGE ロジック (Worker + リカバリ共有)
"""
```

`src/context_store/sync/models.py`:

```python
"""Outbox イベントデータモデル。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

EventType = Literal["SYNC_MEMORY", "DELETE_MEMORY"]
EventStatus = Literal["PENDING", "PROCESSING", "FAILED"]


@dataclass(frozen=True)
class OutboxEvent:
    """Outbox テーブルの 1 レコードを表す不変オブジェクト。"""

    id: str
    event_type: EventType
    memory_id: str
    payload: dict[str, Any]
    status: EventStatus
    retry_count: int
    next_retry_at: datetime
    error_message: str | None
    created_at: datetime
    updated_at: datetime
```

`tests/unit/sync/__init__.py`: 空ファイル

- [ ] **Step 5: CI で動くことを確認**

```bash
uv run ruff check src/context_store/sync/ tests/unit/sync/
uv run mypy src/context_store/sync/
```

Expected: PASS

- [ ] **Step 6: コミット & プッシュ**

```bash
git add .env.example src/context_store/sync/ tests/unit/sync/
git commit -m "chore(outbox): Phase Root - sync パッケージ初期化と環境変数追加"
git push -u origin feat/outbox-base
```

- [ ] **Step 7: Draft PR 作成**

```bash
gh pr create --draft --base master --title "chore(outbox): Phase Root - sync パッケージ初期化" --body "$(cat <<'EOF'
## Summary
- Transactional Outbox Sync 実装の Phase Root ブランチ。
- `src/context_store/sync/` パッケージとデータモデル `OutboxEvent` を追加。
- `.env.example` に `GRAPH_SYNC_MODE`/`OUTBOX_*` 環境変数のテンプレートを追記。

## Scope
本 PR はパッケージ骨格のみ。実ロジックは後続 PR で stack される。

## Test plan
- [ ] CI: ruff/mypy/pytest が全てパス

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

PR URL を「Draft PR 一覧」の Task 0.1 行に記録。

---

# Phase 1: 設定とマイグレーション

## Task 1.1: Config 拡張と Storage Backend バリデーション

- **派生元ブランチ:** `feat/outbox-base`
- **実行モード:** 並列可能
- **前提条件:** Task 0.1 の Draft PR URL が存在
- **作成ブランチ:** `feat/outbox-config`

**Files:**
- Modify: `src/context_store/config.py`
- Create: `tests/unit/test_config_graph_sync.py`

- [ ] **Step 1: ブランチ作成と派生元検証**

```bash
EXPECTED_BASE="feat/outbox-base"
git fetch origin "$EXPECTED_BASE"
git checkout -b feat/outbox-config "origin/$EXPECTED_BASE"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git merge-base --is-ancestor "$EXPECTED_BASE" "$CURRENT_BRANCH" || {
    echo "ERROR: 派生元ブランチが $EXPECTED_BASE ではありません。スタック構造が壊れています。"
    exit 1
}
```

- [ ] **Step 2: 失敗テストを書く (TDD - RED)**

`tests/unit/test_config_graph_sync.py`:

```python
"""Config: graph_sync_mode + outbox_* バリデーションテスト。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from context_store.config import Settings


def _base_env(**overrides: object) -> dict[str, object]:
    env = {
        "STORAGE_BACKEND": "sqlite",
        "GRAPH_ENABLED": "true",
        "NEO4J_PASSWORD": "secret",
        "EMBEDDING_PROVIDER": "local-model",
    }
    env.update({k: str(v) for k, v in overrides.items()})
    return env


def test_default_graph_sync_mode_is_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in _base_env().items():
        monkeypatch.setenv(k, str(v))
    s = Settings()
    assert s.graph_sync_mode == "sync"


def test_async_outbox_requires_graph_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in _base_env(GRAPH_ENABLED="false", GRAPH_SYNC_MODE="async_outbox").items():
        monkeypatch.setenv(k, str(v))
    with pytest.raises(ValidationError, match="graph_sync_mode='async_outbox' requires"):
        Settings()


def test_supabase_with_graph_requires_async_outbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = {
        "STORAGE_BACKEND": "supabase",
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_KEY": "key",
        "GRAPH_ENABLED": "true",
        "NEO4J_PASSWORD": "secret",
        "GRAPH_SYNC_MODE": "sync",
        "EMBEDDING_PROVIDER": "local-model",
    }
    for k, v in env.items():
        monkeypatch.setenv(k, str(v))
    with pytest.raises(ValidationError, match="Supabase \\+ graph"):
        Settings()


def test_supabase_with_async_outbox_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    env = {
        "STORAGE_BACKEND": "supabase",
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_KEY": "key",
        "GRAPH_ENABLED": "true",
        "NEO4J_PASSWORD": "secret",
        "GRAPH_SYNC_MODE": "async_outbox",
        "EMBEDDING_PROVIDER": "local-model",
        "EMBEDDING_DIMENSION": "768",
    }
    for k, v in env.items():
        monkeypatch.setenv(k, str(v))
    s = Settings()
    assert s.graph_sync_mode == "async_outbox"
    assert s.storage_backend == "supabase"


def test_outbox_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in _base_env().items():
        monkeypatch.setenv(k, str(v))
    s = Settings()
    assert s.outbox_poll_interval_seconds == 5.0
    assert s.outbox_batch_size == 100
    assert s.outbox_max_retries == 10
    assert s.outbox_backoff_base_seconds == 1.0
    assert s.outbox_backoff_max_seconds == 60.0
```

- [ ] **Step 3: テストを実行して失敗を確認 (RED)**

```bash
uv run pytest tests/unit/test_config_graph_sync.py -v
```

Expected: FAIL（`graph_sync_mode` 属性が存在しない / バリデーションが未実装）

- [ ] **Step 4: Config 実装 (GREEN)**

`src/context_store/config.py` の `Settings` クラス内、`url_allowed_content_types` 定義の直後に以下を追加:

```python
    # --- Graph Sync (rev.11) ---
    graph_sync_mode: Literal["sync", "async_outbox"] = "sync"
    outbox_poll_interval_seconds: float = Field(default=5.0, gt=0.0)
    outbox_batch_size: int = Field(default=100, ge=1)
    outbox_max_retries: int = Field(default=10, ge=0)
    outbox_backoff_base_seconds: float = Field(default=1.0, gt=0.0)
    outbox_backoff_max_seconds: float = Field(default=60.0, gt=0.0)
```

既存の `_validate_storage_config` の **Supabase + graph_enabled** で raise する行を以下に置換:

```python
        if self.storage_backend == "supabase":
            url = self.supabase_url.strip()
            if not url:
                raise ValueError("SUPABASE_URL は storage_backend=supabase の場合に必須です。")
            key = self.supabase_key.get_secret_value().strip()
            if not key:
                raise ValueError("SUPABASE_KEY は storage_backend=supabase の場合に必須です。")

            self.supabase_url = url
            self.supabase_key = SecretStr(key)

            if not self.supabase_url.startswith("https://"):
                raise ValueError("SUPABASE_URL は https:// で始まる必要があります。")
            # graph_enabled の許可は _validate_graph_sync_mode で行う
            if self.embedding_dimension != SUPABASE_VECTOR_DIM:
                raise ValueError(
                    f"EMBEDDING_DIMENSION={self.embedding_dimension} は "
                    f"storage_backend=supabase のスキーマ vector({SUPABASE_VECTOR_DIM}) "
                    "と一致しません。次元数を変更する場合は "
                    "supabase/migrations/ の SQL とこの定数を同時に更新してください。"
                )
        return self
```

`_validate_storage_config` の後に新規バリデータを追加:

```python
    @model_validator(mode="after")
    def _validate_graph_sync_mode(self) -> "Settings":
        if self.graph_sync_mode == "async_outbox" and not self.graph_enabled:
            raise ValueError(
                "graph_sync_mode='async_outbox' requires graph_enabled=true"
            )
        if (
            self.storage_backend == "supabase"
            and self.graph_enabled
            and self.graph_sync_mode != "async_outbox"
        ):
            raise ValueError(
                "Supabase + graph requires graph_sync_mode='async_outbox' "
                "(Neo4j Bolt cannot be tunneled over HTTPS)"
            )
        return self
```

`graph_backend` の computed_field を更新（supabase + graph_enabled で `neo4j` を返す）:

```python
    @computed_field  # type: ignore[prop-decorator]
    @property
    def graph_backend(self) -> str:
        """Derived: 'sqlite' | 'neo4j' | 'disabled'."""
        if not self.graph_enabled:
            return "disabled"
        if self.storage_backend == "sqlite":
            return "sqlite"
        if self.storage_backend in ("postgres", "supabase"):
            return "neo4j"
        return "disabled"
```

- [ ] **Step 5: テストを実行 (GREEN)**

```bash
uv run pytest tests/unit/test_config_graph_sync.py -v
uv run pytest tests/unit/test_config.py -v  # 既存テスト regression
uv run mypy src/context_store/config.py
```

Expected: 全 PASS

- [ ] **Step 6: コミット & プッシュ**

```bash
git add src/context_store/config.py tests/unit/test_config_graph_sync.py
git commit -m "feat(config): graph_sync_mode と outbox_* 設定を追加"
git push -u origin feat/outbox-config
```

- [ ] **Step 7: Draft PR 作成**

```bash
gh pr create --draft --base feat/outbox-base --title "feat(config): graph_sync_mode と outbox 設定を追加" --body "$(cat <<'EOF'
## Summary
- `Settings.graph_sync_mode` (`sync`/`async_outbox`) と `outbox_*` フィールドを追加。
- `supabase + graph_enabled` を `async_outbox` モード時のみ許可するバリデータを追加。
- `graph_backend` の computed_field を Supabase + Neo4j を返すように拡張。

## Test plan
- [x] `tests/unit/test_config_graph_sync.py` で 5 ケース PASS
- [x] 既存 `test_config.py` regression なし

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

PR URL を記録。

---

## Task 1.2: SQLite + PostgreSQL マイグレーションと MigrationRunner 更新

- **派生元ブランチ:** `feat/outbox-base`
- **実行モード:** 並列可能（他 Task 1.x と並走可、ただし `runner.py` 編集は本 Task に集約）
- **前提条件:** Task 0.1 の Draft PR URL が存在
- **作成ブランチ:** `feat/outbox-storage-migrations`

**Files:**
- Create: `src/context_store/storage/migrations/postgres/0003_graph_sync_outbox.sql`
- Create: `src/context_store/storage/migrations/sqlite/0003_graph_sync_outbox.sql`
- Modify: `src/context_store/storage/migrations/runner.py`
- Modify: `tests/unit/test_migration_runner.py`

- [ ] **Step 1: ブランチ作成と派生元検証**

```bash
EXPECTED_BASE="feat/outbox-base"
git fetch origin "$EXPECTED_BASE"
git checkout -b feat/outbox-storage-migrations "origin/$EXPECTED_BASE"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git merge-base --is-ancestor "$EXPECTED_BASE" "$CURRENT_BRANCH" || {
    echo "ERROR: 派生元ブランチが $EXPECTED_BASE ではありません。スタック構造が壊れています。"
    exit 1
}
```

- [ ] **Step 2: 失敗テストを書く (TDD - RED) - SQLite マイグレーション**

`tests/unit/test_migration_runner.py` に以下のテストを追記:

```python
import aiosqlite
import pytest


@pytest.mark.asyncio
async def test_sqlite_migration_0003_creates_outbox_table(tmp_path) -> None:
    """0003 マイグレーション適用後に graph_sync_outbox テーブルが存在する。"""
    from context_store.storage.migrations.runner import MigrationRunner

    db = tmp_path / "test.db"
    async with aiosqlite.connect(str(db)) as conn:
        runner = MigrationRunner("sqlite", conn)
        await runner.run()
        async with conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='graph_sync_outbox'"
        ) as cur:
            row = await cur.fetchone()
            assert row is not None, "graph_sync_outbox テーブルが作成されていません"


@pytest.mark.asyncio
async def test_sqlite_baseline_includes_0003(tmp_path) -> None:
    """既存 outbox テーブルがあれば baseline 対象に含まれる。"""
    from context_store.storage.migrations.runner import MigrationRunner

    db = tmp_path / "test.db"
    async with aiosqlite.connect(str(db)) as conn:
        # 先に空でないテーブルだけ手動作成
        await conn.executescript(
            "CREATE TABLE memories (id TEXT PRIMARY KEY);"
            "CREATE TABLE memory_nodes (id TEXT PRIMARY KEY);"
            "CREATE TABLE memory_edges (id TEXT PRIMARY KEY);"
            "CREATE TABLE graph_sync_outbox (id TEXT PRIMARY KEY);"
        )
        await conn.commit()

        runner = MigrationRunner("sqlite", conn)
        await runner.run()
        async with conn.execute("SELECT version FROM schema_migrations") as cur:
            applied = {row[0] async for row in cur}

        assert "0003_graph_sync_outbox.sql" in applied
```

- [ ] **Step 3: テスト実行 (RED)**

```bash
uv run pytest tests/unit/test_migration_runner.py::test_sqlite_migration_0003_creates_outbox_table -v
```

Expected: FAIL（マイグレーションファイル不在）

- [ ] **Step 4: SQLite マイグレーション作成**

`src/context_store/storage/migrations/sqlite/0003_graph_sync_outbox.sql`:

```sql
CREATE TABLE graph_sync_outbox (
    id            TEXT PRIMARY KEY,
    event_type    TEXT NOT NULL CHECK (event_type IN ('SYNC_MEMORY', 'DELETE_MEMORY')),
    memory_id     TEXT NOT NULL,
    payload       TEXT NOT NULL DEFAULT '{}',
    status        TEXT NOT NULL DEFAULT 'PENDING'
                       CHECK (status IN ('PENDING', 'PROCESSING', 'FAILED')),
    retry_count   INTEGER NOT NULL DEFAULT 0,
    next_retry_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    error_message TEXT,
    created_at    TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at    TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_outbox_status_retry ON graph_sync_outbox (status, next_retry_at);
CREATE INDEX idx_outbox_memory_id ON graph_sync_outbox (memory_id);
```

- [ ] **Step 5: PostgreSQL マイグレーション作成**

`src/context_store/storage/migrations/postgres/0003_graph_sync_outbox.sql`:

```sql
CREATE TABLE graph_sync_outbox (
    id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type    VARCHAR(20)  NOT NULL CHECK (event_type IN ('SYNC_MEMORY', 'DELETE_MEMORY')),
    memory_id     UUID         NOT NULL,
    payload       JSONB        NOT NULL DEFAULT '{}',
    status        VARCHAR(20)  NOT NULL DEFAULT 'PENDING'
                               CHECK (status IN ('PENDING', 'PROCESSING', 'FAILED')),
    retry_count   INT          NOT NULL DEFAULT 0,
    next_retry_at TIMESTAMPTZ  DEFAULT NOW(),
    error_message TEXT,
    created_at    TIMESTAMPTZ  DEFAULT NOW(),
    updated_at    TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX idx_outbox_status_retry ON graph_sync_outbox (status, next_retry_at ASC);
CREATE INDEX idx_outbox_memory_id ON graph_sync_outbox (memory_id);
```

- [ ] **Step 6: MigrationRunner.baseline に 0003 を追加**

`src/context_store/storage/migrations/runner.py` の `_handle_baseline` 内 `requirements` を:

```python
        requirements = {
            "0001": ["memories"],
            "0002": ["memory_nodes", "memory_edges"],
            "0003": ["graph_sync_outbox"],
        }
```

- [ ] **Step 7: テスト実行 (GREEN)**

```bash
uv run pytest tests/unit/test_migration_runner.py -v
```

Expected: 全 PASS

- [ ] **Step 8: コミット & プッシュ**

```bash
git add src/context_store/storage/migrations/postgres/0003_graph_sync_outbox.sql \
        src/context_store/storage/migrations/sqlite/0003_graph_sync_outbox.sql \
        src/context_store/storage/migrations/runner.py \
        tests/unit/test_migration_runner.py
git commit -m "feat(storage): graph_sync_outbox テーブルのマイグレーションを追加"
git push -u origin feat/outbox-storage-migrations
```

- [ ] **Step 9: Draft PR 作成**

```bash
gh pr create --draft --base feat/outbox-base --title "feat(storage): graph_sync_outbox マイグレーションを追加" --body "$(cat <<'EOF'
## Summary
- SQLite/PostgreSQL 用の `0003_graph_sync_outbox.sql` を追加。
- `MigrationRunner._handle_baseline` の requirements に `"0003": ["graph_sync_outbox"]` を追加。

## Schema
- `id`/`event_type`/`memory_id`/`payload`/`status`/`retry_count`/`next_retry_at`/`error_message`/`created_at`/`updated_at`
- Index: `(status, next_retry_at)` + `(memory_id)`
  - `(memory_id)` は運用/障害調査クエリ用。書き込み時の重複制御には**使用しない**
    （設計 §3.4 を参照）。UNIQUE 制約も追加しない（dedup-at-convergence 方針）。

## Test plan
- [x] 新規マイグレーション適用テスト
- [x] baseline 検出テスト
EOF
)"
```

PR URL を記録。

---

## Task 1.3: Supabase マイグレーション + RPC 関数

- **派生元ブランチ:** `feat/outbox-base`
- **実行モード:** 並列可能
- **前提条件:** Task 0.1 の Draft PR URL が存在
- **作成ブランチ:** `feat/outbox-supabase-migrations`

**Files:**
- Create: `supabase/migrations/20260521000001_graph_sync_outbox.sql`
- Modify: `tests/unit/test_storage_factory.py`（または既存の Supabase テスト）に基本検証を追記

- [ ] **Step 1: ブランチ作成と派生元検証**

```bash
EXPECTED_BASE="feat/outbox-base"
git fetch origin "$EXPECTED_BASE"
git checkout -b feat/outbox-supabase-migrations "origin/$EXPECTED_BASE"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git merge-base --is-ancestor "$EXPECTED_BASE" "$CURRENT_BRANCH" || {
    echo "ERROR: 派生元ブランチが $EXPECTED_BASE ではありません。スタック構造が壊れています。"
    exit 1
}
```

- [ ] **Step 2: マイグレーションファイル作成**

`supabase/migrations/20260521000001_graph_sync_outbox.sql`:

```sql
-- =====================================================================
-- Transactional Outbox Sync (rev.11)
-- =====================================================================

CREATE TABLE graph_sync_outbox (
    id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type    VARCHAR(20)  NOT NULL CHECK (event_type IN ('SYNC_MEMORY', 'DELETE_MEMORY')),
    memory_id     UUID         NOT NULL,
    payload       JSONB        NOT NULL DEFAULT '{}',
    status        VARCHAR(20)  NOT NULL DEFAULT 'PENDING'
                               CHECK (status IN ('PENDING', 'PROCESSING', 'FAILED')),
    retry_count   INT          NOT NULL DEFAULT 0,
    next_retry_at TIMESTAMPTZ  DEFAULT NOW(),
    error_message TEXT,
    created_at   TIMESTAMPTZ   DEFAULT NOW(),
    updated_at   TIMESTAMPTZ   DEFAULT NOW()
);

CREATE INDEX idx_outbox_status_retry ON graph_sync_outbox (status, next_retry_at ASC);
CREATE INDEX idx_outbox_memory_id ON graph_sync_outbox (memory_id);

-- =====================================================================
-- RPC: メモリ UPSERT + Outbox 書き込みをアトミックに実行
-- =====================================================================

CREATE OR REPLACE FUNCTION upsert_memory_with_outbox(
    p_id                  UUID,
    p_content             TEXT,
    p_memory_type         VARCHAR(20),
    p_source_type         VARCHAR(20),
    p_source_metadata     JSONB,
    p_embedding           vector(768),
    p_semantic_relevance  FLOAT,
    p_importance_score    FLOAT,
    p_tags                TEXT[],
    p_project             TEXT,
    p_content_hash        TEXT,
    p_event_type          VARCHAR(20) DEFAULT 'SYNC_MEMORY'
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
    VALUES (p_event_type, v_memory_id);

    RETURN v_memory_id;
END;
$$;

-- =====================================================================
-- RPC: メモリ削除 + Outbox 書き込みをアトミックに実行
-- =====================================================================

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

GRANT EXECUTE ON FUNCTION upsert_memory_with_outbox(
    UUID, TEXT, VARCHAR, VARCHAR, JSONB, vector, FLOAT, FLOAT,
    TEXT[], TEXT, TEXT, VARCHAR
) TO service_role;
GRANT EXECUTE ON FUNCTION delete_memory_with_outbox(UUID) TO service_role;

-- =====================================================================
-- RPC: Worker 側で使用する状態遷移系（Supabase は asyncpg を使えないため）
-- =====================================================================

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

- [ ] **Step 3: SQL 構文チェック**

```bash
# Supabase ローカル環境がない場合は静的構文だけ確認
uv run python -c "import re, pathlib; sql = pathlib.Path('supabase/migrations/20260521000001_graph_sync_outbox.sql').read_text(); assert sql.count('CREATE TABLE') == 1; assert sql.count('CREATE OR REPLACE FUNCTION') == 2; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: 既存の Supabase 関連 lint チェック**

```bash
uv run ruff check src/ tests/
```

Expected: PASS

- [ ] **Step 5: コミット & プッシュ**

```bash
git add supabase/migrations/20260521000001_graph_sync_outbox.sql
git commit -m "feat(supabase): graph_sync_outbox テーブルと RPC 関数を追加"
git push -u origin feat/outbox-supabase-migrations
```

- [ ] **Step 6: Draft PR 作成**

```bash
gh pr create --draft --base feat/outbox-base --title "feat(supabase): graph_sync_outbox マイグレーション + RPC" --body "$(cat <<'EOF'
## Summary
- Supabase `graph_sync_outbox` テーブル追加。
- RPC (書き込み側):
  - `upsert_memory_with_outbox`
  - `delete_memory_with_outbox`
- RPC (Worker 側):
  - `fetch_pending_outbox(p_limit)` — UPDATE + RETURNING を 1 TX
  - `reset_stuck_processing_outbox(p_threshold_seconds, p_max_retries)` — 2 段階 UPDATE を 1 TX
- すべて `SECURITY INVOKER` + `search_path = public` で定義し、`service_role` に EXECUTE 権限を付与。

## Test plan
- [ ] 構文チェック PASS（実適用は Task 3.3 / Task 4.1 で行う）
EOF
)"
```

PR URL を記録。

---

# Phase 2: Sync レイヤー実装

## Task 2.1: OutboxWriter Protocol と実装

- **派生元ブランチ:** `feat/outbox-storage-migrations`
- **実行モード:** 直列必須（Wait for Task 1.2 Draft PR）
- **前提条件:** Task 1.2 の Draft PR URL が存在
- **作成ブランチ:** `feat/outbox-writer`

**Files:**
- Create: `src/context_store/sync/outbox_writer.py`
- Create: `tests/unit/sync/test_outbox_writer.py`

- [ ] **Step 1: ブランチ作成と派生元検証**

```bash
EXPECTED_BASE="feat/outbox-storage-migrations"
git fetch origin "$EXPECTED_BASE"
git checkout -b feat/outbox-writer "origin/$EXPECTED_BASE"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git merge-base --is-ancestor "$EXPECTED_BASE" "$CURRENT_BRANCH" || {
    echo "ERROR: 派生元ブランチが $EXPECTED_BASE ではありません。スタック構造が壊れています。"
    exit 1
}
```

- [ ] **Step 2: 失敗テストを書く (RED)**

`tests/unit/sync/test_outbox_writer.py`:

```python
"""OutboxWriter: Postgres/SQLite それぞれで TX 内に INSERT できることを検証。"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_postgres_outbox_writer_inserts_sync_event() -> None:
    from context_store.sync.outbox_writer import PostgresOutboxWriter

    conn = MagicMock()
    conn.execute = AsyncMock()

    writer = PostgresOutboxWriter()
    await writer.enqueue_sync(
        conn=conn, memory_id="11111111-1111-1111-1111-111111111111",
        event_type="SYNC_MEMORY",
    )

    conn.execute.assert_awaited_once()
    call_args = conn.execute.await_args
    assert "INSERT INTO graph_sync_outbox" in call_args.args[0]
    assert call_args.args[1] == "SYNC_MEMORY"
    assert call_args.args[2] == "11111111-1111-1111-1111-111111111111"


@pytest.mark.asyncio
async def test_postgres_outbox_writer_inserts_delete_event_with_payload() -> None:
    from context_store.sync.outbox_writer import PostgresOutboxWriter

    conn = MagicMock()
    conn.execute = AsyncMock()

    writer = PostgresOutboxWriter()
    await writer.enqueue_sync(
        conn=conn, memory_id="22222222-2222-2222-2222-222222222222",
        event_type="DELETE_MEMORY", payload={"memory_type": "FACT"},
    )
    args = conn.execute.await_args.args
    assert args[1] == "DELETE_MEMORY"
    assert json.loads(args[3]) == {"memory_type": "FACT"}


@pytest.mark.asyncio
async def test_sqlite_outbox_writer_inserts_with_generated_uuid() -> None:
    from context_store.sync.outbox_writer import SqliteOutboxWriter

    conn = MagicMock()
    conn.execute = AsyncMock()

    writer = SqliteOutboxWriter()
    await writer.enqueue_sync(
        conn=conn, memory_id="abc", event_type="SYNC_MEMORY",
    )
    sql, *_ = conn.execute.await_args.args
    assert "INSERT INTO graph_sync_outbox" in sql
    assert "?" in sql  # SQLite placeholders


@pytest.mark.asyncio
async def test_outbox_writer_rejects_invalid_event_type() -> None:
    from context_store.sync.outbox_writer import PostgresOutboxWriter

    conn = MagicMock()
    conn.execute = AsyncMock()
    writer = PostgresOutboxWriter()
    with pytest.raises(ValueError, match="Invalid event_type"):
        await writer.enqueue_sync(
            conn=conn, memory_id="abc", event_type="UNKNOWN",  # type: ignore[arg-type]
        )
```

- [ ] **Step 3: テスト実行 (RED)**

```bash
uv run pytest tests/unit/sync/test_outbox_writer.py -v
```

Expected: FAIL（モジュール未実装）

- [ ] **Step 4: 実装 (GREEN)**

`src/context_store/sync/outbox_writer.py`:

```python
"""OutboxWriter: Storage TX 内で graph_sync_outbox に INSERT する。"""

from __future__ import annotations

import json
import uuid
from typing import Any, Protocol

from context_store.sync.models import EventType

_ALLOWED_EVENT_TYPES = {"SYNC_MEMORY", "DELETE_MEMORY"}


def _validate_event_type(event_type: str) -> None:
    if event_type not in _ALLOWED_EVENT_TYPES:
        raise ValueError(
            f"Invalid event_type={event_type!r}. "
            f"Allowed: {sorted(_ALLOWED_EVENT_TYPES)}"
        )


class OutboxWriter(Protocol):
    """Outbox 書き込みプロトコル。

    各 StorageAdapter のトランザクション内で呼び出される。
    Postgres は asyncpg.Connection、SQLite は aiosqlite.Connection を期待する。

    Note:
        書き込み時の重複チェック (dedup-at-insert) は意図的に行わない。
        同一 memory_id への複数 SYNC_MEMORY は許容され、Worker 側の
        「最新状態フェッチ + MERGE」で収束する。設計 §3.4 を参照。
    """

    async def enqueue_sync(
        self,
        conn: Any,
        memory_id: str,
        event_type: EventType,
        payload: dict[str, Any] | None = None,
    ) -> None: ...


class PostgresOutboxWriter:
    """asyncpg.Connection の TX 内で INSERT する。"""

    _SQL = (
        "INSERT INTO graph_sync_outbox (event_type, memory_id, payload) "
        "VALUES ($1, $2::uuid, $3::jsonb)"
    )

    async def enqueue_sync(
        self,
        conn: Any,
        memory_id: str,
        event_type: EventType,
        payload: dict[str, Any] | None = None,
    ) -> None:
        _validate_event_type(event_type)
        await conn.execute(
            self._SQL,
            event_type,
            memory_id,
            json.dumps(payload or {}),
        )


class SqliteOutboxWriter:
    """aiosqlite.Connection の TX 内で INSERT する。"""

    _SQL = (
        "INSERT INTO graph_sync_outbox (id, event_type, memory_id, payload) "
        "VALUES (?, ?, ?, ?)"
    )

    async def enqueue_sync(
        self,
        conn: Any,
        memory_id: str,
        event_type: EventType,
        payload: dict[str, Any] | None = None,
    ) -> None:
        _validate_event_type(event_type)
        await conn.execute(
            self._SQL,
            (
                str(uuid.uuid4()),
                event_type,
                memory_id,
                json.dumps(payload or {}),
            ),
        )
```

- [ ] **Step 5: テスト実行 (GREEN)**

```bash
uv run pytest tests/unit/sync/test_outbox_writer.py -v
uv run mypy src/context_store/sync/outbox_writer.py
```

Expected: 全 PASS

- [ ] **Step 6: コミット & プッシュ**

```bash
git add src/context_store/sync/outbox_writer.py tests/unit/sync/test_outbox_writer.py
git commit -m "feat(sync): OutboxWriter Protocol と Postgres/SQLite 実装を追加"
git push -u origin feat/outbox-writer
```

- [ ] **Step 7: Draft PR 作成**

```bash
gh pr create --draft --base feat/outbox-storage-migrations --title "feat(sync): OutboxWriter Protocol + 実装" --body "$(cat <<'EOF'
## Summary
- `OutboxWriter` Protocol を定義。
- `PostgresOutboxWriter` (asyncpg) と `SqliteOutboxWriter` (aiosqlite) を実装。
- `payload` は JSON シリアライズ。
- `event_type` の許可リスト検証付き。

## Test plan
- [x] enqueue_sync が正しい SQL を発行する
- [x] DELETE イベントで payload が JSON 化される
- [x] 不正な event_type で ValueError

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

PR URL を記録。

---

## Task 2.2: Neo4jGraphAdapter.execute_write メソッド追加

- **派生元ブランチ:** `feat/outbox-base`
- **実行モード:** 並列可能
- **前提条件:** Task 0.1 の Draft PR URL が存在
- **作成ブランチ:** `feat/outbox-neo4j-execute-write`

**Files:**
- Modify: `src/context_store/storage/neo4j.py`
- Modify: `tests/unit/test_neo4j_storage.py`

- [ ] **Step 1: ブランチ作成と派生元検証**

```bash
EXPECTED_BASE="feat/outbox-base"
git fetch origin "$EXPECTED_BASE"
git checkout -b feat/outbox-neo4j-execute-write "origin/$EXPECTED_BASE"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git merge-base --is-ancestor "$EXPECTED_BASE" "$CURRENT_BRANCH" || {
    echo "ERROR: 派生元ブランチが $EXPECTED_BASE ではありません。スタック構造が壊れています。"
    exit 1
}
```

- [ ] **Step 2: 失敗テストを追記 (RED)**

`tests/unit/test_neo4j_storage.py` に追記:

```python
@pytest.mark.asyncio
async def test_neo4j_execute_write_runs_cypher_with_parameters() -> None:
    """execute_write は session.run で書き込みクエリを実行する。"""
    from context_store.storage.neo4j import Neo4jGraphAdapter

    adp = Neo4jGraphAdapter.__new__(Neo4jGraphAdapter)
    adp._driver = MagicMock()  # type: ignore[attr-defined]
    adp._read_only = False  # type: ignore[attr-defined]

    fake_session = AsyncMock()
    fake_session.__aenter__.return_value = fake_session
    fake_session.__aexit__.return_value = None
    fake_session.run = AsyncMock()

    adp._driver.session.return_value = fake_session

    await adp.execute_write("UNWIND $batch AS r MERGE (m:Memory {id:r.id})", {"batch": [{"id": "x"}]})

    fake_session.run.assert_awaited_once()
    cypher_arg = fake_session.run.await_args.args[0]
    assert "UNWIND" in cypher_arg


@pytest.mark.asyncio
async def test_neo4j_execute_write_logs_warning_on_failure(caplog) -> None:
    """例外発生時は WARNING ログを出して握りつぶす（既存パターン踏襲）。"""
    from context_store.storage.neo4j import Neo4jGraphAdapter

    adp = Neo4jGraphAdapter.__new__(Neo4jGraphAdapter)
    adp._driver = MagicMock()  # type: ignore[attr-defined]
    adp._read_only = False  # type: ignore[attr-defined]
    fake_session = AsyncMock()
    fake_session.__aenter__.side_effect = RuntimeError("network error")
    adp._driver.session.return_value = fake_session

    with caplog.at_level("WARNING"):
        # 既存 traverse() と同じ「失敗→ログ→例外再送」または「ログ→空返却」のどちらか
        # 設計書 §8.5 に従い、ここでは例外を re-raise してワーカー側で Backoff させる
        with pytest.raises(RuntimeError):
            await adp.execute_write("MERGE (m:Memory {id:'x'})", {})
```

- [ ] **Step 3: テスト実行 (RED)**

```bash
uv run pytest tests/unit/test_neo4j_storage.py -v -k execute_write
```

Expected: FAIL（メソッド未実装）

- [ ] **Step 4: 実装 (GREEN)**

`src/context_store/storage/neo4j.py` の `Neo4jGraphAdapter` クラス内に以下を追加（既存メソッドのインデント・スタイルに合わせる）:

```python
    async def execute_write(self, cypher: str, parameters: dict[str, Any]) -> None:
        """任意の書き込み Cypher を実行する。

        Outbox Worker / リカバリスクリプトから使用される汎用書き込み API。
        Read-only モードでは ``StorageError`` を送出する。
        失敗は呼び出し側で Exponential Backoff されるため、例外は再送する。
        """
        if self._read_only:
            raise StorageError(
                "Neo4jGraphAdapter is in read-only mode; execute_write disallowed",
                code="READ_ONLY",
                recoverable=False,
            )
        async with self._driver.session() as session:
            await session.run(cypher, parameters)
```

`StorageError` のインポートが無ければ追加:

```python
from context_store.storage.protocols import StorageError
```

- [ ] **Step 5: テスト実行 (GREEN)**

```bash
uv run pytest tests/unit/test_neo4j_storage.py -v
uv run mypy src/context_store/storage/neo4j.py
```

Expected: PASS

- [ ] **Step 6: コミット & プッシュ**

```bash
git add src/context_store/storage/neo4j.py tests/unit/test_neo4j_storage.py
git commit -m "feat(neo4j): execute_write メソッドを追加 (Outbox 共通書き込み API)"
git push -u origin feat/outbox-neo4j-execute-write
```

- [ ] **Step 7: Draft PR 作成**

```bash
gh pr create --draft --base feat/outbox-base --title "feat(neo4j): execute_write メソッドを追加" --body "$(cat <<'EOF'
## Summary
- `Neo4jGraphAdapter.execute_write(cypher, parameters)` を追加。
- Outbox Worker / リカバリスクリプトの共通書き込み API。
- Read-only モードでは StorageError を送出。

## Test plan
- [x] Cypher 実行確認
- [x] Read-only モードガード
EOF
)"
```

PR URL を記録。

---

## Task 2.3: GraphSyncService（Worker + リカバリ共有ロジック）

- **派生元ブランチ:** `feat/outbox-neo4j-execute-write`
- **実行モード:** 直列必須（Wait for Task 2.2 Draft PR）
- **前提条件:** Task 2.2 の Draft PR URL が存在
- **作成ブランチ:** `feat/outbox-graph-sync`

**Files:**
- Create: `src/context_store/sync/graph_sync.py`
- Create: `tests/unit/sync/test_graph_sync.py`

- [ ] **Step 1: ブランチ作成と派生元検証**

```bash
EXPECTED_BASE="feat/outbox-neo4j-execute-write"
git fetch origin "$EXPECTED_BASE"
git checkout -b feat/outbox-graph-sync "origin/$EXPECTED_BASE"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git merge-base --is-ancestor "$EXPECTED_BASE" "$CURRENT_BRANCH" || {
    echo "ERROR: 派生元ブランチが $EXPECTED_BASE ではありません。スタック構造が壊れています。"
    exit 1
}
```

- [ ] **Step 2: 失敗テストを書く (RED)**

`tests/unit/sync/test_graph_sync.py`:

```python
"""GraphSyncService: Storage → Neo4j のバルク同期ロジック検証。"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from context_store.models.memory import Memory


def _make_memory(mid: str, **overrides) -> Memory:
    base = dict(
        id=mid,
        content="hello",
        memory_type="FACT",
        source_type="USER",
        source_metadata={},
        embedding=[0.1] * 768,
        semantic_relevance=0.5,
        importance_score=0.5,
        tags=["t1"],
        project="p1",
        content_hash="h",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    base.update(overrides)
    return Memory(**base)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_bulk_merge_memories_issues_unwind_merge_cypher() -> None:
    from context_store.sync.graph_sync import GraphSyncService

    graph = MagicMock()
    graph.execute_write = AsyncMock()
    storage = MagicMock()
    storage.list_edges_for_memories = AsyncMock(return_value=[])

    svc = GraphSyncService(graph_adapter=graph, storage_adapter=storage)
    n = await svc.bulk_merge_memories([_make_memory("a"), _make_memory("b")])

    assert n == 2
    # ノード MERGE Cypher が UNWIND ベースであること
    cypher_calls = [c.args[0] for c in graph.execute_write.await_args_list]
    assert any("UNWIND $batch" in c and "MERGE (m:Memory" in c for c in cypher_calls)


@pytest.mark.asyncio
async def test_bulk_merge_memories_only_writes_minimal_props() -> None:
    """Neo4j に格納するプロパティは id / memory_type / created_at / project / tags のみ。"""
    from context_store.sync.graph_sync import GraphSyncService

    graph = MagicMock()
    graph.execute_write = AsyncMock()
    storage = MagicMock()
    storage.list_edges_for_memories = AsyncMock(return_value=[])

    svc = GraphSyncService(graph_adapter=graph, storage_adapter=storage)
    await svc.bulk_merge_memories([_make_memory("a")])

    # 最初の execute_write 呼び出しのバッチパラメータ
    first_call = graph.execute_write.await_args_list[0]
    batch = first_call.args[1]["batch"]
    keys = set(batch[0].keys())
    assert keys == {"id", "memory_type", "created_at", "project", "tags"}


@pytest.mark.asyncio
async def test_bulk_delete_nodes_uses_detach_delete() -> None:
    from context_store.sync.graph_sync import GraphSyncService

    graph = MagicMock()
    graph.execute_write = AsyncMock()
    storage = MagicMock()

    svc = GraphSyncService(graph_adapter=graph, storage_adapter=storage)
    await svc.bulk_delete_nodes(["a", "b"])

    graph.execute_write.assert_awaited_once()
    cypher = graph.execute_write.await_args.args[0]
    assert "DETACH DELETE" in cypher
    params = graph.execute_write.await_args.args[1]
    assert params["ids"] == ["a", "b"]


@pytest.mark.asyncio
async def test_bulk_merge_memories_empty_list_is_noop() -> None:
    from context_store.sync.graph_sync import GraphSyncService

    graph = MagicMock()
    graph.execute_write = AsyncMock()
    storage = MagicMock()

    svc = GraphSyncService(graph_adapter=graph, storage_adapter=storage)
    n = await svc.bulk_merge_memories([])
    assert n == 0
    graph.execute_write.assert_not_called()
```

- [ ] **Step 3: テスト実行 (RED)**

```bash
uv run pytest tests/unit/sync/test_graph_sync.py -v
```

Expected: FAIL（GraphSyncService 未実装）

- [ ] **Step 4: 実装 (GREEN)**

`src/context_store/sync/graph_sync.py`:

```python
"""GraphSyncService: Storage → Neo4j のバルク同期ロジック。

Worker / リカバリスクリプト両方から使用。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from context_store.models.memory import Memory
    from context_store.storage.neo4j import Neo4jGraphAdapter
    from context_store.storage.protocols import StorageAdapter

logger = logging.getLogger(__name__)


# Neo4j に格納するプロパティは Traversal Index に必要な最小限のみ
_NODE_MERGE_CYPHER = """
UNWIND $batch AS row
MERGE (m:Memory {id: row.id})
SET m.memory_type = row.memory_type,
    m.created_at  = row.created_at,
    m.project     = row.project,
    m.tags        = row.tags
"""

_EDGE_MERGE_CYPHER_TEMPLATE = """
UNWIND $batch AS row
MATCH (a:Memory {{id: row.from_id}})
MATCH (b:Memory {{id: row.to_id}})
MERGE (a)-[r:{edge_type}]->(b)
SET r += row.props
"""

_DELETE_CYPHER = """
UNWIND $ids AS mid
MATCH (m:Memory {id: mid})
DETACH DELETE m
"""


class GraphSyncService:
    """Storage Layer → Neo4j のバルク同期サービス。"""

    def __init__(
        self,
        *,
        graph_adapter: "Neo4jGraphAdapter",
        storage_adapter: "StorageAdapter",
    ) -> None:
        self._graph = graph_adapter
        self._storage = storage_adapter

    async def bulk_merge_memories(self, memories: list["Memory"]) -> int:
        """ノード + 関連エッジを Neo4j に MERGE する。

        戻り値: MERGE したメモリ件数。
        """
        if not memories:
            return 0

        batch = [
            {
                "id": m.id,
                "memory_type": m.memory_type,
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "project": m.project,
                "tags": list(m.tags or []),
            }
            for m in memories
        ]
        await self._graph.execute_write(_NODE_MERGE_CYPHER, {"batch": batch})

        # エッジ同期 - Storage 側グラフテーブルから対象メモリのエッジを取得
        memory_ids = [m.id for m in memories]
        edges = await self._storage.list_edges_for_memories(memory_ids)  # type: ignore[attr-defined]

        if not edges:
            return len(memories)

        # エッジ種別ごとにグループ化
        grouped: dict[str, list[dict[str, Any]]] = {}
        for e in edges:
            grouped.setdefault(e.edge_type, []).append(
                {"from_id": e.from_id, "to_id": e.to_id, "props": dict(e.props or {})}
            )
        for edge_type, payload in grouped.items():
            cypher = _EDGE_MERGE_CYPHER_TEMPLATE.format(edge_type=_sanitize_edge_type(edge_type))
            await self._graph.execute_write(cypher, {"batch": payload})

        return len(memories)

    async def bulk_delete_nodes(self, memory_ids: list[str]) -> int:
        """ノード + 関連エッジを DETACH DELETE する。"""
        if not memory_ids:
            return 0
        await self._graph.execute_write(_DELETE_CYPHER, {"ids": list(memory_ids)})
        return len(memory_ids)

    async def full_sync_from_storage(self, *, chunk_size: int = 1000) -> int:
        """Storage 全体から Neo4j を再構築。chunk_size でページネーション。"""
        from context_store.storage.protocols import MemoryFilters

        total = 0
        offset = 0
        while True:
            filters = MemoryFilters(limit=chunk_size, offset=offset, order_by="id")
            page = await self._storage.list_by_filter(filters)
            if not page:
                break
            n = await self.bulk_merge_memories(page)
            total += n
            offset += chunk_size
            logger.info("GraphSyncService.full_sync_from_storage: synced %d so far", total)
        return total


def _sanitize_edge_type(edge_type: str) -> str:
    """Cypher 注入を防ぐためエッジ種別を英数字+アンダースコアに限定。"""
    if not edge_type.replace("_", "").isalnum():
        raise ValueError(f"Invalid edge_type for Cypher: {edge_type!r}")
    return edge_type
```

- [ ] **Step 5: テスト実行 (GREEN)**

```bash
uv run pytest tests/unit/sync/test_graph_sync.py -v
uv run mypy src/context_store/sync/graph_sync.py
```

Expected: PASS

- [ ] **Step 6: コミット & プッシュ**

```bash
git add src/context_store/sync/graph_sync.py tests/unit/sync/test_graph_sync.py
git commit -m "feat(sync): GraphSyncService を追加 (bulk_merge / bulk_delete / full_sync)"
git push -u origin feat/outbox-graph-sync
```

- [ ] **Step 7: Draft PR 作成**

```bash
gh pr create --draft --base feat/outbox-neo4j-execute-write --title "feat(sync): GraphSyncService - 共有 MERGE/DELETE ロジック" --body "$(cat <<'EOF'
## Summary
- `bulk_merge_memories` / `bulk_delete_nodes` / `full_sync_from_storage` を実装。
- UNWIND + MERGE で冪等性を保証。
- Neo4j 格納プロパティを最小限 (id, memory_type, created_at, project, tags) に制限。
- Cypher 注入対策で edge_type をサニタイズ。

## Test plan
- [x] UNWIND $batch + MERGE 発行確認
- [x] 最小プロパティのみ
- [x] DETACH DELETE 発行確認
- [x] 空入力の no-op

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

PR URL を記録。

---

# Phase 3: Storage Adapter 統合

> **構成:** Task 3.1 (Postgres) / 3.2 (SQLite) / 3.3 (Supabase) の 3 タスク。欠番なし。
> 各 Storage Backend ごとに OutboxWriter / RPC を統合する。3.1 と 3.2 は別ファイルを
> 触るため並列実行可能、3.3 は Supabase RPC 依存のため Task 1.3 のマージ後に開始する。

## Task 3.1: PostgresStorageAdapter への OutboxWriter 統合

- **派生元ブランチ:** `feat/outbox-writer`
- **実行モード:** 直列必須（Wait for Task 2.1 Draft PR）
- **前提条件:** Task 2.1 の Draft PR URL が存在
- **作成ブランチ:** `feat/outbox-postgres-integration`

**Files:**
- Modify: `src/context_store/storage/postgres.py`
- Create: `tests/unit/storage/test_postgres_outbox.py`

- [ ] **Step 1: ブランチ作成と派生元検証**

```bash
EXPECTED_BASE="feat/outbox-writer"
git fetch origin "$EXPECTED_BASE"
git checkout -b feat/outbox-postgres-integration "origin/$EXPECTED_BASE"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git merge-base --is-ancestor "$EXPECTED_BASE" "$CURRENT_BRANCH" || {
    echo "ERROR: 派生元ブランチが $EXPECTED_BASE ではありません。スタック構造が壊れています。"
    exit 1
}
```

- [ ] **Step 2: 失敗テストを書く (RED)**

`tests/unit/storage/test_postgres_outbox.py`:

```python
"""PostgresStorageAdapter + OutboxWriter 統合検証。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_save_memory_writes_outbox_when_writer_set(monkeypatch) -> None:
    """outbox_writer が設定されていれば save_memory TX 内で enqueue_sync される。"""
    from context_store.storage.postgres import PostgresStorageAdapter

    # 既存テストフィクスチャに合わせて、PostgresStorageAdapter をモック構築
    adp = PostgresStorageAdapter.__new__(PostgresStorageAdapter)
    fake_conn = MagicMock()
    fake_conn.fetchval = AsyncMock(return_value="33333333-3333-3333-3333-333333333333")
    fake_conn.transaction = MagicMock()
    fake_conn.transaction.return_value.__aenter__ = AsyncMock(return_value=None)
    fake_conn.transaction.return_value.__aexit__ = AsyncMock(return_value=None)

    fake_pool = MagicMock()
    fake_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=fake_conn)
    fake_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    adp._pool = fake_pool  # type: ignore[attr-defined]
    adp._dimension = 768  # type: ignore[attr-defined]

    outbox = AsyncMock()
    adp._outbox_writer = outbox  # type: ignore[attr-defined]

    from context_store.models.memory import Memory
    from datetime import datetime, timezone
    mem = Memory(
        id="33333333-3333-3333-3333-333333333333",
        content="hi", memory_type="FACT", source_type="USER",
        source_metadata={}, embedding=[0.1] * 768,
        semantic_relevance=0.5, importance_score=0.5, tags=[], project="p",
        content_hash="h", created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    await adp.save_memory(mem)

    outbox.enqueue_sync.assert_awaited_once()
    call = outbox.enqueue_sync.await_args
    assert call.kwargs["conn"] is fake_conn
    assert call.kwargs["event_type"] == "SYNC_MEMORY"
    assert call.kwargs["memory_id"] == "33333333-3333-3333-3333-333333333333"


@pytest.mark.asyncio
async def test_save_memory_skips_outbox_when_writer_none() -> None:
    """outbox_writer が None なら従来動作（Outbox 書き込み無し）。"""
    # (同じパターンで _outbox_writer = None で組み立て、enqueue_sync が呼ばれない事を検証)
    pass  # 実装時に展開


@pytest.mark.asyncio
async def test_delete_memory_writes_delete_event_with_metadata() -> None:
    """delete_memory は payload に memory_type/tags/project を含めて enqueue。"""
    pass  # 実装時に展開
```

- [ ] **Step 3: テスト実行 (RED)**

```bash
uv run pytest tests/unit/storage/test_postgres_outbox.py -v
```

Expected: FAIL

- [ ] **Step 4: 実装 (GREEN)**

`src/context_store/storage/postgres.py` の `PostgresStorageAdapter.__init__` (または `create()`) に `outbox_writer` パラメータ受け入れを追加。`save_memory` を以下のように改修:

```python
    async def save_memory(self, memory: Memory) -> str:
        # ... 既存の前処理 ...
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row_id = await conn.fetchval(insert_sql, *params)
                if self._outbox_writer is not None:
                    await self._outbox_writer.enqueue_sync(
                        conn=conn,
                        memory_id=str(row_id),
                        event_type="SYNC_MEMORY",
                    )
                return str(row_id)
```

`delete_memory`:

```python
    async def delete_memory(self, memory_id: str) -> bool:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                if self._outbox_writer is not None:
                    meta_row = await conn.fetchrow(
                        "SELECT memory_type, tags, project FROM memories WHERE id = $1::uuid",
                        memory_id,
                    )
                else:
                    meta_row = None
                result = await conn.execute(
                    "DELETE FROM memories WHERE id = $1::uuid", memory_id
                )
                deleted = result.endswith(" 1")
                if deleted and self._outbox_writer is not None:
                    await self._outbox_writer.enqueue_sync(
                        conn=conn,
                        memory_id=memory_id,
                        event_type="DELETE_MEMORY",
                        payload=dict(meta_row) if meta_row else {},
                    )
                return deleted
```

`__init__` 等で `self._outbox_writer: OutboxWriter | None = None` を初期化し、`create()` クラスメソッドに `outbox_writer` 引数を追加（既存のシグネチャは保持し、デフォルト None）。

- [ ] **Step 5: テスト展開 + 実行 (GREEN)**

「実装時に展開」とした 2 テストを完成させ、

```bash
uv run pytest tests/unit/storage/test_postgres_outbox.py -v
uv run pytest tests/unit/test_postgres_storage.py -v  # regression
uv run mypy src/context_store/storage/postgres.py
```

Expected: 全 PASS

- [ ] **Step 6: コミット & プッシュ**

```bash
git add src/context_store/storage/postgres.py tests/unit/storage/test_postgres_outbox.py
git commit -m "feat(postgres): save/delete_memory に OutboxWriter 統合"
git push -u origin feat/outbox-postgres-integration
```

- [ ] **Step 7: Draft PR 作成**

```bash
gh pr create --draft --base feat/outbox-writer --title "feat(postgres): save/delete_memory に OutboxWriter を統合" --body "..."
```

PR URL を記録。

---

## Task 3.2: SQLiteStorageAdapter への OutboxWriter 統合

- **派生元ブランチ:** `feat/outbox-writer`
- **実行モード:** 並列可能（Task 3.1 と独立ファイル）
- **前提条件:** Task 2.1 の Draft PR URL が存在
- **作成ブランチ:** `feat/outbox-sqlite-integration`

**Files:**
- Modify: `src/context_store/storage/sqlite.py`
- Create: `tests/unit/storage/test_sqlite_outbox.py`

- [ ] **Step 1: ブランチ作成と派生元検証**

```bash
EXPECTED_BASE="feat/outbox-writer"
git fetch origin "$EXPECTED_BASE"
git checkout -b feat/outbox-sqlite-integration "origin/$EXPECTED_BASE"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git merge-base --is-ancestor "$EXPECTED_BASE" "$CURRENT_BRANCH" || {
    echo "ERROR: 派生元ブランチが $EXPECTED_BASE ではありません。スタック構造が壊れています。"
    exit 1
}
```

- [ ] **Step 2: 失敗テスト (RED)**

`tests/unit/storage/test_sqlite_outbox.py`:

```python
"""SQLiteStorageAdapter + OutboxWriter 統合検証 (in-memory DB)。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from context_store.config import Settings
from context_store.models.memory import Memory
from context_store.storage.sqlite import SQLiteStorageAdapter
from context_store.sync.outbox_writer import SqliteOutboxWriter


@pytest.mark.asyncio
async def test_sqlite_save_memory_writes_outbox(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SQLITE_DB_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.setenv("STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "local-model")
    settings = Settings()
    adp = await SQLiteStorageAdapter.create(settings)
    adp._outbox_writer = SqliteOutboxWriter()  # type: ignore[attr-defined]

    mem = Memory(
        id="44444444-4444-4444-4444-444444444444",
        content="hi", memory_type="FACT", source_type="USER",
        source_metadata={}, embedding=[0.1] * 768,
        semantic_relevance=0.5, importance_score=0.5, tags=["t"], project="p",
        content_hash="h", created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    await adp.save_memory(mem)

    # 直接 SQLite を覗いて outbox レコードを確認
    import aiosqlite
    async with aiosqlite.connect(str(tmp_path / "db.sqlite")) as conn:
        async with conn.execute(
            "SELECT event_type, memory_id FROM graph_sync_outbox WHERE memory_id = ?",
            (mem.id,),
        ) as cur:
            row = await cur.fetchone()
            assert row == ("SYNC_MEMORY", mem.id)
    await adp.dispose()
```

- [ ] **Step 3: テスト実行 (RED)**

```bash
uv run pytest tests/unit/storage/test_sqlite_outbox.py -v
```

Expected: FAIL

- [ ] **Step 4: 実装 (GREEN)**

`src/context_store/storage/sqlite.py` で:
1. `__init__` か `create()` に `outbox_writer` を受け入れ、属性 `self._outbox_writer: OutboxWriter | None = None`
2. `save_memory` の BEGIN/COMMIT ブロック内で `await self._outbox_writer.enqueue_sync(conn=conn, memory_id=..., event_type="SYNC_MEMORY")` 追加
3. `delete_memory` で削除前に `memory_type/tags/project` を SELECT、削除後 outbox に DELETE イベント

- [ ] **Step 5: テスト実行 (GREEN)**

```bash
uv run pytest tests/unit/storage/test_sqlite_outbox.py -v
uv run pytest tests/unit/test_sqlite_storage.py -v  # regression
```

Expected: PASS

- [ ] **Step 6-7: コミット + Draft PR (派生元: `feat/outbox-writer`)**

---

## Task 3.3: SupabaseStorageAdapter RPC 切替

- **派生元ブランチ:** `feat/outbox-supabase-migrations`
- **実行モード:** 直列必須（Wait for Task 1.3 Draft PR）
- **前提条件:** Task 1.3 の Draft PR URL が存在
- **作成ブランチ:** `feat/outbox-supabase-integration`

**Files:**
- Modify: `src/context_store/storage/supabase.py`
- Create: `tests/unit/storage/test_supabase_outbox.py`

- [ ] **Step 1: ブランチ作成と派生元検証**

```bash
EXPECTED_BASE="feat/outbox-supabase-migrations"
git fetch origin "$EXPECTED_BASE"
git checkout -b feat/outbox-supabase-integration "origin/$EXPECTED_BASE"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git merge-base --is-ancestor "$EXPECTED_BASE" "$CURRENT_BRANCH" || {
    echo "ERROR: 派生元ブランチが $EXPECTED_BASE ではありません。スタック構造が壊れています。"
    exit 1
}
```

- [ ] **Step 2: 失敗テスト (RED)**

`tests/unit/storage/test_supabase_outbox.py`:

```python
"""SupabaseStorageAdapter の RPC 切替検証。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_supabase_save_memory_uses_rpc_when_outbox_enabled() -> None:
    from context_store.storage.supabase import SupabaseStorageAdapter

    adp = SupabaseStorageAdapter.__new__(SupabaseStorageAdapter)
    adp._outbox_enabled = True  # type: ignore[attr-defined]

    fake_rpc = MagicMock()
    fake_rpc.execute = AsyncMock(return_value=MagicMock(data="55555555-5555-5555-5555-555555555555"))
    fake_client = MagicMock()
    fake_client.rpc = MagicMock(return_value=fake_rpc)
    adp._client = fake_client  # type: ignore[attr-defined]

    from context_store.models.memory import Memory
    from datetime import datetime, timezone
    mem = Memory(
        id="55555555-5555-5555-5555-555555555555",
        content="hi", memory_type="FACT", source_type="USER",
        source_metadata={}, embedding=[0.1] * 768,
        semantic_relevance=0.5, importance_score=0.5, tags=[], project="p",
        content_hash="h", created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    await adp.save_memory(mem)

    fake_client.rpc.assert_called_with("upsert_memory_with_outbox", pytest.approx_or_any_dict())  # 緩い検証
    # 厳密には呼出引数の最初が "upsert_memory_with_outbox" かを直接 assert
    assert fake_client.rpc.call_args.args[0] == "upsert_memory_with_outbox"


@pytest.mark.asyncio
async def test_supabase_delete_memory_uses_rpc_when_outbox_enabled() -> None:
    # 同様に delete_memory_with_outbox の呼び出しを検証
    pass  # 実装時展開
```

- [ ] **Step 3: テスト実行 (RED)**

```bash
uv run pytest tests/unit/storage/test_supabase_outbox.py -v
```

Expected: FAIL

- [ ] **Step 4: 実装 (GREEN)**

`src/context_store/storage/supabase.py` に `_outbox_enabled: bool` フィールドを追加。`save_memory` を以下のように分岐:

```python
    async def save_memory(self, memory: Memory) -> str:
        if self._outbox_enabled:
            result = await self._client.rpc(
                "upsert_memory_with_outbox",
                {
                    "p_id": memory.id,
                    "p_content": memory.content,
                    "p_memory_type": memory.memory_type,
                    "p_source_type": memory.source_type,
                    "p_source_metadata": memory.source_metadata or {},
                    "p_embedding": memory.embedding,
                    "p_semantic_relevance": memory.semantic_relevance,
                    "p_importance_score": memory.importance_score,
                    "p_tags": list(memory.tags or []),
                    "p_project": memory.project,
                    "p_content_hash": memory.content_hash,
                },
            ).execute()
            return result.data
        # 既存の PostgREST INSERT ロジック
        ...
```

`delete_memory` も同様に `delete_memory_with_outbox` を呼び出す分岐を追加。

- [ ] **Step 5: テスト実行 (GREEN)**

```bash
uv run pytest tests/unit/storage/test_supabase_outbox.py -v
uv run pytest tests/unit -k "supabase" -v  # regression
```

Expected: PASS

- [ ] **Step 6-7: コミット + Draft PR (派生元: `feat/outbox-supabase-migrations`)**

---

# Phase 4: Worker

## Task 4.1: OutboxReader Protocol + 各バックエンド実装

- **派生元ブランチ:** `feat/outbox-storage-migrations`
- **実行モード:** 直列必須（Wait for Task 1.2 Draft PR、Supabase RPC を呼ぶため Task 1.3 もマージ済みであることが望ましいが Python 側はモック可）
- **前提条件:** Task 1.2 の Draft PR URL が存在。`SupabaseOutboxReader` の実環境動作には Task 1.3 で導入する RPC (`fetch_pending_outbox` / `reset_stuck_processing_outbox`) が必要 — Phase 5 の結線時にマージ済みであることを確認する
- **作成ブランチ:** `feat/outbox-reader`
- **本 Task で実装する成果物（Storage バックエンドごと）:**
  - `OutboxReader` Protocol（共通インタフェース）
  - `SqliteOutboxReader`（aiosqlite ベース）
  - `PostgresOutboxReader`（asyncpg + `FOR UPDATE SKIP LOCKED`）
  - `SupabaseOutboxReader`（supabase-py + RPC `fetch_pending_outbox` / `reset_stuck_processing_outbox`）

  → Phase 5 の `factory.py` から `from context_store.sync.outbox_reader import SupabaseOutboxReader` で import される前提なので、本 Task で必ず3実装すべて含めること。

**Files:**
- Create: `src/context_store/sync/outbox_reader.py`（上記4成果物を1ファイルに集約）
- Create: `tests/unit/sync/test_outbox_reader.py`（SQLite 実装の通常テスト + Supabase 実装の RPC スモークテスト）

- [ ] **Step 1: ブランチ作成と派生元検証**

```bash
EXPECTED_BASE="feat/outbox-storage-migrations"
git fetch origin "$EXPECTED_BASE"
git checkout -b feat/outbox-reader "origin/$EXPECTED_BASE"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git merge-base --is-ancestor "$EXPECTED_BASE" "$CURRENT_BRANCH" || {
    echo "ERROR: 派生元ブランチが $EXPECTED_BASE ではありません。スタック構造が壊れています。"
    exit 1
}
```

- [ ] **Step 2: 失敗テスト (RED)**

`tests/unit/sync/test_outbox_reader.py`:

```python
"""OutboxReader: SQLite 実装の fetch/mark/reset 動作検証。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import aiosqlite
import pytest


@pytest.fixture
async def sqlite_db(tmp_path):
    db_path = tmp_path / "outbox.db"
    async with aiosqlite.connect(str(db_path)) as conn:
        from context_store.storage.migrations.runner import MigrationRunner
        await MigrationRunner("sqlite", conn).run()
    yield str(db_path)


@pytest.mark.asyncio
async def test_fetch_pending_returns_only_due_events(sqlite_db) -> None:
    """next_retry_at が未来の PENDING は返さない。"""
    from context_store.sync.outbox_reader import SqliteOutboxReader

    # past + future の 2 件を作成
    async with aiosqlite.connect(sqlite_db) as conn:
        await conn.execute(
            "INSERT INTO graph_sync_outbox (id, event_type, memory_id, status, next_retry_at) "
            "VALUES (?, 'SYNC_MEMORY', ?, 'PENDING', '2000-01-01T00:00:00Z')",
            (str(uuid.uuid4()), "m1"),
        )
        await conn.execute(
            "INSERT INTO graph_sync_outbox (id, event_type, memory_id, status, next_retry_at) "
            "VALUES (?, 'SYNC_MEMORY', ?, 'PENDING', '9999-01-01T00:00:00Z')",
            (str(uuid.uuid4()), "m2"),
        )
        await conn.commit()

    reader = SqliteOutboxReader(db_path=sqlite_db)
    events = await reader.fetch_pending(limit=10)

    assert len(events) == 1
    assert events[0].memory_id == "m1"


@pytest.mark.asyncio
async def test_fetch_pending_marks_processing(sqlite_db) -> None:
    """fetch_pending は対象を PROCESSING に遷移させる。"""
    from context_store.sync.outbox_reader import SqliteOutboxReader

    async with aiosqlite.connect(sqlite_db) as conn:
        await conn.execute(
            "INSERT INTO graph_sync_outbox (id, event_type, memory_id, status, next_retry_at) "
            "VALUES (?, 'SYNC_MEMORY', ?, 'PENDING', '2000-01-01T00:00:00Z')",
            (str(uuid.uuid4()), "m1"),
        )
        await conn.commit()

    reader = SqliteOutboxReader(db_path=sqlite_db)
    await reader.fetch_pending(limit=10)

    async with aiosqlite.connect(sqlite_db) as conn:
        async with conn.execute(
            "SELECT status FROM graph_sync_outbox WHERE memory_id = 'm1'"
        ) as cur:
            row = await cur.fetchone()
            assert row[0] == "PROCESSING"


@pytest.mark.asyncio
async def test_reset_stuck_processing_resets_to_pending_below_max_retries(sqlite_db) -> None:
    from context_store.sync.outbox_reader import SqliteOutboxReader

    eid = str(uuid.uuid4())
    async with aiosqlite.connect(sqlite_db) as conn:
        await conn.execute(
            "INSERT INTO graph_sync_outbox (id, event_type, memory_id, status, retry_count, "
            "updated_at, next_retry_at) "
            "VALUES (?, 'SYNC_MEMORY', 'm', 'PROCESSING', 3, '2000-01-01T00:00:00Z', "
            "'2000-01-01T00:00:00Z')",
            (eid,),
        )
        await conn.commit()

    reader = SqliteOutboxReader(db_path=sqlite_db)
    recovered = await reader.reset_stuck_processing(threshold_seconds=60, max_retries=10)
    assert recovered == 1

    async with aiosqlite.connect(sqlite_db) as conn:
        async with conn.execute(
            "SELECT status, retry_count FROM graph_sync_outbox WHERE id = ?", (eid,)
        ) as cur:
            row = await cur.fetchone()
            assert row == ("PENDING", 4)


@pytest.mark.asyncio
async def test_reset_stuck_processing_marks_failed_at_max_retries(sqlite_db) -> None:
    from context_store.sync.outbox_reader import SqliteOutboxReader

    eid = str(uuid.uuid4())
    async with aiosqlite.connect(sqlite_db) as conn:
        await conn.execute(
            "INSERT INTO graph_sync_outbox (id, event_type, memory_id, status, retry_count, "
            "updated_at, next_retry_at) "
            "VALUES (?, 'SYNC_MEMORY', 'm', 'PROCESSING', 10, '2000-01-01T00:00:00Z', "
            "'2000-01-01T00:00:00Z')",
            (eid,),
        )
        await conn.commit()

    reader = SqliteOutboxReader(db_path=sqlite_db)
    recovered = await reader.reset_stuck_processing(threshold_seconds=60, max_retries=10)
    assert recovered == 1

    async with aiosqlite.connect(sqlite_db) as conn:
        async with conn.execute(
            "SELECT status FROM graph_sync_outbox WHERE id = ?", (eid,)
        ) as cur:
            row = await cur.fetchone()
            assert row[0] == "FAILED"
```

- [ ] **Step 3: テスト実行 (RED)**

```bash
uv run pytest tests/unit/sync/test_outbox_reader.py -v
```

Expected: FAIL

- [ ] **Step 4: 実装 (GREEN)**

`src/context_store/sync/outbox_reader.py`:

```python
"""OutboxReader: graph_sync_outbox の読み取り/状態遷移操作。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

import aiosqlite

from context_store.sync.models import EventStatus, OutboxEvent


class OutboxReader(Protocol):
    async def fetch_pending(self, limit: int) -> list[OutboxEvent]: ...
    async def delete_completed(self, event_ids: list[str]) -> None: ...
    async def mark_failed(self, event_id: str, error_message: str) -> None: ...
    async def reset_to_pending(
        self, event_id: str, retry_count: int, next_retry_at: datetime, error_message: str
    ) -> None: ...
    async def fetch_all_actionable(self) -> list[OutboxEvent]: ...
    async def reset_stuck_processing(
        self, threshold_seconds: int = 300, max_retries: int = 10
    ) -> int: ...


class SqliteOutboxReader:
    """SQLite バックエンド向け OutboxReader 実装。"""

    def __init__(self, *, db_path: str) -> None:
        self._db_path = db_path

    async def fetch_pending(self, limit: int) -> list[OutboxEvent]:
        async with aiosqlite.connect(self._db_path) as conn:
            conn.row_factory = aiosqlite.Row
            await conn.execute("BEGIN")
            try:
                rows = await (await conn.execute(
                    "SELECT id, event_type, memory_id, payload, retry_count, "
                    "next_retry_at, created_at, updated_at, error_message "
                    "FROM graph_sync_outbox "
                    "WHERE status = 'PENDING' "
                    "AND next_retry_at <= strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                    "ORDER BY next_retry_at ASC LIMIT ?",
                    (limit,),
                )).fetchall()
                ids = [r["id"] for r in rows]
                for eid in ids:
                    await conn.execute(
                        "UPDATE graph_sync_outbox "
                        "SET status = 'PROCESSING', "
                        "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                        "WHERE id = ? AND status = 'PENDING'",
                        (eid,),
                    )
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise
        # fetch_pending 直後はすべて PROCESSING に遷移済み
        return [_row_to_event(r, status="PROCESSING") for r in rows]

    async def delete_completed(self, event_ids: list[str]) -> None:
        if not event_ids:
            return
        async with aiosqlite.connect(self._db_path) as conn:
            for eid in event_ids:
                await conn.execute("DELETE FROM graph_sync_outbox WHERE id = ?", (eid,))
            await conn.commit()

    async def mark_failed(self, event_id: str, error_message: str) -> None:
        async with aiosqlite.connect(self._db_path) as conn:
            await conn.execute(
                "UPDATE graph_sync_outbox "
                "SET status = 'FAILED', error_message = ?, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE id = ?",
                (error_message, event_id),
            )
            await conn.commit()

    async def reset_to_pending(
        self, event_id: str, retry_count: int,
        next_retry_at: datetime, error_message: str,
    ) -> None:
        async with aiosqlite.connect(self._db_path) as conn:
            await conn.execute(
                "UPDATE graph_sync_outbox SET status = 'PENDING', retry_count = ?, "
                "next_retry_at = ?, error_message = ?, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE id = ?",
                (retry_count, next_retry_at.isoformat(), error_message, event_id),
            )
            await conn.commit()

    async def fetch_all_actionable(self) -> list[OutboxEvent]:
        async with aiosqlite.connect(self._db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(
                "SELECT id, event_type, memory_id, payload, status, retry_count, "
                "next_retry_at, created_at, updated_at, error_message "
                "FROM graph_sync_outbox "
                "WHERE status IN ('PENDING', 'PROCESSING', 'FAILED')"
            ) as cur:
                rows = await cur.fetchall()
        return [_row_to_event(r, status=r["status"]) for r in rows]

    async def reset_stuck_processing(
        self, threshold_seconds: int = 300, max_retries: int = 10
    ) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=threshold_seconds)).isoformat()
        async with aiosqlite.connect(self._db_path) as conn:
            conn.row_factory = aiosqlite.Row
            await conn.execute("BEGIN")
            try:
                rows = await (await conn.execute(
                    "SELECT id, retry_count FROM graph_sync_outbox "
                    "WHERE status = 'PROCESSING' AND updated_at <= ?",
                    (cutoff,),
                )).fetchall()
                count = 0
                for r in rows:
                    new_retry = r["retry_count"] + 1
                    if new_retry > max_retries:
                        await conn.execute(
                            "UPDATE graph_sync_outbox SET status = 'FAILED', "
                            "error_message = 'Recovered from stuck PROCESSING (max retries)', "
                            "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
                            (r["id"],),
                        )
                    else:
                        await conn.execute(
                            "UPDATE graph_sync_outbox SET status = 'PENDING', "
                            "retry_count = ?, "
                            "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                            "WHERE id = ?",
                            (new_retry, r["id"]),
                        )
                    count += 1
                await conn.commit()
                return count
            except Exception:
                await conn.rollback()
                raise


def _row_to_event(row: Any, *, status: EventStatus) -> OutboxEvent:
    """SQLite Row → OutboxEvent。status は呼び出し側のコンテキストで決定する。

    - `fetch_pending`: UPDATE 直後なので明示的に "PROCESSING" を渡す
    - `fetch_all_actionable`: 行の status カラムをそのまま渡す
    """
    return OutboxEvent(
        id=row["id"],
        event_type=row["event_type"],
        memory_id=row["memory_id"],
        payload=json.loads(row["payload"]) if row["payload"] else {},
        status=status,
        retry_count=row["retry_count"],
        next_retry_at=_parse_dt(row["next_retry_at"]),
        error_message=row["error_message"],
        created_at=_parse_dt(row["created_at"]),
        updated_at=_parse_dt(row["updated_at"]),
    )


def _parse_dt(s: str | None) -> datetime:
    if not s:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


# --- PostgresOutboxReader ---
# (asyncpg ベースで類似実装。fetch_pending は FOR UPDATE SKIP LOCKED を用いる)
class PostgresOutboxReader:
    """PostgreSQL バックエンド向け OutboxReader 実装。

    `FOR UPDATE SKIP LOCKED` で水平スケール時の競合を回避する。
    """

    _FETCH_SQL = """
    UPDATE graph_sync_outbox
    SET status = 'PROCESSING', updated_at = NOW()
    WHERE id IN (
        SELECT id FROM graph_sync_outbox
        WHERE status = 'PENDING' AND next_retry_at <= NOW()
        ORDER BY next_retry_at ASC
        LIMIT $1
        FOR UPDATE SKIP LOCKED
    )
    RETURNING id, event_type, memory_id::text AS memory_id, payload, retry_count,
              next_retry_at, created_at, updated_at, error_message
    """

    def __init__(self, *, pool: Any) -> None:
        self._pool = pool

    async def fetch_pending(self, limit: int) -> list[OutboxEvent]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(self._FETCH_SQL, limit)
        return [
            OutboxEvent(
                id=str(r["id"]),
                event_type=r["event_type"],
                memory_id=r["memory_id"],
                payload=dict(r["payload"]) if r["payload"] else {},
                status="PROCESSING",
                retry_count=r["retry_count"],
                next_retry_at=r["next_retry_at"],
                error_message=r["error_message"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
            for r in rows
        ]

    async def delete_completed(self, event_ids: list[str]) -> None:
        if not event_ids:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM graph_sync_outbox WHERE id = ANY($1::uuid[])", event_ids
            )

    async def mark_failed(self, event_id: str, error_message: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE graph_sync_outbox SET status='FAILED', error_message=$2, "
                "updated_at=NOW() WHERE id=$1::uuid",
                event_id, error_message,
            )

    async def reset_to_pending(
        self, event_id: str, retry_count: int,
        next_retry_at: datetime, error_message: str,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE graph_sync_outbox SET status='PENDING', retry_count=$2, "
                "next_retry_at=$3, error_message=$4, updated_at=NOW() WHERE id=$1::uuid",
                event_id, retry_count, next_retry_at, error_message,
            )

    async def fetch_all_actionable(self) -> list[OutboxEvent]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, event_type, memory_id::text AS memory_id, payload, status, "
                "retry_count, next_retry_at, created_at, updated_at, error_message "
                "FROM graph_sync_outbox WHERE status IN ('PENDING','PROCESSING','FAILED')"
            )
        return [
            OutboxEvent(
                id=str(r["id"]), event_type=r["event_type"], memory_id=r["memory_id"],
                payload=dict(r["payload"]) if r["payload"] else {},
                status=r["status"],
                retry_count=r["retry_count"], next_retry_at=r["next_retry_at"],
                error_message=r["error_message"], created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
            for r in rows
        ]

    async def reset_stuck_processing(
        self, threshold_seconds: int = 300, max_retries: int = 10
    ) -> int:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                # max_retries 超過は FAILED 化
                failed = await conn.execute(
                    "UPDATE graph_sync_outbox "
                    "SET status='FAILED', error_message='Recovered from stuck PROCESSING (max retries)', "
                    "updated_at=NOW() "
                    "WHERE status='PROCESSING' "
                    "AND updated_at < NOW() - ($1 || ' seconds')::interval "
                    "AND retry_count + 1 > $2",
                    str(threshold_seconds), max_retries,
                )
                # それ以外は PENDING にリセット
                pending = await conn.execute(
                    "UPDATE graph_sync_outbox "
                    "SET status='PENDING', retry_count = retry_count + 1, updated_at=NOW() "
                    "WHERE status='PROCESSING' "
                    "AND updated_at < NOW() - ($1 || ' seconds')::interval",
                    str(threshold_seconds),
                )
        # asyncpg の execute は "UPDATE n" を返す
        def _count(tag: str) -> int:
            parts = tag.split()
            return int(parts[-1]) if parts and parts[-1].isdigit() else 0
        return _count(failed) + _count(pending)


# --- SupabaseOutboxReader ---
# Supabase は asyncpg を直接使えないため、状態遷移を伴う操作は RPC
# (Task 1.3 で定義した fetch_pending_outbox / reset_stuck_processing_outbox)
# を呼び、それ以外は supabase-py の table API で実装する。
class SupabaseOutboxReader:
    """Supabase バックエンド向け OutboxReader 実装。"""

    def __init__(self, *, client: Any) -> None:
        self._client = client

    async def fetch_pending(self, limit: int) -> list[OutboxEvent]:
        result = await self._client.rpc(
            "fetch_pending_outbox", {"p_limit": limit}
        ).execute()
        rows = result.data or []
        return [_supabase_row_to_event(r) for r in rows]

    async def delete_completed(self, event_ids: list[str]) -> None:
        if not event_ids:
            return
        await (
            self._client.table("graph_sync_outbox")
            .delete()
            .in_("id", event_ids)
            .execute()
        )

    async def mark_failed(self, event_id: str, error_message: str) -> None:
        await (
            self._client.table("graph_sync_outbox")
            .update({"status": "FAILED", "error_message": error_message})
            .eq("id", event_id)
            .execute()
        )

    async def reset_to_pending(
        self, event_id: str, retry_count: int,
        next_retry_at: datetime, error_message: str,
    ) -> None:
        await (
            self._client.table("graph_sync_outbox")
            .update(
                {
                    "status": "PENDING",
                    "retry_count": retry_count,
                    "next_retry_at": next_retry_at.isoformat(),
                    "error_message": error_message,
                }
            )
            .eq("id", event_id)
            .execute()
        )

    async def fetch_all_actionable(self) -> list[OutboxEvent]:
        result = await (
            self._client.table("graph_sync_outbox")
            .select(
                "id,event_type,memory_id,payload,status,retry_count,"
                "next_retry_at,created_at,updated_at,error_message"
            )
            .in_("status", ["PENDING", "PROCESSING", "FAILED"])
            .execute()
        )
        rows = result.data or []
        return [_supabase_row_to_event(r) for r in rows]

    async def reset_stuck_processing(
        self, threshold_seconds: int = 300, max_retries: int = 10
    ) -> int:
        result = await self._client.rpc(
            "reset_stuck_processing_outbox",
            {
                "p_threshold_seconds": threshold_seconds,
                "p_max_retries": max_retries,
            },
        ).execute()
        return int(result.data) if result.data is not None else 0


def _supabase_row_to_event(row: dict[str, Any]) -> OutboxEvent:
    """Supabase REST レスポンス (dict) → OutboxEvent。"""
    payload_raw = row.get("payload") or {}
    return OutboxEvent(
        id=row["id"],
        event_type=row["event_type"],
        memory_id=row["memory_id"],
        payload=payload_raw if isinstance(payload_raw, dict) else json.loads(payload_raw),
        status=row["status"],
        retry_count=row["retry_count"],
        next_retry_at=_parse_dt(row.get("next_retry_at")),
        error_message=row.get("error_message"),
        created_at=_parse_dt(row.get("created_at")),
        updated_at=_parse_dt(row.get("updated_at")),
    )
```

- [ ] **Step 5: SupabaseOutboxReader のスモークテストを追加**

`tests/unit/sync/test_outbox_reader.py` の末尾に追加:

```python
@pytest.mark.asyncio
async def test_supabase_reader_fetch_pending_calls_rpc() -> None:
    from unittest.mock import AsyncMock, MagicMock
    from context_store.sync.outbox_reader import SupabaseOutboxReader

    fake_rpc = MagicMock()
    fake_rpc.execute = AsyncMock(return_value=MagicMock(data=[
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "event_type": "SYNC_MEMORY",
            "memory_id": "22222222-2222-2222-2222-222222222222",
            "payload": {},
            "status": "PROCESSING",
            "retry_count": 0,
            "next_retry_at": "2026-01-01T00:00:00+00:00",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "error_message": None,
        }
    ]))
    client = MagicMock()
    client.rpc = MagicMock(return_value=fake_rpc)

    reader = SupabaseOutboxReader(client=client)
    events = await reader.fetch_pending(limit=10)

    client.rpc.assert_called_with("fetch_pending_outbox", {"p_limit": 10})
    assert len(events) == 1
    assert events[0].status == "PROCESSING"


@pytest.mark.asyncio
async def test_supabase_reader_reset_stuck_processing_calls_rpc() -> None:
    from unittest.mock import AsyncMock, MagicMock
    from context_store.sync.outbox_reader import SupabaseOutboxReader

    fake_rpc = MagicMock()
    fake_rpc.execute = AsyncMock(return_value=MagicMock(data=2))
    client = MagicMock()
    client.rpc = MagicMock(return_value=fake_rpc)

    reader = SupabaseOutboxReader(client=client)
    n = await reader.reset_stuck_processing(threshold_seconds=60, max_retries=10)

    client.rpc.assert_called_with(
        "reset_stuck_processing_outbox",
        {"p_threshold_seconds": 60, "p_max_retries": 10},
    )
    assert n == 2
```

- [ ] **Step 6: テスト実行 (GREEN)**

```bash
uv run pytest tests/unit/sync/test_outbox_reader.py -v
uv run mypy src/context_store/sync/outbox_reader.py
```

Expected: PASS

- [ ] **Step 7: コミット + Draft PR (派生元: `feat/outbox-storage-migrations`)**

注: Supabase 環境で実際に動かすには Task 1.3 でマージされる `fetch_pending_outbox`
/ `reset_stuck_processing_outbox` RPC が必要。本 Task では Python 側のみを実装し、
両者は Phase 5 の Factory タスクで結線される。

---

## Task 4.2: OutboxWorker（ポーリング + リトライ + リカバリ）

- **派生元ブランチ:** `feat/outbox-graph-sync`
- **実行モード:** 直列必須（Wait for Task 2.3 Draft PR AND Task 4.1 Draft PR）
- **前提条件:** Task 2.3 と Task 4.1 の Draft PR URL が存在
- **作成ブランチ:** `feat/outbox-worker-loop`

**Files:**
- Create: `src/context_store/sync/outbox_worker.py`
- Create: `tests/unit/sync/test_outbox_worker.py`

- [ ] **Step 1: ブランチ作成と派生元検証**

```bash
EXPECTED_BASE="feat/outbox-graph-sync"
git fetch origin "$EXPECTED_BASE"
git checkout -b feat/outbox-worker-loop "origin/$EXPECTED_BASE"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git merge-base --is-ancestor "$EXPECTED_BASE" "$CURRENT_BRANCH" || {
    echo "ERROR: 派生元ブランチが $EXPECTED_BASE ではありません。スタック構造が壊れています。"
    exit 1
}
# Task 4.1 (OutboxReader) も必須なので fetch でマージ済みかを確認
git fetch origin feat/outbox-reader
git merge --no-edit --no-commit origin/feat/outbox-reader || {
    echo "ERROR: feat/outbox-reader をマージできません。Task 4.1 完了確認後に再試行。"
    exit 1
}
git commit -m "merge: feat/outbox-reader into worker branch"
```

- [ ] **Step 2: 失敗テスト (RED)**

`tests/unit/sync/test_outbox_worker.py`:

```python
"""OutboxWorker: ポーリングループ・リトライ・Backoff・リカバリ検証。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from context_store.sync.models import OutboxEvent


def _evt(event_type="SYNC_MEMORY", retry_count=0) -> OutboxEvent:
    now = datetime.now(timezone.utc)
    return OutboxEvent(
        id="e1", event_type=event_type, memory_id="m1", payload={},
        status="PROCESSING", retry_count=retry_count, next_retry_at=now,
        error_message=None, created_at=now, updated_at=now,
    )


@pytest.mark.asyncio
async def test_worker_processes_pending_events_then_deletes() -> None:
    from context_store.sync.outbox_worker import OutboxWorker

    reader = MagicMock()
    reader.reset_stuck_processing = AsyncMock(return_value=0)
    reader.fetch_pending = AsyncMock(side_effect=[[_evt()], []])
    reader.delete_completed = AsyncMock()

    storage = MagicMock()
    storage.get_memories_batch = AsyncMock(return_value=[MagicMock(id="m1")])
    graph_sync = MagicMock()
    graph_sync.bulk_merge_memories = AsyncMock(return_value=1)

    settings = MagicMock(
        outbox_poll_interval_seconds=0.01,
        outbox_batch_size=10, outbox_max_retries=5,
        outbox_backoff_base_seconds=0.1, outbox_backoff_max_seconds=1.0,
    )
    worker = OutboxWorker(
        reader=reader, storage_adapter=storage, graph_sync=graph_sync, settings=settings,
    )

    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.05)
    await worker.stop()
    await task

    graph_sync.bulk_merge_memories.assert_awaited()
    reader.delete_completed.assert_awaited_with(["e1"])


@pytest.mark.asyncio
async def test_worker_retries_on_neo4j_failure_with_backoff() -> None:
    from context_store.sync.outbox_worker import OutboxWorker

    reader = MagicMock()
    reader.reset_stuck_processing = AsyncMock(return_value=0)
    reader.fetch_pending = AsyncMock(side_effect=[[_evt(retry_count=2)], []])
    reader.reset_to_pending = AsyncMock()

    storage = MagicMock()
    storage.get_memories_batch = AsyncMock(return_value=[MagicMock(id="m1")])
    graph_sync = MagicMock()
    graph_sync.bulk_merge_memories = AsyncMock(side_effect=RuntimeError("neo4j down"))

    settings = MagicMock(
        outbox_poll_interval_seconds=0.01,
        outbox_batch_size=10, outbox_max_retries=5,
        outbox_backoff_base_seconds=1.0, outbox_backoff_max_seconds=10.0,
    )
    worker = OutboxWorker(
        reader=reader, storage_adapter=storage, graph_sync=graph_sync, settings=settings,
    )
    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.05)
    await worker.stop()
    await task

    reader.reset_to_pending.assert_awaited_once()
    call = reader.reset_to_pending.await_args
    # retry_count = 2 -> 3
    assert call.kwargs["retry_count"] == 3
    # backoff: min(1 * 2^3, 10) = 8 秒 (今+8s 程度)
    delta = (call.kwargs["next_retry_at"] - datetime.now(timezone.utc)).total_seconds()
    assert 6 < delta <= 9


@pytest.mark.asyncio
async def test_worker_marks_failed_after_max_retries() -> None:
    from context_store.sync.outbox_worker import OutboxWorker

    reader = MagicMock()
    reader.reset_stuck_processing = AsyncMock(return_value=0)
    reader.fetch_pending = AsyncMock(side_effect=[[_evt(retry_count=5)], []])
    reader.mark_failed = AsyncMock()

    storage = MagicMock()
    storage.get_memories_batch = AsyncMock(return_value=[MagicMock(id="m1")])
    graph_sync = MagicMock()
    graph_sync.bulk_merge_memories = AsyncMock(side_effect=RuntimeError("neo4j down"))

    settings = MagicMock(
        outbox_poll_interval_seconds=0.01,
        outbox_batch_size=10, outbox_max_retries=5,
        outbox_backoff_base_seconds=1.0, outbox_backoff_max_seconds=10.0,
    )
    worker = OutboxWorker(
        reader=reader, storage_adapter=storage, graph_sync=graph_sync, settings=settings,
    )
    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.05)
    await worker.stop()
    await task

    reader.mark_failed.assert_awaited_once()


@pytest.mark.asyncio
async def test_worker_recovers_stuck_processing_on_startup() -> None:
    from context_store.sync.outbox_worker import OutboxWorker

    reader = MagicMock()
    reader.reset_stuck_processing = AsyncMock(return_value=3)
    reader.fetch_pending = AsyncMock(return_value=[])

    settings = MagicMock(
        outbox_poll_interval_seconds=0.01,
        outbox_batch_size=10, outbox_max_retries=5,
        outbox_backoff_base_seconds=1.0, outbox_backoff_max_seconds=10.0,
    )
    worker = OutboxWorker(
        reader=reader, storage_adapter=MagicMock(),
        graph_sync=MagicMock(), settings=settings,
    )
    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.05)
    await worker.stop()
    await task

    reader.reset_stuck_processing.assert_awaited_once()


@pytest.mark.asyncio
async def test_worker_handles_orphaned_sync_event() -> None:
    """対象メモリが Storage に存在しない場合、イベントを削除して続行。"""
    from context_store.sync.outbox_worker import OutboxWorker

    reader = MagicMock()
    reader.reset_stuck_processing = AsyncMock(return_value=0)
    reader.fetch_pending = AsyncMock(side_effect=[[_evt()], []])
    reader.delete_completed = AsyncMock()

    storage = MagicMock()
    storage.get_memories_batch = AsyncMock(return_value=[])  # メモリが見つからない

    settings = MagicMock(
        outbox_poll_interval_seconds=0.01, outbox_batch_size=10,
        outbox_max_retries=5, outbox_backoff_base_seconds=1.0,
        outbox_backoff_max_seconds=10.0,
    )
    worker = OutboxWorker(
        reader=reader, storage_adapter=storage,
        graph_sync=MagicMock(), settings=settings,
    )
    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.05)
    await worker.stop()
    await task

    reader.delete_completed.assert_awaited_with(["e1"])


@pytest.mark.asyncio
async def test_worker_run_catchup_processes_all_actionable() -> None:
    """run_catchup は fetch_all_actionable + _process_batch を 1 回実行する。"""
    from context_store.sync.outbox_worker import OutboxWorker

    reader = MagicMock()
    reader.fetch_all_actionable = AsyncMock(return_value=[_evt(), _evt()])
    reader.delete_completed = AsyncMock()

    storage = MagicMock()
    storage.get_memories_batch = AsyncMock(return_value=[MagicMock(id="m1")])
    graph_sync = MagicMock()
    graph_sync.bulk_merge_memories = AsyncMock(return_value=1)

    settings = MagicMock(
        outbox_poll_interval_seconds=0.01, outbox_batch_size=10,
        outbox_max_retries=5, outbox_backoff_base_seconds=1.0,
        outbox_backoff_max_seconds=10.0,
    )
    worker = OutboxWorker(
        reader=reader, storage_adapter=storage,
        graph_sync=graph_sync, settings=settings,
    )
    n = await worker.run_catchup()
    assert n == 2
    reader.fetch_all_actionable.assert_awaited_once()
    graph_sync.bulk_merge_memories.assert_awaited()


@pytest.mark.asyncio
async def test_worker_run_catchup_dry_run_skips_processing() -> None:
    from context_store.sync.outbox_worker import OutboxWorker

    reader = MagicMock()
    reader.fetch_all_actionable = AsyncMock(return_value=[_evt()])

    settings = MagicMock(
        outbox_poll_interval_seconds=0.01, outbox_batch_size=10,
        outbox_max_retries=5, outbox_backoff_base_seconds=1.0,
        outbox_backoff_max_seconds=10.0,
    )
    worker = OutboxWorker(
        reader=reader, storage_adapter=MagicMock(),
        graph_sync=MagicMock(), settings=settings,
    )
    n = await worker.run_catchup(dry_run=True)
    assert n == 1
    # dry_run なので _process_batch は呼ばれない → storage / graph も叩かれない


@pytest.mark.asyncio
async def test_worker_process_pending_once_returns_event_count() -> None:
    from context_store.sync.outbox_worker import OutboxWorker

    reader = MagicMock()
    reader.fetch_pending = AsyncMock(return_value=[_evt()])
    reader.delete_completed = AsyncMock()

    storage = MagicMock()
    storage.get_memories_batch = AsyncMock(return_value=[MagicMock(id="m1")])
    graph_sync = MagicMock()
    graph_sync.bulk_merge_memories = AsyncMock(return_value=1)

    settings = MagicMock(
        outbox_poll_interval_seconds=0.01, outbox_batch_size=10,
        outbox_max_retries=5, outbox_backoff_base_seconds=1.0,
        outbox_backoff_max_seconds=10.0,
    )
    worker = OutboxWorker(
        reader=reader, storage_adapter=storage,
        graph_sync=graph_sync, settings=settings,
    )
    n = await worker.process_pending_once()
    assert n == 1
```

- [ ] **Step 3: テスト実行 (RED)**

```bash
uv run pytest tests/unit/sync/test_outbox_worker.py -v
```

Expected: FAIL

- [ ] **Step 4: 実装 (GREEN)**

`src/context_store/sync/outbox_worker.py`:

```python
"""OutboxWorker: ポーリングループ + バッチ処理 + Exponential Backoff + リカバリ。"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from context_store.config import Settings
    from context_store.storage.protocols import StorageAdapter
    from context_store.sync.graph_sync import GraphSyncService
    from context_store.sync.outbox_reader import OutboxReader

from context_store.sync.models import OutboxEvent

logger = logging.getLogger(__name__)


class OutboxWorker:
    def __init__(
        self,
        *,
        reader: "OutboxReader",
        storage_adapter: "StorageAdapter",
        graph_sync: "GraphSyncService",
        settings: "Settings",
    ) -> None:
        self._reader = reader
        self._storage = storage_adapter
        self._graph_sync = graph_sync
        self._settings = settings
        self._stop_event = asyncio.Event()

    async def run(self) -> None:
        # 起動時リカバリ
        try:
            recovered = await self._reader.reset_stuck_processing(
                threshold_seconds=300,
                max_retries=self._settings.outbox_max_retries,
            )
            if recovered:
                logger.info(
                    "OutboxWorker: recovered stuck PROCESSING events",
                    extra={"count": recovered},
                )
        except Exception as exc:
            logger.warning("OutboxWorker: reset_stuck_processing failed: %s", exc)

        # メインループ
        while not self._stop_event.is_set():
            try:
                events = await self._reader.fetch_pending(
                    limit=self._settings.outbox_batch_size
                )
                if events:
                    await self._process_batch(events)
            except Exception as exc:
                logger.exception("OutboxWorker: poll cycle failed: %s", exc)

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._settings.outbox_poll_interval_seconds,
                )
                return  # stop() が呼ばれた
            except asyncio.TimeoutError:
                continue

    async def stop(self) -> None:
        self._stop_event.set()

    async def process_pending_once(self) -> int:
        """1 サイクル分の PENDING を取得して処理する。

        Worker メインループの 1 イテレーション相当。リカバリスクリプトや
        テストから「ループを 1 回だけ回したい」場合に使う公開 API。
        戻り値: 処理した（完了 or リトライ予約された）イベント件数。
        """
        events = await self._reader.fetch_pending(
            limit=self._settings.outbox_batch_size
        )
        if not events:
            return 0
        await self._process_batch(events)
        return len(events)

    async def run_catchup(self, *, dry_run: bool = False) -> int:
        """`scripts/sync_storage_to_neo4j.py --catchup` のための公開エントリ。

        Outbox の actionable (PENDING / PROCESSING / FAILED) を 1 度だけ
        全件処理する。dry_run=True の場合は対象件数のみ返す。
        """
        events = await self._reader.fetch_all_actionable()
        if dry_run:
            logger.info(
                "Catchup dry run: would process %d events", len(events)
            )
            return len(events)
        if events:
            await self._process_batch(events)
        return len(events)

    async def _process_batch(self, events: list[OutboxEvent]) -> None:
        sync_events = [e for e in events if e.event_type == "SYNC_MEMORY"]
        del_events = [e for e in events if e.event_type == "DELETE_MEMORY"]

        completed_ids: list[str] = []

        if sync_events:
            mids = [e.memory_id for e in sync_events]
            try:
                memories = await self._storage.get_memories_batch(mids)
                # 削除済みメモリのイベントは orphan として削除する
                found_ids = {m.id for m in memories}
                orphan_ids = [e.id for e in sync_events if e.memory_id not in found_ids]
                if memories:
                    await self._graph_sync.bulk_merge_memories(memories)
                completed_ids.extend(orphan_ids)
                completed_ids.extend(
                    e.id for e in sync_events if e.memory_id in found_ids
                )
            except Exception as exc:
                await self._apply_backoff(sync_events, exc)
                # SYNC イベントが失敗したら DELETE は次サイクルへ
                return

        if del_events:
            ids = [e.memory_id for e in del_events]
            try:
                await self._graph_sync.bulk_delete_nodes(ids)
                completed_ids.extend(e.id for e in del_events)
            except Exception as exc:
                await self._apply_backoff(del_events, exc)
                return

        if completed_ids:
            await self._reader.delete_completed(completed_ids)

    async def _apply_backoff(
        self, events: list[OutboxEvent], exc: Exception
    ) -> None:
        base = self._settings.outbox_backoff_base_seconds
        max_s = self._settings.outbox_backoff_max_seconds
        max_retries = self._settings.outbox_max_retries
        for e in events:
            new_retry = e.retry_count + 1
            if new_retry > max_retries:
                await self._reader.mark_failed(e.id, str(exc))
                logger.error(
                    "OutboxWorker: event %s exceeded max retries", e.id,
                )
                continue
            backoff = min(base * (2 ** new_retry), max_s)
            next_at = datetime.now(timezone.utc) + timedelta(seconds=backoff)
            await self._reader.reset_to_pending(
                event_id=e.id,
                retry_count=new_retry,
                next_retry_at=next_at,
                error_message=str(exc),
            )
```

- [ ] **Step 5: テスト実行 (GREEN)**

```bash
uv run pytest tests/unit/sync/test_outbox_worker.py -v
uv run mypy src/context_store/sync/outbox_worker.py
```

Expected: PASS

- [ ] **Step 6-7: コミット + Draft PR (派生元: `feat/outbox-graph-sync`)**

---

# Phase 5: Orchestration

## Task 5.1: Factory ルーティングと OutboxWriter/Worker 生成

- **派生元ブランチ:** `feat/outbox-worker-loop`
- **実行モード:** 直列必須
- **前提条件:** Task 4.2 の Draft PR URL が存在 / Task 3.1 / 3.2 / 3.3 のマージ確認
- **作成ブランチ:** `feat/outbox-factory`

**Files:**
- Modify: `src/context_store/storage/factory.py`
- Modify: `tests/unit/test_storage_factory.py`

- [ ] **Step 1: ブランチ作成と派生元検証**

```bash
EXPECTED_BASE="feat/outbox-worker-loop"
git fetch origin "$EXPECTED_BASE"
git checkout -b feat/outbox-factory "origin/$EXPECTED_BASE"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git merge-base --is-ancestor "$EXPECTED_BASE" "$CURRENT_BRANCH" || {
    echo "ERROR: 派生元ブランチが $EXPECTED_BASE ではありません。スタック構造が壊れています。"
    exit 1
}
# Task 3.1, 3.2, 3.3 を取り込む（既にマージ済みなら no-op）
for branch in feat/outbox-postgres-integration feat/outbox-sqlite-integration feat/outbox-supabase-integration; do
    git fetch origin "$branch" || true
    git merge --no-edit "origin/$branch" || {
        echo "ERROR: $branch をマージできません。事前に Phase 3 完了を確認。"
        exit 1
    }
done
```

- [ ] **Step 2: 失敗テスト (RED)**

`tests/unit/test_storage_factory.py` に追加:

```python
@pytest.mark.asyncio
async def test_factory_returns_outbox_writer_when_async_outbox(monkeypatch, tmp_path) -> None:
    """async_outbox モード時、Storage に OutboxWriter が注入される。"""
    monkeypatch.setenv("STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("SQLITE_DB_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.setenv("GRAPH_ENABLED", "true")
    monkeypatch.setenv("GRAPH_SYNC_MODE", "async_outbox")
    monkeypatch.setenv("NEO4J_PASSWORD", "secret")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "local-model")

    from context_store.config import Settings
    from context_store.storage.factory import create_storage_with_outbox

    settings = Settings()
    storage, graph, cache, worker = await create_storage_with_outbox(settings)
    assert worker is not None
    assert getattr(storage, "_outbox_writer", None) is not None
    await storage.dispose()
    await graph.dispose()
    await cache.dispose()


@pytest.mark.asyncio
async def test_factory_supabase_async_outbox_returns_neo4j_graph(monkeypatch) -> None:
    """Supabase + async_outbox で Neo4j graph adapter が返る。"""
    monkeypatch.setenv("STORAGE_BACKEND", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "key")
    monkeypatch.setenv("GRAPH_ENABLED", "true")
    monkeypatch.setenv("GRAPH_SYNC_MODE", "async_outbox")
    monkeypatch.setenv("NEO4J_PASSWORD", "secret")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "local-model")
    monkeypatch.setenv("EMBEDDING_DIMENSION", "768")

    # supabase クライアントと Neo4j ドライバはモック化
    # (詳細は実装時に既存テストパターンに合わせる)
    pass
```

- [ ] **Step 3: テスト実行 (RED)**

```bash
uv run pytest tests/unit/test_storage_factory.py -v
```

Expected: FAIL

- [ ] **Step 4: 実装 (GREEN)**

`src/context_store/storage/factory.py` に以下を追加:

```python
async def create_storage_with_outbox(
    settings: "Settings",
    *,
    read_only: bool = False,
) -> tuple[
    "StorageAdapter", "GraphAdapter | None", "CacheAdapter",
    "OutboxWorker | None",
]:
    """async_outbox モード対応の Factory。Worker も生成して返す。"""
    from context_store.sync.outbox_reader import (
        PostgresOutboxReader, SqliteOutboxReader,
    )
    from context_store.sync.outbox_writer import (
        PostgresOutboxWriter, SqliteOutboxWriter,
    )
    from context_store.sync.outbox_worker import OutboxWorker
    from context_store.sync.graph_sync import GraphSyncService

    # 通常の create_storage を呼び出すが、OutboxWriter を渡せるよう修正
    storage, graph_adp, cache_adp = await create_storage(settings, read_only=read_only)

    if settings.graph_sync_mode != "async_outbox":
        return storage, graph_adp, cache_adp, None

    if graph_adp is None:
        raise ValueError("async_outbox requires graph_enabled=true")

    # Writer/Reader を Storage backend ごとに生成
    if settings.storage_backend == "sqlite":
        import os
        db_path = os.path.expanduser(settings.sqlite_db_path)
        storage._outbox_writer = SqliteOutboxWriter()  # type: ignore[attr-defined]
        reader = SqliteOutboxReader(db_path=db_path)
    elif settings.storage_backend == "postgres":
        storage._outbox_writer = PostgresOutboxWriter()  # type: ignore[attr-defined]
        reader = PostgresOutboxReader(pool=storage._pool)  # type: ignore[attr-defined]
    elif settings.storage_backend == "supabase":
        storage._outbox_enabled = True  # type: ignore[attr-defined]
        # Supabase は asyncpg を直接使えないため、Task 1.3 で定義した RPC を
        # 呼び出す SupabaseOutboxReader を使用する（Python 実装は Task 4.1
        # の `outbox_reader.py` 内で SqliteOutboxReader / PostgresOutboxReader
        # と並んで提供される）。
        from context_store.sync.outbox_reader import SupabaseOutboxReader
        reader = SupabaseOutboxReader(client=storage._client)  # type: ignore[attr-defined]
    else:
        raise ValueError(f"Unsupported backend for outbox: {settings.storage_backend}")

    graph_sync = GraphSyncService(graph_adapter=graph_adp, storage_adapter=storage)
    worker = OutboxWorker(
        reader=reader, storage_adapter=storage,
        graph_sync=graph_sync, settings=settings,
    )
    return storage, graph_adp, cache_adp, worker
```

また `_create_graph_adapter` の Supabase 分岐を更新:

```python
    if settings.storage_backend == "supabase":
        if settings.graph_sync_mode != "async_outbox":
            raise ValueError(
                "Supabase + graph requires graph_sync_mode='async_outbox'"
            )
        from context_store.storage.neo4j import Neo4jGraphAdapter
        return await Neo4jGraphAdapter.create(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
            read_only=read_only,
        )
```

注: `SupabaseOutboxReader` の Python 実装は Task 4.1 で完了済み。本 Task は
Factory ルーティングで結線するのみで、追加実装は不要。

- [ ] **Step 5: テスト実行 (GREEN)**

```bash
uv run pytest tests/unit/test_storage_factory.py -v
uv run mypy src/context_store/storage/factory.py
```

Expected: PASS

- [ ] **Step 6-7: コミット + Draft PR (派生元: `feat/outbox-worker-loop`)**

---

## Task 5.2: Orchestrator Worker ライフサイクル

- **派生元ブランチ:** `feat/outbox-factory`
- **実行モード:** 直列必須
- **前提条件:** Task 5.1 の Draft PR URL が存在
- **作成ブランチ:** `feat/outbox-orchestrator`

**Files:**
- Modify: `src/context_store/orchestrator.py`
- Modify: `tests/unit/test_orchestrator.py`

- [ ] **Step 1: ブランチ作成と派生元検証**

```bash
EXPECTED_BASE="feat/outbox-factory"
git fetch origin "$EXPECTED_BASE"
git checkout -b feat/outbox-orchestrator "origin/$EXPECTED_BASE"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git merge-base --is-ancestor "$EXPECTED_BASE" "$CURRENT_BRANCH" || {
    echo "ERROR: 派生元ブランチが $EXPECTED_BASE ではありません。スタック構造が壊れています。"
    exit 1
}
```

- [ ] **Step 2: 失敗テスト (RED)**

`tests/unit/test_orchestrator.py` に追加:

```python
@pytest.mark.asyncio
async def test_orchestrator_starts_outbox_worker_in_async_mode(monkeypatch, tmp_path) -> None:
    """async_outbox 設定で Orchestrator.create() 時に Worker タスクが起動する。"""
    # ... 設定 ...
    from context_store.orchestrator import create_orchestrator
    orch = await create_orchestrator(settings)
    assert orch._outbox_worker_task is not None
    assert not orch._outbox_worker_task.done()
    await orch.dispose()
    assert orch._outbox_worker_task.done()


@pytest.mark.asyncio
async def test_orchestrator_skips_worker_in_sync_mode(monkeypatch) -> None:
    """sync モードでは Worker は起動しない。"""
    pass  # 実装時展開
```

- [ ] **Step 3: テスト実行 (RED)**

```bash
uv run pytest tests/unit/test_orchestrator.py -v -k outbox
```

Expected: FAIL

- [ ] **Step 4: 実装 (GREEN)**

`src/context_store/orchestrator.py`:

```python
class Orchestrator:
    def __init__(self, ..., outbox_worker: "OutboxWorker | None" = None) -> None:
        ...
        self._outbox_worker: "OutboxWorker | None" = outbox_worker
        self._outbox_worker_task: asyncio.Task | None = None

    async def start_lifecycle(self) -> None:
        # ... 既存処理 ...
        if self._outbox_worker is not None:
            self._outbox_worker_task = asyncio.create_task(
                self._outbox_worker.run(), name="outbox-worker"
            )

    async def dispose(self) -> None:
        if self._outbox_worker is not None and self._outbox_worker_task is not None:
            await self._outbox_worker.stop()
            try:
                await asyncio.wait_for(self._outbox_worker_task, timeout=10)
            except asyncio.TimeoutError:
                self._outbox_worker_task.cancel()
        # ... 既存処理 ...
```

`create_orchestrator()` で `create_storage_with_outbox` を呼ぶように変更し、worker を Orchestrator に渡す。

- [ ] **Step 5: テスト実行 (GREEN)**

```bash
uv run pytest tests/unit/test_orchestrator.py -v
uv run mypy src/context_store/orchestrator.py
```

Expected: PASS

- [ ] **Step 6-7: コミット + Draft PR (派生元: `feat/outbox-factory`)**

---

## Task 5.3: IngestionPipeline の GraphLinker 制御

- **派生元ブランチ:** `feat/outbox-orchestrator`
- **実行モード:** 直列必須
- **前提条件:** Task 5.2 の Draft PR URL が存在
- **作成ブランチ:** `feat/outbox-pipeline`

**Files:**
- Modify: `src/context_store/ingestion/pipeline.py`
- Modify: `tests/unit/test_ingestion_pipeline.py`

- [ ] **Step 1: ブランチ作成と派生元検証**

```bash
EXPECTED_BASE="feat/outbox-orchestrator"
git fetch origin "$EXPECTED_BASE"
git checkout -b feat/outbox-pipeline "origin/$EXPECTED_BASE"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git merge-base --is-ancestor "$EXPECTED_BASE" "$CURRENT_BRANCH" || {
    echo "ERROR: 派生元ブランチが $EXPECTED_BASE ではありません。スタック構造が壊れています。"
    exit 1
}
```

- [ ] **Step 2: 失敗テスト (RED)**

`tests/unit/test_ingestion_pipeline.py` に追記:

```python
@pytest.mark.asyncio
async def test_pipeline_skips_neo4j_write_in_async_outbox_mode() -> None:
    """async_outbox モードでは GraphLinker が Storage 側にのみ書き込み、
    Neo4j には書き込まない。"""
    # GraphLinker のモードフラグ or pipeline 側分岐で検証
    pass
```

- [ ] **Step 3-5: 実装 + テスト**

`src/context_store/ingestion/pipeline.py` の IngestionPipeline 初期化を変更:

```python
class IngestionPipeline:
    def __init__(
        self, ..., graph_sync_mode: str = "sync",
    ) -> None:
        ...
        # async_outbox モードでは GraphLinker に Neo4j を渡さず Storage 側だけ書く
        graph_for_linker = None if graph_sync_mode == "async_outbox" else graph
        self._graph_linker = GraphLinker(storage=storage, graph=graph_for_linker)
```

注: `GraphLinker` 側で `graph` が None の場合に Neo4j 書き込みをスキップする実装になっている必要がある。なっていなければ本 Task で軽微修正を加える。

- [ ] **Step 6-7: コミット + Draft PR (派生元: `feat/outbox-orchestrator`)**

---

# Phase 6: リカバリスクリプト + E2E

## Task 6.1: scripts/sync_storage_to_neo4j.py リカバリ CLI

- **派生元ブランチ:** `feat/outbox-graph-sync`
- **実行モード:** 直列必須（Wait for Task 2.3 Draft PR）
- **前提条件:** Task 2.3 の Draft PR URL が存在
- **作成ブランチ:** `feat/outbox-recovery-script`

**Files:**
- Create: `scripts/sync_storage_to_neo4j.py`
- Modify: `pyproject.toml`（必要なら CLI エントリ追加）
- Create: `tests/unit/sync/test_recovery_script.py`

- [ ] **Step 1: ブランチ作成と派生元検証**

```bash
EXPECTED_BASE="feat/outbox-graph-sync"
git fetch origin "$EXPECTED_BASE"
git checkout -b feat/outbox-recovery-script "origin/$EXPECTED_BASE"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git merge-base --is-ancestor "$EXPECTED_BASE" "$CURRENT_BRANCH" || {
    echo "ERROR: 派生元ブランチが $EXPECTED_BASE ではありません。スタック構造が壊れています。"
    exit 1
}
```

- [ ] **Step 2-4: 実装 + テスト**

`scripts/sync_storage_to_neo4j.py`:

```python
"""Storage → Neo4j リカバリ CLI。

Usage:
    python -m scripts.sync_storage_to_neo4j --catchup
    python -m scripts.sync_storage_to_neo4j --full [--yes]
    python -m scripts.sync_storage_to_neo4j --full --dry-run --chunk-size 500

WARNING — `--full` モードのダウンタイム:
    --full は Neo4j の全 :Memory ノードを `MATCH (m:Memory) DETACH DELETE m`
    で削除してから再構築するため、実行中はグラフ traversal クエリが空結果を返す。
    設計仕様書 §10.1.1 (`docs/superpowers/specs/2026-05-21-neo4j-aura-outbox-sync-design.md`)
    に記載の通り、以下を必ず守ること:

      - 想定ユースケース: スキーマ非互換変更後の再構築 / 災害復旧時のみ。
        通常運用での実行は禁止
      - メンテナンス窓口内で、アプリケーション側がグラフ検索の空結果を許容する
        スケジュールで実行
      - 実行前に必ず --dry-run で対象件数を確認
      - 非対話バッチ実行時は --yes を明示（既定では TTY 経由の対話承認必須）

設計判断（パージなし MERGE での実装は採用しない）:
    レビュー時に「MERGE ベースのパージなし全同期」が代替案として提案されたが、
    本リリースでは採用しない。理由: パージなし全同期は Storage に存在せず Neo4j
    にのみ残る孤児ノードを検知できず、`--full` の本来用途である「整合性を完全に
    リセットする」目的を満たせないため。ダウンタイムレスな差分再同期が必要な
    ケースに対しては、設計仕様書 §10.1.1 で言及している将来の `--reconcile`
    モード（Storage 全 ID と Neo4j 全 ID の集合差分を取り、不足ノードを MERGE /
    孤児ノードのみ DETACH DELETE する非破壊同期）として別タスクで対応する方針。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from context_store.config import Settings

logger = logging.getLogger(__name__)

_FULL_CONFIRM_PROMPT = (
    "[!] --full は Neo4j の全 :Memory ノードを DETACH DELETE してから再構築します。\n"
    "    実行中はグラフ traversal が空結果を返すため、メンテナンス窓口内でのみ\n"
    "    実行してください。続行しますか? [yes/NO]: "
)


def _confirm_full(assume_yes: bool) -> bool:
    if assume_yes:
        logger.warning("--yes が指定されたため対話確認をスキップして --full を実行")
        return True
    if not sys.stdin.isatty():
        logger.error(
            "--full は TTY 経由か --yes 明示が必要です。バッチ実行時は --yes を付与してください。"
        )
        return False
    answer = input(_FULL_CONFIRM_PROMPT).strip().lower()
    return answer == "yes"


async def _run_full(chunk_size: int, dry_run: bool) -> int:
    settings = Settings()
    if dry_run:
        logger.info("Dry run: full sync would process chunks of %d", chunk_size)
        return 0
    from context_store.storage.factory import create_storage_with_outbox
    from context_store.sync.graph_sync import GraphSyncService

    storage, graph, cache, _ = await create_storage_with_outbox(settings)
    try:
        if graph is None:
            raise RuntimeError("graph_enabled=true required for sync")
        svc = GraphSyncService(graph_adapter=graph, storage_adapter=storage)
        logger.warning("Full sync 開始: Neo4j を完全パージします")
        await graph.execute_write("MATCH (m:Memory) DETACH DELETE m", {})
        total = await svc.full_sync_from_storage(chunk_size=chunk_size)
        logger.info("Full sync done: %d memories", total)
        return total
    finally:
        await storage.dispose()
        if graph: await graph.dispose()
        await cache.dispose()


async def _run_catchup(dry_run: bool) -> int:
    """Outbox の actionable イベント (PENDING/PROCESSING/FAILED) を 1 度だけ処理する。

    Worker の内部実装には依存せず、公開 API である `OutboxWorker.run_catchup()`
    のみを呼び出す。`_reader` や `_process_batch` といった private メンバーへの
    アクセスは Task 4.2 で禁止された設計方針 — リカバリスクリプトは
    Worker のパブリック契約（`run`/`stop`/`process_pending_once`/`run_catchup`）
    のみを使うこと。
    """
    settings = Settings()
    from context_store.storage.factory import create_storage_with_outbox
    storage, graph, cache, worker = await create_storage_with_outbox(settings)
    try:
        if worker is None:
            raise RuntimeError("graph_sync_mode='async_outbox' required for catchup")
        return await worker.run_catchup(dry_run=dry_run)
    finally:
        await storage.dispose()
        if graph: await graph.dispose()
        await cache.dispose()


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--full", action="store_true")
    group.add_argument("--catchup", action="store_true")
    parser.add_argument("--chunk-size", type=int, default=1000)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--yes", action="store_true",
        help="--full 実行時の対話確認をスキップ（非対話バッチ用）",
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(level=args.log_level)
    if args.full:
        if not args.dry_run and not _confirm_full(assume_yes=args.yes):
            logger.info("--full を中止しました")
            return 1
        asyncio.run(_run_full(args.chunk_size, args.dry_run))
    else:
        asyncio.run(_run_catchup(args.dry_run))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

`tests/unit/sync/test_recovery_script.py`: `argparse` ベースのスモークテスト。

- [ ] **Step 5: テスト実行**

```bash
uv run pytest tests/unit/sync/test_recovery_script.py -v
uv run python scripts/sync_storage_to_neo4j.py --full --dry-run  # 動作確認
```

Expected: 0 件処理を報告して正常終了

- [ ] **Step 6-7: コミット + Draft PR (派生元: `feat/outbox-graph-sync`)**

---

## Task 6.2: E2E 結合テスト

- **派生元ブランチ:** `feat/outbox-pipeline`
- **実行モード:** 直列必須
- **前提条件:** Task 5.3 の Draft PR URL が存在 / Task 6.1 のマージ確認
- **作成ブランチ:** `feat/outbox-e2e`

**Files:**
- Create: `tests/integration/test_outbox_e2e.py`
- Modify: `tests/conftest.py`（必要なら fixture 追加）

- [ ] **Step 1: ブランチ作成と派生元検証**

```bash
EXPECTED_BASE="feat/outbox-pipeline"
git fetch origin "$EXPECTED_BASE"
git checkout -b feat/outbox-e2e "origin/$EXPECTED_BASE"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git merge-base --is-ancestor "$EXPECTED_BASE" "$CURRENT_BRANCH" || {
    echo "ERROR: 派生元ブランチが $EXPECTED_BASE ではありません。スタック構造が壊れています。"
    exit 1
}
# Task 6.1 を取り込む
git fetch origin feat/outbox-recovery-script
git merge --no-edit origin/feat/outbox-recovery-script
```

- [ ] **Step 2-5: E2E テスト実装**

`tests/integration/test_outbox_e2e.py`:

```python
"""Outbox 全サイクル結合テスト (SQLite + Mock Neo4j)。

シナリオ:
1. Storage に save_memory → Outbox PENDING を確認
2. Worker を 1 サイクル実行 → Mock Neo4j に MERGE 呼び出し
3. Outbox が空になることを確認
4. delete_memory → DELETE_MEMORY イベント → Neo4j DETACH DELETE
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import pytest


@pytest.mark.asyncio
async def test_outbox_full_cycle_sqlite(monkeypatch, tmp_path) -> None:
    """save → outbox → worker → mock neo4j → delete → outbox 空。"""
    db_path = tmp_path / "e2e.db"
    monkeypatch.setenv("SQLITE_DB_PATH", str(db_path))
    monkeypatch.setenv("STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("GRAPH_ENABLED", "true")
    monkeypatch.setenv("GRAPH_SYNC_MODE", "async_outbox")
    monkeypatch.setenv("NEO4J_PASSWORD", "secret")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "local-model")
    monkeypatch.setenv("OUTBOX_POLL_INTERVAL_SECONDS", "0.01")

    # Neo4jGraphAdapter.create をパッチして MagicMock を返す
    from context_store.storage import neo4j as neo4j_mod
    fake_graph = MagicMock()
    fake_graph.execute_write = AsyncMock()
    fake_graph.dispose = AsyncMock()
    monkeypatch.setattr(neo4j_mod.Neo4jGraphAdapter, "create",
                        AsyncMock(return_value=fake_graph))

    from context_store.config import Settings
    from context_store.storage.factory import create_storage_with_outbox

    settings = Settings()
    storage, graph, cache, worker = await create_storage_with_outbox(settings)
    assert worker is not None

    # 1. save_memory
    from context_store.models.memory import Memory
    mem = Memory(
        id="77777777-7777-7777-7777-777777777777",
        content="e2e", memory_type="FACT", source_type="USER",
        source_metadata={}, embedding=[0.1] * 768,
        semantic_relevance=0.5, importance_score=0.5, tags=["e2e"], project="p",
        content_hash="h", created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    await storage.save_memory(mem)

    # Outbox に PENDING あり
    async with aiosqlite.connect(str(db_path)) as conn:
        async with conn.execute(
            "SELECT COUNT(*) FROM graph_sync_outbox WHERE status = 'PENDING'"
        ) as cur:
            (cnt,) = await cur.fetchone()
            assert cnt == 1

    # 2. Worker 1 サイクル
    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.05)
    await worker.stop()
    await task

    # 3. Mock Neo4j に MERGE が走った
    fake_graph.execute_write.assert_awaited()

    # 4. Outbox 空
    async with aiosqlite.connect(str(db_path)) as conn:
        async with conn.execute("SELECT COUNT(*) FROM graph_sync_outbox") as cur:
            (cnt,) = await cur.fetchone()
            assert cnt == 0

    # cleanup
    await storage.dispose()
    await graph.dispose()
    await cache.dispose()
```

- [ ] **Step 5: テスト実行**

```bash
uv run pytest tests/integration/test_outbox_e2e.py -v
uv run pytest tests/unit -q  # full regression
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/
```

Expected: 全 PASS

- [ ] **Step 6-7: コミット + Draft PR (派生元: `feat/outbox-pipeline`)**

```bash
git add tests/integration/test_outbox_e2e.py
git commit -m "test(outbox): SQLite + Mock Neo4j の E2E 結合テスト"
git push -u origin feat/outbox-e2e
gh pr create --draft --base feat/outbox-pipeline \
    --title "test(outbox): E2E 結合テスト" \
    --body "全サイクル (save → outbox → worker → mock neo4j → delete) の結合検証"
```

---

# 統合チェックリスト

すべての Task が完了し、各 PR が Ready for Review に遷移したら以下を確認:

- [ ] CI: ubuntu-slim ランナーで全 PR が PASS
- [ ] Devcontainer: `Run All Checks (CI)` タスクが PASS
- [ ] 設計書 §13.1 / 13.2 の変更対象ファイル全件が PR に含まれる
- [ ] `GRAPH_SYNC_MODE=async_outbox` 環境で E2E テストが PASS
- [ ] `scripts/sync_storage_to_neo4j.py --full --dry-run` が成功
- [ ] `scripts/sync_storage_to_neo4j.py --catchup --dry-run` が成功
- [ ] Supabase + Neo4j 構成のバリデーションが通る
- [ ] `sync` モード（既存動作）の regression なし

---

# 実行方針

**「Plan complete and saved to `docs/superpowers/plans/2026-05-22-neo4j-aura-outbox-sync.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — 各 Task ごとに fresh subagent を dispatch し、Task 間で人間レビューを挟む。並列可能 Task は同時実行で高速化。

**2. Inline Execution** — 本セッション内で `superpowers:executing-plans` 経由で順次実行。チェックポイントごとにレビュー。

**Which approach?"**
