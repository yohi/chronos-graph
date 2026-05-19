# RL Action Logging & Reward Signal Foundation — 設計仕様書 (Phase 1)

| 項目 | 内容 |
| --- | --- |
| Spec ID | 2026-05-19-rl-action-logging-reward-foundation-design |
| Status | Approved (Design Phase) |
| 作成日 | 2026-05-19 |
| 関連 Spec | `2026-05-18-supabase-storage-adapter-design.md` (バックエンド非依存方針) |
| 想定実装 | `src/context_store/extensions/`、`src/context_store/storage/rl_*.py` 他 |

## 1. 背景と目的

### 1.1 課題

ChronosGraph は SPEC.md §10 で「RL 拡張ポイント」を Protocol レベルで予約しているが、現状は
`src/context_store/extensions/noop.py` の NoOp 実装のみで、エージェントの検索行動と人間/システムからの
フィードバック信号はどこにも永続化されていない。Phase 2 で強化学習ループ (Gymnasium + Stable
Baselines3) を導入するには、その入力となる ActionLog と RewardSignal を **先行して収集する基盤** が必要。

### 1.2 目的

本フェーズは「データ収集と永続化のみ」を扱うスモールスタート。以下を達成する。

- 検索パイプライン (RetrievalPipeline) の各サブステップを `action_log` テーブルに記録
- 3 種の `reward_signal` (INTERNAL_EVAL / IMPLICIT_USER / EXPLICIT_FEEDBACK) を一貫したスキーマで永続化
- バックエンド非依存 (`RLDataStore` Protocol) で、Postgres / SQLite の双方に対応
- クエリレイテンシへの影響ゼロ (fire-and-forget)
- Phase 2 の RL ループ・Policy 動的化に対し設計的互換性を保つ

### 1.3 非ゴール (Phase 1 で扱わない)

- PyTorch / Stable Baselines3 / Gymnasium の導入
- `PolicyHook` の動的化 (`NoOpPolicyHook` のまま)
- `IMPLICIT_USER` 信号の自動生成ロジック (DB 列と Protocol 受け口のみ用意)
- バッチ Worker、報酬集約、リプレイバッファ
- ダッシュボードへの可視化
- Prisma スキーマへの追加 (Supabase 置換予定 — `2026-05-18-supabase-storage-adapter-design.md` 参照)

## 2. スコープ

### 2.1 対象

- 新規 SQL: `src/context_store/storage/migrations/{postgres,sqlite}/0003_rl_basis.sql`
- 改修: `src/context_store/extensions/protocols.py` (破壊的変更)
- 改修: `src/context_store/extensions/noop.py`
- 新規: `src/context_store/extensions/storage_logger.py`
- 新規: `src/context_store/extensions/session_context.py`
- 改修: `src/context_store/storage/protocols.py` (`RLDataStore` Protocol 追記)
- 新規: `src/context_store/storage/rl_postgres.py`
- 新規: `src/context_store/storage/rl_sqlite.py`
- 新規: `src/context_store/storage/rl_inmemory.py`
- 改修: `src/context_store/storage/factory.py` (`create_rl_data_store`)
- 改修: `src/context_store/orchestrator.py`
- 改修: `src/context_store/retrieval/pipeline.py`
- 改修: `src/context_store/server.py` (`memory_search` 引数追加、`memory_feedback` 新設)
- 改修: `src/context_store/config.py` (`rl_logging_enabled`、`rl_data_store_backend`、`rl_reward_context_max_bytes`)
- 改修: `src/context_store/storage/migrations/runner.py` 周辺は変更なし (既存 runner が `0003_*.sql` を自動適用)
- 新規/改修: テストスイート (§6 参照)

### 2.2 対象外

- Prisma `schema.prisma` への追加 (廃止予定のためスコープ外)
- Phase 2 で扱う `actionType` 列挙の拡張
- ActionLog / RewardSignal 参照用 MCP ツール
- Web ダッシュボードでの可視化

## 3. アーキテクチャ

### 3.1 全体図

```text
┌─────────────────────────────────────────────────────────────────┐
│  MCP Server (FastMCP) — server.py                                │
│    memory_search(query, session_id?, ...)   ← session_id 引数追加 │
│    memory_feedback(session_id, score, action_log_id?, ...)  NEW  │
└──────────────┬──────────────────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────────────┐
│  Orchestrator — orchestrator.py                                  │
│    - action_logger: ActionLogger (拡張 Protocol)                 │
│    - reward_signal: RewardSignal (拡張 Protocol)                 │
│    - search(): contextvar で session_id 伝播 → 内部 EVAL 発行     │
└──────────────┬──────────────────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────────────┐
│  RetrievalPipeline — retrieval/pipeline.py                       │
│    各サブステップ (Vector/Keyword/Graph/Fusion) の完了直後に      │
│    action_logger.log_action() を fire-and-forget で発火          │
└──────────────┬──────────────────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────────────┐
│  RL Data Layer — extensions/                                     │
│    Protocol:   ActionLogger / RewardSignal (rewritten)           │
│    Adapter:    StorageActionLogger / StorageRewardSignal         │
│                → RLDataStore Protocol に委譲                      │
│    Store:      PostgresRLDataStore (asyncpg)                     │
│                SQLiteRLDataStore (aiosqlite)                     │
│                InMemoryRLDataStore (テスト/開発用)                │
└──────────────┬──────────────────────────────────────────────────┘
               │
               ▼  SQL migrations
        ┌────────────────┐  ┌────────────────┐
        │ Postgres       │  │ SQLite         │
        │  action_log    │  │  action_log    │
        │  reward_signal │  │  reward_signal │
        └────────────────┘  └────────────────┘
```

### 3.2 主要設計判断

| 判断 | 採用 | 根拠 |
| --- | --- | --- |
| 抽象境界 | `RLDataStore` Protocol を `storage/protocols.py` に追加 | StorageAdapter と独立。Prisma 廃止/Supabase 移行の影響を受けない |
| ログ粒度 | サブステップ (4 step/request) | 要件の `actionType` 列挙と一致、Phase 2 の MDP 構造に直結 |
| `session_id` 伝播 | `contextvars.ContextVar` + MCP 引数 | Pipeline 各層への引数注入を避ける |
| 永続化レイテンシ | INSERT を `asyncio.create_task` で並行発火し、`RetrievalPipeline.search()` の応答前に `gather` で確定待ち | クエリレイテンシ影響を実質ゼロに保ちつつ、`memory_feedback` との Race Condition を構造的に排除 |
| `action_log_id` の整合性 | 事前存在確認はせず、DB FK 違反を捕捉して `action_log_id=NULL` で再 INSERT (`context.unverified_action_log_id` に元 ID 保存) | search 直後 feedback でも race を起こさず、孤立 ID も graceful に取り込む |
| 報酬収集 | 内部 EVAL 自動 + MCP `memory_feedback` (Explicit) | Implicit は Phase 2 へ繰延 |
| Prisma 取扱 | スキーマ追加なし | Supabase 置換予定により凍結 |
| Protocol | 既存 (`AgentAction`/`ActionLogger`/`RewardSignal`) を破壊的拡張 | 「初期実装は行わない、NoOp デフォルト」段階の今が確定タイミング |

## 4. データモデル (SQL マイグレーション)

### 4.1 PostgreSQL — `migrations/postgres/0003_rl_basis.sql`

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

### 4.2 SQLite — `migrations/sqlite/0003_rl_basis.sql`

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
    action_details  TEXT    NOT NULL DEFAULT '{}',  -- JSON encoded
    context_volume  INTEGER NOT NULL DEFAULT 0 CHECK (context_volume >= 0),
    created_at      TEXT    NOT NULL                -- ISO8601 UTC
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
    context         TEXT    NOT NULL DEFAULT '{}',  -- JSON encoded
    created_at      TEXT    NOT NULL                -- ISO8601 UTC
);

CREATE INDEX idx_reward_signal_session_id    ON reward_signal (session_id);
CREATE INDEX idx_reward_signal_action_log_id ON reward_signal (action_log_id);
CREATE INDEX idx_reward_signal_signal_type   ON reward_signal (signal_type);
CREATE INDEX idx_reward_signal_created_at    ON reward_signal (created_at DESC);
```

### 4.3 要件との対応

| 要件カラム | 採用名 | 備考 |
| --- | --- | --- |
| `id` (UUID) | `id` | Postgres は `UUID`、SQLite は `TEXT` で UUID 文字列 |
| `sessionId` | `session_id` | snake_case (プロジェクト規約) |
| `step` | `step` | `>= 0` 制約 |
| `actionType` | `action_type` | 4 値 CHECK 制約で要件列挙を強制 |
| `actionDetails` | `action_details` | Postgres `JSONB` / SQLite テキスト JSON |
| `contextVolume` | `context_volume` | 文字数固定 (`action_details.unit = "chars"`) |
| `timestamp` | `created_at` | 既存テーブルと命名統一 |
| `signalType` | `signal_type` | 3 値 CHECK |
| `score` | `score` | `-1.0..1.0` を CHECK で強制 |
| `actionLogId` | `action_log_id` | 任意 FK、`ON DELETE SET NULL` |

### 4.4 設計上の補足

- **`reward_signal.context` カラム追加**: 既存 `RewardSignal.record_reward` の `context: dict` を維持しつつ Phase 2 で source content / response 文脈を残す用途。
- **`ON DELETE SET NULL`**: ActionLog が将来 prune されても RewardSignal の履歴は学習素材として残す。
- **CHECK 制約による列挙保証**: enum はアプリ層と DB 層で二重防御。Phase 2 で `actionType` 拡張時は migration 0004 で `DROP CONSTRAINT` + `ADD CONSTRAINT`。
- **複合インデックス `(session_id, step)`**: Phase 2 の MDP 系列復元クエリを高速化。

## 5. Protocol 改修と RLDataStore

### 5.1 既存 Protocol 改修 — `extensions/protocols.py`

**破壊的変更**。

```python
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

### 5.2 RLDataStore Protocol — `storage/protocols.py` 追記

```python
@runtime_checkable
class RLDataStore(Protocol):
    async def insert_action_log(self, action: AgentAction) -> str: ...
    async def insert_reward_signal(self, signal: RewardSignalRecord) -> str: ...
    async def fetch_actions_by_session(
        self, session_id: str, limit: int = 1000
    ) -> list[AgentAction]: ...
    async def fetch_rewards_by_session(
        self, session_id: str, limit: int = 1000
    ) -> list[RewardSignalRecord]: ...
    async def dispose(self) -> None: ...
```

### 5.3 ファイル構成

```text
src/context_store/extensions/
├── protocols.py             # 破壊的改修
├── noop.py                  # 新シグネチャ追従
├── storage_logger.py    NEW # StorageActionLogger / StorageRewardSignal
├── session_context.py   NEW # contextvars 伝播ヘルパ
└── __init__.py

src/context_store/storage/
├── protocols.py             # RLDataStore Protocol 追記
├── rl_postgres.py       NEW # PostgresRLDataStore (asyncpg)
├── rl_sqlite.py         NEW # SQLiteRLDataStore (aiosqlite)
├── rl_inmemory.py       NEW # InMemoryRLDataStore (テスト用)
└── factory.py               # create_rl_data_store(settings)
```

### 5.4 設定追加 — `config.py`

```python
class Settings(BaseSettings):
    # ...
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

## 6. パイプライン統合

### 6.1 `session_id` 伝播 — `extensions/session_context.py`

```python
import contextvars
import uuid

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

### 6.2 Orchestrator 変更

```python
async def search(self, query, *, session_id: str | None = None, ...) -> RetrievalResponse:
    from context_store.extensions import session_context as sc

    effective_session_id = session_id or sc.new_session_id()
    token = sc.set_session_id(effective_session_id)
    try:
        # ... 既存処理 ...
        result = await self._retrieval_pipeline.search(
            query, ..., action_logger=self.action_logger,
        )
        await self._emit_internal_eval(
            session_id=effective_session_id, response=result,
        )
        return result
    finally:
        sc.reset_session_id(token)


async def _emit_internal_eval(self, session_id, response):
    results = response.get("results", [])
    if not results:
        score = -0.5
    else:
        avg = sum(float(r.get("score", 0.0)) for r in results) / len(results)
        score = max(-1.0, min(1.0, 2.0 * avg - 1.0))

    record = RewardSignalRecord(
        session_id=session_id,
        signal_type=SignalType.INTERNAL_EVAL,
        score=score,
        context={"top_k_count": len(results), "query": response.get("query")},
    )
    asyncio.create_task(self._safe_record_reward(record))


async def record_reward(
    self, *, session_id, score, signal_type=SignalType.EXPLICIT_FEEDBACK,
    action_log_id=None, context=None,
) -> str:
    record = RewardSignalRecord(
        session_id=session_id, signal_type=signal_type, score=score,
        action_log_id=action_log_id, context=context or {},
    )
    return await self.reward_signal.record_reward(record)
```

### 6.3 RetrievalPipeline 変更

各サブステップ完了直後に `action_logger.log_action()` を `asyncio.create_task` で発火し、
`pending: list[asyncio.Task[str]]` に蓄積する。`RetrievalPipeline.search()` の **応答返却前** に
`await asyncio.gather(*pending, return_exceptions=True)` で全 INSERT の確定を待つ。

- INSERT 自体は検索処理と並行実行されるためレイテンシ影響は実質ゼロ
  (各タスクは独立した DB 接続を使うため検索クエリと直列化されない)
- **応答返却時点で全 ActionLog が DB に確定済み** となるため、後続の `memory_feedback` で
  `action_log_id` を渡されても Race Condition が発生しない
- step=0 `VECTOR_SEARCH` / step=1 `KEYWORD_SEARCH` は `asyncio.gather` 後にまとめて発火
- step=2 `GRAPH_TRAVERSAL` は `strategy.graph_weight > 0` かつ vector ヒットあり時のみ
- step=3 `RESULT_FUSION` は常に発火
- `context_volume` は当該ステップで取得した `memory.content` の文字数合計
- `action_details.unit = "chars"` を明示
- `session_id` 未設定 (contextvar が None) のときは発火しない (後方互換)
- 例外は `_safe_log` 内でログにダウングレード、`search()` は正常応答
  (`gather(..., return_exceptions=True)` で個別失敗を吸収)

### 6.4 ファクトリ統合

```python
# storage/factory.py
async def create_rl_data_store(settings: Settings) -> RLDataStore:
    backend = settings.rl_data_store_backend
    if backend == "auto":
        backend = (
            "postgres" if settings.storage_backend in ("postgres", "prisma")
            else "sqlite" if settings.storage_backend == "sqlite"
            else "inmemory"
        )
    if backend == "postgres":
        from context_store.storage.rl_postgres import PostgresRLDataStore
        return await PostgresRLDataStore.create(settings)
    if backend == "sqlite":
        from context_store.storage.rl_sqlite import SQLiteRLDataStore
        return await SQLiteRLDataStore.create(settings)
    from context_store.storage.rl_inmemory import InMemoryRLDataStore
    return InMemoryRLDataStore()
```

`create_orchestrator` 内: `settings.rl_logging_enabled and action_logger is None and reward_signal is None`
のとき自動的に `StorageActionLogger` / `StorageRewardSignal` を注入し、Orchestrator が `rl_store` を保持。
`Orchestrator.dispose()` 末尾で `await rl_store.dispose()`。

## 7. MCP 公開面

### 7.1 `memory_search` 拡張 (後方互換)

`session_id: str | None = None` を追加。未指定時は自動採番。レスポンス JSON に `session_id` を必ず含める。

### 7.2 `memory_feedback` 新設

```python
@mcp.tool()
async def memory_feedback(
    session_id: str,
    score: float,                  # -1.0 .. +1.0
    action_log_id: str | None = None,
    comment: str | None = None,
) -> str:
    """Explicit Feedback を記録する。"""
```

- レンジ違反は MCP・Orchestrator・dataclass の三層でチェック
- `comment` は **1024 文字** (Python の `str` スライス `comment[:1024]`) で切り詰め
- `reward_signal.context` JSON 全体は **4096 バイト** 上限
  (`rl_reward_context_max_bytes`、`json.dumps(...).encode("utf-8")` バイト長で評価)
- `action_log_id` の **事前存在確認 (SELECT) は行わない**。Race Condition の温床になるため
  廃止。UUID 文字列としての形式バリデーションのみ実施し、DB の FK 制約に整合性を委ねる
- `action_log_id` が DB に存在しないケース (古い ID / セッション跨ぎの誤指定など) は
  `insert_reward_signal` 内で FK 違反例外を捕捉し、`action_log_id=NULL` で再 INSERT する。
  元の ID は `context["unverified_action_log_id"]` に保存する (feedback は失敗させずに取り込む)
- 戻り値: `{"reward_signal_id": "<uuid>", "score": <float>}`
  (`unverified_action_log_id` が記録されたかは Phase 2 の監査クエリで把握可能)

### 7.3 Phase 1 で公開しないもの

- `INTERNAL_EVAL` 取得 API (Phase 2)
- `IMPLICIT_USER` 専用ツール (Phase 2)
- ActionLog 参照 API (Phase 2 ダッシュボード拡張)

## 8. テスト戦略

### 8.1 ファイル構成

```text
tests/unit/
├── test_extensions.py              # 既存改修 (新 Protocol/NoOp)
├── test_rl_basis.py            NEW # 要件指定の統合テスト
├── test_rl_data_store.py       NEW # 3 種ストアを parametrize で網羅
├── test_rl_storage_logger.py   NEW # StorageActionLogger / StorageRewardSignal
├── test_session_context.py     NEW # contextvar 伝播
├── test_orchestrator.py            # 既存改修
├── test_retrieval_pipeline.py      # 既存改修
└── test_api_server.py              # 既存改修
```

### 8.2 検証項目 (主要)

| 検証対象 | 確認ポイント |
| --- | --- |
| `AgentAction` / `RewardSignalRecord` | `frozen=True`、`score` レンジ違反は `ValueError` |
| `NoOp` 実装 | 戻り値は `""`、Protocol 準拠 |
| `session_context` | デフォルト None、set/reset、`asyncio.gather` 越し伝播、タスク間独立 |
| `RLDataStore` (SQLite 統合) | insert/fetch、CHECK 制約違反、`ON DELETE SET NULL`、dispose 冪等、FK 違反時の `action_log_id=NULL` 格下げと `context.unverified_action_log_id` 保存 |
| `RLDataStore` (Postgres) | asyncpg モックで SQL 発行を検証 (FK 違反フォールバックの SQL 順序を含む) |
| `RetrievalPipeline` | 4 step の発火条件、`context_volume`、例外吸収、`session_id` 未設定時は無発火、**応答返却時点で全 ActionLog が DB に確定済み** (pending タスクを `gather` で待機) |
| `Orchestrator` | contextvar の set/reset、`_emit_internal_eval` のスコア計算、`record_reward` 公開 API、`dispose` で `rl_store` 解放 |
| `memory_search` (MCP) | `session_id` の自動採番とレスポンスエコー |
| `memory_feedback` (MCP) | 正常系、レンジ違反、コメント切り詰め、**存在しない `action_log_id` でも 200 応答** (`unverified_action_log_id` に格下げ) |
| `test_rl_basis.py` | エンド to エンド (search → 4 ActionLog → INTERNAL_EVAL → EXPLICIT_FEEDBACK)、および **search 直後 feedback の race-free 検証** (`memory_search` 戻り直後に `memory_feedback(action_log_id=...)` を `asyncio.sleep` なしで呼び出し、FK 違反フォールバックに **頼らず** 成功することを確認) |

### 8.3 カバレッジと CI

- 100% coverage:
  `uv run pytest tests/unit/ --cov=context_store.extensions
  --cov=context_store.storage.rl_postgres --cov=context_store.storage.rl_sqlite
  --cov=context_store.storage.rl_inmemory --cov-fail-under=100`
- 静的解析: `uv run ruff check src/ tests/` / `uv run ruff format --check src/ tests/`
  / `uv run mypy src/`
- 全コマンドは Devcontainer 内で実行 (AGENTS.md §3)

### 8.4 既存テストの後方互換

- `RetrievalPipeline.search()` 直接呼出: `action_logger` 引数省略時は NoOp、contextvar 未設定で無発火
- `Orchestrator.search()` 直接呼出: `session_id=None` で従来どおり (レスポンスへの `session_id` 付与は `server.py` 層のみ)
- `tests/unit/test_extensions.py` の改修は破壊的だがセクション 3 で承認済み

## 9. Phase 2 への接続性

| Phase 2 機能 | Phase 1 で予約済みの基盤 |
| --- | --- |
| RL バッチ Worker (PPO/DQN) | `RLDataStore.fetch_actions_by_session` / `fetch_rewards_by_session` |
| 動的 PolicyHook | `Orchestrator.policy_hook` 注入口、`action_log` の系列データ |
| IMPLICIT_USER 自動生成 | `signal_type` enum と DB 列、`RewardSignal.record_reward` Python API |
| `actionType` の拡張 | migration 0004 で CHECK 制約を `DROP/ADD` |
| ActionLog 参照ダッシュボード | `(session_id, step)` 複合インデックス |

## 10. リスクと緩和策

| リスク | 緩和策 |
| --- | --- |
| RL ログ書込みでレイテンシ増 | INSERT を `asyncio.create_task` で並行発火し、検索処理と独立 DB 接続で並行実行。`search()` 応答前に `gather(return_exceptions=True)` で確定待ちすることで、レイテンシは検索本体の処理時間に吸収される (実測影響は数 ms 以内を想定)。例外は `_safe_log` で吸収 |
| `memory_feedback` と ActionLog 書込みの Race Condition | (1) `search()` 応答返却前に全 INSERT を `gather` で確定。(2) それでも整合しない `action_log_id` は FK 違反捕捉で `NULL` 格下げ + `context.unverified_action_log_id` 保存 |
| DB 障害で検索が落ちる | RL ログ失敗は警告ログのみ、`search` のレスポンスには影響なし。`gather(return_exceptions=True)` により個別タスクの失敗は他に波及しない |
| `session_id` 漏洩 | UUID v4 を自動採番、ユーザ入力は受けるが PII 紐付けはアプリ層で禁止 |
| `comment` フィールドからの長文流入 | 1024 文字で切り詰め、`context` JSON 全体 4096 バイト上限 |
| Prisma 撤去との競合 | 本仕様は Prisma スキーマに触れない (`storage_backend == "prisma"` 時は `rl_data_store_backend="auto"` で Postgres を選択) |
| 既存テストの破壊 | `test_extensions.py` は新シグネチャへ追従改修、その他は後方互換維持 |
