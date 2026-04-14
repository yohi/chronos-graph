# ChronosGraph: 記憶保存戦略アーキテクチャ設計

**レビュー回数: 2回目**

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
| ジョブ管理 | `TaskDispatcher` 経由の非同期ジョブ | テスト時に同期実行を注入可能 |
| トリガー管理 | クライアント側が全責任 | サーバーで会話ターン追跡は不適切 |
| RL フック | 既存 Protocol + NoOp を維持（実装は将来フェーズ） | 学習ループ本体が未導入のため YAGNI |
| 逐次返却方式 | `ingest_stream()` AsyncGenerator + `ingest()` ラッパー | リアルタイム進捗更新を実現しつつ既存 API の後方互換性を維持 |
| ベストエフォート書き込み | 共通ユーティリティ `best_effort_write` に集約 | DRY: 同一パターンの散在を防止 |
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
│  │  ┌──────────────┐  ┌──────────────┐                     │ │
│  │  │  Ingestion   │  │   Batch      │                     │ │
│  │  │  Pipeline    │  │   Processor  │                     │ │
│  │  │  (既存)      │  │  NEW         │                     │ │
│  │  └──────┬───────┘  └──────┬───────┘                     │ │
│  │         │    ┌────────────┘                              │ │
│  │         │    │  ┌───────────────┐  ┌──────────────────┐ │ │
│  │         │    │  │ Job Manager   │  │ TaskDispatcher   │ │ │
│  │         │    │  │ NEW           │  │ NEW              │ │ │
│  │         │    │  └───────────────┘  └──────────────────┘ │ │
│  │         │    │                                          │ │
│  │  ┌──────┴────┴──────────────────────────────────────┐   │ │
│  │  │    Storage Layer (既存) + best_effort_write 共通  │   │ │
│  │  └─────────────────────────────────────────────────┘   │ │
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
  ├─ TaskDispatcher.dispatch(BatchProcessor.process(job_id, ...)) → task
  ├─ JobManager.register_task(job_id, task)
  └─ return {job_id, status: "queued", estimated_chunks}

# Background:
BatchProcessor.process()
  ├─ JobManager.mark_running(job_id)
  ├─ async for result in IngestionPipeline.ingest_stream(...):
  │   │  # 各チャンクが処理完了するたびに yield される
  │   │  ├─ Chunker._split_conversation() → Q&A pair splitting
  │   │  ├─ Classifier.classify() → EPISODIC (default)
  │   │  ├─ EmbeddingProvider.embed() → vectorization
  │   │  ├─ Deduplicator.deduplicate() → dedup check (>= 0.90 → SUPERSEDES)
  │   │  └─ StorageAdapter.save_memory() → persist (per-chunk commit)
  │   └─ JobManager.update_progress(job_id, result.memory_id)  ← リアルタイム更新
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
        2. async for result in IngestionPipeline.ingest_stream():
             JobManager.update_progress(job_id, result.memory_id)
           → チャンク処理完了のたびにリアルタイムで進捗更新
        3. JobManager.mark_completed(job_id) on success
        4. JobManager.mark_failed(job_id, error) on exception (after logging)

        ingest_stream() は AsyncGenerator[IngestionResult, None] を返し、
        各チャンクの処理が完了するたびに yield する。これにより
        session_flush_status で中間進捗をリアルタイムに確認可能。
        """
```

### 3.3 TaskDispatcher

**File:** `src/context_store/ingestion/task_dispatcher.py`

```python
@runtime_checkable
class TaskDispatcher(Protocol):
    """非同期タスクのディスパッチを抽象化するプロトコル。

    本番環境では asyncio.create_task() に委譲し、
    テスト環境ではコルーチンを同期的に実行するスタブを注入できる。
    """

    def dispatch(self, coro: Coroutine[Any, Any, T]) -> asyncio.Task[T]: ...


class AsyncTaskDispatcher:
    """本番用: asyncio.create_task() に委譲するデフォルト実装。"""

    def dispatch(self, coro: Coroutine[Any, Any, T]) -> asyncio.Task[T]:
        return asyncio.create_task(coro)


class SyncTaskDispatcher:
    """テスト用: コルーチンを即座に同期実行し、完了済みTaskを返す。

    テストコードから注入することで、バックグラウンドジョブの
    実行タイミングを決定論的に制御できる。
    """

    def dispatch(self, coro: Coroutine[Any, Any, T]) -> asyncio.Task[T]:
        loop = asyncio.get_event_loop()
        task = loop.create_task(coro)
        # テスト内で await task を呼ぶことで同期的に完了を待機可能
        return task
```

**設計意図:**

- `Orchestrator.session_flush()` は `TaskDispatcher.dispatch()` 経由でバッチジョブを起動
- テスト時は `SyncTaskDispatcher` を注入し、`await task` で同期完了を保証
- 既存の `asyncio.create_task()` 呼び出し箇所（lifecycle/manager.py, pipeline.py）は
  本設計のスコープ外だが、将来的に同一パターンで移行可能

### 3.4 best_effort_write ユーティリティ

**File:** `src/context_store/utils/best_effort.py`

```python
async def best_effort_write(
    operation: str,
    coro: Coroutine[Any, Any, T],
    *,
    logger: logging.Logger | None = None,
) -> T | None:
    """ベストエフォート型の非同期書き込みを実行する共通ユーティリティ。

    成功時は結果を返し、失敗時は WARNING ログを出力して None を返す。
    例外は呼び出し元に伝播しない。

    Args:
        operation: ログ出力用の操作名（例: "graph_delete", "batch_chunk_save"）
        coro: 実行する非同期コルーチン
        logger: ロガーインスタンス（省略時はモジュールロガーを使用）

    Returns:
        成功時: コルーチンの戻り値 / 失敗時: None

    Usage:
        result = await best_effort_write(
            "graph_delete",
            self._graph.delete_node(memory_id),
        )
    """
    _logger = logger or logging.getLogger(__name__)
    try:
        return await coro
    except Exception:
        _logger.warning("Best-effort %s failed", operation, exc_info=True)
        return None
```

**設計意図:**

- エラー時の WARNING ログ出力 + 例外握りつぶしパターンを単一箇所に集約
- BatchProcessor のチャンクレベルエラー処理で使用
- Orchestrator 内の既存のグラフ操作エラー処理も段階的に移行可能
- 将来 RL コンポーネント（SqliteActionLogger 等）を追加する際も本ユーティリティを使用

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

## 5. Configuration

### 5.1 New Settings Parameters

| Parameter | Env Var | Default | Description |
|---|---|---|---|
| `batch_max_concurrent_jobs` | `BATCH_MAX_CONCURRENT_JOBS` | `3` | Max concurrent batch jobs |
| `batch_max_retained_jobs` | `BATCH_MAX_RETAINED_JOBS` | `100` | Max in-memory job history |

---

## 6. Modified Existing Files

### 6.1 server.py

- Add `session_flush` and `session_flush_status` MCP tool registrations
- Delegate to `ChronosServer.session_flush()` and `ChronosServer.session_flush_status()`

### 6.2 orchestrator.py

- Add `BatchProcessor`, `JobManager`, `TaskDispatcher` as constructor dependencies
- Add `session_flush()` method: estimate chunks → create job → `TaskDispatcher.dispatch()` → return job_id
- Add `session_flush_status()` method: delegate to JobManager.get_job()
- Update `dispose()` to call `JobManager.cancel_all()`

### 6.3 orchestrator.py (create_orchestrator factory)

- Instantiate `JobManager`, `BatchProcessor`, `AsyncTaskDispatcher`
- Pass `TaskDispatcher` to Orchestrator

### 6.4 ingestion/pipeline.py (ingest_stream / IngestionResult / _process_chunk)

#### 6.4.1 ingest_stream() — AsyncGenerator によるチャンク逐次返却

既存の `ingest()` が全チャンクを処理後にまとめて `list[IngestionResult]` を返す設計を改め、
チャンク処理完了のたびに `yield` する `ingest_stream()` を導入する。

```python
async def ingest_stream(
    self,
    source: str,
    *,
    source_type: SourceType = SourceType.MANUAL,
    metadata: dict[str, Any] | None = None,
) -> AsyncGenerator[IngestionResult, None]:
    """コンテンツを取り込み、チャンクごとに逐次 yield する。

    各チャンクの処理（分類→埋め込み→重複排除→永続化）が完了するたびに
    IngestionResult を yield する。呼び出し元は async for でリアルタイムに
    結果を受け取り、進捗更新や中間処理を実行できる。

    Args:
        source: コンテンツ本文または URL
        source_type: ソースタイプ
        metadata: 追加メタデータ（project, session_id など）

    Yields:
        IngestionResult: 各チャンクの処理結果

    Raises:
        RuntimeError: 全チャンクが失敗した場合
    """
    meta = metadata or {}

    if source_type == SourceType.URL:
        raw_contents = await self._fetch_url_content(source)
    elif source_type == SourceType.CONVERSATION:
        raw_contents = await self._conversation_adapter.adapt(source, metadata=meta)
    else:
        raw_contents = [RawContent(content=source, source_type=source_type, metadata=meta)]

    document_memories: dict[str, list[Memory]] = {}
    failed_chunks: list[dict[str, Any]] = []
    total_chunks = 0
    yielded_count = 0

    for raw in raw_contents:
        chunks = list(self._chunker.chunk(raw))
        total_chunks += len(chunks)

        for chunk in chunks:
            document_id = str(chunk.metadata.get("document_id", ""))
            prior_document_memories = document_memories.get(document_id, [])
            content_hash = self._compute_hash(chunk.content)
            try:
                result = await self._process_chunk(
                    chunk,
                    base_metadata=meta,
                    prior_document_memories=prior_document_memories,
                )
                if result:
                    yielded_count += 1
                    if document_id and result.persisted_memory is not None:
                        document_memories.setdefault(document_id, []).append(
                            result.persisted_memory
                        )
                    yield result  # チャンク完了のたびに逐次返却
            except Exception as e:
                logger.error(
                    "Chunk 処理失敗 (content_hash=%s, doc_id=%s): %s",
                    content_hash[:8], document_id, e, exc_info=True,
                )
                failed_chunks.append({
                    "content_hash": content_hash,
                    "document_id": document_id,
                    "error": str(e),
                })

    if total_chunks > 0 and yielded_count == 0:
        raise RuntimeError(
            f"Ingestion 全件失敗 ({len(failed_chunks)}/{total_chunks} chunks). "
            f"Failures: {failed_chunks}"
        )
```

#### 6.4.2 ingest() — 既存インターフェースの維持（DRY ラッパー）

既存の `ingest()` は `ingest_stream()` を内部利用するラッパーとして再実装する。
これにより、`memory_save` 等の既存呼び出し元は変更不要。

```python
async def ingest(
    self,
    source: str,
    *,
    source_type: SourceType = SourceType.MANUAL,
    metadata: dict[str, Any] | None = None,
) -> list[IngestionResult]:
    """コンテンツを取り込んで永続化する（一括返却）。

    内部的に ingest_stream() を使用し、全結果を収集して返す。
    既存の呼び出し元との後方互換性を維持する。
    """
    return [
        result
        async for result in self.ingest_stream(
            source, source_type=source_type, metadata=metadata
        )
    ]
```

#### 6.4.3 IngestionResult / _process_chunk の変更

- `IngestionResult` に `embedding_completed_at: datetime` フィールドを追加
- `_process_chunk()` 内で `embed()` 完了直後にタイムスタンプを記録し、`IngestionResult` に格納
- 既存の `persisted_memory` には `created_at`（= `persisted_at` 相当）が含まれるため、
  `embedding_completed_at < persisted_memory.created_at` をテスト側でアサートすることで、
  モック呼び出し順序に依存せずトランザクション境界の正しさを検証可能

```python
# _process_chunk() 内の変更イメージ:
embedding = await self._embedding_provider.embed(chunk.content)
embedding_completed_at = datetime.now(timezone.utc)  # NEW: タイムスタンプ記録
# ... (以降は既存のロック取得 → save_memory)

return IngestionResult(
    memory_id=str(memory_id),
    action=dedup_result.action,
    memory_type=classification.memory_type,
    chunk_index=chunk_index,
    chunk_count=chunk_count,
    persisted_memory=persisted_memory,
    embedding_completed_at=embedding_completed_at,  # NEW
)
```

### 6.5 config.py

- Add batch configuration parameters (see Section 5.1)

---

## 7. Error Handling

| Scenario | Behavior |
|---|---|
| Process terminates during `session_flush` | Committed chunks are retained; uncommitted are lost. Job state (in-memory) is lost |
| `batch_max_concurrent_jobs` exceeded | Immediate error response: `{"error": "Too many concurrent jobs"}` |
| Unknown `job_id` in `session_flush_status` | Return `{"error": "Job not found", "job_id": "..."}` |
| Individual chunk ingestion failure in batch | `best_effort_write` でWARNINGログを出力し、失敗チャンクをスキップして継続。全チャンク失敗時のみジョブを `failed` に遷移 |

---

## 8. Testing Strategy

All tests MUST be executed within the devcontainer environment.

### 8.1 New Test Files

| Test File | Coverage |
|---|---|
| `tests/unit/test_job_manager.py` | JobManager state transitions, concurrency limits, cleanup |
| `tests/unit/test_batch_processor.py` | BatchProcessor chunk estimation, Ingestion delegation, progress updates |
| `tests/unit/test_task_dispatcher.py` | TaskDispatcher Protocol 準拠、SyncTaskDispatcher の同期実行保証 |
| `tests/unit/test_best_effort.py` | `best_effort_write` の成功パス、例外握りつぶし、ログ出力検証 |
| `tests/unit/test_session_flush_tools.py` | session_flush / session_flush_status MCP tool E2E |

### 8.2 Key Test Scenarios

1. **Job state transitions:** `QUEUED → RUNNING → COMPLETED` and `QUEUED → RUNNING → FAILED`
2. **Concurrency limit:** Reject when exceeding `batch_max_concurrent_jobs`
3. **TaskDispatcher 注入によるテスト決定性:** `SyncTaskDispatcher` を注入し、バッチジョブの完了を `await` で同期的に待機することで、テストの非決定性を排除
4. **Transaction boundary (IngestionResult ベースの検証):** `IngestionPipeline._process_chunk()` の戻り値 `IngestionResult` に `embedding_completed_at` タイムスタンプを含め、`embedding_completed_at < persisted_at` をアサートすることで、モック順序に依存せず embed → save_memory の実行順序を検証。並行実行時は複数チャンクの `IngestionResult` を収集し、各結果のタイムスタンプの一貫性を検証
5. **Graceful shutdown:** `cancel_all()` cancels running jobs within timeout
6. **Chunk failure resilience:** `best_effort_write` 経由で失敗チャンクをスキップし、部分的な失敗がジョブ全体を失敗させないことを検証
7. **ingest_stream() リアルタイム進捗:** `BatchProcessor.process()` 内で `ingest_stream()` の各 yield ごとに `JobManager.update_progress()` が呼ばれ、`session_flush_status` で中間進捗（`done: 1/5`, `done: 2/5`, ...）が確認できることを検証
8. **ingest_stream() モック容易性:** テスト用の `AsyncGenerator` をモックとして注入し、yield タイミングと進捗更新の対応関係を決定論的に検証。パターン: `async def mock_stream(): yield result1; yield result2`
9. **ingest() 後方互換性:** `ingest_stream()` ラッパーとしての `ingest()` が、既存テストと同一の `list[IngestionResult]` を返すことを検証

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
| RL データ蓄積基盤 (SqliteActionLogger / SqliteRewardSignal / DBテーブル) | 学習ループ本体が未導入のためYAGNI。既存 Protocol + NoOp を維持し、学習フェーズで実装 |
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
| §10 RL Extension Points (Protocol definitions) | Protocol + NoOp を維持。SQLite 実装は学習フェーズまで保留 |
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
