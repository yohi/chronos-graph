# ChronosGraph: 記憶保存戦略アーキテクチャ設計

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:writing-plans to create
> an implementation plan from this spec before writing any code.

**Goal:** エージェントの自律的保存とシステムのバッチ保存を組み合わせたハイブリッド記憶保存戦略を実装する

**Date:** 2026-04-14

**Status:** Draft

---

## 1. Overview

ChronosGraph の記憶形成において、以下の2軸を統合するハイブリッド保存戦略を実装する:

- **A. エージェント駆動の自律的保存 (主軸)**: エージェントが重要と判断した Semantic/Procedural 情報を `memory_save` で即座に保存
- **B. バックグラウンドバッチ処理 (補助)**: セッションの会話ログを `session_flush` で非同期バッチ保存

加えて、RL 拡張ポイントの実体実装として `ActionLogger` / `RewardSignal` の SQLite 実装を提供する。

### 1.1 Design Decisions

| 決定事項 | 選択 | 理由 |
|---|---|---|
| バッチ保存 | サーバー側 `session_flush` + クライアント呼び出し | 両側の責務を明確に分離 |
| エンドポイント方式 | 非同期ジョブ型 | `stdio` の逐次 RPC をブロックしない |
| ジョブ管理 | インメモリ `asyncio.create_task()` | 外部依存なし、YAGNI |
| トリガー管理 | クライアント側が全責任 | サーバーで会話ターン追跡は不適切 |
| RL フック | Protocol の SQLite 実装 (ログ蓄積のみ) | 学習ループは将来フェーズ |
| システムプロンプト | `docs/` 配下のドキュメント | コードベースへの影響なし |

---

## 2. Architecture

### 2.1 Component Diagram

```text
┌─────────────────────────────────────────────────────────────┐
│                    MCP Server (FastMCP)                       │
│                                                               │
│  既存ツール:                     新規ツール:                    │
│  ├─ memory_save                 ├─ session_flush  ← NEW      │
│  ├─ memory_search               └─ session_flush_status ← NEW│
│  ├─ memory_save_url                                           │
│  └─ ...                                                       │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │                    Orchestrator                          │ │
│  │                                                          │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │ │
│  │  │  Ingestion   │  │   Batch      │  │  Action      │  │ │
│  │  │  Pipeline    │  │   Processor  │  │  Logger      │  │ │
│  │  │  (既存)      │  │  NEW         │  │  NEW impl    │  │ │
│  │  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  │ │
│  │         │                 │                  │          │ │
│  │         │    ┌────────────┘                  │          │ │
│  │         │    │  ┌───────────────┐            │          │ │
│  │         │    │  │ Job Manager   │            │          │ │
│  │         │    │  │ NEW           │            │          │ │
│  │         │    │  └───────────────┘            │          │ │
│  │         │    │                               │          │ │
│  │  ┌──────┴────┴───────────────────────────────┴───────┐  │ │
│  │  │            Storage Layer (既存)                     │  │ │
│  │  └───────────────────────────────────────────────────┘  │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                               │
│  新規テーブル:                                                 │
│  ├─ action_log (ActionLogger 用)                              │
│  └─ reward_log (RewardSignal 用)                              │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Data Flow: session_flush

```text
session_flush(conversation_log)
  │
  ▼
Orchestrator.session_flush()
  ├─ BatchProcessor.estimate_chunks() → estimated_chunks
  ├─ JobManager.create_job(estimated_chunks) → job_id
  ├─ asyncio.create_task(BatchProcessor.process(job_id, ...))
  ├─ JobManager.register_task(job_id, task)
  └─ return {job_id, status: "queued", estimated_chunks}

# Background:
BatchProcessor.process()
  ├─ JobManager.mark_running(job_id)
  ├─ results = IngestionPipeline.ingest(conversation_log, source_type=CONVERSATION)
  │   ├─ Chunker._split_conversation() → Q&A pair splitting
  │   ├─ Classifier.classify() → EPISODIC (default)
  │   ├─ EmbeddingProvider.embed() → vectorization
  │   ├─ Deduplicator.deduplicate() → dedup check (>= 0.90 → SUPERSEDES)
  │   └─ StorageAdapter.save_memory() → persist (per-chunk commit)
  ├─ for result in results: JobManager.update_progress(job_id, result.memory_id)
  └─ JobManager.mark_completed(job_id)
```

### 2.3 Data Flow: RL Hooks

```text
# ActionLogger (save 操作後):
Orchestrator.save() → IngestionPipeline.ingest() → success
  └─ ActionLogger.log_action(AgentAction(action_type="memory_save", memory_id=...))
       └─ INSERT INTO action_log (best-effort, no exception propagation)

# RewardSignal (search 操作後):
RetrievalPipeline.search() → PostProcessor.process()
  ├─ access_count / last_accessed_at update (existing)
  └─ RewardSignal.record_reward(memory_id, signal=score, context={query, score, source})
       └─ INSERT INTO reward_log (best-effort, no exception propagation)
```

---

## 3. New Components

### 3.1 JobManager

**File:** `src/context_store/ingestion/job_manager.py`

```python
class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

@dataclass
class JobState:
    job_id: str
    status: JobStatus
    total_chunks: int
    completed_chunks: int = 0
    results: list[str] = field(default_factory=list)
    error: str | None = None
    created_at: datetime
    completed_at: datetime | None = None

class JobManager:
    """In-memory async job state management.

    - Tracks job lifecycle: QUEUED → RUNNING → COMPLETED/FAILED
    - Auto-cleans old completed jobs beyond MAX_RETAINED_JOBS
    - Provides graceful shutdown via cancel_all()
    """

    def __init__(self, max_retained_jobs: int = 100) -> None:
        self._jobs: dict[str, JobState] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._max_retained_jobs = max_retained_jobs

    def create_job(self, estimated_chunks: int) -> str:
        """Register a new job and return its job_id (UUID)."""

    def get_job(self, job_id: str) -> JobState | None:
        """Return current job state, or None if not found."""

    def update_progress(self, job_id: str, memory_id: str) -> None:
        """Increment completed_chunks and append memory_id to results."""

    def mark_running(self, job_id: str) -> None:
        """Transition job to RUNNING status."""

    def mark_completed(self, job_id: str) -> None:
        """Transition job to COMPLETED status with timestamp."""

    def mark_failed(self, job_id: str, error: str) -> None:
        """Transition job to FAILED status with error message."""

    def register_task(self, job_id: str, task: asyncio.Task) -> None:
        """Associate asyncio.Task with job. Add done_callback for error logging."""

    async def cancel_all(self, timeout: float = 5.0) -> None:
        """Cancel all running tasks with timeout. Called during graceful shutdown."""

    def _cleanup_old_jobs(self) -> None:
        """Remove oldest completed/failed jobs when exceeding max_retained_jobs."""
```

### 3.2 BatchProcessor

**File:** `src/context_store/ingestion/batch_processor.py`

```python
class BatchProcessor:
    """Thin wrapper over IngestionPipeline for batch conversation log processing.

    Delegates to IngestionPipeline.ingest() and updates JobManager progress.
    """

    def __init__(
        self,
        ingestion_pipeline: IngestionPipeline,
        job_manager: JobManager,
    ) -> None:
        self._pipeline = ingestion_pipeline
        self._job_manager = job_manager

    def estimate_chunks(self, conversation_log: str) -> int:
        """Estimate chunk count using Chunker dry-run (no side effects).

        Creates a temporary RawContent with source_type=CONVERSATION,
        passes it through Chunker.chunk() to count yielded chunks,
        but does NOT persist anything. This is a pure read-only estimation.
        """

    async def process(
        self,
        job_id: str,
        conversation_log: str,
        *,
        session_id: str,
        project: str | None = None,
        tags: list[str] | None = None,
    ) -> None:
        """Background batch processing entry point.

        Flow:
        1. JobManager.mark_running(job_id)
        2. results = IngestionPipeline.ingest() with source_type=CONVERSATION
        3. Iterate over results: JobManager.update_progress(job_id, result.memory_id)
        4. JobManager.mark_completed(job_id) on success
        5. JobManager.mark_failed(job_id, error) on exception (after logging)

        Note: Progress updates happen AFTER ingest() returns (not via per-chunk
        callback), because IngestionPipeline.ingest() processes all chunks
        internally and returns the full result list.
        """
```

### 3.3 SqliteActionLogger

**File:** `src/context_store/extensions/action_logger.py`

```python
class SqliteActionLogger:
    """ActionLogger Protocol implementation for SQLite.

    Persists agent actions to the action_log table.
    Uses a separate DB connection from StorageAdapter to avoid
    transaction boundary interference.

    All writes are best-effort: failures emit WARNING logs but
    do not propagate exceptions to callers.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def log_action(self, action: AgentAction) -> None:
        """INSERT action into action_log table (best-effort)."""

    async def close(self) -> None:
        """Close DB connection."""
```

**Action logging points in Orchestrator:**

| Operation | action_type | memory_id | query |
|---|---|---|---|
| `save()` success | `"memory_save"` | saved memory_id | None |
| `search()` success | `"memory_search"` | None | search query |
| `session_flush()` start | `"session_flush"` | None | None (job_id in metadata) |
| `delete()` success | `"memory_delete"` | deleted memory_id | None |

### 3.4 SqliteRewardSignal

**File:** `src/context_store/extensions/reward_signal.py`

```python
class SqliteRewardSignal:
    """RewardSignal Protocol implementation for SQLite.

    Records reward signals for memories that are retrieved during search.
    Signal value is the final search score of the scored memory.

    All writes are best-effort: failures emit WARNING logs but
    do not propagate exceptions to callers.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def record_reward(
        self, memory_id: str, signal: float, context: dict[str, Any]
    ) -> None:
        """INSERT reward signal into reward_log table (best-effort)."""

    async def close(self) -> None:
        """Close DB connection."""
```

**Integration point:** `retrieval/post_processor.py`

The existing `PostProcessor` updates `access_count` and `last_accessed_at` for search results.
The `RewardSignal` hook is added here — after the access update, call `record_reward()`
for each scored memory with the search score as the reward signal value.

---

## 4. MCP Tool Interface

### 4.1 session_flush

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `conversation_log` | str | Yes | — | Full conversation log (`User: ...\nAssistant: ...` format) |
| `session_id` | str | No | auto UUID | Session identifier |
| `project` | str? | No | None | Project name |
| `tags` | list[str] | No | [] | Additional tags |

**Response:**

```json
{
  "job_id": "abc123-...",
  "status": "queued",
  "estimated_chunks": 5
}
```

### 4.2 session_flush_status

| Argument | Type | Required | Description |
|---|---|---|---|
| `job_id` | str | Yes | Job ID returned by session_flush |

**Response:**

```json
{
  "job_id": "abc123-...",
  "status": "completed",
  "progress": {"done": 5, "total": 5},
  "results": ["mem-id-1", "mem-id-2"],
  "error": null
}
```

---

## 5. Data Model

### 5.1 action_log Table

```sql
CREATE TABLE IF NOT EXISTS action_log (
    id          TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    action_type TEXT NOT NULL,
    memory_id   TEXT,
    query       TEXT,
    metadata    TEXT DEFAULT '{}',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_action_log_type ON action_log(action_type);
CREATE INDEX IF NOT EXISTS idx_action_log_memory ON action_log(memory_id);
CREATE INDEX IF NOT EXISTS idx_action_log_created ON action_log(created_at);
```

### 5.2 reward_log Table

```sql
CREATE TABLE IF NOT EXISTS reward_log (
    id          TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    memory_id   TEXT NOT NULL,
    signal      REAL NOT NULL,
    context     TEXT DEFAULT '{}',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_reward_log_memory ON reward_log(memory_id);
CREATE INDEX IF NOT EXISTS idx_reward_log_created ON reward_log(created_at);
```

---

## 6. Configuration

### 6.1 New Settings Parameters

| Parameter | Env Var | Default | Description |
|---|---|---|---|
| `batch_max_concurrent_jobs` | `BATCH_MAX_CONCURRENT_JOBS` | `3` | Max concurrent batch jobs |
| `batch_max_retained_jobs` | `BATCH_MAX_RETAINED_JOBS` | `100` | Max in-memory job history |
| `rl_action_logging_enabled` | `RL_ACTION_LOGGING_ENABLED` | `true` | Enable ActionLogger |
| `rl_reward_logging_enabled` | `RL_REWARD_LOGGING_ENABLED` | `true` | Enable RewardSignal |

---

## 7. Modified Existing Files

### 7.1 server.py

- Add `session_flush` and `session_flush_status` MCP tool registrations
- Delegate to `ChronosServer.session_flush()` and `ChronosServer.session_flush_status()`

### 7.2 orchestrator.py

- Add `BatchProcessor` and `JobManager` as constructor dependencies
- Add `session_flush()` method: estimate chunks → create job → create_task → return job_id
- Add `session_flush_status()` method: delegate to JobManager.get_job()
- Add `ActionLogger.log_action()` calls after save/search/delete operations
- Update `dispose()` to call `JobManager.cancel_all()` and close RL components

### 7.3 orchestrator.py (create_orchestrator factory)

- Instantiate `JobManager` and `BatchProcessor`
- When `storage_backend == "sqlite"` and `rl_action_logging_enabled`:
  instantiate `SqliteActionLogger` instead of `NoOpActionLogger`
- When `storage_backend == "sqlite"` and `rl_reward_logging_enabled`:
  instantiate `SqliteRewardSignal` instead of `NoOpRewardSignal`
- Pass `RewardSignal` to `PostProcessor`

### 7.4 retrieval/post_processor.py

- Add `reward_signal: RewardSignal | None = None` constructor parameter
- After access_count/last_accessed_at update, call `record_reward()` for each result

### 7.5 config.py

- Add batch and RL configuration parameters (see Section 6.1)

### 7.6 storage/sqlite.py

- Add `action_log` and `reward_log` table creation in schema initialization

---

## 8. Error Handling

| Scenario | Behavior |
|---|---|
| Process terminates during `session_flush` | Committed chunks are retained; uncommitted are lost. Job state (in-memory) is lost |
| `batch_max_concurrent_jobs` exceeded | Immediate error response: `{"error": "Too many concurrent jobs"}` |
| Unknown `job_id` in `session_flush_status` | Return `{"error": "Job not found", "job_id": "..."}` |
| ActionLogger/RewardSignal DB write failure | WARNING log only; main save/search continues (best-effort) |
| Individual chunk ingestion failure in batch | Skip failed chunk, continue others. Mark job as `failed` only if ALL chunks fail |

---

## 9. Testing Strategy

All tests MUST be executed within the devcontainer environment.

### 9.1 New Test Files

| Test File | Coverage |
|---|---|
| `tests/unit/test_job_manager.py` | JobManager state transitions, concurrency limits, cleanup |
| `tests/unit/test_batch_processor.py` | BatchProcessor chunk estimation, Ingestion delegation, progress updates |
| `tests/unit/test_action_logger.py` | SqliteActionLogger INSERT, best-effort error handling |
| `tests/unit/test_reward_signal.py` | SqliteRewardSignal INSERT, PostProcessor integration |
| `tests/unit/test_session_flush_tools.py` | session_flush / session_flush_status MCP tool E2E |

### 9.2 Key Test Scenarios

1. **Job state transitions:** `QUEUED → RUNNING → COMPLETED` and `QUEUED → RUNNING → FAILED`
2. **Concurrency limit:** Reject when exceeding `batch_max_concurrent_jobs`
3. **Best-effort logging:** ActionLogger DB connection failure does not block main processing
4. **Transaction boundary:** Verify `embed()` completes before `save_memory()` (mock ordering)
5. **Graceful shutdown:** `cancel_all()` cancels running jobs within timeout
6. **Chunk failure resilience:** Partial chunk failures in batch do not fail the entire job

---

## 10. Graceful Shutdown Integration

```python
# Orchestrator.dispose() changes:
async def dispose(self) -> None:
    # NEW: Cancel running batch jobs (5s timeout)
    if self._job_manager is not None:
        await self._job_manager.cancel_all(timeout=5.0)

    await self._lifecycle_manager.graceful_shutdown()
    await self._storage.dispose()
    if self._graph is not None:
        await self._graph.dispose()
    await self._cache.dispose()

    # NEW: Close RL components
    if hasattr(self.action_logger, 'close'):
        await self.action_logger.close()
    if hasattr(self.reward_signal, 'close'):
        await self.reward_signal.close()
```

---

## 11. Out of Scope

| Item | Reason |
|---|---|
| RL learning loop | Data accumulation only in action_log/reward_log. Learning is a future phase |
| PostgreSQL ActionLogger/RewardSignal | Initial implementation is SQLite only. Extensible via Protocol |
| Job persistence across process restarts | YAGNI for `stdio` short-lived MCP server |
| HTTP/SSE transport | Planned for v2.1 (per SPEC.md §7.1.1) |
| Concept drift detection | Future extension point (per SPEC.md §6.5) |

---

## 12. SPEC.md Alignment

| SPEC.md Section | This Design |
|---|---|
| §4.3 Chunker (Q&A pair splitting, 1-3 turns) | Reuse existing `Chunker._split_conversation()` |
| §4.4 Deduplicator (cosine >= 0.90 → SUPERSEDES) | All batch-saved memories pass through existing Deduplicator |
| §6 Lifecycle Manager | Batch-saved memories are subject to normal lifecycle (decay, archive, purge) |
| §10 RL Extension Points (Protocol definitions) | Maintain Protocol; add SQLite implementations |
| Devcontainer constraint | All testing must run in devcontainer |

---

## Appendix A: Agent System Prompt Template

The following system prompt template is intended for integration into Claude 4.6 or
equivalent AI agent system instructions. It is NOT embedded in the MCP server code.

```xml
<role>
あなたは、ChronosGraphシステムをバックエンドに持つ高度な自律型AIエージェントです。
あなたのミッションは、ユーザーとの対話やコード操作を通じてタスクを解決するだけでなく、
将来のセッションで役立つ「価値ある記憶」を自律的に識別し、長期記憶システムへ保存することです。
</role>

<instructions>
タスクを実行する際、以下の基準に従って memory_save ツールを能動的に呼び出してください。

1. **記憶の評価（Thinkingプロセス）:**
   ユーザーからの指示を完了した後、または重要なエラーを解決した直後に、
   現在のコンテキスト内に「再利用価値のある知識」が含まれているか
   適応的思考（Adaptive Thinking）を用いて評価してください。

2. **保存対象の抽出:**
   単なる相槌や一時的な状態は保存しないでください。以下のいずれかに該当する
   高密度の情報のみを要約して保存します。
   - **Semantic（概念・知識）:** ユーザーの好み、プロジェクト固有のアーキテクチャ規則、
     環境特有の設定値、ドメイン知識。
   - **Procedural（手順・解決策）:** 複雑なエラーの根本原因とそれを解決した具体的な手順、
     特定のタスクを遂行するための最適なコマンド群。

3. **ツールの実行:**
   価値ある記憶を特定した場合、即座に memory_save ツールを呼び出します。
   保存するテキストは、将来のあなた自身（または他のエージェント）が検索した際に、
   背景状況なしでも理解できる「具体的で独立した要約文」にしてください。

4. **会話ログのバッチ保存:**
   3〜5ターンの会話が蓄積されたタイミング、またはセッション終了時に、
   session_flush ツールを呼び出して会話ログ全体をバッチ保存してください。
   これにより、EPISODIC 記憶がシステムに自動分類・保存されます。
</instructions>

<memory_rules>
- **自律的分類:** memory_save 呼び出し時、記憶の性質に応じて適切にカテゴリ
  （Semantic または Procedural）を意識してテキストを構成してください。
  一時的な会話ログ（EPISODIC）は session_flush で自動バッチ保存されるため、
  あなたが能動的に保存する必要はありません。
- **重複の心配は不要:** 以前に保存したルールや知識が更新された場合でも、
  単に最新の状態を memory_save で保存してください。バックエンドの Deduplicator
  （類似度 >= 0.90 の判定）が自動的に SUPERSEDES エッジを作成し、
  記憶を統合・最新化します。
- **session_flush の使い方:** 会話ログ全文を conversation_log 引数に渡してください。
  session_id は省略可能です（自動生成されます）。
  進捗を確認したい場合は session_flush_status を呼び出してください。
</memory_rules>

<constraints>
- ユーザーに「記憶に保存しますか？」と尋ねてはいけません。
  あなたの判断で自律的かつサイレントに memory_save を実行し、
  ユーザーへの返答はタスクの完了報告や本題のみに留めてください。
- 情報が不足している、または判断に迷う曖昧なケースでは、
  推測で記憶を保存せず、保存を見送ってください。
  不確実なノイズを長期記憶に混入させないことが優先されます。
- テストや静的解析を実行する場合は、必ずDevcontainer環境内で実行してください。
</constraints>
```
