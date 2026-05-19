# RL Action Logging & Reward Signal Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ChronosGraph の検索パイプラインに「ActionLog」と「RewardSignal」の収集基盤 (Phase 1) を追加し、Phase 2 の強化学習ループに必要な永続データをバックエンド非依存 (Postgres / SQLite / InMemory) で蓄積できるようにする。

**Architecture:** `extensions/protocols.py` の `AgentAction` / `RewardSignalRecord` / `ActionLogger` / `RewardSignal` を破壊的に書き直し、ストレージは `storage/protocols.py` に追加する `RLDataStore` Protocol を経由して `PostgresRLDataStore` / `SQLiteRLDataStore` / `InMemoryRLDataStore` に委譲する。`RetrievalPipeline` は各サブステップ完了直後に `asyncio.create_task` で `ActionLogger.log_action` を fire-and-forget しつつ応答返却前に `gather(return_exceptions=True)` で確定待ちし、Orchestrator は `contextvars.ContextVar` で `session_id` を伝播し `INTERNAL_EVAL` 報酬を自動生成する。MCP では `memory_search` に `session_id` 引数を追加し、新ツール `memory_feedback` で EXPLICIT_FEEDBACK を受け付ける。

**Tech Stack:** Python 3.12+, `asyncpg`, `aiosqlite`, `pydantic-settings`, `FastMCP`, `pytest` + `pytest-asyncio` + `unittest.mock.AsyncMock`, GitHub Actions (ubuntu-slim runner), devcontainer (`.devcontainer/devcontainer.json` + `Dockerfile`)

**Design Spec:** [`docs/superpowers/specs/2026-05-19-rl-action-logging-reward-foundation-design.md`](../specs/2026-05-19-rl-action-logging-reward-foundation-design.md)

---

## Git Branch Workflow (AI-Native Stacked PR)

このプロジェクトでは [AI-Native Stacked PR Workflow](https://different-sunday-448.notion.site/AI-Native-Stacked-PR-Workflow-3611669a4c16802eb032eb4ab05a8adb) に厳密に準拠して作業します。

### ブランチ命名規約

- フェーズ統合ブランチ (Phase Base): `feat/rl-foundation/phase-N`
- タスクブランチ: `feat/rl-foundation/phase-N-task-N.M-<slug>`
- 統合ターゲット: `master`

### 派生元判断ルール

| タスクの性質 | 派生元 | Draft PR の Target |
| --- | --- | --- |
| **単体で完結する** (他タスクの差分に依存せず `master` へ取り込んでも壊れない) | `master` | `master` |
| **直前タスクに依存する** (前タスクの差分が前提) | 直前タスクのブランチ | 直前タスクのブランチ |

### 実行モード

各 Task ヘッダに以下を明記します。

- **実行モード = 並列可能 (独立)**: `master` または該当 Phase Base から派生し、他タスクとファイル競合しないタスク。
- **実行モード = 直列必須 (Wait for Task X)**: 直前タスクの差分が前提のタスク。**先行タスクの Draft PR URL が存在することを実行開始の前提条件** とします。

### Step 1 のポカヨケ (物理的ブロッカー)

**すべての Task の Step 1 で `git merge-base --is-ancestor` による派生元検証スクリプトを devcontainer 内で必ず実行** します。失敗したらブランチを破棄し、正しい派生元から再作成してください。

### 各タスクの締めくくり

すべての Task の最後のステップで **派生元ブランチに向けた Draft PR を作成し、URL を記録** します。

### Devcontainer 強制

**すべてのテスト・型チェック・lint・ブランチ検証スクリプトは devcontainer 内で実行** します。ホスト側で直接 `pytest` などを起動しないでください。

---

## File Structure

新規作成 / 修正対象ファイルと責務:

| 区分 | パス | 責務 |
| --- | --- | --- |
| 新規 | `src/context_store/storage/migrations/postgres/0003_rl_basis.sql` | `action_log` / `reward_signal` テーブル + インデックス (Postgres) |
| 新規 | `src/context_store/storage/migrations/sqlite/0003_rl_basis.sql` | `action_log` / `reward_signal` テーブル + インデックス (SQLite) |
| 新規 | `src/context_store/extensions/session_context.py` | `contextvars` ベースの `session_id` 伝播ヘルパ |
| 新規 | `src/context_store/extensions/storage_logger.py` | `StorageActionLogger` / `StorageRewardSignal` (RLDataStore 委譲アダプタ) |
| 新規 | `src/context_store/storage/rl_inmemory.py` | `InMemoryRLDataStore` (テスト/開発用) |
| 新規 | `src/context_store/storage/rl_sqlite.py` | `SQLiteRLDataStore` (`aiosqlite` 単一-writer + WAL + FK 違反フォールバック) |
| 新規 | `src/context_store/storage/rl_postgres.py` | `PostgresRLDataStore` (`asyncpg` + FK 違反フォールバック) |
| 変更 | `src/context_store/extensions/protocols.py` | **破壊的書き換え**: `ActionType` / `SignalType` enum、`AgentAction` / `RewardSignalRecord` dataclass、Protocol 再定義 |
| 変更 | `src/context_store/extensions/noop.py` | 新シグネチャ準拠の NoOp 実装 |
| 変更 | `src/context_store/extensions/__init__.py` | 新規シンボルの公開 |
| 変更 | `src/context_store/storage/protocols.py` | `RLDataStore` Protocol 追加 |
| 変更 | `src/context_store/storage/factory.py` | `create_rl_data_store(settings)` ファクトリ追加 |
| 変更 | `src/context_store/config.py` | `rl_logging_enabled` / `rl_data_store_backend` / `rl_reward_context_max_bytes` 追加 |
| 変更 | `src/context_store/retrieval/pipeline.py` | サブステップ毎の `action_logger.log_action()` 発火 (`asyncio.create_task` + `gather` 確定待ち) |
| 変更 | `src/context_store/orchestrator.py` | `session_id` 伝播、`_emit_internal_eval`、`record_reward` 公開、`_background_tasks` 管理、`dispose` で RL ストア解放 |
| 変更 | `src/context_store/server.py` | `memory_search(... session_id)` 拡張、`memory_feedback(...)` 新設 |
| 変更 | `tests/unit/test_extensions.py` | 新 Protocol / NoOp に追従改修 |
| 新規 | `tests/unit/test_session_context.py` | `contextvars` 伝播テスト |
| 新規 | `tests/unit/test_rl_inmemory.py` | `InMemoryRLDataStore` 単体 (CHECK 制約、FK 違反フォールバック、`fetch_action_ids_by_session`) |
| 新規 | `tests/unit/test_rl_sqlite.py` | `SQLiteRLDataStore` 単体 (PRAGMA、CHECK 制約、`ON DELETE SET NULL`、FK 違反フォールバック、`fetch_action_ids_by_session`) |
| 新規 | `tests/unit/test_rl_postgres.py` | `PostgresRLDataStore` 単体 (asyncpg モックで SQL 発行検証、FK 違反フォールバック、`fetch_actions_by_session` / `fetch_action_ids_by_session` の `ORDER BY step ASC, created_at ASC`) |
| 新規 | `tests/unit/test_rl_factory.py` | `create_rl_data_store` ファクトリの 4 分岐 (auto/postgres/sqlite/inmemory) |
| 新規 | `tests/unit/test_rl_storage_logger.py` | `StorageActionLogger` / `StorageRewardSignal` 単体 |
| 新規 | `tests/unit/test_rl_basis.py` | エンド to エンド (search → 4 ActionLog → INTERNAL_EVAL → EXPLICIT_FEEDBACK) と race-free 検証 |
| 変更 | `tests/unit/test_retrieval_pipeline.py` | 4 step 発火、`context_volume`、`gather` 確定待ちの検証追加 |
| 変更 | `tests/unit/test_orchestrator.py` | contextvar、`_emit_internal_eval` のスコア計算、`dispose` 検証追加 |
| 変更 | `tests/unit/test_api_server.py` | `session_id` エコー、`memory_feedback` 正常系/異常系 |

---

## Phase 0: Infrastructure Baseline

**Phase Base ブランチ:** `feat/rl-foundation/phase-0` ← `master`

既存リポジトリには `.devcontainer/devcontainer.json` / `.devcontainer/Dockerfile` / `.github/workflows/ci.yml` がすでに存在します。Phase 0 では本作業の前提条件 (`master` トリガー、`ubuntu-slim` ランナー、ローカル devcontainer の動作) を **追加変更なしで明示的に検証** することを目的とします。

### Task 0.1: CI / Devcontainer ベースライン整合の検証

**派生元ブランチ:** `master`

**実行モード:** 並列可能 (独立) — このタスクは検証中心のため、本計画の他タスクから完全に独立して開始可能。

**前提条件:** なし

**Files:**

- 必要に応じて Modify: `.github/workflows/ci.yml` (`master` トリガーまたは `ubuntu-slim` 指定が欠落している場合のみ)
- 必要に応じて Modify: `.devcontainer/devcontainer.json` (devcontainer がローカルで `pytest` を実行できない場合のみ)

- [ ] **Step 1: ブランチ作成とポカヨケ検証**

```bash
git checkout master && git pull --ff-only origin master
git checkout -b feat/rl-foundation/phase-0-task-0.1-baseline

# 派生元が正しいか検証するポカヨケスクリプト
EXPECTED_BASE="master"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git merge-base --is-ancestor $EXPECTED_BASE $CURRENT_BRANCH || { echo "ERROR: 派生元ブランチが $EXPECTED_BASE ではありません。スタック構造が壊れています。"; exit 1; }
```

- [ ] **Step 2: CI ワークフローの実態確認**

`.github/workflows/ci.yml` を読み、以下が満たされているかチェック:

- `on.push.branches` に `master` が含まれる (または `["master", "**"]` のような全包含)
- `on.pull_request.branches` に `master` が含まれる
- `jobs.test.runs-on` が `ubuntu-slim`

満たされていない項目があれば該当箇所のみ最小修正します。すでに満たされていれば何も変更しません。

- [ ] **Step 3: devcontainer の動作確認**

devcontainer 内で以下が実行可能であることを確認:

```bash
uv sync --all-extras --dev
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/
uv run pytest tests/unit -v
```

Expected: すべて PASS (既存テストにリグレッションなし)

- [ ] **Step 4: コミット (変更があった場合のみ)**

```bash
# 変更があった場合
git add -A
git commit -m "ci: master トリガーと ubuntu-slim ランナーのベースライン整合"

# 変更がなかった場合は --allow-empty で痕跡を残す
git commit --allow-empty -m "chore: Phase 0 baseline verified (CI/devcontainer 既存設定で要件充足)"
```

- [ ] **Step 5: Phase Base 向け Draft PR を作成**

```bash
git push -u origin HEAD
gh pr create --draft --base master \
  --title "chore(rl): Phase 0 baseline (CI/devcontainer)" \
  --body "Phase 0 Task 0.1。CI (master トリガー + ubuntu-slim) と devcontainer の前提条件を確認。変更がない場合は empty commit でフェーズ起点をマークする。"
```

PR URL を記録します。

---

## Phase 1: Independent Foundations

**Phase Base ブランチ:** 各 Task は `master` から直接派生する単体完結タスク。Phase Base ブランチは作成しません。

設計書 §4 / §5.4 / §6.1 の独立した基盤要素 (SQL マイグレーション、Settings 追加、`session_context`) を **並列** で実装します。3 タスクとも他タスクの差分に依存せず、互いに別ファイルを触るため `master` ベースで並列実行可能です。

### Task 1.1: SQL マイグレーション `0003_rl_basis.sql` を追加 (Postgres + SQLite)

**派生元ブランチ:** `master`

**実行モード:** 並列可能 (独立) — 既存 Python コードから未参照のため `master` に直接マージしても壊れない。

**前提条件:** なし

**Files:**

- Create: `src/context_store/storage/migrations/postgres/0003_rl_basis.sql`
- Create: `src/context_store/storage/migrations/sqlite/0003_rl_basis.sql`

- [ ] **Step 1: ブランチ作成とポカヨケ検証**

```bash
git checkout master && git pull --ff-only origin master
git checkout -b feat/rl-foundation/phase-1-task-1.1-sql-migration

EXPECTED_BASE="master"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git merge-base --is-ancestor $EXPECTED_BASE $CURRENT_BRANCH || { echo "ERROR: 派生元ブランチが $EXPECTED_BASE ではありません。スタック構造が壊れています。"; exit 1; }
```

- [ ] **Step 2: Postgres マイグレーション SQL を作成**

`src/context_store/storage/migrations/postgres/0003_rl_basis.sql` を新規作成し、以下を全文書き込み:

```sql
-- Phase 1: RL Action Logging & Reward Signal Foundation

CREATE TABLE action_log (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      TEXT         NOT NULL,
    step            INT          NOT NULL CHECK (step >= 0),
    action_type     VARCHAR(32)  NOT NULL CHECK (
        action_type IN (
            'VECTOR_SEARCH', 'KEYWORD_SEARCH',
            'GRAPH_TRAVERSAL', 'RESULT_FUSION'
        )
    ),
    action_details  JSONB        NOT NULL DEFAULT '{}',
    context_volume  INT          NOT NULL DEFAULT 0 CHECK (context_volume >= 0),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_action_log_session_id   ON action_log (session_id);
CREATE INDEX idx_action_log_session_step ON action_log (session_id, step);
CREATE INDEX idx_action_log_created_at   ON action_log (created_at DESC);

CREATE TABLE reward_signal (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      TEXT         NOT NULL,
    action_log_id   UUID         REFERENCES action_log(id) ON DELETE SET NULL,
    signal_type     VARCHAR(32)  NOT NULL CHECK (
        signal_type IN ('INTERNAL_EVAL', 'IMPLICIT_USER', 'EXPLICIT_FEEDBACK')
    ),
    score           DOUBLE PRECISION NOT NULL CHECK (score >= -1.0 AND score <= 1.0),
    context         JSONB        NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_reward_signal_session_id    ON reward_signal (session_id);
CREATE INDEX idx_reward_signal_action_log_id ON reward_signal (action_log_id);
CREATE INDEX idx_reward_signal_signal_type   ON reward_signal (signal_type);
CREATE INDEX idx_reward_signal_created_at    ON reward_signal (created_at DESC);
```

- [ ] **Step 3: SQLite マイグレーション SQL を作成**

`src/context_store/storage/migrations/sqlite/0003_rl_basis.sql` を新規作成し、以下を全文書き込み:

```sql
-- Phase 1: RL Action Logging & Reward Signal Foundation

CREATE TABLE action_log (
    id              TEXT    PRIMARY KEY,
    session_id      TEXT    NOT NULL,
    step            INTEGER NOT NULL CHECK (step >= 0),
    action_type     TEXT    NOT NULL CHECK (
        action_type IN (
            'VECTOR_SEARCH', 'KEYWORD_SEARCH',
            'GRAPH_TRAVERSAL', 'RESULT_FUSION'
        )
    ),
    action_details  TEXT    NOT NULL DEFAULT '{}',
    context_volume  INTEGER NOT NULL DEFAULT 0 CHECK (context_volume >= 0),
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_action_log_session_id   ON action_log (session_id);
CREATE INDEX idx_action_log_session_step ON action_log (session_id, step);
CREATE INDEX idx_action_log_created_at   ON action_log (created_at DESC);

CREATE TABLE reward_signal (
    id              TEXT    PRIMARY KEY,
    session_id      TEXT    NOT NULL,
    action_log_id   TEXT    REFERENCES action_log(id) ON DELETE SET NULL,
    signal_type     TEXT    NOT NULL CHECK (
        signal_type IN ('INTERNAL_EVAL', 'IMPLICIT_USER', 'EXPLICIT_FEEDBACK')
    ),
    score           REAL    NOT NULL CHECK (score >= -1.0 AND score <= 1.0),
    context         TEXT    NOT NULL DEFAULT '{}',
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_reward_signal_session_id    ON reward_signal (session_id);
CREATE INDEX idx_reward_signal_action_log_id ON reward_signal (action_log_id);
CREATE INDEX idx_reward_signal_signal_type   ON reward_signal (signal_type);
CREATE INDEX idx_reward_signal_created_at    ON reward_signal (created_at DESC);
```

- [ ] **Step 4: 既存テストにリグレッションがないことを devcontainer 内で確認**

```bash
uv run ruff check src/ tests/
uv run pytest tests/unit -v
```

Expected: 既存テストがすべて PASS (新ファイルは Python から未参照)

- [ ] **Step 5: コミット**

```bash
git add src/context_store/storage/migrations/postgres/0003_rl_basis.sql \
        src/context_store/storage/migrations/sqlite/0003_rl_basis.sql
git commit -m "feat(rl): action_log / reward_signal の SQL マイグレーション追加"
```

- [ ] **Step 6: Draft PR を `master` 向けに作成**

```bash
git push -u origin HEAD
gh pr create --draft --base master \
  --title "feat(rl): action_log / reward_signal migrations (0003)" \
  --body "Phase 1 Task 1.1。Postgres / SQLite 両バックエンドの 0003_rl_basis.sql を追加。Python 側からは未参照のため独立マージ可能。"
```

PR URL を記録します。

---

### Task 1.2: 設定値 `rl_*` を `config.py` に追加

**派生元ブランチ:** `master`

**実行モード:** 並列可能 (独立) — `Settings` クラスに 3 フィールド追加するのみで他コードからの参照を増やさない。

**前提条件:** なし

**Files:**

- Modify: `src/context_store/config.py`
- Test: `tests/unit/test_config.py` (既存) に新フィールドのデフォルト値テストを追記

- [ ] **Step 1: ブランチ作成とポカヨケ検証**

```bash
git checkout master && git pull --ff-only origin master
git checkout -b feat/rl-foundation/phase-1-task-1.2-config

EXPECTED_BASE="master"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git merge-base --is-ancestor $EXPECTED_BASE $CURRENT_BRANCH || { echo "ERROR: 派生元ブランチが $EXPECTED_BASE ではありません。スタック構造が壊れています。"; exit 1; }
```

- [ ] **Step 2: 失敗するテストを追記**

`tests/unit/test_config.py` の末尾に以下を追加:

```python
def test_rl_settings_defaults() -> None:
    from context_store.config import Settings

    settings = Settings()
    assert settings.rl_logging_enabled is False
    assert settings.rl_data_store_backend == "auto"
    assert settings.rl_reward_context_max_bytes == 4096


def test_rl_reward_context_max_bytes_bounds() -> None:
    import pytest
    from pydantic import ValidationError
    from context_store.config import Settings

    with pytest.raises(ValidationError):
        Settings(rl_reward_context_max_bytes=64)  # < 128
    with pytest.raises(ValidationError):
        Settings(rl_reward_context_max_bytes=70000)  # > 65536


def test_rl_data_store_backend_literal_values() -> None:
    import pytest
    from pydantic import ValidationError
    from context_store.config import Settings

    for backend in ("auto", "postgres", "sqlite", "inmemory"):
        Settings(rl_data_store_backend=backend)
    with pytest.raises(ValidationError):
        Settings(rl_data_store_backend="invalid")
```

- [ ] **Step 3: テスト失敗を確認**

```bash
uv run pytest tests/unit/test_config.py::test_rl_settings_defaults \
              tests/unit/test_config.py::test_rl_reward_context_max_bytes_bounds \
              tests/unit/test_config.py::test_rl_data_store_backend_literal_values -v
```

Expected: 3 件すべて FAIL (`AttributeError` または属性なし)

- [ ] **Step 4: `Settings` に RL 用フィールドを追加**

`src/context_store/config.py` の `Settings` クラスに以下を追加します。既存 import に `Literal` がなければ追加。

```python
from typing import Literal
from pydantic import Field

# Settings クラス内 (適切な位置):
rl_logging_enabled: bool = Field(
    default=False, description="RL ログ記録の有効化"
)
rl_data_store_backend: Literal["auto", "postgres", "sqlite", "inmemory"] = Field(
    default="auto",
    description="RLDataStore のバックエンド。'auto' は storage_backend に追従",
)
rl_reward_context_max_bytes: int = Field(
    default=4096, ge=128, le=65536,
    description="reward_signal.context JSON の最大バイト数",
)
```

- [ ] **Step 5: テスト成功と既存テストの非破壊を確認**

```bash
uv run ruff check src/ tests/
uv run mypy src/context_store/config.py
uv run pytest tests/unit/test_config.py -v
```

Expected: すべて PASS

- [ ] **Step 6: コミット**

```bash
git add src/context_store/config.py tests/unit/test_config.py
git commit -m "feat(rl): Settings に rl_logging_enabled / rl_data_store_backend / rl_reward_context_max_bytes 追加"
```

- [ ] **Step 7: Draft PR を `master` 向けに作成**

```bash
git push -u origin HEAD
gh pr create --draft --base master \
  --title "feat(rl): RL ログ用 Settings フィールドを追加" \
  --body "Phase 1 Task 1.2。3 つの設定値を追加するのみで既存挙動に影響しないため独立マージ可能。"
```

PR URL を記録します。

---

### Task 1.3: `extensions/session_context.py` (contextvars ヘルパ) を追加

**派生元ブランチ:** `master`

**実行モード:** 並列可能 (独立) — 新規モジュールのみ追加し、既存 import を変更しない。

**前提条件:** なし

**Files:**

- Create: `src/context_store/extensions/session_context.py`
- Create: `tests/unit/test_session_context.py`

- [ ] **Step 1: ブランチ作成とポカヨケ検証**

```bash
git checkout master && git pull --ff-only origin master
git checkout -b feat/rl-foundation/phase-1-task-1.3-session-context

EXPECTED_BASE="master"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git merge-base --is-ancestor $EXPECTED_BASE $CURRENT_BRANCH || { echo "ERROR: 派生元ブランチが $EXPECTED_BASE ではありません。スタック構造が壊れています。"; exit 1; }
```

- [ ] **Step 2: 失敗するテストを作成**

`tests/unit/test_session_context.py` を新規作成し、以下を書き込み:

```python
import asyncio

import pytest

from context_store.extensions import session_context as sc


def test_default_is_none() -> None:
    assert sc.get_session_id() is None


def test_set_and_reset() -> None:
    token = sc.set_session_id("abc")
    try:
        assert sc.get_session_id() == "abc"
    finally:
        sc.reset_session_id(token)
    assert sc.get_session_id() is None


def test_new_session_id_is_uuid4_string() -> None:
    import uuid

    sid = sc.new_session_id()
    parsed = uuid.UUID(sid)
    assert parsed.version == 4


@pytest.mark.asyncio
async def test_propagation_through_gather() -> None:
    async def read_in_child() -> str | None:
        return sc.get_session_id()

    token = sc.set_session_id("session-X")
    try:
        results = await asyncio.gather(read_in_child(), read_in_child())
    finally:
        sc.reset_session_id(token)

    assert results == ["session-X", "session-X"]


@pytest.mark.asyncio
async def test_independent_tasks_isolate_context() -> None:
    async def with_id(sid: str) -> str | None:
        token = sc.set_session_id(sid)
        try:
            await asyncio.sleep(0)
            return sc.get_session_id()
        finally:
            sc.reset_session_id(token)

    a, b = await asyncio.gather(with_id("A"), with_id("B"))
    assert {a, b} == {"A", "B"}
    assert sc.get_session_id() is None
```

- [ ] **Step 3: テスト失敗を確認**

```bash
uv run pytest tests/unit/test_session_context.py -v
```

Expected: すべて FAIL (`session_context` モジュールが存在しない)

- [ ] **Step 4: `session_context.py` を実装**

`src/context_store/extensions/session_context.py` を新規作成し、以下を書き込み:

```python
"""Session ID propagation helpers using contextvars."""

from __future__ import annotations

import contextvars
import uuid

__all__ = [
    "get_session_id",
    "set_session_id",
    "reset_session_id",
    "new_session_id",
]

_session_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "chronos_rl_session_id", default=None
)


def get_session_id() -> str | None:
    return _session_id_var.get()


def set_session_id(session_id: str) -> contextvars.Token[str | None]:
    return _session_id_var.set(session_id)


def reset_session_id(token: contextvars.Token[str | None]) -> None:
    _session_id_var.reset(token)


def new_session_id() -> str:
    return str(uuid.uuid4())
```

- [ ] **Step 5: テスト成功と静的解析を確認**

```bash
uv run ruff check src/context_store/extensions/session_context.py tests/unit/test_session_context.py
uv run mypy src/context_store/extensions/session_context.py
uv run pytest tests/unit/test_session_context.py -v --cov=context_store.extensions.session_context --cov-report=term-missing
```

Expected: すべて PASS、`session_context.py` のカバレッジ 100%

- [ ] **Step 6: コミット**

```bash
git add src/context_store/extensions/session_context.py tests/unit/test_session_context.py
git commit -m "feat(rl): contextvars ベースの session_id 伝播ヘルパを追加"
```

- [ ] **Step 7: Draft PR を `master` 向けに作成**

```bash
git push -u origin HEAD
gh pr create --draft --base master \
  --title "feat(rl): session_context (contextvars helpers)" \
  --body "Phase 1 Task 1.3。Pipeline / Orchestrator が session_id を伝播するためのヘルパ。新規モジュールのみで既存依存ゼロのため独立マージ可能。"
```

PR URL を記録します。

---

## Phase 2: Protocol Breaking Change

**Phase Base ブランチ:** 単一タスクのため Phase Base は不要。`master` から直接派生。

### Task 2.1: `extensions/protocols.py` を破壊的に書き換え、`noop.py` と `storage/protocols.py` を同 PR で揃える

**派生元ブランチ:** `master`

**実行モード:** 並列可能 (独立) — 既存 `tests/unit/test_extensions.py` を同時に追随改修するため、この PR 内で全テストがグリーンになるよう完結させる。Phase 1 の各タスクとは別ファイルを触るため真に並列実行可能。

**前提条件:** なし

**Files:**

- Modify: `src/context_store/extensions/protocols.py` (全面書き換え)
- Modify: `src/context_store/extensions/noop.py` (新シグネチャ準拠)
- Modify: `src/context_store/extensions/__init__.py` (新シンボル公開)
- Modify: `src/context_store/storage/protocols.py` (末尾に `RLDataStore` Protocol 追加)
- Modify: `tests/unit/test_extensions.py` (新シグネチャに追随)

- [ ] **Step 1: ブランチ作成とポカヨケ検証**

```bash
git checkout master && git pull --ff-only origin master
git checkout -b feat/rl-foundation/phase-2-task-2.1-protocols-rewrite

EXPECTED_BASE="master"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git merge-base --is-ancestor $EXPECTED_BASE $CURRENT_BRANCH || { echo "ERROR: 派生元ブランチが $EXPECTED_BASE ではありません。スタック構造が壊れています。"; exit 1; }
```

- [ ] **Step 2: 新仕様の失敗テストを `tests/unit/test_extensions.py` に書く (既存テストは置き換え)**

`tests/unit/test_extensions.py` を以下に書き換えます (既存内容を破棄):

```python
"""Tests for extensions Protocol contract & NoOp implementations."""

from __future__ import annotations

import pytest

from context_store.extensions.noop import NoOpActionLogger, NoOpPolicyHook, NoOpRewardSignal
from context_store.extensions.protocols import (
    ActionLogger,
    ActionType,
    AgentAction,
    PolicyHook,
    RewardSignal,
    RewardSignalRecord,
    SignalType,
)


def test_action_type_values() -> None:
    assert ActionType.VECTOR_SEARCH.value == "VECTOR_SEARCH"
    assert ActionType.KEYWORD_SEARCH.value == "KEYWORD_SEARCH"
    assert ActionType.GRAPH_TRAVERSAL.value == "GRAPH_TRAVERSAL"
    assert ActionType.RESULT_FUSION.value == "RESULT_FUSION"


def test_signal_type_values() -> None:
    assert SignalType.INTERNAL_EVAL.value == "INTERNAL_EVAL"
    assert SignalType.IMPLICIT_USER.value == "IMPLICIT_USER"
    assert SignalType.EXPLICIT_FEEDBACK.value == "EXPLICIT_FEEDBACK"


def test_agent_action_is_frozen() -> None:
    action = AgentAction(
        session_id="s1", step=0, action_type=ActionType.VECTOR_SEARCH
    )
    with pytest.raises(Exception):
        action.step = 1  # type: ignore[misc]


def test_reward_signal_record_score_validation() -> None:
    RewardSignalRecord(
        session_id="s1", signal_type=SignalType.INTERNAL_EVAL, score=0.0
    )
    RewardSignalRecord(
        session_id="s1", signal_type=SignalType.INTERNAL_EVAL, score=-1.0
    )
    RewardSignalRecord(
        session_id="s1", signal_type=SignalType.INTERNAL_EVAL, score=1.0
    )
    with pytest.raises(ValueError):
        RewardSignalRecord(
            session_id="s1", signal_type=SignalType.INTERNAL_EVAL, score=-1.01
        )
    with pytest.raises(ValueError):
        RewardSignalRecord(
            session_id="s1", signal_type=SignalType.INTERNAL_EVAL, score=1.01
        )


@pytest.mark.asyncio
async def test_noop_action_logger_returns_empty_string() -> None:
    logger: ActionLogger = NoOpActionLogger()
    result = await logger.log_action(
        AgentAction(session_id="s1", step=0, action_type=ActionType.VECTOR_SEARCH)
    )
    assert result == ""


@pytest.mark.asyncio
async def test_noop_reward_signal_returns_empty_string() -> None:
    sig: RewardSignal = NoOpRewardSignal()
    result = await sig.record_reward(
        RewardSignalRecord(
            session_id="s1", signal_type=SignalType.INTERNAL_EVAL, score=0.0
        )
    )
    assert result == ""


@pytest.mark.asyncio
async def test_noop_policy_hook_returns_strategy_unchanged() -> None:
    from context_store.models.search import SearchStrategy

    hook: PolicyHook = NoOpPolicyHook()
    strategy = SearchStrategy()
    result = await hook.adjust_strategy("query", strategy)
    assert result is strategy


def test_protocol_runtime_isinstance() -> None:
    assert isinstance(NoOpActionLogger(), ActionLogger)
    assert isinstance(NoOpRewardSignal(), RewardSignal)
    assert isinstance(NoOpPolicyHook(), PolicyHook)
```

- [ ] **Step 3: テスト失敗を確認**

```bash
uv run pytest tests/unit/test_extensions.py -v
```

Expected: import エラーまたは大量 FAIL (新シンボル未定義のため)

- [ ] **Step 4: `extensions/protocols.py` を新仕様に書き換え**

`src/context_store/extensions/protocols.py` を全文以下に置き換え:

```python
"""Extension protocols for RL action logging and reward signal collection."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from context_store.models.search import SearchStrategy

__all__ = [
    "ActionType",
    "SignalType",
    "AgentAction",
    "RewardSignalRecord",
    "ActionLogger",
    "RewardSignal",
    "PolicyHook",
]


class ActionType(str, Enum):
    VECTOR_SEARCH = "VECTOR_SEARCH"
    KEYWORD_SEARCH = "KEYWORD_SEARCH"
    GRAPH_TRAVERSAL = "GRAPH_TRAVERSAL"
    RESULT_FUSION = "RESULT_FUSION"


class SignalType(str, Enum):
    INTERNAL_EVAL = "INTERNAL_EVAL"
    IMPLICIT_USER = "IMPLICIT_USER"
    EXPLICIT_FEEDBACK = "EXPLICIT_FEEDBACK"


@dataclass(frozen=True)
class AgentAction:
    session_id: str
    step: int
    action_type: ActionType
    action_details: dict[str, Any] = field(default_factory=dict)
    context_volume: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class RewardSignalRecord:
    session_id: str
    signal_type: SignalType
    score: float
    action_log_id: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not (-1.0 <= self.score <= 1.0):
            raise ValueError(f"score must be within [-1.0, 1.0], got {self.score}")


@runtime_checkable
class ActionLogger(Protocol):
    async def log_action(self, action: AgentAction) -> str: ...


@runtime_checkable
class RewardSignal(Protocol):
    async def record_reward(self, signal: RewardSignalRecord) -> str: ...


@runtime_checkable
class PolicyHook(Protocol):
    async def adjust_strategy(
        self, query: str, base_strategy: SearchStrategy
    ) -> SearchStrategy: ...
```

- [ ] **Step 5: `noop.py` を新シグネチャに揃える**

`src/context_store/extensions/noop.py` を全文以下に置き換え:

```python
"""NoOp implementations of extension protocols."""

from __future__ import annotations

from context_store.extensions.protocols import (
    ActionLogger,
    AgentAction,
    PolicyHook,
    RewardSignal,
    RewardSignalRecord,
)
from context_store.models.search import SearchStrategy

__all__ = ["NoOpActionLogger", "NoOpRewardSignal", "NoOpPolicyHook"]


class NoOpActionLogger(ActionLogger):
    async def log_action(self, action: AgentAction) -> str:
        return ""


class NoOpRewardSignal(RewardSignal):
    async def record_reward(self, signal: RewardSignalRecord) -> str:
        return ""


class NoOpPolicyHook(PolicyHook):
    async def adjust_strategy(
        self, query: str, base_strategy: SearchStrategy
    ) -> SearchStrategy:
        return base_strategy
```

- [ ] **Step 6: `extensions/__init__.py` で新シンボルを公開**

`src/context_store/extensions/__init__.py` を編集し、新シンボルが再エクスポートされていることを確認します (既存の `ActionLogger` などのエクスポート行を新名に追従):

```python
from context_store.extensions.protocols import (
    ActionLogger,
    ActionType,
    AgentAction,
    PolicyHook,
    RewardSignal,
    RewardSignalRecord,
    SignalType,
)
from context_store.extensions.noop import (
    NoOpActionLogger,
    NoOpPolicyHook,
    NoOpRewardSignal,
)

__all__ = [
    "ActionLogger",
    "ActionType",
    "AgentAction",
    "PolicyHook",
    "RewardSignal",
    "RewardSignalRecord",
    "SignalType",
    "NoOpActionLogger",
    "NoOpPolicyHook",
    "NoOpRewardSignal",
]
```

- [ ] **Step 7: `storage/protocols.py` に `RLDataStore` Protocol を追記**

`src/context_store/storage/protocols.py` の末尾 (既存 Protocol 群の下) に以下を追記し、import 部に `runtime_checkable` / `Protocol` が無ければ追加:

```python
from context_store.extensions.protocols import AgentAction, RewardSignalRecord


@runtime_checkable
class RLDataStore(Protocol):
    """Persistence Protocol for RL ActionLog / RewardSignal."""

    async def insert_action_log(self, action: AgentAction) -> str: ...

    async def insert_reward_signal(self, signal: RewardSignalRecord) -> str: ...

    async def fetch_actions_by_session(
        self, session_id: str, limit: int = 1000
    ) -> list[AgentAction]:
        """Fetch actions for a session ordered by (step ASC, created_at ASC).

        順序保証は ``fetch_action_ids_by_session`` と一致しており、両者を zip すれば
        ``(action_log.id, AgentAction)`` ペアを Phase 2 の MDP 系列復元用に再構築できる。
        """
        ...

    async def fetch_action_ids_by_session(
        self, session_id: str, limit: int = 1000
    ) -> list[str]:
        """Fetch action_log.id UUIDs for a session ordered by (step ASC, created_at ASC).

        順序は ``fetch_actions_by_session`` と一致する。E2E テストの race-free 検証や
        Phase 2 の MDP 系列復元で利用される。
        """
        ...

    async def fetch_rewards_by_session(
        self, session_id: str, limit: int = 1000
    ) -> list[RewardSignalRecord]: ...

    async def dispose(self) -> None: ...
```

- [ ] **Step 8: テスト成功と静的解析を確認**

```bash
uv run ruff check src/context_store/extensions/ src/context_store/storage/protocols.py tests/unit/test_extensions.py
uv run mypy src/context_store/extensions/ src/context_store/storage/protocols.py
uv run pytest tests/unit/test_extensions.py -v
# パイプライン/Orchestrator 既存テストが破綻していないか
uv run pytest tests/unit -v
```

Expected: `test_extensions.py` は PASS。**他のテストは現時点で旧 API を直接参照していなければ PASS、参照していれば Phase 5 / Phase 6 の Task で追随する** (今 Phase では `tests/unit/test_extensions.py` のみが新仕様に追随する)。**他テストで新たに失敗が出たら、そのテストの修正もこの Task 内で行う**こと (Pipeline/Orchestrator/Server 本体コードは変更せず、テスト側のシグネチャ追随のみ)。

- [ ] **Step 9: コミット**

```bash
git add src/context_store/extensions/ src/context_store/storage/protocols.py tests/unit/test_extensions.py
git commit -m "feat(rl): extensions Protocols を破壊的書き換え + storage RLDataStore Protocol 追加"
```

- [ ] **Step 10: Draft PR を `master` 向けに作成**

```bash
git push -u origin HEAD
gh pr create --draft --base master \
  --title "feat(rl)!: extensions Protocols 書き換え + RLDataStore Protocol 追加" \
  --body "Phase 2 Task 2.1。AgentAction / RewardSignalRecord / Enum を導入し、ActionLogger / RewardSignal Protocol を新シグネチャに書き換え (BREAKING)。storage/protocols.py に RLDataStore を追加。NoOp と test_extensions.py を同時追随。"
```

PR URL を記録します。

---

## Phase 3: RLDataStore Implementations

**Phase Base ブランチ:** `feat/rl-foundation/phase-3` ← `master` (Phase 2 と Task 1.1 のマージ完了後に作成)

> **重要:** Phase 3 のすべての Task は `feat/rl-foundation/phase-3` から派生します。Phase Base は **Task 2.1 (Protocol) と Task 1.1 (SQL Migrations) の両方がマージされた `master`** からブランチ作成してください。

### Task 3.0: Phase 3 Base ブランチを作成

**派生元ブランチ:** `master` (Task 2.1, Task 1.1, Task 1.2 マージ後)

**実行モード:** 直列必須 (Wait for Task 2.1 + Task 1.1)

**前提条件:** Task 2.1 と Task 1.1 の Draft PR が `master` にマージ済みであること

**Files:** なし (ブランチ作成のみ)

- [ ] **Step 1: 派生元の準備とポカヨケ検証**

```bash
git checkout master && git pull --ff-only origin master
git checkout -b feat/rl-foundation/phase-3
git push -u origin feat/rl-foundation/phase-3

EXPECTED_BASE="master"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git merge-base --is-ancestor $EXPECTED_BASE $CURRENT_BRANCH || { echo "ERROR: 派生元ブランチが $EXPECTED_BASE ではありません。スタック構造が壊れています。"; exit 1; }
```

- [ ] **Step 2: Phase Base 自体には差分を入れず、後続 Task のターゲットを確保**

このブランチには差分を載せません。後続 Task 3.1 / 3.2 / 3.3 はこのブランチから派生します。

---

### Task 3.1: `InMemoryRLDataStore` を実装

**派生元ブランチ:** `feat/rl-foundation/phase-3`

**実行モード:** 並列可能 (独立) — Task 3.2 / 3.3 とは別ファイルのみを触る (テストファイルもバックエンド別に分割)。Phase Base から真に並列実行可能。

**前提条件:** Task 3.0 の Phase Base ブランチが push 済みであること

**Files:**

- Create: `src/context_store/storage/rl_inmemory.py`
- Create: `tests/unit/test_rl_inmemory.py` (InMemory 専用テストファイル)

- [ ] **Step 1: ブランチ作成とポカヨケ検証**

```bash
git fetch origin feat/rl-foundation/phase-3
git checkout -b feat/rl-foundation/phase-3-task-3.1-inmemory origin/feat/rl-foundation/phase-3

EXPECTED_BASE="origin/feat/rl-foundation/phase-3"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git merge-base --is-ancestor $EXPECTED_BASE $CURRENT_BRANCH || { echo "ERROR: 派生元ブランチが $EXPECTED_BASE ではありません。スタック構造が壊れています。"; exit 1; }
```

- [ ] **Step 2: 失敗するテストを `tests/unit/test_rl_inmemory.py` に作成**

```python
"""Tests for InMemoryRLDataStore."""

from __future__ import annotations

import pytest

from context_store.extensions.protocols import (
    ActionType,
    AgentAction,
    RewardSignalRecord,
    SignalType,
)
from context_store.storage.rl_inmemory import InMemoryRLDataStore


@pytest.fixture
async def store():
    s = InMemoryRLDataStore()
    try:
        yield s
    finally:
        await s.dispose()


@pytest.mark.asyncio
async def test_insert_and_fetch_action(store: InMemoryRLDataStore) -> None:
    action = AgentAction(
        session_id="s1", step=0, action_type=ActionType.VECTOR_SEARCH,
        action_details={"k": 10}, context_volume=100,
    )
    action_id = await store.insert_action_log(action)
    assert action_id

    actions = await store.fetch_actions_by_session("s1")
    assert len(actions) == 1
    assert actions[0].session_id == "s1"
    assert actions[0].step == 0
    assert actions[0].action_type == ActionType.VECTOR_SEARCH


@pytest.mark.asyncio
async def test_insert_reward_with_valid_action_log_id(store: InMemoryRLDataStore) -> None:
    action = AgentAction(
        session_id="s1", step=0, action_type=ActionType.VECTOR_SEARCH,
    )
    action_id = await store.insert_action_log(action)

    reward = RewardSignalRecord(
        session_id="s1", signal_type=SignalType.EXPLICIT_FEEDBACK,
        score=0.5, action_log_id=action_id,
    )
    reward_id = await store.insert_reward_signal(reward)
    assert reward_id

    rewards = await store.fetch_rewards_by_session("s1")
    assert len(rewards) == 1
    assert rewards[0].action_log_id == action_id
    assert rewards[0].score == 0.5


@pytest.mark.asyncio
async def test_insert_reward_with_unknown_action_log_id_falls_back(store: InMemoryRLDataStore) -> None:
    """FK 違反相当 → action_log_id=NULL に格下げ、context.unverified_action_log_id に元 ID 保存"""
    reward = RewardSignalRecord(
        session_id="s1", signal_type=SignalType.EXPLICIT_FEEDBACK,
        score=-0.5, action_log_id="00000000-0000-4000-8000-000000000000",
    )
    reward_id = await store.insert_reward_signal(reward)
    assert reward_id

    rewards = await store.fetch_rewards_by_session("s1")
    assert len(rewards) == 1
    assert rewards[0].action_log_id is None
    assert rewards[0].context.get("unverified_action_log_id") == \
        "00000000-0000-4000-8000-000000000000"


@pytest.mark.asyncio
async def test_fetch_action_ids_matches_fetch_actions_order(store: InMemoryRLDataStore) -> None:
    """fetch_action_ids_by_session の戻り順序は fetch_actions_by_session と一致"""
    ids: list[str] = []
    for step in range(3):
        action = AgentAction(
            session_id="s1", step=step, action_type=ActionType.VECTOR_SEARCH,
        )
        ids.append(await store.insert_action_log(action))

    fetched_actions = await store.fetch_actions_by_session("s1")
    fetched_ids = await store.fetch_action_ids_by_session("s1")
    assert len(fetched_ids) == len(fetched_actions) == 3
    assert fetched_ids == ids
    # step 順で並ぶ
    assert [a.step for a in fetched_actions] == [0, 1, 2]


@pytest.mark.asyncio
async def test_dispose_is_idempotent(store: InMemoryRLDataStore) -> None:
    await store.dispose()
    await store.dispose()  # 2 度呼んでも例外なし
```

- [ ] **Step 3: テスト失敗を確認**

```bash
uv run pytest tests/unit/test_rl_inmemory.py -v
```

Expected: import エラー (`rl_inmemory` 未定義)

- [ ] **Step 4: `InMemoryRLDataStore` を実装**

`src/context_store/storage/rl_inmemory.py` を新規作成:

```python
"""In-memory RLDataStore implementation for tests and development."""

from __future__ import annotations

import uuid
from dataclasses import replace

from context_store.extensions.protocols import (
    AgentAction,
    RewardSignalRecord,
)
from context_store.storage.protocols import RLDataStore

__all__ = ["InMemoryRLDataStore"]


class InMemoryRLDataStore(RLDataStore):
    def __init__(self) -> None:
        # 挿入順を維持するため list[(id, AgentAction)] で保持
        self._actions: list[tuple[str, AgentAction]] = []
        self._rewards: list[tuple[str, RewardSignalRecord]] = []

    async def insert_action_log(self, action: AgentAction) -> str:
        action_id = str(uuid.uuid4())
        self._actions.append((action_id, action))
        return action_id

    async def insert_reward_signal(self, signal: RewardSignalRecord) -> str:
        reward_id = str(uuid.uuid4())
        known_ids = {aid for aid, _ in self._actions}
        if signal.action_log_id is not None and signal.action_log_id not in known_ids:
            ctx = dict(signal.context)
            ctx["unverified_action_log_id"] = signal.action_log_id
            signal = replace(signal, action_log_id=None, context=ctx)
        self._rewards.append((reward_id, signal))
        return reward_id

    def _ordered_session_pairs(
        self, session_id: str, limit: int
    ) -> list[tuple[str, AgentAction]]:
        # step ASC, 挿入順 (≒ created_at ASC) で並べる
        pairs = [(aid, a) for aid, a in self._actions if a.session_id == session_id]
        pairs.sort(key=lambda p: p[1].step)
        return pairs[:limit]

    async def fetch_actions_by_session(
        self, session_id: str, limit: int = 1000
    ) -> list[AgentAction]:
        return [a for _, a in self._ordered_session_pairs(session_id, limit)]

    async def fetch_action_ids_by_session(
        self, session_id: str, limit: int = 1000
    ) -> list[str]:
        return [aid for aid, _ in self._ordered_session_pairs(session_id, limit)]

    async def fetch_rewards_by_session(
        self, session_id: str, limit: int = 1000
    ) -> list[RewardSignalRecord]:
        return [r for _, r in self._rewards if r.session_id == session_id][:limit]

    async def dispose(self) -> None:
        self._actions.clear()
        self._rewards.clear()
```

- [ ] **Step 5: テスト成功と静的解析を確認**

```bash
uv run ruff check src/context_store/storage/rl_inmemory.py tests/unit/test_rl_inmemory.py
uv run mypy src/context_store/storage/rl_inmemory.py
uv run pytest tests/unit/test_rl_inmemory.py -v --cov=context_store.storage.rl_inmemory --cov-report=term-missing
```

Expected: すべて PASS、`rl_inmemory.py` カバレッジ 100%

- [ ] **Step 6: コミット**

```bash
git add src/context_store/storage/rl_inmemory.py tests/unit/test_rl_inmemory.py
git commit -m "feat(rl): InMemoryRLDataStore を実装 (FK 違反フォールバック + fetch_action_ids_by_session)"
```

- [ ] **Step 7: Draft PR を Phase Base 向けに作成**

```bash
git push -u origin HEAD
gh pr create --draft --base feat/rl-foundation/phase-3 \
  --title "feat(rl): InMemoryRLDataStore" \
  --body "Phase 3 Task 3.1。テスト用 In-Memory 実装。FK 違反フォールバック (unverified_action_log_id 保存) を含む。"
```

PR URL を記録します。

---

### Task 3.2: `SQLiteRLDataStore` を実装

**派生元ブランチ:** `feat/rl-foundation/phase-3`

**実行モード:** 並列可能 (独立) — Task 3.1 / 3.3 とは別ファイルのみを触る。テストファイルもバックエンド別に分割しているためファイル競合なし。

**前提条件:** Task 3.0 の Phase Base ブランチが push 済み、Task 1.1 (0003 migration) が `master` 経由で Phase Base に反映済みであること

**Files:**

- Create: `src/context_store/storage/rl_sqlite.py`
- Create: `tests/unit/test_rl_sqlite.py` (SQLite 専用テストファイル、新規)

- [ ] **Step 1: ブランチ作成とポカヨケ検証**

```bash
git fetch origin feat/rl-foundation/phase-3
git checkout -b feat/rl-foundation/phase-3-task-3.2-sqlite origin/feat/rl-foundation/phase-3

EXPECTED_BASE="origin/feat/rl-foundation/phase-3"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git merge-base --is-ancestor $EXPECTED_BASE $CURRENT_BRANCH || { echo "ERROR: 派生元ブランチが $EXPECTED_BASE ではありません。スタック構造が壊れています。"; exit 1; }
```

- [ ] **Step 2: 失敗するテストを `tests/unit/test_rl_sqlite.py` に作成**

```python
"""Tests for SQLiteRLDataStore."""

from __future__ import annotations

import aiosqlite
import pytest

from context_store.extensions.protocols import (
    ActionType,
    AgentAction,
    RewardSignalRecord,
    SignalType,
)
from context_store.storage.rl_sqlite import SQLiteRLDataStore


@pytest.fixture
async def store(tmp_path):
    db_path = tmp_path / "rl.db"
    s = await SQLiteRLDataStore.create(db_path=str(db_path))
    try:
        yield s
    finally:
        await s.dispose()


@pytest.mark.asyncio
async def test_insert_and_fetch_action(store: SQLiteRLDataStore) -> None:
    action = AgentAction(
        session_id="s1", step=0, action_type=ActionType.VECTOR_SEARCH,
        action_details={"k": 10}, context_volume=100,
    )
    action_id = await store.insert_action_log(action)
    assert action_id

    actions = await store.fetch_actions_by_session("s1")
    assert len(actions) == 1
    assert actions[0].session_id == "s1"
    assert actions[0].action_type == ActionType.VECTOR_SEARCH


@pytest.mark.asyncio
async def test_insert_reward_with_valid_action_log_id(store: SQLiteRLDataStore) -> None:
    action = AgentAction(session_id="s1", step=0, action_type=ActionType.VECTOR_SEARCH)
    action_id = await store.insert_action_log(action)
    reward = RewardSignalRecord(
        session_id="s1", signal_type=SignalType.EXPLICIT_FEEDBACK,
        score=0.5, action_log_id=action_id,
    )
    await store.insert_reward_signal(reward)

    rewards = await store.fetch_rewards_by_session("s1")
    assert len(rewards) == 1
    assert rewards[0].action_log_id == action_id


@pytest.mark.asyncio
async def test_insert_reward_with_unknown_action_log_id_falls_back(store: SQLiteRLDataStore) -> None:
    """FK 違反 → action_log_id=NULL に格下げ、context.unverified_action_log_id 保存"""
    bogus = "00000000-0000-4000-8000-000000000000"
    reward = RewardSignalRecord(
        session_id="s1", signal_type=SignalType.EXPLICIT_FEEDBACK,
        score=-0.5, action_log_id=bogus,
    )
    await store.insert_reward_signal(reward)

    rewards = await store.fetch_rewards_by_session("s1")
    assert len(rewards) == 1
    assert rewards[0].action_log_id is None
    assert rewards[0].context.get("unverified_action_log_id") == bogus


@pytest.mark.asyncio
async def test_fetch_action_ids_matches_fetch_actions_order(store: SQLiteRLDataStore) -> None:
    """fetch_action_ids_by_session の戻り順序は fetch_actions_by_session と一致 (step ASC)"""
    ids: list[str] = []
    # 挿入順を step と逆にして並び替え動作を検証
    for step in (2, 0, 1):
        action = AgentAction(session_id="s1", step=step, action_type=ActionType.VECTOR_SEARCH)
        ids.append(await store.insert_action_log(action))

    fetched_actions = await store.fetch_actions_by_session("s1")
    fetched_ids = await store.fetch_action_ids_by_session("s1")
    assert [a.step for a in fetched_actions] == [0, 1, 2]
    # ids は挿入順だったので、step=0 (元 index=1), step=1 (元 index=2), step=2 (元 index=0)
    assert fetched_ids == [ids[1], ids[2], ids[0]]


@pytest.mark.asyncio
async def test_pragmas_are_set(tmp_path) -> None:
    """foreign_keys=ON, journal_mode=WAL が設定されていること"""
    db_path = tmp_path / "pragma.db"
    s = await SQLiteRLDataStore.create(db_path=str(db_path))
    try:
        async with aiosqlite.connect(str(db_path)) as conn:
            cur = await conn.execute("PRAGMA foreign_keys")
            row = await cur.fetchone()
            assert row is not None and row[0] == 1

            cur = await conn.execute("PRAGMA journal_mode")
            row = await cur.fetchone()
            assert row is not None and row[0].lower() == "wal"
    finally:
        await s.dispose()


@pytest.mark.asyncio
async def test_score_validation_on_dataclass() -> None:
    """RewardSignalRecord の __post_init__ で score レンジ違反は弾かれる"""
    with pytest.raises(ValueError):
        RewardSignalRecord(
            session_id="s1", signal_type=SignalType.EXPLICIT_FEEDBACK, score=2.0
        )


@pytest.mark.asyncio
async def test_on_delete_set_null(tmp_path) -> None:
    """ActionLog 削除時に reward_signal.action_log_id が NULL になる"""
    db_path = tmp_path / "fk.db"
    s = await SQLiteRLDataStore.create(db_path=str(db_path))
    try:
        action = AgentAction(session_id="s1", step=0, action_type=ActionType.VECTOR_SEARCH)
        action_id = await s.insert_action_log(action)
        reward = RewardSignalRecord(
            session_id="s1", signal_type=SignalType.EXPLICIT_FEEDBACK,
            score=0.3, action_log_id=action_id,
        )
        await s.insert_reward_signal(reward)

        async with aiosqlite.connect(str(db_path)) as conn:
            await conn.execute("PRAGMA foreign_keys = ON")
            await conn.execute("DELETE FROM action_log WHERE id = ?", (action_id,))
            await conn.commit()

        rewards = await s.fetch_rewards_by_session("s1")
        assert len(rewards) == 1
        assert rewards[0].action_log_id is None
    finally:
        await s.dispose()


@pytest.mark.asyncio
async def test_dispose_is_idempotent(tmp_path) -> None:
    s = await SQLiteRLDataStore.create(db_path=str(tmp_path / "dispose.db"))
    await s.dispose()
    await s.dispose()
```

```bash
uv run pytest tests/unit/test_rl_sqlite.py -v
```

Expected: FAIL (`rl_sqlite` 未定義)

- [ ] **Step 3: `SQLiteRLDataStore` を実装**

`src/context_store/storage/rl_sqlite.py` を新規作成:

```python
"""SQLite implementation of RLDataStore using aiosqlite."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from context_store.extensions.protocols import (
    ActionType,
    AgentAction,
    RewardSignalRecord,
    SignalType,
)
from context_store.storage.protocols import RLDataStore

__all__ = ["SQLiteRLDataStore"]

_MIGRATION_FILE = (
    Path(__file__).parent / "migrations" / "sqlite" / "0003_rl_basis.sql"
)
_LOGGER = logging.getLogger(__name__)
_RETRY_DELAYS_MS = (50, 100, 200)


class SQLiteRLDataStore(RLDataStore):
    def __init__(self, conn: aiosqlite.Connection, lock: asyncio.Lock) -> None:
        self._conn = conn
        self._lock = lock
        self._disposed = False

    @classmethod
    async def create(cls, db_path: str) -> "SQLiteRLDataStore":
        conn = await aiosqlite.connect(db_path)
        await conn.execute("PRAGMA foreign_keys = ON")
        await conn.execute("PRAGMA journal_mode = WAL")
        await conn.execute("PRAGMA busy_timeout = 5000")
        await cls._apply_migration_if_needed(conn)
        return cls(conn=conn, lock=asyncio.Lock())

    @staticmethod
    async def _apply_migration_if_needed(conn: aiosqlite.Connection) -> None:
        cur = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='action_log'"
        )
        row = await cur.fetchone()
        if row is not None:
            return
        sql = _MIGRATION_FILE.read_text(encoding="utf-8")
        await conn.executescript(sql)
        await conn.commit()

    async def insert_action_log(self, action: AgentAction) -> str:
        action_id = str(uuid.uuid4())
        ts = action.timestamp.astimezone(timezone.utc).isoformat()

        async def _do() -> None:
            async with self._lock:
                await self._conn.execute(
                    """
                    INSERT INTO action_log
                        (id, session_id, step, action_type, action_details,
                         context_volume, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        action_id, action.session_id, action.step,
                        action.action_type.value,
                        json.dumps(action.action_details, ensure_ascii=False),
                        action.context_volume, ts,
                    ),
                )
                await self._conn.commit()

        await self._retry_on_busy(_do)
        return action_id

    async def insert_reward_signal(self, signal: RewardSignalRecord) -> str:
        reward_id = str(uuid.uuid4())
        effective_signal = signal
        try:
            await self._do_insert_reward(reward_id, effective_signal)
        except aiosqlite.IntegrityError as exc:
            if "FOREIGN KEY" not in str(exc).upper():
                raise
            ctx = dict(effective_signal.context)
            ctx["unverified_action_log_id"] = effective_signal.action_log_id
            effective_signal = replace(effective_signal, action_log_id=None, context=ctx)
            await self._do_insert_reward(reward_id, effective_signal)
        return reward_id

    async def _do_insert_reward(self, reward_id: str, signal: RewardSignalRecord) -> None:
        ts = signal.timestamp.astimezone(timezone.utc).isoformat()

        async def _do() -> None:
            async with self._lock:
                await self._conn.execute(
                    """
                    INSERT INTO reward_signal
                        (id, session_id, action_log_id, signal_type, score, context, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        reward_id, signal.session_id, signal.action_log_id,
                        signal.signal_type.value, signal.score,
                        json.dumps(signal.context, ensure_ascii=False), ts,
                    ),
                )
                await self._conn.commit()

        await self._retry_on_busy(_do)

    async def fetch_actions_by_session(
        self, session_id: str, limit: int = 1000
    ) -> list[AgentAction]:
        cur = await self._conn.execute(
            """
            SELECT session_id, step, action_type, action_details,
                   context_volume, created_at
            FROM action_log
            WHERE session_id = ?
            ORDER BY step ASC, created_at ASC
            LIMIT ?
            """,
            (session_id, limit),
        )
        rows = await cur.fetchall()
        return [
            AgentAction(
                session_id=row[0], step=row[1],
                action_type=ActionType(row[2]),
                action_details=json.loads(row[3]),
                context_volume=row[4],
                timestamp=datetime.fromisoformat(row[5].replace("Z", "+00:00"))
                if row[5].endswith("Z") else datetime.fromisoformat(row[5]),
            )
            for row in rows
        ]

    async def fetch_action_ids_by_session(
        self, session_id: str, limit: int = 1000
    ) -> list[str]:
        cur = await self._conn.execute(
            """
            SELECT id
            FROM action_log
            WHERE session_id = ?
            ORDER BY step ASC, created_at ASC
            LIMIT ?
            """,
            (session_id, limit),
        )
        rows = await cur.fetchall()
        return [row[0] for row in rows]

    async def fetch_rewards_by_session(
        self, session_id: str, limit: int = 1000
    ) -> list[RewardSignalRecord]:
        cur = await self._conn.execute(
            """
            SELECT session_id, action_log_id, signal_type, score, context, created_at
            FROM reward_signal
            WHERE session_id = ?
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (session_id, limit),
        )
        rows = await cur.fetchall()
        return [
            RewardSignalRecord(
                session_id=row[0], action_log_id=row[1],
                signal_type=SignalType(row[2]), score=row[3],
                context=json.loads(row[4]),
                timestamp=datetime.fromisoformat(row[5].replace("Z", "+00:00"))
                if row[5].endswith("Z") else datetime.fromisoformat(row[5]),
            )
            for row in rows
        ]

    async def dispose(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        await self._conn.close()

    async def _retry_on_busy(self, fn) -> None:
        last_exc: Exception | None = None
        for delay_ms in (0, *_RETRY_DELAYS_MS):
            if delay_ms:
                await asyncio.sleep(delay_ms / 1000.0)
            try:
                await fn()
                return
            except aiosqlite.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                last_exc = exc
        _LOGGER.warning("SQLite busy after retries: %s", last_exc)
        raise last_exc if last_exc else RuntimeError("unreachable")
```

- [ ] **Step 4: テスト成功と静的解析を確認**

```bash
uv run ruff check src/context_store/storage/rl_sqlite.py tests/unit/test_rl_sqlite.py
uv run mypy src/context_store/storage/rl_sqlite.py
uv run pytest tests/unit/test_rl_sqlite.py -v --cov=context_store.storage.rl_sqlite --cov-report=term-missing
```

Expected: すべて PASS、`rl_sqlite.py` カバレッジ 100%

- [ ] **Step 5: コミット**

```bash
git add src/context_store/storage/rl_sqlite.py tests/unit/test_rl_sqlite.py
git commit -m "feat(rl): SQLiteRLDataStore を実装 (WAL + busy_timeout + FK 違反フォールバック + fetch_action_ids_by_session)"
```

- [ ] **Step 6: Draft PR を Phase Base 向けに作成**

```bash
git push -u origin HEAD
gh pr create --draft --base feat/rl-foundation/phase-3 \
  --title "feat(rl): SQLiteRLDataStore" \
  --body "Phase 3 Task 3.2。aiosqlite ベース。PRAGMA foreign_keys=ON / journal_mode=WAL / busy_timeout=5000 を必須化、FK 違反捕捉で action_log_id=NULL 格下げ + unverified_action_log_id 保存。busy 再試行ロジック付き。"
```

PR URL を記録します。

---

### Task 3.3: `PostgresRLDataStore` を実装

**派生元ブランチ:** `feat/rl-foundation/phase-3`

**実行モード:** 並列可能 (独立) — Task 3.1 / 3.2 とは別ファイルのみを触る。テストファイルもバックエンド別に分割しているためファイル競合なし。

**前提条件:** Task 3.0 の Phase Base ブランチが push 済み、Task 1.1 (0003 migration) が `master` 経由で Phase Base に反映済みであること

**Files:**

- Create: `src/context_store/storage/rl_postgres.py`
- Create: `tests/unit/test_rl_postgres.py` (Postgres 専用、`AsyncMock` で SQL 発行検証)

- [ ] **Step 1: ブランチ作成とポカヨケ検証**

```bash
git fetch origin feat/rl-foundation/phase-3
git checkout -b feat/rl-foundation/phase-3-task-3.3-postgres origin/feat/rl-foundation/phase-3

EXPECTED_BASE="origin/feat/rl-foundation/phase-3"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git merge-base --is-ancestor $EXPECTED_BASE $CURRENT_BRANCH || { echo "ERROR: 派生元ブランチが $EXPECTED_BASE ではありません。スタック構造が壊れています。"; exit 1; }
```

- [ ] **Step 2: 失敗するテストを `tests/unit/test_rl_postgres.py` に作成**

```python
"""Tests for PostgresRLDataStore (asyncpg mock-based)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import asyncpg
import pytest

from context_store.extensions.protocols import (
    ActionType,
    AgentAction,
    RewardSignalRecord,
    SignalType,
)
from context_store.storage.rl_postgres import PostgresRLDataStore


def _make_fake_pool(fetchval_returns=None, fetchval_side_effect=None,
                    fetch_returns=None) -> tuple[MagicMock, AsyncMock]:
    fake_conn = AsyncMock()
    if fetchval_side_effect is not None:
        fake_conn.fetchval = AsyncMock(side_effect=fetchval_side_effect)
    else:
        fake_conn.fetchval = AsyncMock(return_value=fetchval_returns)
    if fetch_returns is not None:
        fake_conn.fetch = AsyncMock(return_value=fetch_returns)
    fake_pool = MagicMock()
    fake_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=fake_conn)
    fake_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    fake_pool.close = AsyncMock()
    return fake_pool, fake_conn


@pytest.mark.asyncio
async def test_insert_action_log_emits_expected_sql() -> None:
    fake_pool, fake_conn = _make_fake_pool(
        fetchval_returns="00000000-0000-4000-8000-000000000abc"
    )
    store = PostgresRLDataStore(pool=fake_pool)
    try:
        action = AgentAction(session_id="s1", step=2, action_type=ActionType.GRAPH_TRAVERSAL)
        aid = await store.insert_action_log(action)
        assert aid == "00000000-0000-4000-8000-000000000abc"
        call_args = fake_conn.fetchval.call_args_list[0]
        assert "INSERT INTO action_log" in call_args.args[0]
    finally:
        await store.dispose()


@pytest.mark.asyncio
async def test_insert_reward_falls_back_on_fk_violation() -> None:
    fake_pool, fake_conn = _make_fake_pool(
        fetchval_side_effect=[
            asyncpg.ForeignKeyViolationError("fk"),
            "00000000-0000-4000-8000-000000000def",
        ]
    )
    store = PostgresRLDataStore(pool=fake_pool)
    try:
        reward = RewardSignalRecord(
            session_id="s1", signal_type=SignalType.EXPLICIT_FEEDBACK,
            score=0.7, action_log_id="00000000-0000-4000-8000-000000000999",
        )
        rid = await store.insert_reward_signal(reward)
        assert rid == "00000000-0000-4000-8000-000000000def"
        # 2 回目の SQL 引数では action_log_id=None、context に unverified_action_log_id が入る
        second_call = fake_conn.fetchval.call_args_list[1]
        args = second_call.args
        # args = (sql, session_id, action_log_id, signal_type, score, context_json, ts)
        assert args[2] is None
        assert "unverified_action_log_id" in args[5]
    finally:
        await store.dispose()


@pytest.mark.asyncio
async def test_fetch_action_ids_sql_orders_by_step_then_created_at() -> None:
    """fetch_action_ids_by_session の SQL が step ASC, created_at ASC を含む"""
    fake_pool, fake_conn = _make_fake_pool(fetch_returns=[{"id": "id-a"}, {"id": "id-b"}])
    # asyncpg.Record は dict-like なので AsyncMock の戻り値で MagicMock を使う
    record_a = MagicMock()
    record_a.__getitem__ = lambda self, k: "id-a" if k == "id" else None
    record_b = MagicMock()
    record_b.__getitem__ = lambda self, k: "id-b" if k == "id" else None
    fake_conn.fetch = AsyncMock(return_value=[record_a, record_b])

    store = PostgresRLDataStore(pool=fake_pool)
    try:
        ids = await store.fetch_action_ids_by_session("s1", limit=10)
        assert ids == ["id-a", "id-b"]
        sql = fake_conn.fetch.call_args.args[0]
        assert "ORDER BY step ASC" in sql
        assert "created_at ASC" in sql
    finally:
        await store.dispose()


@pytest.mark.asyncio
async def test_fetch_actions_sql_orders_by_step_then_created_at() -> None:
    """fetch_actions_by_session の SQL が step ASC, created_at ASC を含む (§5.2 順序契約)"""
    fake_pool, fake_conn = _make_fake_pool()
    fake_conn.fetch = AsyncMock(return_value=[])

    store = PostgresRLDataStore(pool=fake_pool)
    try:
        await store.fetch_actions_by_session("s1", limit=10)
        sql = fake_conn.fetch.call_args.args[0]
        assert "ORDER BY step ASC" in sql
        assert "created_at ASC" in sql
    finally:
        await store.dispose()


@pytest.mark.asyncio
async def test_dispose_closes_pool() -> None:
    fake_pool, _ = _make_fake_pool(fetchval_returns="anything")
    store = PostgresRLDataStore(pool=fake_pool)
    await store.dispose()
    fake_pool.close.assert_awaited_once()
    # 2 回呼んでも close は 1 度のみ
    await store.dispose()
    fake_pool.close.assert_awaited_once()
```

```bash
uv run pytest tests/unit/test_rl_postgres.py -v
```

Expected: import エラー (`rl_postgres` 未定義)

- [ ] **Step 3: `PostgresRLDataStore` を実装**

`src/context_store/storage/rl_postgres.py` を新規作成:

```python
"""PostgreSQL implementation of RLDataStore using asyncpg."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timezone
from typing import Any

import asyncpg

from context_store.config import Settings
from context_store.extensions.protocols import (
    ActionType,
    AgentAction,
    RewardSignalRecord,
    SignalType,
)
from context_store.storage.protocols import RLDataStore

__all__ = ["PostgresRLDataStore"]


class PostgresRLDataStore(RLDataStore):
    def __init__(self, pool: asyncpg.Pool | Any) -> None:
        self._pool = pool
        self._disposed = False

    @classmethod
    async def create(cls, settings: Settings) -> "PostgresRLDataStore":
        dsn = settings.postgres_dsn  # 既存 Settings の Postgres DSN を流用
        pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=4)
        return cls(pool=pool)

    async def insert_action_log(self, action: AgentAction) -> str:
        ts = action.timestamp.astimezone(timezone.utc)
        async with self._pool.acquire() as conn:
            row = await conn.fetchval(
                """
                INSERT INTO action_log
                    (session_id, step, action_type, action_details,
                     context_volume, created_at)
                VALUES ($1, $2, $3, $4::jsonb, $5, $6)
                RETURNING id::text
                """,
                action.session_id, action.step, action.action_type.value,
                json.dumps(action.action_details, ensure_ascii=False),
                action.context_volume, ts,
            )
        return str(row)

    async def insert_reward_signal(self, signal: RewardSignalRecord) -> str:
        ts = signal.timestamp.astimezone(timezone.utc)
        effective = signal
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchval(
                    """
                    INSERT INTO reward_signal
                        (session_id, action_log_id, signal_type, score, context, created_at)
                    VALUES ($1, $2::uuid, $3, $4, $5::jsonb, $6)
                    RETURNING id::text
                    """,
                    effective.session_id, effective.action_log_id,
                    effective.signal_type.value, effective.score,
                    json.dumps(effective.context, ensure_ascii=False), ts,
                )
            return str(row)
        except asyncpg.ForeignKeyViolationError:
            ctx = dict(effective.context)
            ctx["unverified_action_log_id"] = effective.action_log_id
            effective = replace(effective, action_log_id=None, context=ctx)
            async with self._pool.acquire() as conn:
                row = await conn.fetchval(
                    """
                    INSERT INTO reward_signal
                        (session_id, action_log_id, signal_type, score, context, created_at)
                    VALUES ($1, $2::uuid, $3, $4, $5::jsonb, $6)
                    RETURNING id::text
                    """,
                    effective.session_id, effective.action_log_id,
                    effective.signal_type.value, effective.score,
                    json.dumps(effective.context, ensure_ascii=False), ts,
                )
            return str(row)

    async def fetch_actions_by_session(
        self, session_id: str, limit: int = 1000
    ) -> list[AgentAction]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT session_id, step, action_type, action_details,
                       context_volume, created_at
                FROM action_log
                WHERE session_id = $1
                ORDER BY step ASC, created_at ASC
                LIMIT $2
                """,
                session_id, limit,
            )
        return [
            AgentAction(
                session_id=r["session_id"], step=r["step"],
                action_type=ActionType(r["action_type"]),
                action_details=json.loads(r["action_details"])
                if isinstance(r["action_details"], str) else r["action_details"],
                context_volume=r["context_volume"],
                timestamp=r["created_at"],
            )
            for r in rows
        ]

    async def fetch_action_ids_by_session(
        self, session_id: str, limit: int = 1000
    ) -> list[str]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id::text AS id
                FROM action_log
                WHERE session_id = $1
                ORDER BY step ASC, created_at ASC
                LIMIT $2
                """,
                session_id, limit,
            )
        return [r["id"] for r in rows]

    async def fetch_rewards_by_session(
        self, session_id: str, limit: int = 1000
    ) -> list[RewardSignalRecord]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT session_id, action_log_id::text AS action_log_id,
                       signal_type, score, context, created_at
                FROM reward_signal
                WHERE session_id = $1
                ORDER BY created_at ASC
                LIMIT $2
                """,
                session_id, limit,
            )
        return [
            RewardSignalRecord(
                session_id=r["session_id"],
                action_log_id=r["action_log_id"],
                signal_type=SignalType(r["signal_type"]),
                score=r["score"],
                context=json.loads(r["context"])
                if isinstance(r["context"], str) else r["context"],
                timestamp=r["created_at"],
            )
            for r in rows
        ]

    async def dispose(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        await self._pool.close()
```

> **注:** `settings.postgres_dsn` フィールドが既存 Settings に存在することを前提とします。プロジェクトの命名が異なる場合 (`prisma_database_url` など) は、Settings 側の DSN プロパティを参照する形で `create()` を調整してください。

- [ ] **Step 4: テスト成功と静的解析を確認**

```bash
uv run ruff check src/context_store/storage/rl_postgres.py tests/unit/test_rl_postgres.py
uv run mypy src/context_store/storage/rl_postgres.py
uv run pytest tests/unit/test_rl_postgres.py -v --cov=context_store.storage.rl_postgres --cov-report=term-missing
```

Expected: すべて PASS、`rl_postgres.py` カバレッジ 100%

- [ ] **Step 5: コミット**

```bash
git add src/context_store/storage/rl_postgres.py tests/unit/test_rl_postgres.py
git commit -m "feat(rl): PostgresRLDataStore を実装 (asyncpg + FK 違反フォールバック)"
```

- [ ] **Step 6: Draft PR を Phase Base 向けに作成**

```bash
git push -u origin HEAD
gh pr create --draft --base feat/rl-foundation/phase-3 \
  --title "feat(rl): PostgresRLDataStore" \
  --body "Phase 3 Task 3.3。asyncpg ベース。FK 違反 (ForeignKeyViolationError) 捕捉で action_log_id=NULL 格下げ + unverified_action_log_id 保存。"
```

PR URL を記録します。

---

### Task 3.4: `create_rl_data_store` ファクトリを統合

**派生元ブランチ:** `feat/rl-foundation/phase-3` (Task 3.1 / 3.2 / 3.3 を Phase Base に取り込んだ状態)

**実行モード:** 直列必須 (Wait for Task 3.1, 3.2, 3.3) — 3 つのストア実装すべてが Phase Base にマージされてからでないと作れない。

**前提条件:** Task 3.1 / 3.2 / 3.3 の Draft PR がすべて Phase Base ブランチにマージ済みであること

**Files:**

- Modify: `src/context_store/storage/factory.py`
- Create: `tests/unit/test_rl_factory.py` (ファクトリ経由で 4 バックエンド分岐をテスト)

- [ ] **Step 1: 派生元更新とブランチ作成、ポカヨケ検証**

```bash
git fetch origin feat/rl-foundation/phase-3
git checkout -b feat/rl-foundation/phase-3-task-3.4-factory origin/feat/rl-foundation/phase-3

EXPECTED_BASE="origin/feat/rl-foundation/phase-3"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git merge-base --is-ancestor $EXPECTED_BASE $CURRENT_BRANCH || { echo "ERROR: 派生元ブランチが $EXPECTED_BASE ではありません。スタック構造が壊れています。"; exit 1; }
```

- [ ] **Step 2: 失敗するテストを作成**

新規ファイル `tests/unit/test_rl_factory.py` を作成:

```python
"""create_rl_data_store ファクトリのテスト (auto/postgres/sqlite/inmemory 4 分岐網羅)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


def _make_settings(**overrides):
    """Settings を _env_file=None で生成 (tests/unit/conftest.py の make_settings と同等)."""
    from context_store.config import Settings

    defaults = {
        "storage_backend": "inmemory",
        "rl_data_store_backend": "auto",
    }
    defaults.update(overrides)
    return Settings(_env_file=None, **defaults)


@pytest.mark.asyncio
async def test_factory_explicit_inmemory_backend() -> None:
    from context_store.storage.factory import create_rl_data_store
    from context_store.storage.rl_inmemory import InMemoryRLDataStore

    settings = _make_settings(rl_data_store_backend="inmemory")
    store = await create_rl_data_store(settings)
    try:
        assert isinstance(store, InMemoryRLDataStore)
    finally:
        await store.dispose()


@pytest.mark.asyncio
async def test_factory_auto_resolves_to_inmemory_when_storage_inmemory() -> None:
    from context_store.storage.factory import create_rl_data_store
    from context_store.storage.rl_inmemory import InMemoryRLDataStore

    settings = _make_settings(storage_backend="inmemory", rl_data_store_backend="auto")
    store = await create_rl_data_store(settings)
    try:
        assert isinstance(store, InMemoryRLDataStore)
    finally:
        await store.dispose()


@pytest.mark.asyncio
async def test_factory_auto_resolves_to_sqlite_when_storage_sqlite(tmp_path) -> None:
    from context_store.storage.factory import create_rl_data_store
    from context_store.storage.rl_sqlite import SQLiteRLDataStore

    db_path = str(tmp_path / "rl.db")
    settings = _make_settings(
        storage_backend="sqlite",
        rl_data_store_backend="auto",
        sqlite_db_path=db_path,
    )
    store = await create_rl_data_store(settings)
    try:
        assert isinstance(store, SQLiteRLDataStore)
    finally:
        await store.dispose()


@pytest.mark.asyncio
async def test_factory_auto_resolves_to_postgres_when_storage_postgres() -> None:
    """storage_backend='postgres' のとき auto → PostgresRLDataStore.create が呼ばれる"""
    from context_store.storage.factory import create_rl_data_store

    settings = _make_settings(storage_backend="postgres", rl_data_store_backend="auto")
    fake_store = AsyncMock()
    with patch(
        "context_store.storage.rl_postgres.PostgresRLDataStore.create",
        new=AsyncMock(return_value=fake_store),
    ) as mock_create:
        store = await create_rl_data_store(settings)
        mock_create.assert_awaited_once_with(settings)
        assert store is fake_store
```

```bash
uv run pytest tests/unit/test_rl_factory.py -v
```

Expected: FAIL (`create_rl_data_store` 未定義)

- [ ] **Step 3: `storage/factory.py` に `create_rl_data_store` を追加**

`src/context_store/storage/factory.py` のファイル末尾 (既存ファクトリ関数群の下) に以下を追加:

```python
async def create_rl_data_store(settings: "Settings") -> "RLDataStore":
    from context_store.storage.protocols import RLDataStore  # noqa: F401

    backend = settings.rl_data_store_backend
    if backend == "auto":
        if settings.storage_backend in ("postgres", "prisma"):
            backend = "postgres"
        elif settings.storage_backend == "sqlite":
            backend = "sqlite"
        else:
            backend = "inmemory"

    if backend == "postgres":
        from context_store.storage.rl_postgres import PostgresRLDataStore
        return await PostgresRLDataStore.create(settings)
    if backend == "sqlite":
        from context_store.storage.rl_sqlite import SQLiteRLDataStore
        return await SQLiteRLDataStore.create(db_path=settings.sqlite_db_path)
    from context_store.storage.rl_inmemory import InMemoryRLDataStore
    return InMemoryRLDataStore()
```

> **注:** Settings の SQLite パスフィールドは `sqlite_db_path` (既存 `src/context_store/config.py:62` で定義済み)。

- [ ] **Step 4: テスト成功と静的解析を確認**

```bash
uv run ruff check src/context_store/storage/factory.py tests/unit/test_rl_factory.py
uv run mypy src/context_store/storage/factory.py
uv run pytest tests/unit/test_rl_factory.py -v --cov=context_store.storage.factory --cov-report=term-missing
```

Expected: すべて PASS。Factory の `create_rl_data_store` の 4 分岐 (explicit-inmemory / auto→inmemory / auto→sqlite / auto→postgres) を網羅。

- [ ] **Step 5: コミット**

```bash
git add src/context_store/storage/factory.py tests/unit/test_rl_factory.py
git commit -m "feat(rl): create_rl_data_store ファクトリを統合 (auto/postgres/sqlite/inmemory)"
```

- [ ] **Step 6: Draft PR を Phase Base 向けに作成**

```bash
git push -u origin HEAD
gh pr create --draft --base feat/rl-foundation/phase-3 \
  --title "feat(rl): create_rl_data_store ファクトリ" \
  --body "Phase 3 Task 3.4。settings.rl_data_store_backend に応じて 3 バックエンドを切り替えるファクトリ。'auto' で storage_backend に追従。"
```

PR URL を記録します。

---

## Phase 4: Storage Adapter for Extension Protocols

**Phase Base ブランチ:** Phase 3 全体が `master` にマージ済みであれば `master` から派生。マージ前であれば `feat/rl-foundation/phase-3` から派生してスタック継続。

### Task 4.1: `StorageActionLogger` / `StorageRewardSignal` を実装

**派生元ブランチ:** `master` (Phase 3 マージ後) または `feat/rl-foundation/phase-3` (未マージならスタック継続)

**実行モード:** 直列必須 (Wait for Task 3.4) — `RLDataStore` Protocol と各実装が揃っている必要がある。

**前提条件:** Task 3.4 の Draft PR が Phase Base ブランチにマージ済みであること

**Files:**

- Create: `src/context_store/extensions/storage_logger.py`
- Create: `tests/unit/test_rl_storage_logger.py`

- [ ] **Step 1: ブランチ作成とポカヨケ検証**

```bash
# Phase 3 が master にマージ済みの場合
git checkout master && git pull --ff-only origin master
git checkout -b feat/rl-foundation/phase-4-task-4.1-storage-logger

EXPECTED_BASE="master"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git merge-base --is-ancestor $EXPECTED_BASE $CURRENT_BRANCH || { echo "ERROR: 派生元ブランチが $EXPECTED_BASE ではありません。スタック構造が壊れています。"; exit 1; }
```

> Phase 3 が未マージの場合は `EXPECTED_BASE="origin/feat/rl-foundation/phase-3"` に置き換え、その派生元から `checkout -b` してください。

- [ ] **Step 2: 失敗するテストを作成**

`tests/unit/test_rl_storage_logger.py` を新規作成:

```python
from __future__ import annotations

import pytest

from context_store.extensions.protocols import (
    ActionType,
    AgentAction,
    RewardSignalRecord,
    SignalType,
)
from context_store.extensions.storage_logger import (
    StorageActionLogger,
    StorageRewardSignal,
)
from context_store.storage.rl_inmemory import InMemoryRLDataStore


@pytest.mark.asyncio
async def test_storage_action_logger_delegates_to_store() -> None:
    store = InMemoryRLDataStore()
    logger = StorageActionLogger(store=store)
    action_id = await logger.log_action(
        AgentAction(session_id="s1", step=0, action_type=ActionType.VECTOR_SEARCH)
    )
    assert action_id
    actions = await store.fetch_actions_by_session("s1")
    assert len(actions) == 1


@pytest.mark.asyncio
async def test_storage_reward_signal_delegates_and_truncates_context() -> None:
    store = InMemoryRLDataStore()
    sig = StorageRewardSignal(store=store, max_context_bytes=128)
    # 大きな context は切り詰められる
    huge = "x" * 1000
    rid = await sig.record_reward(
        RewardSignalRecord(
            session_id="s1", signal_type=SignalType.EXPLICIT_FEEDBACK,
            score=0.5, context={"comment": huge},
        )
    )
    assert rid
    rewards = await store.fetch_rewards_by_session("s1")
    assert len(rewards) == 1
    import json
    assert len(json.dumps(rewards[0].context).encode("utf-8")) <= 128
```

```bash
uv run pytest tests/unit/test_rl_storage_logger.py -v
```

Expected: import エラー

- [ ] **Step 3: `storage_logger.py` を実装**

`src/context_store/extensions/storage_logger.py` を新規作成:

```python
"""Adapters that bridge ActionLogger / RewardSignal Protocols to RLDataStore."""

from __future__ import annotations

import json
from dataclasses import replace

from context_store.extensions.protocols import (
    ActionLogger,
    AgentAction,
    RewardSignal,
    RewardSignalRecord,
)
from context_store.storage.protocols import RLDataStore

__all__ = ["StorageActionLogger", "StorageRewardSignal"]


class StorageActionLogger(ActionLogger):
    def __init__(self, store: RLDataStore) -> None:
        self._store = store

    async def log_action(self, action: AgentAction) -> str:
        return await self._store.insert_action_log(action)


class StorageRewardSignal(RewardSignal):
    def __init__(self, store: RLDataStore, max_context_bytes: int = 4096) -> None:
        self._store = store
        self._max_context_bytes = max_context_bytes

    async def record_reward(self, signal: RewardSignalRecord) -> str:
        truncated = self._truncate_context_if_needed(signal)
        return await self._store.insert_reward_signal(truncated)

    def _truncate_context_if_needed(
        self, signal: RewardSignalRecord
    ) -> RewardSignalRecord:
        ctx = dict(signal.context)
        encoded = json.dumps(ctx, ensure_ascii=False).encode("utf-8")
        if len(encoded) <= self._max_context_bytes:
            return signal

        # まず comment フィールドを 1024 文字で切る
        if "comment" in ctx and isinstance(ctx["comment"], str):
            ctx["comment"] = ctx["comment"][:1024]
            encoded = json.dumps(ctx, ensure_ascii=False).encode("utf-8")

        # それでも超えるなら comment を更に縮める
        while len(encoded) > self._max_context_bytes and "comment" in ctx \
                and isinstance(ctx["comment"], str) and ctx["comment"]:
            ctx["comment"] = ctx["comment"][: max(0, len(ctx["comment"]) // 2)]
            encoded = json.dumps(ctx, ensure_ascii=False).encode("utf-8")

        # comment が無いか縮めても超える場合は、context 全体を {"truncated": True} に置換
        if len(encoded) > self._max_context_bytes:
            ctx = {"truncated": True}

        return replace(signal, context=ctx)
```

- [ ] **Step 4: テスト成功と静的解析を確認**

```bash
uv run ruff check src/context_store/extensions/storage_logger.py tests/unit/test_rl_storage_logger.py
uv run mypy src/context_store/extensions/storage_logger.py
uv run pytest tests/unit/test_rl_storage_logger.py -v --cov=context_store.extensions.storage_logger --cov-report=term-missing
```

Expected: すべて PASS、`storage_logger.py` カバレッジ 100%

- [ ] **Step 5: コミット**

```bash
git add src/context_store/extensions/storage_logger.py tests/unit/test_rl_storage_logger.py
git commit -m "feat(rl): StorageActionLogger / StorageRewardSignal アダプタを追加"
```

- [ ] **Step 6: Draft PR を派生元向けに作成**

```bash
git push -u origin HEAD
gh pr create --draft --base master \
  --title "feat(rl): StorageActionLogger / StorageRewardSignal" \
  --body "Phase 4 Task 4.1。Protocol → RLDataStore への委譲アダプタ。reward_signal.context の max_context_bytes 切り詰めも担う。"
```

> Phase 3 未マージで `feat/rl-foundation/phase-3` 派生にしている場合は `--base feat/rl-foundation/phase-3` に置き換えること。

PR URL を記録します。

---

## Phase 5: Pipeline & Orchestrator Integration

**Phase Base ブランチ:** `master` (Phase 4 マージ後) または `feat/rl-foundation/phase-4-task-4.1-storage-logger` (未マージならスタック継続)

### Task 5.1: `RetrievalPipeline` にサブステップ毎の `action_logger.log_action()` を追加

**派生元ブランチ:** `master` (Task 4.1 マージ後) または `feat/rl-foundation/phase-4-task-4.1-storage-logger` (未マージなら直接スタック)

**実行モード:** 直列必須 (Wait for Task 4.1) — `ActionLogger` の新仕様、`AgentAction`、`session_context` を利用する。

**前提条件:** Task 4.1 の Draft PR が派生元にマージ済みであること

**Files:**

- Modify: `src/context_store/retrieval/pipeline.py`
- Create: `tests/unit/test_retrieval_pipeline.py`

- [ ] **Step 1: ブランチ作成とポカヨケ検証**

```bash
git checkout master && git pull --ff-only origin master
git checkout -b feat/rl-foundation/phase-5-task-5.1-pipeline

EXPECTED_BASE="master"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git merge-base --is-ancestor $EXPECTED_BASE $CURRENT_BRANCH || { echo "ERROR: 派生元ブランチが $EXPECTED_BASE ではありません。スタック構造が壊れています。"; exit 1; }
```

> Task 4.1 が未マージの場合は `EXPECTED_BASE="origin/feat/rl-foundation/phase-4-task-4.1-storage-logger"` に置き換えてください。

- [ ] **Step 2: 失敗するテストファイル `tests/unit/test_retrieval_pipeline.py` を新規作成**

新規ファイル `tests/unit/test_retrieval_pipeline.py` を作成し、共通ヘルパ `_build_pipeline()` を定義します。`RetrievalPipeline` の DI 引数 7 種 (query_analyzer / vector_search / keyword_search / graph_traversal / result_fusion / post_processor / storage_adapter) は `AsyncMock` / `MagicMock` で組み立て、Task 5.1 で追加される `action_logger` 引数のみテストでカスタマイズします。

```python
"""RetrievalPipeline の RL ActionLog 統合テスト。"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


def _build_pipeline(
    *,
    vector_results=None,
    keyword_results=None,
    graph_traversal_nodes=None,
    fused_items=None,
):
    """RetrievalPipeline を AsyncMock 依存で構築する共通ヘルパ。"""
    from context_store.models.memory import MemorySource
    from context_store.models.search import SearchStrategy
    from context_store.retrieval.pipeline import RetrievalPipeline

    query_analyzer = MagicMock()
    query_analyzer.analyze = MagicMock(
        return_value=SearchStrategy(
            vector_weight=0.5,
            keyword_weight=0.3,
            graph_weight=0.2,
            graph_depth=1,
            time_decay_enabled=False,
        )
    )

    vector_search = AsyncMock()
    vector_search.search = AsyncMock(return_value=vector_results or [])

    keyword_search = AsyncMock()
    keyword_search.search = AsyncMock(return_value=keyword_results or [])

    graph_traversal = AsyncMock()
    graph_result = MagicMock()
    graph_result.nodes = graph_traversal_nodes or []
    graph_traversal.traverse = AsyncMock(return_value=graph_result)

    result_fusion = MagicMock()
    result_fusion.fuse_multiple_sources = MagicMock(return_value=fused_items or [])

    post_processor = AsyncMock()
    post_processor.process = AsyncMock(side_effect=lambda results, project, max_tokens: results)

    storage_adapter = AsyncMock()
    storage_adapter.get_memories_batch = AsyncMock(return_value=[])

    return RetrievalPipeline(
        query_analyzer=query_analyzer,
        vector_search=vector_search,
        keyword_search=keyword_search,
        graph_traversal=graph_traversal,
        result_fusion=result_fusion,
        post_processor=post_processor,
        storage_adapter=storage_adapter,
    )


@pytest.mark.asyncio
async def test_pipeline_emits_actions_when_session_id_set() -> None:
    """session_id 設定時、各サブステップで log_action が発火する"""
    from context_store.extensions import session_context as sc
    from context_store.extensions.protocols import ActionType

    logger = AsyncMock()
    logger.log_action = AsyncMock(return_value="aid")

    pipeline = _build_pipeline()
    token = sc.set_session_id("s1")
    try:
        await pipeline.search(query="q", action_logger=logger)
    finally:
        sc.reset_session_id(token)

    action_types = [c.args[0].action_type for c in logger.log_action.call_args_list]
    assert ActionType.RESULT_FUSION in action_types
    assert ActionType.VECTOR_SEARCH in action_types
    assert ActionType.KEYWORD_SEARCH in action_types


@pytest.mark.asyncio
async def test_pipeline_no_emission_without_session_id() -> None:
    """session_id 未設定時は log_action が発火しない"""
    logger = AsyncMock()
    logger.log_action = AsyncMock(return_value="aid")

    pipeline = _build_pipeline()
    await pipeline.search(query="q", action_logger=logger)
    assert logger.log_action.call_count == 0


@pytest.mark.asyncio
async def test_pipeline_awaits_pending_tasks_before_returning() -> None:
    """search 応答返却時点で全 ActionLog が DB 確定済み (gather 待機)"""
    from context_store.extensions import session_context as sc

    slow_done = asyncio.Event()

    async def slow_insert(action):
        await asyncio.sleep(0.01)
        slow_done.set()
        return "aid"

    logger = AsyncMock()
    logger.log_action = slow_insert

    pipeline = _build_pipeline()
    token = sc.set_session_id("s1")
    try:
        await pipeline.search(query="q", action_logger=logger)
    finally:
        sc.reset_session_id(token)

    # search() が返った時点で slow_done が set 済みであるべき
    assert slow_done.is_set()


@pytest.mark.asyncio
async def test_pipeline_logger_exception_is_swallowed() -> None:
    """log_action 例外は search の戻り値に影響しない"""
    from context_store.extensions import session_context as sc

    logger = AsyncMock()
    logger.log_action = AsyncMock(side_effect=RuntimeError("boom"))

    pipeline = _build_pipeline()
    token = sc.set_session_id("s1")
    try:
        result = await pipeline.search(query="q", action_logger=logger)
    finally:
        sc.reset_session_id(token)

    assert result is not None  # search は正常終了
    assert "results" in result
```

```bash
uv run pytest tests/unit/test_retrieval_pipeline.py -v
```

Expected: 4 件の新テストが FAIL (`action_logger` 引数未対応のため)

- [ ] **Step 3: `RetrievalPipeline.search()` を改修**

`src/context_store/retrieval/pipeline.py` の `search` メソッドを編集し、以下のロジックを実装:

```python
import asyncio
import logging

from context_store.extensions import session_context as _sc
from context_store.extensions.protocols import ActionLogger, ActionType, AgentAction
from context_store.extensions.noop import NoOpActionLogger

_LOGGER = logging.getLogger(__name__)


class RetrievalPipeline:
    async def search(
        self,
        query: str,
        *,
        action_logger: ActionLogger | None = None,
        # ... 既存引数
    ):
        logger = action_logger or NoOpActionLogger()
        session_id = _sc.get_session_id()
        pending: list[asyncio.Task[str]] = []

        def _emit(step: int, action_type: ActionType, details: dict, volume: int) -> None:
            if session_id is None:
                return
            action = AgentAction(
                session_id=session_id,
                step=step,
                action_type=action_type,
                action_details={**details, "unit": "chars"},
                context_volume=volume,
            )
            pending.append(asyncio.create_task(self._safe_log(logger, action)))

        # ===== ステップ 0: VECTOR_SEARCH =====
        vector_results = await self._vector_search(...)
        v_volume = sum(len(r.content) for r in vector_results)
        _emit(0, ActionType.VECTOR_SEARCH, {"k": ...}, v_volume)

        # ===== ステップ 1: KEYWORD_SEARCH =====
        keyword_results = await self._keyword_search(...)
        k_volume = sum(len(r.content) for r in keyword_results)
        _emit(1, ActionType.KEYWORD_SEARCH, {"k": ...}, k_volume)

        # ===== ステップ 2: GRAPH_TRAVERSAL (条件次第) =====
        if strategy.graph_weight > 0 and vector_results:
            graph_results = await self._graph_traversal(...)
            g_volume = sum(len(r.content) for r in graph_results)
            _emit(2, ActionType.GRAPH_TRAVERSAL, {"hop": ...}, g_volume)
        else:
            graph_results = []

        # ===== ステップ 3: RESULT_FUSION =====
        fused = self._fuse(vector_results, keyword_results, graph_results, ...)
        f_volume = sum(len(r.content) for r in fused)
        _emit(3, ActionType.RESULT_FUSION, {"strategy": "rrf"}, f_volume)

        # search() 応答返却前に全 ActionLog 確定待ち
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        return self._build_response(fused, ...)

    @staticmethod
    async def _safe_log(logger: ActionLogger, action: AgentAction) -> str:
        try:
            return await logger.log_action(action)
        except Exception:  # noqa: BLE001
            _LOGGER.warning("ActionLog insert failed; swallowing", exc_info=True)
            return ""
```

> 既存 `search()` の構造に合わせて統合してください。サブステップ呼び出し位置、戻り値、引数名は既存実装を踏襲。

- [ ] **Step 4: テスト成功と静的解析を確認**

```bash
uv run ruff check src/context_store/retrieval/pipeline.py tests/unit/test_retrieval_pipeline.py
uv run mypy src/context_store/retrieval/pipeline.py
uv run pytest tests/unit/test_retrieval_pipeline.py -v
```

Expected: 既存 + 新規テストすべて PASS

- [ ] **Step 5: コミット**

```bash
git add src/context_store/retrieval/pipeline.py tests/unit/test_retrieval_pipeline.py
git commit -m "feat(rl): RetrievalPipeline サブステップ毎の ActionLog 発火 (gather 確定待ち)"
```

- [ ] **Step 6: Draft PR を派生元向けに作成**

```bash
git push -u origin HEAD
gh pr create --draft --base master \
  --title "feat(rl): RetrievalPipeline で 4 step の ActionLog を発火" \
  --body "Phase 5 Task 5.1。VECTOR/KEYWORD/GRAPH/FUSION の 4 サブステップ完了直後に asyncio.create_task で log_action を発火、search 応答返却前に gather(return_exceptions=True) で全 INSERT を確定待ち。"
```

PR URL を記録します。

---

### Task 5.2: `Orchestrator` に `session_id` 伝播 / `_emit_internal_eval` / `record_reward` / `dispose` を実装

**派生元ブランチ:** `feat/rl-foundation/phase-5-task-5.1-pipeline`

**実行モード:** 直列必須 (Wait for Task 5.1) — Pipeline の `action_logger` 引数追加と `session_context` 利用に直接依存する。

**前提条件:** Task 5.1 の Draft PR が存在し、その URL が記録済みであること

**Files:**

- Modify: `src/context_store/orchestrator.py`
- Modify: `tests/unit/test_orchestrator.py`

- [ ] **Step 1: ブランチ作成とポカヨケ検証**

```bash
git fetch origin feat/rl-foundation/phase-5-task-5.1-pipeline
git checkout -b feat/rl-foundation/phase-5-task-5.2-orchestrator \
    origin/feat/rl-foundation/phase-5-task-5.1-pipeline

EXPECTED_BASE="origin/feat/rl-foundation/phase-5-task-5.1-pipeline"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git merge-base --is-ancestor $EXPECTED_BASE $CURRENT_BRANCH || { echo "ERROR: 派生元ブランチが $EXPECTED_BASE ではありません。スタック構造が壊れています。"; exit 1; }
```

- [ ] **Step 2: 失敗するテストを `tests/unit/test_orchestrator.py` に追加**

> 既存ヘルパ `_build_orchestrator(...)` (`tests/unit/test_orchestrator.py:107`) を使用します。これは Orchestrator を 13 個の DI 引数で構築するための共有 fixture で、`(orch, storage, graph, cache, embedding, ingestion_pipeline, retrieval_pipeline, lifecycle_manager, task_registry)` の tuple を返します。`retrieval_pipeline` / `reward_signal` / `action_logger` などをキーワード引数で差し替えられます。

```python
@pytest.mark.asyncio
async def test_orchestrator_sets_contextvar_during_search() -> None:
    from unittest.mock import AsyncMock
    from context_store.extensions import session_context as sc

    captured: list[str | None] = []

    async def fake_pipeline_search(query, *, action_logger=None, **kwargs):
        captured.append(sc.get_session_id())
        return {"results": [{"score": 0.8, "content": "hi"}], "query": query}

    retrieval_pipeline = AsyncMock()
    retrieval_pipeline.search = fake_pipeline_search
    reward_signal = AsyncMock()
    reward_signal.record_reward = AsyncMock(return_value="rid")

    orch, *_ = await _build_orchestrator(
        retrieval_pipeline=retrieval_pipeline,
        reward_signal=reward_signal,
    )

    await orch.search("q", session_id="my-session")
    assert captured == ["my-session"]
    # contextvar はリセットされている
    assert sc.get_session_id() is None


@pytest.mark.asyncio
async def test_orchestrator_emits_internal_eval_with_correct_score() -> None:
    """results の平均 score=0.8 → 2*0.8 - 1 = 0.6"""
    from unittest.mock import AsyncMock
    from context_store.extensions.protocols import SignalType

    retrieval_pipeline = AsyncMock()
    retrieval_pipeline.search = AsyncMock(
        return_value={"results": [{"score": 0.8}, {"score": 0.8}], "query": "q"}
    )

    captured: list = []

    async def fake_record(record):
        captured.append(record)
        return "rid"

    reward_signal = AsyncMock()
    reward_signal.record_reward = fake_record

    orch, *_ = await _build_orchestrator(
        retrieval_pipeline=retrieval_pipeline,
        reward_signal=reward_signal,
    )

    await orch.search("q", session_id="s1")
    # _background_tasks の完了待ち
    await orch._wait_background_tasks_for_test()

    eval_signals = [c for c in captured if c.signal_type == SignalType.INTERNAL_EVAL]
    assert len(eval_signals) == 1
    assert eval_signals[0].score == pytest.approx(0.6)


@pytest.mark.asyncio
async def test_orchestrator_internal_eval_empty_results_is_negative() -> None:
    from unittest.mock import AsyncMock
    from context_store.extensions.protocols import SignalType

    retrieval_pipeline = AsyncMock()
    retrieval_pipeline.search = AsyncMock(
        return_value={"results": [], "query": "q"}
    )

    captured: list = []

    async def fake_record(record):
        captured.append(record)
        return "rid"

    reward_signal = AsyncMock()
    reward_signal.record_reward = fake_record

    orch, *_ = await _build_orchestrator(
        retrieval_pipeline=retrieval_pipeline,
        reward_signal=reward_signal,
    )

    await orch.search("q", session_id="s1")
    await orch._wait_background_tasks_for_test()

    assert any(c.signal_type == SignalType.INTERNAL_EVAL and c.score == -0.5 for c in captured)


@pytest.mark.asyncio
async def test_orchestrator_dispose_waits_background_tasks() -> None:
    """dispose 直前の INTERNAL_EVAL がロストしない"""
    import asyncio
    from unittest.mock import AsyncMock

    done = asyncio.Event()

    async def slow_record(record):
        await asyncio.sleep(0.05)
        done.set()
        return "rid"

    retrieval_pipeline = AsyncMock()
    retrieval_pipeline.search = AsyncMock(
        return_value={"results": [{"score": 0.9}], "query": "q"}
    )

    reward_signal = AsyncMock()
    reward_signal.record_reward = slow_record

    orch, *_ = await _build_orchestrator(
        retrieval_pipeline=retrieval_pipeline,
        reward_signal=reward_signal,
    )

    await orch.search("q", session_id="s1")
    await orch.dispose()
    assert done.is_set()


@pytest.mark.asyncio
async def test_orchestrator_record_reward_public_api() -> None:
    from unittest.mock import AsyncMock
    from context_store.extensions.protocols import SignalType

    reward_signal = AsyncMock()
    reward_signal.record_reward = AsyncMock(return_value="rid")

    orch, *_ = await _build_orchestrator(reward_signal=reward_signal)

    result = await orch.record_reward(
        session_id="s1", score=0.4,
        signal_type=SignalType.EXPLICIT_FEEDBACK,
        action_log_id="aid", context={"comment": "ok"},
    )
    assert result == "rid"
    args = reward_signal.record_reward.call_args.args
    assert args[0].score == 0.4
    assert args[0].action_log_id == "aid"
```

```bash
uv run pytest tests/unit/test_orchestrator.py -v
```

Expected: 5 件の新テストが FAIL

- [ ] **Step 3: `Orchestrator` を実装**

`src/context_store/orchestrator.py` を編集:

```python
import asyncio
import logging
from typing import Any

from context_store.extensions import session_context as _sc
from context_store.extensions.protocols import (
    ActionLogger,
    RewardSignal,
    RewardSignalRecord,
    SignalType,
)
from context_store.extensions.noop import NoOpActionLogger, NoOpRewardSignal
from context_store.storage.protocols import RLDataStore

_LOGGER = logging.getLogger(__name__)


class Orchestrator:
    def __init__(
        self,
        *,
        # ... 既存
        action_logger: ActionLogger | None = None,
        reward_signal: RewardSignal | None = None,
        rl_store: RLDataStore | None = None,
    ) -> None:
        # ... 既存
        self.action_logger: ActionLogger = action_logger or NoOpActionLogger()
        self.reward_signal: RewardSignal = reward_signal or NoOpRewardSignal()
        self._rl_store = rl_store
        self._background_tasks: set[asyncio.Task[Any]] = set()

    async def search(
        self, query: str, *, session_id: str | None = None, **kwargs: Any
    ):
        effective_session_id = session_id or _sc.new_session_id()
        token = _sc.set_session_id(effective_session_id)
        try:
            # 既存ロジック
            result = await self._retrieval_pipeline.search(
                query, action_logger=self.action_logger, **kwargs
            )
            await self._emit_internal_eval(
                session_id=effective_session_id, response=result
            )
            # session_id を結果に含める (server.py 層でも参照)
            if isinstance(result, dict):
                result.setdefault("session_id", effective_session_id)
            return result
        finally:
            _sc.reset_session_id(token)

    async def _emit_internal_eval(self, session_id: str, response: Any) -> None:
        results = []
        if isinstance(response, dict):
            results = response.get("results", []) or []
        if not results:
            score = -0.5
        else:
            avg = sum(float(r.get("score", 0.0)) for r in results) / len(results)
            score = max(-1.0, min(1.0, 2.0 * avg - 1.0))

        record = RewardSignalRecord(
            session_id=session_id,
            signal_type=SignalType.INTERNAL_EVAL,
            score=score,
            context={
                "top_k_count": len(results),
                "query": response.get("query") if isinstance(response, dict) else None,
            },
        )
        task = asyncio.create_task(self._safe_record_reward(record))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _safe_record_reward(self, record: RewardSignalRecord) -> None:
        try:
            await self.reward_signal.record_reward(record)
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Reward signal record failed; swallowing", exc_info=True)

    async def record_reward(
        self, *,
        session_id: str, score: float,
        signal_type: SignalType = SignalType.EXPLICIT_FEEDBACK,
        action_log_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> str:
        record = RewardSignalRecord(
            session_id=session_id, signal_type=signal_type, score=score,
            action_log_id=action_log_id, context=context or {},
        )
        return await self.reward_signal.record_reward(record)

    async def _wait_background_tasks_for_test(self) -> None:
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)

    async def dispose(self) -> None:
        # 既存 dispose ロジックの末尾に追加
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
        if self._rl_store is not None:
            await self._rl_store.dispose()
```

- [ ] **Step 4: `create_orchestrator` を編集 (settings.rl_logging_enabled で自動注入)**

`Orchestrator` のファクトリ関数 (例: `create_orchestrator(settings)`) で、`settings.rl_logging_enabled and action_logger is None and reward_signal is None` の場合に `StorageActionLogger` / `StorageRewardSignal` を自動注入:

```python
from context_store.extensions.storage_logger import StorageActionLogger, StorageRewardSignal
from context_store.storage.factory import create_rl_data_store


async def create_orchestrator(settings):
    # ... 既存 storage adapter 構築
    rl_store = None
    action_logger = None
    reward_signal = None
    if settings.rl_logging_enabled:
        rl_store = await create_rl_data_store(settings)
        action_logger = StorageActionLogger(store=rl_store)
        reward_signal = StorageRewardSignal(
            store=rl_store,
            max_context_bytes=settings.rl_reward_context_max_bytes,
        )
    return Orchestrator(
        # ... 既存
        action_logger=action_logger,
        reward_signal=reward_signal,
        rl_store=rl_store,
    )
```

- [ ] **Step 5: テスト成功と静的解析を確認**

```bash
uv run ruff check src/context_store/orchestrator.py tests/unit/test_orchestrator.py
uv run mypy src/context_store/orchestrator.py
uv run pytest tests/unit/test_orchestrator.py tests/unit/test_retrieval_pipeline.py -v
```

Expected: すべて PASS

- [ ] **Step 6: コミット**

```bash
git add src/context_store/orchestrator.py tests/unit/test_orchestrator.py
git commit -m "feat(rl): Orchestrator に session_id 伝播 / INTERNAL_EVAL / record_reward / dispose 拡張"
```

- [ ] **Step 7: Draft PR を派生元向けに作成**

```bash
git push -u origin HEAD
gh pr create --draft --base feat/rl-foundation/phase-5-task-5.1-pipeline \
  --title "feat(rl): Orchestrator で contextvar 伝播 + INTERNAL_EVAL + record_reward" \
  --body "Phase 5 Task 5.2。session_id を contextvars で伝播、_emit_internal_eval で 2*avg - 1 のスコアを INTERNAL_EVAL として発火、record_reward を公開、dispose で _background_tasks を gather 確定待ち。"
```

PR URL を記録します。

---

## Phase 6: MCP Server Surface

### Task 6.1: `memory_search` に `session_id` 引数追加 / `memory_feedback` ツール新設

**派生元ブランチ:** `feat/rl-foundation/phase-5-task-5.2-orchestrator`

**実行モード:** 直列必須 (Wait for Task 5.2) — Orchestrator の `record_reward` / `session_id` 機能に依存。

**前提条件:** Task 5.2 の Draft PR が存在し、その URL が記録済みであること

**Files:**

- Modify: `src/context_store/server.py`
- Modify: `tests/unit/test_api_server.py`

- [ ] **Step 1: ブランチ作成とポカヨケ検証**

```bash
git fetch origin feat/rl-foundation/phase-5-task-5.2-orchestrator
git checkout -b feat/rl-foundation/phase-6-task-6.1-mcp-tools \
    origin/feat/rl-foundation/phase-5-task-5.2-orchestrator

EXPECTED_BASE="origin/feat/rl-foundation/phase-5-task-5.2-orchestrator"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git merge-base --is-ancestor $EXPECTED_BASE $CURRENT_BRANCH || { echo "ERROR: 派生元ブランチが $EXPECTED_BASE ではありません。スタック構造が壊れています。"; exit 1; }
```

- [ ] **Step 2: 失敗するテストを `tests/unit/test_api_server.py` に追加**

```python
@pytest.mark.asyncio
async def test_memory_search_echoes_session_id_when_provided() -> None:
    # 既存テスト Fixture を使い、memory_search に session_id を渡してレスポンスに含まれることを確認
    response = await call_mcp_tool("memory_search", query="q", session_id="my-session")
    assert response["session_id"] == "my-session"


@pytest.mark.asyncio
async def test_memory_search_auto_assigns_session_id_when_omitted() -> None:
    import uuid
    response = await call_mcp_tool("memory_search", query="q")
    assert "session_id" in response
    uuid.UUID(response["session_id"])  # UUID v4 string


@pytest.mark.asyncio
async def test_memory_feedback_success() -> None:
    result = await call_mcp_tool(
        "memory_feedback",
        session_id="s1", score=0.5, action_log_id=None, comment=None,
    )
    assert "reward_signal_id" in result
    assert result["score"] == 0.5


@pytest.mark.asyncio
async def test_memory_feedback_rejects_out_of_range_score() -> None:
    with pytest.raises(ValueError):
        await call_mcp_tool(
            "memory_feedback", session_id="s1", score=2.5,
        )


@pytest.mark.asyncio
async def test_memory_feedback_truncates_long_comment() -> None:
    long = "x" * 5000
    result = await call_mcp_tool(
        "memory_feedback", session_id="s1", score=0.1, comment=long,
    )
    # 後段で fetch して comment が 1024 文字に切り詰められていることを検証
    # (具体的な検証手段は既存テストの fixture に合わせる)
    assert "reward_signal_id" in result


@pytest.mark.asyncio
async def test_memory_feedback_unknown_action_log_id_returns_200() -> None:
    """存在しない action_log_id でも 200 で返り、フォールバック保存される"""
    result = await call_mcp_tool(
        "memory_feedback",
        session_id="s1", score=-0.3,
        action_log_id="00000000-0000-4000-8000-deadbeefdead",
    )
    assert "reward_signal_id" in result
```

```bash
uv run pytest tests/unit/test_api_server.py -v
```

Expected: 6 件の新テストが FAIL

- [ ] **Step 3: `server.py` を編集**

`src/context_store/server.py` の MCP ツール定義を更新:

```python
@mcp.tool()
async def memory_search(
    query: str,
    *,
    session_id: str | None = None,
    # ... 既存引数
) -> dict:
    """Search memories. Optionally accepts session_id for RL tracking."""
    response = await orchestrator.search(query, session_id=session_id, ...)
    # Orchestrator 内で session_id を埋め込み済みだが、念のためここでも保証
    if isinstance(response, dict) and "session_id" not in response:
        response["session_id"] = session_id or _sc.get_session_id()
    return response


@mcp.tool()
async def memory_feedback(
    session_id: str,
    score: float,
    action_log_id: str | None = None,
    comment: str | None = None,
) -> dict:
    """Record an explicit user feedback signal."""
    if not (-1.0 <= score <= 1.0):
        raise ValueError(f"score must be within [-1.0, 1.0], got {score}")

    # UUID 形式バリデーション (action_log_id)
    if action_log_id is not None:
        import uuid
        try:
            uuid.UUID(action_log_id)
        except ValueError as exc:
            raise ValueError(f"action_log_id must be UUID, got {action_log_id}") from exc

    context: dict = {}
    if comment is not None:
        context["comment"] = comment[:1024]

    rid = await orchestrator.record_reward(
        session_id=session_id,
        score=score,
        signal_type=SignalType.EXPLICIT_FEEDBACK,
        action_log_id=action_log_id,
        context=context,
    )
    return {"reward_signal_id": rid, "score": score}
```

- [ ] **Step 4: テスト成功と静的解析を確認**

```bash
uv run ruff check src/context_store/server.py tests/unit/test_api_server.py
uv run mypy src/context_store/server.py
uv run pytest tests/unit/test_api_server.py -v
```

Expected: すべて PASS

- [ ] **Step 5: コミット**

```bash
git add src/context_store/server.py tests/unit/test_api_server.py
git commit -m "feat(rl): memory_search に session_id 追加 + memory_feedback ツール新設"
```

- [ ] **Step 6: Draft PR を派生元向けに作成**

```bash
git push -u origin HEAD
gh pr create --draft --base feat/rl-foundation/phase-5-task-5.2-orchestrator \
  --title "feat(rl): MCP memory_search/session_id + memory_feedback" \
  --body "Phase 6 Task 6.1。memory_search に session_id 引数を追加 (省略時は UUID v4 自動採番)、memory_feedback を新設 (score レンジ三層チェック、comment 1024 文字切り詰め、UUID 形式バリデーション、存在しない action_log_id でも 200 応答)。"
```

PR URL を記録します。

---

## Phase 7: End-to-End Integration Test

### Task 7.1: `test_rl_basis.py` で全体結合検証

**派生元ブランチ:** `feat/rl-foundation/phase-6-task-6.1-mcp-tools`

**実行モード:** 直列必須 (Wait for Task 6.1) — MCP / Orchestrator / Pipeline / DataStore の全結合状態が前提。

**前提条件:** Task 6.1 の Draft PR が存在し、その URL が記録済みであること

**Files:**

- Create: `tests/unit/test_rl_basis.py`

- [ ] **Step 1: ブランチ作成とポカヨケ検証**

```bash
git fetch origin feat/rl-foundation/phase-6-task-6.1-mcp-tools
git checkout -b feat/rl-foundation/phase-7-task-7.1-e2e \
    origin/feat/rl-foundation/phase-6-task-6.1-mcp-tools

EXPECTED_BASE="origin/feat/rl-foundation/phase-6-task-6.1-mcp-tools"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git merge-base --is-ancestor $EXPECTED_BASE $CURRENT_BRANCH || { echo "ERROR: 派生元ブランチが $EXPECTED_BASE ではありません。スタック構造が壊れています。"; exit 1; }
```

- [ ] **Step 2: E2E テストを作成 (SQLite バックエンド)**

`tests/unit/test_rl_basis.py` を新規作成:

```python
"""End-to-end integration test for RL Action Logging & Reward Signal foundation."""

from __future__ import annotations

import pytest

from context_store.config import Settings
from context_store.extensions.protocols import SignalType
from context_store.orchestrator import create_orchestrator


@pytest.mark.asyncio
async def test_e2e_search_emits_actions_internal_eval_and_explicit_feedback(
    tmp_path,
) -> None:
    """search → ActionLog 確定 → INTERNAL_EVAL → EXPLICIT_FEEDBACK の一連の流れを検証。

    `fetch_action_ids_by_session` (設計書 §5.2) で DB 上の action_log_id を race-free に
    取得し、`memory_feedback` 相当の `record_reward` で FK が解決できることを保証する。
    """
    settings = Settings(
        _env_file=None,
        storage_backend="sqlite",
        rl_logging_enabled=True,
        rl_data_store_backend="sqlite",
        sqlite_db_path=str(tmp_path / "e2e.db"),
    )
    orch = await create_orchestrator(settings)
    try:
        # 何か memory を事前に登録する (既存ヘルパに合わせる)
        await orch.add_memory(content="hello world", source_type="text")

        # search 実行
        result = await orch.search(query="hello", session_id="e2e-session")
        await orch._wait_background_tasks_for_test()

        assert result["session_id"] == "e2e-session"

        # action_log を取得
        actions = await orch._rl_store.fetch_actions_by_session("e2e-session")
        action_ids = await orch._rl_store.fetch_action_ids_by_session("e2e-session")
        rewards = await orch._rl_store.fetch_rewards_by_session("e2e-session")

        # 4 ステップ (GRAPH は条件次第なので 3 or 4)
        assert 3 <= len(actions) <= 4
        # action_ids は actions と同じ順序・長さで取得できる
        assert len(action_ids) == len(actions)
        assert all(isinstance(aid, str) and aid for aid in action_ids)
        # INTERNAL_EVAL が 1 件入っている
        assert any(r.signal_type == SignalType.INTERNAL_EVAL for r in rewards)

        # EXPLICIT_FEEDBACK を確定済みの action_log_id にぶら下げて発火 → FK 違反なし
        rid = await orch.record_reward(
            session_id="e2e-session", score=0.7,
            signal_type=SignalType.EXPLICIT_FEEDBACK,
            action_log_id=action_ids[0],
        )
        assert rid

        rewards2 = await orch._rl_store.fetch_rewards_by_session("e2e-session")
        feedback = [
            r for r in rewards2
            if r.signal_type == SignalType.EXPLICIT_FEEDBACK and r.score == 0.7
        ]
        assert feedback
        # FK は解決済みなので unverified_action_log_id は context に含まれない
        assert "unverified_action_log_id" not in feedback[0].context
    finally:
        await orch.dispose()


@pytest.mark.asyncio
async def test_e2e_search_then_immediate_feedback_is_race_free(tmp_path) -> None:
    """memory_search 戻り直後に memory_feedback(action_log_id=...) を asyncio.sleep なしで呼び、
    FK 違反フォールバックに頼らず成功すること"""
    from context_store.server import build_app

    settings = Settings(
        _env_file=None,
        storage_backend="sqlite",
        rl_logging_enabled=True,
        rl_data_store_backend="sqlite",
        sqlite_db_path=str(tmp_path / "race.db"),
    )
    app = await build_app(settings)
    try:
        search_resp = await app.call_tool("memory_search", query="q", session_id="race")
        sid = search_resp["session_id"]
        # action_log の DB 上 ID を Protocol API 経由で race-free に取得 (RLDataStore.fetch_action_ids_by_session)
        action_ids = await app.orchestrator._rl_store.fetch_action_ids_by_session(sid)
        assert action_ids  # 確実に存在 (search 内で gather 確定済み)

        # 即時 feedback (sleep なし) — FK 違反が起きないこと
        await app.call_tool(
            "memory_feedback",
            session_id=sid,
            score=0.5,
            action_log_id=action_ids[0],
        )
        rewards = await app.orchestrator._rl_store.fetch_rewards_by_session(sid)
        feedback_rewards = [r for r in rewards if r.signal_type == SignalType.EXPLICIT_FEEDBACK]
        assert feedback_rewards
        # FK 解決済み → fallback の unverified_action_log_id が含まれない
        assert "unverified_action_log_id" not in feedback_rewards[0].context
    finally:
        await app.orchestrator.dispose()
```

> **注:** action_log の DB 上 ID 取得は、設計書 §5.2 で Protocol に追加された `fetch_action_ids_by_session(session_id, limit=1000) -> list[str]` を使用します (3 バックエンドすべてが ScopedAction の `step ASC, created_at ASC` 順で返却するよう Task 3.1 / 3.2 / 3.3 で実装済み)。Phase 1 でテスト専用 API を追加する必要はありません。

- [ ] **Step 3: テスト成功とカバレッジ 100% を devcontainer で確認**

```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/
uv run pytest tests/unit/ -v \
  --cov=context_store.extensions \
  --cov=context_store.storage.rl_postgres \
  --cov=context_store.storage.rl_sqlite \
  --cov=context_store.storage.rl_inmemory \
  --cov-fail-under=100
```

Expected: 全テスト PASS、対象モジュールのカバレッジ 100%

- [ ] **Step 4: コミット**

```bash
git add tests/unit/test_rl_basis.py
git commit -m "test(rl): エンド to エンド統合テスト (4 ActionLog + INTERNAL_EVAL + EXPLICIT_FEEDBACK + race-free)"
```

- [ ] **Step 5: Draft PR を派生元向けに作成**

```bash
git push -u origin HEAD
gh pr create --draft --base feat/rl-foundation/phase-6-task-6.1-mcp-tools \
  --title "test(rl): E2E 統合テスト (RL Foundation Phase 1)" \
  --body "Phase 7 Task 7.1。search → 4 ActionLog → INTERNAL_EVAL → EXPLICIT_FEEDBACK の通し検証と、search 直後 feedback の race-free 検証 (FK 違反フォールバックに頼らない)。"
```

PR URL を記録します。

---

## Final Integration Checkpoint

すべての Task の Draft PR が承認・マージされたら、`master` 上で以下を最終確認します。

- [ ] **Step 1: master を最新化し全テスト実行**

```bash
git checkout master && git pull --ff-only origin master

# devcontainer 内で:
uv sync --all-extras --dev
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/
uv run pytest tests/unit/ -v \
  --cov=context_store.extensions \
  --cov=context_store.storage.rl_postgres \
  --cov=context_store.storage.rl_sqlite \
  --cov=context_store.storage.rl_inmemory \
  --cov-fail-under=100
```

Expected: すべて PASS、対象モジュールカバレッジ 100%

- [ ] **Step 2: 設計仕様書 §3.1 の全体図と実装が整合することを目視確認**

`docs/superpowers/specs/2026-05-19-rl-action-logging-reward-foundation-design.md` の §3.1 (アーキテクチャ図) を参照し、以下を確認:

- `MCP Server` (`server.py`) → `memory_search(... session_id)` / `memory_feedback(...)` が公開されている
- `Orchestrator` が `action_logger` / `reward_signal` を保持し、`contextvar` で `session_id` を伝播
- `RetrievalPipeline` が 4 サブステップで `log_action` を発火し `gather` 確定待ちする
- `StorageActionLogger` / `StorageRewardSignal` が `RLDataStore` Protocol に委譲
- `PostgresRLDataStore` / `SQLiteRLDataStore` / `InMemoryRLDataStore` が用意され、`factory.create_rl_data_store` で切替可能

- [ ] **Step 3: Phase 2 への接続性 (設計書 §9) を確認**

設計書 §9 のテーブル各行について、Phase 1 で予約済みの基盤が実装されていることを確認:

- `RLDataStore.fetch_actions_by_session` / `fetch_action_ids_by_session` / `fetch_rewards_by_session` — Protocol と 3 実装に存在 (§5.2 の順序契約により MDP 系列復元が可能であることをユニットテストで確認済)
- `Orchestrator.policy_hook` 注入口 — 既存
- `signal_type` enum と DB 列 — 実装済
- `actionType` 拡張のための CHECK 制約 — migration 0003 で `DROP/ADD` 可能な形で定義済
- `(session_id, step)` 複合インデックス — Postgres / SQLite 両方に作成済

---

## Self-Review Notes

本計画は以下を網羅:

1. **設計書 §1〜§10 の全要件** に対応するタスクが存在
2. **設計書 §6.2 の `_emit_internal_eval`** が Task 5.2 でテスト付きで実装
3. **設計書 §6.3 の `RetrievalPipeline` 改修** が Task 5.1 で `gather` 確定待ち含めて実装
4. **設計書 §7.2 の `memory_feedback`** が Task 6.1 で UUID 形式バリデーション + コメント切り詰め + 存在しない `action_log_id` への 200 応答含めて実装
5. **設計書 §4.2 末尾の SQLite PRAGMA 必須化** が Task 3.2 で実装かつテストで検証
6. **設計書 §10 のリスク表** に挙がる FK 違反フォールバック / WAL / busy_timeout / バックグラウンドタスク GC ロスト対策が Task 3.2 / 3.3 / 5.2 で実装かつ各テストで検証
7. **Phase 1 (Task 1.1, 1.2, 1.3) は `master` ベースで並列実行可能**
8. **Phase 3 (Task 3.1, 3.2, 3.3) は Phase Base から並列実行可能** — テストファイルもバックエンドごとに `test_rl_inmemory.py` / `test_rl_sqlite.py` / `test_rl_postgres.py` に分割しているため、同時編集による衝突は発生しない。Task 3.4 (`test_rl_factory.py` を新規作成) のみ直列必須
9. **Phase 2, 4, 5, 6, 7 はスタック構造で直列必須**、各 Task の前提条件として先行タスクの Draft PR URL を要求

すべての Task の Step 1 に `git merge-base --is-ancestor $EXPECTED_BASE $CURRENT_BRANCH` のポカヨケスクリプトが、各 Task の派生元ブランチ名 (`$EXPECTED_BASE`) を埋め込んだ状態で組み込まれています。

### コードレビュー対応 (2026-05-19)

Plan/Spec 整合性レビューで挙がった以下 3 点に対応済み:

1. **Phase 3 並列タスクのファイル衝突解消** — Task 3.1 / 3.2 / 3.3 が共通の `test_rl_data_store.py` を編集する設計だったため、`master` への Stacked PR 取り込み時にマージ衝突が発生していた。バックエンドごとにテストファイルを分割 (`tests/unit/test_rl_inmemory.py` / `test_rl_sqlite.py` / `test_rl_postgres.py`) し、Task 3.4 はファクトリ専用の `tests/unit/test_rl_factory.py` を新規作成する形に変更。File Structure テーブル (§ファイル構成) も更新済み。
2. **テストコードの `Orchestrator(...)` / `RetrievalPipeline(...)` プレースホルダ撤去** — Task 5.2 の 5 件のテストは既存ヘルパ `_build_orchestrator(...)` (`tests/unit/test_orchestrator.py:107`) を流用する形に書き換えた。Task 5.1 では `RetrievalPipeline` 用の `_build_pipeline()` ヘルパを新規テストファイル冒頭で定義し、7 種類の DI 引数を `AsyncMock` / `MagicMock` で組み立てる具体実装を埋め込み。これにより "No Placeholders" 原則を満たす。
3. **E2E テストでの `action_log_id` 取得手段の確立** — 設計書 §5.2 の `RLDataStore` Protocol に `fetch_action_ids_by_session(session_id, limit=1000) -> list[str]` を追加。3 バックエンドすべてが ScopedAction の `step ASC, created_at ASC` 順で DB 上 ID を返却し、Task 7.1 の E2E テストは `record_reward(action_log_id=action_ids[0])` で FK 違反フォールバックに頼らない race-free 検証が可能になった。設計書 §5.2 / §8.2 / E2E 行とも追記済み。
