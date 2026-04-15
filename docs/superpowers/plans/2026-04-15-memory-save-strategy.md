# Memory Save Strategy 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** エージェントの自律的保存とシステムのバッチ保存を組み合わせたハイブリッド記憶保存戦略の `session_flush` 機能を実装する

**Architecture:** 新規コンポーネント `TaskRegistry`（バックグラウンドタスク管理）と `BatchProcessor`（バッチ処理ラッパー）を追加し、既存の `IngestionPipeline` に委譲する。MCP ツール `session_flush` は Fire-and-forget 方式で即座に `accepted` を返し、バックグラウンドで処理する。

**Tech Stack:** Python 3.12+, asyncio, FastMCP, pydantic-settings, pytest

**Design Doc:** [2026-04-14-memory-save-strategy-design.md](file:///home/y_ohi/program/private/chronos-graph/docs/superpowers/specs/2026-04-14-memory-save-strategy-design.md)

---

## File Structure

| ファイル | 責務 | 操作 |
|---|---|---|
| `src/context_store/ingestion/task_registry.py` | バックグラウンド asyncio.Task のライフサイクル管理 | **Create** |
| `src/context_store/ingestion/batch_processor.py` | 会話ログのバッチ処理ラッパー（IngestionPipeline 委譲） | **Create** |
| `src/context_store/config.py` | `batch_max_concurrent_jobs` 設定追加 | **Modify** |
| `src/context_store/orchestrator.py` | `session_flush()` メソッド追加、`dispose()` 拡張 | **Modify** |
| `src/context_store/server.py` | `session_flush` MCP ツール登録 | **Modify** |
| `src/context_store/ingestion/__init__.py` | 新規コンポーネントのエクスポート | **Modify** |
| `tests/unit/test_task_registry.py` | TaskRegistry のユニットテスト | **Create** |
| `tests/unit/test_batch_processor.py` | BatchProcessor のユニットテスト | **Create** |
| `tests/unit/test_session_flush_tools.py` | session_flush MCP ツール E2E テスト | **Create** |
| `docs/agent-prompts/memory-save-system-prompt.md` | Agent System Prompt Template | **Create** |

---

## Task 1: TaskRegistry — バックグラウンドタスク管理

> **PR スコープ:** 新規ファイル1個 + テスト1個。既存コードへの変更なし。

**Files:**

- Create: `src/context_store/ingestion/task_registry.py`
- Test: `tests/unit/test_task_registry.py`

### Step 1: テスト作成 — register と自動除去

- [ ] **Step 1.1: テストファイル作成**

```python
# tests/unit/test_task_registry.py
"""TaskRegistry のユニットテスト。"""

from __future__ import annotations

import asyncio
import logging

import pytest

from context_store.ingestion.task_registry import TaskRegistry


class TestTaskRegistryRegister:
    """TaskRegistry.register() のテスト。"""

    @pytest.mark.asyncio
    async def test_register_adds_task_and_removes_on_completion(self) -> None:
        """register() でタスクが追加され、完了後に done_callback で除去される。"""
        registry = TaskRegistry()

        async def noop() -> None:
            pass

        task = asyncio.create_task(noop())
        registry.register(task)
        assert len(registry) == 1

        # タスク完了を待機
        await task
        # done_callback はイベントループの次のサイクルで呼ばれる
        await asyncio.sleep(0)
        assert len(registry) == 0

    @pytest.mark.asyncio
    async def test_register_multiple_tasks(self) -> None:
        """複数タスクを register し、それぞれが独立して除去される。"""
        registry = TaskRegistry()
        event = asyncio.Event()

        async def wait_for_event() -> None:
            await event.wait()

        async def instant() -> None:
            pass

        task1 = asyncio.create_task(wait_for_event())
        task2 = asyncio.create_task(instant())
        registry.register(task1)
        registry.register(task2)
        assert len(registry) == 2

        # task2 は即完了
        await task2
        await asyncio.sleep(0)
        assert len(registry) == 1

        # task1 も完了させる
        event.set()
        await task1
        await asyncio.sleep(0)
        assert len(registry) == 0


class TestTaskRegistryDoneCallback:
    """done_callback のエラーハンドリングテスト。"""

    @pytest.mark.asyncio
    async def test_done_callback_logs_exception(self, caplog: pytest.LogCaptureFixture) -> None:
        """未処理例外のあるタスクは logger.error() で記録される。"""
        registry = TaskRegistry()

        async def raise_error() -> None:
            raise RuntimeError("test error")

        task = asyncio.create_task(raise_error())
        registry.register(task)

        # タスク完了を待機（例外はコールバックでキャッチ）
        with pytest.raises(RuntimeError):
            await task
        await asyncio.sleep(0)

        assert len(registry) == 0
        assert any("test error" in record.message for record in caplog.records)

    @pytest.mark.asyncio
    async def test_done_callback_logs_cancellation(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """キャンセルされたタスクは logger.debug() で記録される。"""
        registry = TaskRegistry()

        async def long_running() -> None:
            await asyncio.sleep(100)

        task = asyncio.create_task(long_running())
        registry.register(task)
        assert len(registry) == 1

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0)

        assert len(registry) == 0
        assert any(
            "cancelled" in record.message.lower()
            for record in caplog.records
            if record.levelno == logging.DEBUG
        )


class TestTaskRegistryCancelAll:
    """TaskRegistry.cancel_all() のテスト。"""

    @pytest.mark.asyncio
    async def test_cancel_all_cancels_running_tasks(self) -> None:
        """cancel_all() は全タスクをキャンセルする。"""
        registry = TaskRegistry()

        async def long_running() -> None:
            await asyncio.sleep(100)

        task1 = asyncio.create_task(long_running())
        task2 = asyncio.create_task(long_running())
        registry.register(task1)
        registry.register(task2)
        assert len(registry) == 2

        await registry.cancel_all(timeout=1.0)
        await asyncio.sleep(0)

        assert task1.cancelled()
        assert task2.cancelled()
        assert len(registry) == 0

    @pytest.mark.asyncio
    async def test_cancel_all_with_empty_registry(self) -> None:
        """空のレジストリで cancel_all() はエラーなく完了する。"""
        registry = TaskRegistry()
        await registry.cancel_all(timeout=1.0)
        assert len(registry) == 0

    @pytest.mark.asyncio
    async def test_cancel_all_timeout_handles_stubborn_task(self) -> None:
        """タイムアウト内にキャンセルできないタスクがあっても cancel_all() はハングしない。"""
        registry = TaskRegistry()

        async def stubborn() -> None:
            try:
                await asyncio.sleep(100)
            except asyncio.CancelledError:
                # キャンセルを無視してスリープ（ただしタイムアウト以内に終わる）
                await asyncio.sleep(0.1)

        task = asyncio.create_task(stubborn())
        registry.register(task)

        # タイムアウト 0.5s で cancel_all
        await registry.cancel_all(timeout=0.5)
        # cancel_all がハングせずに戻ることを確認
```

- [ ] **Step 1.2: テスト実行で失敗を確認**

Run: `uv run pytest tests/unit/test_task_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'context_store.ingestion.task_registry'`

### Step 2: TaskRegistry 実装

- [ ] **Step 2.1: task_registry.py 作成**

```python
# src/context_store/ingestion/task_registry.py
"""TaskRegistry: バックグラウンド asyncio.Task のライフサイクル管理。

バッチ処理等のバックグラウンドタスクを追跡し、
graceful shutdown 時の一括キャンセルを提供する。
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


class TaskRegistry:
    """In-memory registry of running asyncio.Task objects.

    Sole purpose: track background tasks for graceful shutdown cancellation.
    No state tracking, no history, no progress monitoring.
    """

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[None]] = set()

    def register(self, task: asyncio.Task[None]) -> None:
        """Register a task. Add done_callback for auto-removal and error logging.

        done_callback implementation:
        1. self._tasks.discard(task) で自身を除去
        2. task.cancelled() を確認
           - True の場合: logger.debug() で正常キャンセルとして記録 → 終了
        3. task.exception() で未処理例外を取得
           - 例外が存在する場合: logger.error() でスタックトレース付きログ出力
           - 例外なしの場合: logger.debug() で正常完了を記録
        4. 例外は再送出しない（バックグラウンドタスクのため呼び出し元に伝播不可）

        Note: task.cancelled() を先行チェックしないと、キャンセル済みタスクに対して
        task.exception() を呼んだ際に CancelledError が送出されるため順序は重要。
        """
        self._tasks.add(task)
        task.add_done_callback(self._on_task_done)

    def __len__(self) -> int:
        """Return the number of currently running tasks."""
        return len(self._tasks)

    def _on_task_done(self, task: asyncio.Task[None]) -> None:
        """Done callback: auto-remove task and log errors."""
        self._tasks.discard(task)

        if task.cancelled():
            logger.debug("Background task cancelled: %s", task.get_name())
            return

        exc = task.exception()
        if exc is not None:
            logger.error(
                "Background task failed: %s: %s",
                task.get_name(),
                exc,
                exc_info=exc,
            )
        else:
            logger.debug("Background task completed: %s", task.get_name())

    async def cancel_all(self, timeout: float = 5.0) -> None:
        """Cancel all running tasks with timeout. Called during graceful shutdown."""
        if not self._tasks:
            return

        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()

        # タスクの完了を待機（タイムアウト付き）
        await asyncio.wait(tasks, timeout=timeout)
```

- [ ] **Step 2.2: テスト実行で PASS を確認**

Run: `uv run pytest tests/unit/test_task_registry.py -v`
Expected: All tests PASS

- [ ] **Step 2.3: コミット**

```bash
git add src/context_store/ingestion/task_registry.py tests/unit/test_task_registry.py
git commit -m "feat(ingestion): TaskRegistry を追加 — バックグラウンドタスク管理"
```

---

## Task 2: BatchProcessor — バッチ処理ラッパー

> **PR スコープ:** 新規ファイル1個 + テスト1個。既存コードへの変更なし。

**Files:**

- Create: `src/context_store/ingestion/batch_processor.py`
- Test: `tests/unit/test_batch_processor.py`

### Step 1: テスト作成

- [ ] **Step 1.1: テストファイル作成**

```python
# tests/unit/test_batch_processor.py
"""BatchProcessor のユニットテスト。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from context_store.ingestion.batch_processor import BatchProcessor


class TestEstimateChunks:
    """BatchProcessor.estimate_chunks() のテスト。"""

    def test_estimate_chunks_with_qa_pairs(self) -> None:
        """Q&A ペアを含む会話ログのチャンク数を推定できる。"""
        mock_pipeline = MagicMock()
        processor = BatchProcessor(ingestion_pipeline=mock_pipeline)

        conversation_log = (
            "User: こんにちは\nAssistant: はい、こんにちは\n"
            "User: 質問があります\nAssistant: どうぞ\n"
            "User: Pythonについて教えてください\nAssistant: Pythonは...\n"
            "User: ありがとう\nAssistant: どういたしまして\n"
        )
        result = processor.estimate_chunks(conversation_log)
        # 4ターンペア → MAX_TURNS_PER_CHUNK=3 で分割 → 2チャンク程度
        assert isinstance(result, int)
        assert result >= 1

    def test_estimate_chunks_empty_returns_zero(self) -> None:
        """空文字列は 0 チャンクを返す。"""
        mock_pipeline = MagicMock()
        processor = BatchProcessor(ingestion_pipeline=mock_pipeline)

        result = processor.estimate_chunks("")
        assert result == 0

    def test_estimate_chunks_no_qa_pattern(self) -> None:
        """Q&A パターンなしのテキストも 0 以上のチャンク数を返す。"""
        mock_pipeline = MagicMock()
        processor = BatchProcessor(ingestion_pipeline=mock_pipeline)

        result = processor.estimate_chunks("ランダムテキスト\n改行のみ")
        assert isinstance(result, int)
        assert result >= 0


class TestProcess:
    """BatchProcessor.process() のテスト。"""

    @pytest.mark.asyncio
    async def test_process_delegates_to_ingestion_pipeline(self) -> None:
        """process() は IngestionPipeline.ingest() に委譲する。"""
        mock_pipeline = MagicMock()
        mock_pipeline.ingest = AsyncMock(return_value=[])
        processor = BatchProcessor(ingestion_pipeline=mock_pipeline)

        await processor.process(
            "User: test\nAssistant: response",
            session_id="test-session",
            project="test-project",
            tags=["tag1"],
        )

        mock_pipeline.ingest.assert_called_once()
        call_args = mock_pipeline.ingest.call_args
        assert call_args[0][0] == "User: test\nAssistant: response"

    @pytest.mark.asyncio
    async def test_process_passes_metadata(self) -> None:
        """process() は session_id, project, tags をメタデータに含める。"""
        mock_pipeline = MagicMock()
        mock_pipeline.ingest = AsyncMock(return_value=[])
        processor = BatchProcessor(ingestion_pipeline=mock_pipeline)

        await processor.process(
            "User: hello\nAssistant: hi",
            session_id="sess-123",
            project="my-project",
            tags=["important"],
        )

        call_kwargs = mock_pipeline.ingest.call_args[1]
        metadata = call_kwargs["metadata"]
        assert metadata["session_id"] == "sess-123"
        assert metadata["project"] == "my-project"
        assert metadata["tags"] == ["important"]

    @pytest.mark.asyncio
    async def test_process_logs_error_on_pipeline_failure(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """IngestionPipeline.ingest() が例外を投げた場合、ログに記録する。"""
        mock_pipeline = MagicMock()
        mock_pipeline.ingest = AsyncMock(side_effect=RuntimeError("pipeline error"))
        processor = BatchProcessor(ingestion_pipeline=mock_pipeline)

        # process() は例外をキャッチしてログに記録する
        await processor.process(
            "User: test\nAssistant: fail",
            session_id="test-session",
        )

        assert any("pipeline error" in record.message for record in caplog.records)
```

- [ ] **Step 1.2: テスト実行で失敗を確認**

Run: `uv run pytest tests/unit/test_batch_processor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'context_store.ingestion.batch_processor'`

### Step 2: BatchProcessor 実装

- [ ] **Step 2.1: batch_processor.py 作成**

```python
# src/context_store/ingestion/batch_processor.py
"""BatchProcessor: 会話ログのバッチ処理ラッパー。

IngestionPipeline への委譲を行う薄いラッパー。
チャンク数の推定と、バックグラウンドバッチ処理のエントリーポイントを提供する。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from context_store.ingestion.adapters import RawContent
from context_store.ingestion.chunker import Chunker
from context_store.models.memory import SourceType

if TYPE_CHECKING:
    from context_store.ingestion.pipeline import IngestionPipeline

logger = logging.getLogger(__name__)


class BatchProcessor:
    """Thin wrapper over IngestionPipeline for batch conversation log processing.

    Delegates all processing to IngestionPipeline.ingest().
    """

    def __init__(
        self,
        ingestion_pipeline: "IngestionPipeline",
    ) -> None:
        self._pipeline = ingestion_pipeline
        self._chunker = Chunker()

    def estimate_chunks(self, conversation_log: str) -> int:
        """Estimate chunk count using Chunker dry-run (no side effects).

        Creates a temporary RawContent with source_type=CONVERSATION,
        passes it through Chunker.chunk() to count yielded chunks,
        but does NOT persist anything. This is a pure read-only estimation.
        """
        if not conversation_log:
            return 0

        raw = RawContent(
            content=conversation_log,
            source_type=SourceType.CONVERSATION,
            metadata={},
        )
        # Chunker.chunk() はジェネレータなので、全件をカウントする
        return sum(1 for _ in self._chunker.chunk(raw))

    async def process(
        self,
        conversation_log: str,
        *,
        session_id: str,
        project: str | None = None,
        tags: list[str] | None = None,
    ) -> None:
        """Background batch processing entry point.

        Flow:
        1. IngestionPipeline.ingest() with source_type=CONVERSATION
        2. Errors are logged (committed chunks are retained, uncommitted are lost)
        """
        metadata: dict[str, object] = {"session_id": session_id}
        if project is not None:
            metadata["project"] = project
        if tags:
            metadata["tags"] = tags

        try:
            await self._pipeline.ingest(
                conversation_log,
                source_type=SourceType.CONVERSATION,
                metadata=metadata,
            )
            logger.info(
                "Batch processing completed: session_id=%s",
                session_id,
            )
        except Exception:
            logger.error(
                "Batch processing failed: session_id=%s",
                session_id,
                exc_info=True,
            )
```

- [ ] **Step 2.2: テスト実行で PASS を確認**

Run: `uv run pytest tests/unit/test_batch_processor.py -v`
Expected: All tests PASS

- [ ] **Step 2.3: コミット**

```bash
git add src/context_store/ingestion/batch_processor.py tests/unit/test_batch_processor.py
git commit -m "feat(ingestion): BatchProcessor を追加 — バッチ処理ラッパー"
```

---

## Task 3: Config 拡張 — batch_max_concurrent_jobs

> **PR スコープ:** 既存ファイル1行追加 + テスト1ケース追加。最小差分。

**Files:**

- Modify: `src/context_store/config.py:96-97` (Ingestion セクション付近に追加)
- Modify: `tests/unit/test_config.py` (新規テストケース追加)

### Step 1: テスト作成

- [ ] **Step 1.1: test_config.py にテストケース追加**

以下のテストを `tests/unit/test_config.py` の末尾に追加:

```python
class TestBatchConfig:
    """バッチ処理設定のテスト。"""

    def test_batch_max_concurrent_jobs_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """batch_max_concurrent_jobs のデフォルト値は 3。"""
        monkeypatch.delenv("BATCH_MAX_CONCURRENT_JOBS", raising=False)
        settings = Settings(embedding_provider="local-model")
        assert settings.batch_max_concurrent_jobs == 3

    def test_batch_max_concurrent_jobs_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """環境変数から batch_max_concurrent_jobs を設定できる。"""
        monkeypatch.setenv("BATCH_MAX_CONCURRENT_JOBS", "5")
        settings = Settings(embedding_provider="local-model")
        assert settings.batch_max_concurrent_jobs == 5

    def test_batch_max_concurrent_jobs_minimum(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """batch_max_concurrent_jobs は最小 1。"""
        monkeypatch.setenv("BATCH_MAX_CONCURRENT_JOBS", "0")
        with pytest.raises(Exception):
            Settings(embedding_provider="local-model")
```

- [ ] **Step 1.2: テスト実行で失敗を確認**

Run: `uv run pytest tests/unit/test_config.py::TestBatchConfig -v`
Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'batch_max_concurrent_jobs'`

### Step 2: config.py に設定追加

- [ ] **Step 2.1: config.py の Ingestion セクションに追加**

`src/context_store/config.py` の `conversation_chunk_size` の次の行 (L99) に以下を追加:

```python
    # --- Batch Processing ---
    batch_max_concurrent_jobs: int = Field(default=3, ge=1)
```

- [ ] **Step 2.2: テスト実行で PASS を確認**

Run: `uv run pytest tests/unit/test_config.py::TestBatchConfig -v`
Expected: All tests PASS

- [ ] **Step 2.3: コミット**

```bash
git add src/context_store/config.py tests/unit/test_config.py
git commit -m "feat(config): batch_max_concurrent_jobs 設定を追加"
```

---

## Task 4: Orchestrator 統合 — session_flush メソッド

> **PR スコープ:** Orchestrator に `session_flush()` 追加、`dispose()` 拡張、ファクトリ関数更新。

**Files:**

- Modify: `src/context_store/orchestrator.py`
- Modify: `tests/unit/test_orchestrator.py` (新規テストケース追加)

### Step 1: テスト作成

- [ ] **Step 1.1: test_orchestrator.py にテストケース追加**

以下のテストを `tests/unit/test_orchestrator.py` の末尾に追加:

```python
class TestSessionFlush:
    """Orchestrator.session_flush() のテスト。"""

    @pytest.fixture
    def orchestrator_with_batch(self, orchestrator: Orchestrator) -> Orchestrator:
        """TaskRegistry と BatchProcessor を注入した Orchestrator。"""
        from unittest.mock import MagicMock

        from context_store.ingestion.batch_processor import BatchProcessor
        from context_store.ingestion.task_registry import TaskRegistry

        orchestrator._task_registry = TaskRegistry()
        mock_batch = MagicMock(spec=BatchProcessor)
        mock_batch.estimate_chunks = MagicMock(return_value=5)
        orchestrator._batch_processor = mock_batch
        return orchestrator

    @pytest.mark.asyncio
    async def test_session_flush_returns_accepted(
        self, orchestrator_with_batch: Orchestrator
    ) -> None:
        """session_flush() は status=accepted を返す。"""
        result = await orchestrator_with_batch.session_flush(
            conversation_log="User: hello\nAssistant: hi",
        )
        assert result["status"] == "accepted"
        assert result["estimated_chunks"] == 5

    @pytest.mark.asyncio
    async def test_session_flush_rejects_empty_log(
        self, orchestrator_with_batch: Orchestrator
    ) -> None:
        """空の conversation_log はエラーを返す。"""
        result = await orchestrator_with_batch.session_flush(
            conversation_log="",
        )
        assert "error" in result

    @pytest.mark.asyncio
    async def test_session_flush_rejects_oversized_log(
        self, orchestrator_with_batch: Orchestrator
    ) -> None:
        """200,000 文字超過の conversation_log はエラーを返す。"""
        result = await orchestrator_with_batch.session_flush(
            conversation_log="A" * 200_001,
        )
        assert "error" in result
        assert "200000" in result["error"]

    @pytest.mark.asyncio
    async def test_session_flush_accepts_max_length(
        self, orchestrator_with_batch: Orchestrator
    ) -> None:
        """200,000 文字ちょうどの conversation_log は受理される。"""
        result = await orchestrator_with_batch.session_flush(
            conversation_log="A" * 200_000,
        )
        assert result["status"] == "accepted"

    @pytest.mark.asyncio
    async def test_session_flush_rejects_when_too_many_jobs(
        self, orchestrator_with_batch: Orchestrator
    ) -> None:
        """batch_max_concurrent_jobs 超過時はエラーを返す。"""
        import asyncio

        # TaskRegistry にダミータスクを 3 つ追加
        for _ in range(3):
            task = asyncio.create_task(asyncio.sleep(100))
            orchestrator_with_batch._task_registry.register(task)

        # 設定上限を 3 に
        orchestrator_with_batch._settings.batch_max_concurrent_jobs = 3

        result = await orchestrator_with_batch.session_flush(
            conversation_log="User: test\nAssistant: test",
        )
        assert "error" in result
        assert "Too many concurrent jobs" in result["error"]

        # クリーンアップ
        await orchestrator_with_batch._task_registry.cancel_all(timeout=1.0)


class TestDisposeWithTaskRegistry:
    """dispose() が TaskRegistry.cancel_all() を呼ぶことを検証。"""

    @pytest.mark.asyncio
    async def test_dispose_calls_task_registry_cancel_all(
        self, orchestrator: Orchestrator
    ) -> None:
        """dispose() は TaskRegistry.cancel_all() を呼び出す。"""
        from unittest.mock import AsyncMock

        from context_store.ingestion.task_registry import TaskRegistry

        mock_registry = AsyncMock(spec=TaskRegistry)
        orchestrator._task_registry = mock_registry

        await orchestrator.dispose()

        mock_registry.cancel_all.assert_called_once_with(timeout=5.0)
```

- [ ] **Step 1.2: テスト実行で失敗を確認**

Run: `uv run pytest tests/unit/test_orchestrator.py::TestSessionFlush -v`
Expected: FAIL with `AttributeError: 'Orchestrator' object has no attribute 'session_flush'`

### Step 2: Orchestrator 実装

- [ ] **Step 2.1: orchestrator.py に session_flush メソッドと依存追加**

`src/context_store/orchestrator.py` に以下の変更を適用:

**1. インポート追加** (TYPE_CHECKING ブロック内):

```python
    from context_store.ingestion.batch_processor import BatchProcessor
    from context_store.ingestion.task_registry import TaskRegistry
```

**2. `__init__` のシグネチャ拡張** — `settings` 引数の後に追加:

```python
        task_registry: "TaskRegistry | None" = None,
        batch_processor: "BatchProcessor | None" = None,
```

コンストラクタ本体にインスタンス変数追加:

```python
        self._task_registry = task_registry
        self._batch_processor = batch_processor
```

**3. `session_flush()` メソッド追加** — `save()` メソッドの前:

```python
    # 入力バリデーション定数
    _SESSION_FLUSH_MAX_LOG_LENGTH = 200_000

    async def session_flush(
        self,
        conversation_log: str,
        session_id: str | None = None,
        project: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """会話ログをバックグラウンドでバッチ保存する (Fire-and-forget)。

        Args:
            conversation_log: 会話ログ全文。
            session_id: セッション ID（None の場合は自動生成）。
            project: プロジェクト名。
            tags: タグのリスト。

        Returns:
            status=accepted の dict、またはエラー dict。
        """
        import uuid as uuid_mod

        # 入力バリデーション
        if not conversation_log:
            return {"error": "conversation_log must not be empty"}
        if len(conversation_log) > self._SESSION_FLUSH_MAX_LOG_LENGTH:
            return {
                "error": f"conversation_log exceeds maximum length of "
                f"{self._SESSION_FLUSH_MAX_LOG_LENGTH} characters"
            }

        if self._task_registry is None or self._batch_processor is None:
            return {"error": "Batch processing is not configured"}

        # 同時実行数チェック
        max_jobs = self._settings.batch_max_concurrent_jobs if self._settings else 3
        if len(self._task_registry) >= max_jobs:
            return {"error": "Too many concurrent jobs"}

        # チャンク数推定
        estimated_chunks = self._batch_processor.estimate_chunks(conversation_log)

        # バックグラウンドタスク作成
        effective_session_id = session_id or str(uuid_mod.uuid4())
        task = asyncio.create_task(
            self._batch_processor.process(
                conversation_log,
                session_id=effective_session_id,
                project=project,
                tags=tags,
            ),
            name=f"session_flush:{effective_session_id}",
        )
        self._task_registry.register(task)

        return {"status": "accepted", "estimated_chunks": estimated_chunks}
```

**4. `dispose()` メソッド拡張** — 先頭に TaskRegistry のキャンセル追加:

```python
    async def dispose(self) -> None:
        """全アダプターのリソースを解放する。"""
        # バックグラウンドタスクのキャンセル（5s タイムアウト）
        if self._task_registry is not None:
            await self._task_registry.cancel_all(timeout=5.0)

        await self._lifecycle_manager.graceful_shutdown()
        await self._storage.dispose()
        if self._graph is not None:
            await self._graph.dispose()
        await self._cache.dispose()
```

**5. `create_orchestrator()` ファクトリ関数更新**:

インポート追加（既存の遅延インポートブロック内）:

```python
        from context_store.ingestion.batch_processor import BatchProcessor
        from context_store.ingestion.task_registry import TaskRegistry
```

Orchestrator 生成の直前に追加:

```python
        # TaskRegistry と BatchProcessor 組み立て
        task_registry = TaskRegistry()
        batch_processor = BatchProcessor(ingestion_pipeline=ingestion_pipeline)
```

`Orchestrator(...)` コンストラクタ呼び出しに引数追加:

```python
            task_registry=task_registry,
            batch_processor=batch_processor,
```

- [ ] **Step 2.2: テスト実行で PASS を確認**

Run: `uv run pytest tests/unit/test_orchestrator.py::TestSessionFlush tests/unit/test_orchestrator.py::TestDisposeWithTaskRegistry -v`
Expected: All tests PASS

- [ ] **Step 2.3: 既存テストのリグレッションチェック**

Run: `uv run pytest tests/unit/test_orchestrator.py -v`
Expected: All tests PASS (既存テスト含む)

- [ ] **Step 2.4: コミット**

```bash
git add src/context_store/orchestrator.py tests/unit/test_orchestrator.py
git commit -m "feat(orchestrator): session_flush メソッドと dispose 拡張を追加"
```

---

## Task 5: MCP ツール登録 — session_flush

> **PR スコープ:** server.py にツール登録、E2E テスト。

**Files:**

- Modify: `src/context_store/server.py`
- Create: `tests/unit/test_session_flush_tools.py`

### Step 1: テスト作成

- [ ] **Step 1.1: test_session_flush_tools.py 作成**

```python
# tests/unit/test_session_flush_tools.py
"""session_flush MCP ツールの E2E テスト。"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from context_store.server import ChronosServer


@pytest.fixture
def server_with_mock_orchestrator() -> ChronosServer:
    """Mock Orchestrator を持つ ChronosServer。"""
    server = ChronosServer()
    mock_orchestrator = MagicMock()
    mock_orchestrator.session_flush = AsyncMock(
        return_value={"status": "accepted", "estimated_chunks": 3}
    )
    mock_orchestrator.url_fetch_concurrency = 3
    server._orchestrator = mock_orchestrator
    server._initialized = True
    return server


class TestSessionFlushTool:
    """session_flush MCP ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_session_flush_returns_accepted(
        self, server_with_mock_orchestrator: ChronosServer
    ) -> None:
        """session_flush ツールが accepted を返す。"""
        result_str = await server_with_mock_orchestrator.session_flush(
            conversation_log="User: hello\nAssistant: hi",
        )
        result = json.loads(result_str)
        assert result["status"] == "accepted"
        assert result["estimated_chunks"] == 3

    @pytest.mark.asyncio
    async def test_session_flush_passes_all_args(
        self, server_with_mock_orchestrator: ChronosServer
    ) -> None:
        """session_flush ツールが全引数を Orchestrator に渡す。"""
        await server_with_mock_orchestrator.session_flush(
            conversation_log="User: test\nAssistant: test",
            session_id="test-session",
            project="my-project",
            tags=["tag1", "tag2"],
        )

        mock_orch = server_with_mock_orchestrator._orchestrator
        mock_orch.session_flush.assert_called_once_with(
            conversation_log="User: test\nAssistant: test",
            session_id="test-session",
            project="my-project",
            tags=["tag1", "tag2"],
        )

    @pytest.mark.asyncio
    async def test_session_flush_empty_log_returns_error(
        self, server_with_mock_orchestrator: ChronosServer
    ) -> None:
        """空 conversation_log のエラーが JSON で返る。"""
        mock_orch = server_with_mock_orchestrator._orchestrator
        mock_orch.session_flush = AsyncMock(
            return_value={"error": "conversation_log must not be empty"}
        )

        result_str = await server_with_mock_orchestrator.session_flush(
            conversation_log="",
        )
        result = json.loads(result_str)
        assert "error" in result
```

- [ ] **Step 1.2: テスト実行で失敗を確認**

Run: `uv run pytest tests/unit/test_session_flush_tools.py -v`
Expected: FAIL with `AttributeError: 'ChronosServer' object has no attribute 'session_flush'`

### Step 2: server.py にツール登録

- [ ] **Step 2.1: ChronosServer に session_flush メソッド追加**

`src/context_store/server.py` の `ChronosServer` クラスに追加（`memory_save` の前に配置）:

```python
    async def session_flush(
        self,
        conversation_log: str,
        session_id: str | None = None,
        project: str | None = None,
        tags: list[str] | None = None,
    ) -> str:
        """会話ログをバックグラウンドでバッチ保存する。

        Args:
            conversation_log: 会話ログ全文 (User: .../Assistant: ... 形式)。
                最大 200,000 文字。
            session_id: セッション識別子（省略可、自動生成）。
            project: プロジェクト名。
            tags: タグのリスト。

        Returns:
            処理結果の JSON 文字列。
        """
        await self._ensure_initialized()
        if self._orchestrator is None:
            raise RuntimeError("Orchestrator not initialized")

        result = await self._orchestrator.session_flush(
            conversation_log=conversation_log,
            session_id=session_id,
            project=project,
            tags=tags,
        )
        return json.dumps(result)
```

- [ ] **Step 2.2: FastMCP ツール関数登録**

`src/context_store/server.py` のツール登録セクション（`memory_save` の前）に追加:

```python
@mcp.tool()
async def session_flush(
    conversation_log: str,
    session_id: str | None = None,
    project: str | None = None,
    tags: list[str] | None = None,
) -> str:
    """会話ログをバックグラウンドでバッチ保存する。

    Args:
        conversation_log: 会話ログ全文 (User: .../Assistant: ... 形式)。
            最大 200,000 文字。超過時はバリデーションエラーを返す。
        session_id: セッション識別子（省略可、自動生成）。
        project: プロジェクト名。
        tags: タグのリスト。
    """
    return await _server.session_flush(
        conversation_log=conversation_log,
        session_id=session_id,
        project=project,
        tags=tags,
    )
```

- [ ] **Step 2.3: テスト実行で PASS を確認**

Run: `uv run pytest tests/unit/test_session_flush_tools.py -v`
Expected: All tests PASS

- [ ] **Step 2.4: 既存テストのリグレッションチェック**

Run: `uv run pytest tests/unit/test_server.py -v`
Expected: All tests PASS (既存テスト含む)

- [ ] **Step 2.5: コミット**

```bash
git add src/context_store/server.py tests/unit/test_session_flush_tools.py
git commit -m "feat(server): session_flush MCP ツールを登録"
```

---

## Task 6: エクスポート整理と Agent System Prompt

> **PR スコープ:** `__init__.py` 更新 + ドキュメント追加。コードロジックの変更なし。

**Files:**

- Modify: `src/context_store/ingestion/__init__.py`
- Create: `docs/agent-prompts/memory-save-system-prompt.md`

### Step 1: __init__.py 更新

- [ ] **Step 1.1: 新規コンポーネントをエクスポート**

`src/context_store/ingestion/__init__.py` に以下を追加:

インポート追加:

```python
from context_store.ingestion.batch_processor import BatchProcessor
from context_store.ingestion.task_registry import TaskRegistry
```

`__all__` リストに追加:

```python
    "BatchProcessor",
    "TaskRegistry",
```

### Step 2: Agent System Prompt ドキュメント配置

- [ ] **Step 2.1: ドキュメントファイル作成**

設計ドキュメントの Appendix A (Agent System Prompt Template) を
`docs/agent-prompts/memory-save-system-prompt.md` にコピー。
内容は設計ドキュメントの Section "Appendix A" をそのまま転記する。

```markdown
# Memory Save — Agent System Prompt Template

> このファイルは AI エージェントのシステムプロンプトに統合するためのテンプレートです。
> MCP サーバーのコードベースには埋め込みません。

<!-- 設計ドキュメントの Appendix A の XML テンプレートをここにコピー -->
```

- [ ] **Step 2.2: コミット**

```bash
git add src/context_store/ingestion/__init__.py docs/agent-prompts/memory-save-system-prompt.md
git commit -m "docs: エクスポート整理と Agent System Prompt テンプレートを配置"
```

---

## Task 7: 全体リグレッションテスト

> **PR スコープ:** テスト実行のみ。コード変更なし。

- [ ] **Step 1: 全ユニットテスト実行**

Run: `uv run pytest tests/unit/ -v`
Expected: All tests PASS

- [ ] **Step 2: ruff lint チェック**

Run: `uv run ruff check src/context_store/ingestion/task_registry.py src/context_store/ingestion/batch_processor.py src/context_store/orchestrator.py src/context_store/server.py src/context_store/config.py`
Expected: No errors

- [ ] **Step 3: mypy 型チェック**

Run: `uv run mypy src/context_store/ingestion/task_registry.py src/context_store/ingestion/batch_processor.py src/context_store/orchestrator.py src/context_store/server.py`
Expected: No errors

---

## Summary: コミット/PR 構成

| # | コミット | 変更ファイル数 | スコープ |
|---|---|---|---|
| 1 | `feat(ingestion): TaskRegistry を追加` | 2 (src + test) | 新規のみ |
| 2 | `feat(ingestion): BatchProcessor を追加` | 2 (src + test) | 新規のみ |
| 3 | `feat(config): batch_max_concurrent_jobs 設定を追加` | 2 (src + test) | 1行追加 |
| 4 | `feat(orchestrator): session_flush と dispose 拡張` | 2 (src + test) | 既存修正 |
| 5 | `feat(server): session_flush MCP ツールを登録` | 2 (src + test) | 既存修正 |
| 6 | `docs: エクスポート整理と Agent System Prompt` | 2 (src + doc) | 整理のみ |

> [!TIP]
> PR は **1つの PR にまとめる** ことを推奨します。コミットが6個に分かれているため、
> レビュアーはコミット単位で差分を確認できます。
> 各コミットは独立してテストが通る状態を維持しています。
