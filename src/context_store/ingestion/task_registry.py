"""TaskRegistry: バックグラウンド asyncio.Task のライフサイクル管理。

バッチ処理等のバックグラウンドタスクを追跡し、
graceful shutdown 時の一括キャンセルを提供する。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class TaskRegistry:
    """In-memory registry of running asyncio.Task objects.

    Sole purpose: track background tasks for graceful shutdown cancellation.
    No state tracking, no history, no progress monitoring.
    """

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[Any]] = set()

    def register(self, task: asyncio.Task[Any]) -> None:
        """Register a task. Add done_callback for auto-removal and error logging.

        done_callback implementation:
        1. self._tasks.discard(task) で自身を除去
        2. task.cancelled() を確認
           - True の場合: logger.debug() で正常キャンセルとして記録 → 終了
        3. task.exception() で未処理例外を取得
           - 例外が存在する場合: logger.error() でスタックトレース付きログ出力
           - 例外なしの場合: logger.debug() で正常完了を記録
        4. 例外は再送出しない (バックグラウンドタスクのため呼び出し元に伝播不可)

        Note: task.cancelled() を先行チェックしないと、キャンセル済みタスクに対して
        task.exception() を呼んだ際に CancelledError が送出されるため順序は重要。
        """
        self._tasks.add(task)
        task.add_done_callback(self._on_task_done)

    def __len__(self) -> int:
        """Return the number of currently running tasks."""
        return len(self._tasks)

    def _on_task_done(self, task: asyncio.Task[Any]) -> None:
        """Done callback: auto-remove task and log errors."""
        self._tasks.discard(task)

        try:
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
        except Exception as e:
            logger.error(
                "Error in TaskRegistry._on_task_done for task %s: %s",
                task.get_name(),
                e,
                exc_info=e,
            )

    async def wait_all(self, timeout: float = 5.0) -> None:
        """Wait for all running tasks to complete with timeout.

        If timeout is reached, remaining tasks are NOT cancelled by this method.
        Use cancel_all() if you want to ensure all tasks are terminated.
        """
        if not self._tasks:
            return

        tasks = list(self._tasks)
        _done, pending = await asyncio.wait(tasks, timeout=timeout)
        if pending:
            logger.warning(
                "wait_all: %d task(s) did not finish within timeout=%.1fs: %s",
                len(pending),
                timeout,
                [t.get_name() for t in pending],
            )

    async def cancel_all(self, timeout: float = 5.0) -> None:
        """Cancel all running tasks with timeout. Called during graceful shutdown."""
        if not self._tasks:
            return

        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()

        # タスクの完了を待機 (タイムアウト付き)
        _done, pending = await asyncio.wait(tasks, timeout=timeout)
        if pending:
            logger.warning(
                "cancel_all: %d task(s) did not finish within timeout=%.1fs: %s",
                len(pending),
                timeout,
                [t.get_name() for t in pending],
            )
