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

### 1.1 Design Decisions

| 決定事項 | 選択 | 理由 |
|---|---|---|
| バッチ保存 | サーバー側 `session_flush` + クライアント呼び出し | 両側の責務を明確に分離 |
| エンドポイント方式 | 非同期ジョブ型 | `stdio` の逐次 RPC をブロックしない |
| ジョブ管理 | インメモリ `asyncio.create_task()` | 外部依存なし、YAGNI |
| トリガー管理 | クライアント側が全責任 | サーバーで会話ターン追跡は不適切 |
| システムプロンプト | `docs/` 配下のドキュメント | コードベースへの影響なし |

---

## 2. Architecture

### 2.1 Component Diagram

```text
┌─────────────────────────────────────────────────────────────┐
│                    MCP Server (FastMCP)                       │
│                                                               │
│  既存ツール:                     新規ツール:                    │
│  ├─ memory_save                 └─ session_flush  ← NEW      │
│  ├─ memory_search                                             │
│  ├─ memory_save_url                                           │
│  └─ ...                                                       │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │                    Orchestrator                          │ │
│  │                                                          │ │
│  │  ┌──────────────┐  ┌──────────────┐                     │ │
│  │  │  Ingestion   │  │   Batch      │                     │ │
│  │  │  Pipeline    │  │   Processor  │                     │ │
│  │  │  (既存)      │  │  NEW         │                     │ │
│  │  └──────┬───────┘  └──────┬───────┘                     │ │
│  │         │                 │                              │ │
│  │         │    ┌────────────┘                              │ │
│  │         │    │  ┌───────────────┐                        │ │
│  │         │    │  │ Job Manager   │                        │ │
│  │         │    │  │ NEW           │                        │ │
│  │         │    │  └───────────────┘                        │ │
│  │         │    │                                           │ │
│  │  ┌──────┴────┴──────────────────────────────────────┐   │ │
│  │  │            Storage Layer (既存)                    │   │ │
│  │  └──────────────────────────────────────────────────┘   │ │
│  └─────────────────────────────────────────────────────────┘ │
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

---

## 5. Configuration

### 5.1 New Settings Parameters

| Parameter | Env Var | Default | Description |
|---|---|---|---|
| `batch_max_concurrent_jobs` | `BATCH_MAX_CONCURRENT_JOBS` | `3` | Max concurrent batch jobs |
| `batch_max_retained_jobs` | `BATCH_MAX_RETAINED_JOBS` | `100` | Max in-memory job history |

---

## 6. Modified Existing Files

### 6.1 server.py

- Add `session_flush` MCP tool registration
- Delegate to `ChronosServer.session_flush()`

### 6.2 orchestrator.py

- Add `BatchProcessor` and `JobManager` as constructor dependencies
- Add `session_flush()` method: estimate chunks → create job → create_task → return job_id
- Update `dispose()` to call `JobManager.cancel_all()`

### 6.3 orchestrator.py (create_orchestrator factory)

- Instantiate `JobManager` and `BatchProcessor`

### 6.4 config.py

- Add batch configuration parameters (see Section 5.1)

---

## 7. Error Handling

| Scenario | Behavior |
|---|---|
| Process terminates during `session_flush` | Committed chunks are retained; uncommitted are lost. Job state (in-memory) is lost |
| `batch_max_concurrent_jobs` exceeded | Immediate error response: `{"error": "Too many concurrent jobs"}` |
| Individual chunk ingestion failure in batch | Skip failed chunk, continue others. Mark job as `failed` only if ALL chunks fail |

---

## 8. Testing Strategy

All tests MUST be executed within the devcontainer environment.

### 8.1 New Test Files

| Test File | Coverage |
|---|---|
| `tests/unit/test_job_manager.py` | JobManager state transitions, concurrency limits, cleanup |
| `tests/unit/test_batch_processor.py` | BatchProcessor chunk estimation, Ingestion delegation, progress updates |
| `tests/unit/test_session_flush_tools.py` | session_flush MCP tool E2E |

### 8.2 Key Test Scenarios

1. **Job state transitions:** `QUEUED → RUNNING → COMPLETED` and `QUEUED → RUNNING → FAILED`
2. **Concurrency limit:** Reject when exceeding `batch_max_concurrent_jobs`
3. **Transaction boundary:** Verify `embed()` completes before `save_memory()` (mock ordering)
4. **Graceful shutdown:** `cancel_all()` cancels running jobs within timeout
5. **Chunk failure resilience:** Partial chunk failures in batch do not fail the entire job

---

## 9. Graceful Shutdown Integration

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
```

---

## 10. Out of Scope

| Item | Reason |
|---|---|
| RL hooks (ActionLogger / RewardSignal) | ログ蓄積・学習ループともに将来フェーズへ延期 |
| Job persistence across process restarts | YAGNI for `stdio` short-lived MCP server |
| HTTP/SSE transport | Planned for v2.1 (per SPEC.md §7.1.1) |
| Concept drift detection | Future extension point (per SPEC.md §6.5) |

---

## 11. SPEC.md Alignment

| SPEC.md Section | This Design |
|---|---|
| §4.3 Chunker (Q&A pair splitting, 1-3 turns) | Reuse existing `Chunker._split_conversation()` |
| §4.4 Deduplicator (cosine >= 0.90 → SUPERSEDES) | All batch-saved memories pass through existing Deduplicator |
| §6 Lifecycle Manager | Batch-saved memories are subject to normal lifecycle (decay, archive, purge) |
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
   以下のいずれかの条件を満たした時点で、現在のコンテキスト内に
   「再利用価値のある知識」が含まれているか適応的思考（Adaptive Thinking）を
   用いて評価してください。
   - ユーザーからの指示を完了した後
   - コマンド実行がエラー終了（非0）から正常終了（0）に変化した実行の直後

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

4. **会話ログのバッチ保存（session_flush）:**
   以下のいずれかの条件を満たした時点で、session_flush ツールを呼び出して
   会話ログ全体をバッチ保存してください。
   - 会話ログの総文字数が 8,000 文字に達した時
   - MCPサーバープロセスの終了前（graceful shutdown 時）

   一時的な会話ログは session_flush により自動的に EPISODIC 記憶として分類・保存されるため、
   memory_save での手動保存は不要です。

   会話ログ全文を conversation_log 引数に渡してください。
   session_id は省略可能です（自動生成されます）。
</instructions>

<memory_rules>
- **自律的分類:** memory_save 呼び出し時、記憶の性質に応じて適切にカテゴリ
  （Semantic または Procedural）を意識してテキストを構成してください。
- **重複の心配は不要:** 以前に保存したルールや知識が更新された場合でも、
  単に最新の状態を memory_save で保存してください。バックエンドの Deduplicator
  （類似度 >= 0.90 の判定）が自動的に SUPERSEDES エッジを作成し、
  記憶を統合・最新化します。
</memory_rules>

<constraints>
- ユーザーに「記憶に保存しますか？」と尋ねてはいけません。
  あなたの判断で自律的かつサイレントに memory_save を実行し、
  ユーザーへの返答はタスクの完了報告や本題のみに留めてください。
- 情報が不足している、または判断に迷う曖昧なケースでは、
  推測で記憶を保存せず、保存を見送ってください。
  不確実なノイズを長期記憶に混入させないことが優先されます。
</constraints>

<quick_rubric>
memory_save または session_flush を呼び出した後、以下のチェックリストで
自己検証を行い、すべて合格した場合のみ保存を確定してください。

1. **ツール呼び出しの正当性:**
   - [ ] 以下の保存トリガー条件のいずれかに該当するか？
         - memory_save: ユーザー指示の完了後、またはエラー→正常終了への変化直後
         - session_flush: 会話ログの総文字数が 8,000 文字に達した時、またはプロセス終了前
   - [ ] memory_save の場合: Semantic または Procedural に分類できる具体的な知識か？
         （一時的な状態・相槌・感情表現ではないか？）
   - [ ] session_flush の場合: conversation_log 引数に会話ログ全文を渡しているか？

2. **要約の自己完結性:**
   - [ ] 保存するテキストは、背景状況や会話履歴を参照せずに単体で理解できるか？
   - [ ] 固有名詞・コマンド・パス等の具体的な情報が省略されていないか？
   - [ ] 「先ほどの」「上記の」「これ」等の指示代名詞を含んでいないか？

3. **重複・ノイズの回避:**
   - [ ] 同一セッション内で、実質的に同じ内容を既に memory_save していないか？
   - [ ] 情報が不足・曖昧な場合は、保存を見送る判断をしたか？

いずれかのチェック項目が不合格の場合、保存を取り消すか内容を修正してください。
</quick_rubric>
```
