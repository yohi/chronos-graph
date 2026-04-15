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

    @pytest.mark.asyncio
    async def test_register_task_with_return_value(self) -> None:
        """Any 型のタスク（戻り値あり）を register できる。"""
        registry = TaskRegistry()

        async def returns_bool() -> bool:
            return True

        # asyncio.Task[bool] は asyncio.Task[Any] に適合するはず
        task = asyncio.create_task(returns_bool())
        registry.register(task)
        assert len(registry) == 1

        await task
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
    async def test_done_callback_logs_cancellation(self, caplog: pytest.LogCaptureFixture) -> None:
        """キャンセルされたタスクは logger.debug() で記録される。"""
        caplog.set_level(logging.DEBUG, logger="context_store.ingestion.task_registry")
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

    @pytest.mark.asyncio
    async def test_cancel_all_logs_warning_on_timeout(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """キャンセルが間に合わないタスクがある場合、警告ログを出力する。"""
        registry = TaskRegistry()

        async def stubborn() -> None:
            try:
                await asyncio.sleep(100)
            except asyncio.CancelledError:
                # キャンセルされても無視して長くスリープ
                await asyncio.sleep(1.0)

        task = asyncio.create_task(stubborn(), name="StubbornTask")
        registry.register(task)

        # タスクを開始させる
        await asyncio.sleep(0)

        # タイムアウト 0.1s で cancel_all
        await registry.cancel_all(timeout=0.1)

        assert any(
            "StubbornTask" in record.message and "terminate within 0.1 seconds" in record.message
            for record in caplog.records
            if record.levelno == logging.WARNING
        )

        # 後片付け（テストが終わった後にタスクが残らないようにする）
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
