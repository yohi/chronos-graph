"""OutboxWorker: ポーリングループ・リトライ・Backoff・リカバリ検証。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from context_store.sync.models import OutboxEvent


def _evt(event_type: str = "SYNC_MEMORY", retry_count: int = 0) -> OutboxEvent:
    now = datetime.now(timezone.utc)
    return OutboxEvent(
        id="e1",
        event_type=event_type,  # type: ignore[arg-type]
        memory_id="m1",
        payload={},
        status="PROCESSING",
        retry_count=retry_count,
        next_retry_at=now,
        error_message=None,
        created_at=now,
        updated_at=now,
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
        outbox_batch_size=10,
        outbox_max_retries=5,
        outbox_backoff_base_seconds=0.1,
        outbox_backoff_max_seconds=1.0,
    )
    worker = OutboxWorker(
        reader=reader, storage_adapter=storage, graph_sync=graph_sync, settings=settings
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
        outbox_batch_size=10,
        outbox_max_retries=5,
        outbox_backoff_base_seconds=1.0,
        outbox_backoff_max_seconds=10.0,
    )
    worker = OutboxWorker(
        reader=reader, storage_adapter=storage, graph_sync=graph_sync, settings=settings
    )
    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.05)
    await worker.stop()
    await task

    reader.reset_to_pending.assert_awaited_once()
    call = reader.reset_to_pending.await_args
    assert call.kwargs["retry_count"] == 3
    delta = (call.kwargs["next_retry_at"] - datetime.now(timezone.utc)).total_seconds()
    assert 6 < delta <= 9  # backoff: min(1 * 2^3, 10) = 8 秒


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
        outbox_batch_size=10,
        outbox_max_retries=5,
        outbox_backoff_base_seconds=1.0,
        outbox_backoff_max_seconds=10.0,
    )
    worker = OutboxWorker(
        reader=reader, storage_adapter=storage, graph_sync=graph_sync, settings=settings
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
        outbox_batch_size=10,
        outbox_max_retries=5,
        outbox_backoff_base_seconds=1.0,
        outbox_backoff_max_seconds=10.0,
    )
    worker = OutboxWorker(
        reader=reader,
        storage_adapter=MagicMock(),
        graph_sync=MagicMock(),
        settings=settings,
    )
    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.05)
    await worker.stop()
    await task

    reader.reset_stuck_processing.assert_awaited_once()


@pytest.mark.asyncio
async def test_worker_handles_orphaned_sync_event() -> None:
    from context_store.sync.outbox_worker import OutboxWorker

    reader = MagicMock()
    reader.reset_stuck_processing = AsyncMock(return_value=0)
    reader.fetch_pending = AsyncMock(side_effect=[[_evt()], []])
    reader.delete_completed = AsyncMock()

    storage = MagicMock()
    storage.get_memories_batch = AsyncMock(return_value=[])

    settings = MagicMock(
        outbox_poll_interval_seconds=0.01,
        outbox_batch_size=10,
        outbox_max_retries=5,
        outbox_backoff_base_seconds=1.0,
        outbox_backoff_max_seconds=10.0,
    )
    worker = OutboxWorker(
        reader=reader,
        storage_adapter=storage,
        graph_sync=MagicMock(),
        settings=settings,
    )
    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.05)
    await worker.stop()
    await task

    reader.delete_completed.assert_awaited_with(["e1"])


@pytest.mark.asyncio
async def test_worker_run_catchup_processes_all_actionable() -> None:
    from context_store.sync.outbox_worker import OutboxWorker

    reader = MagicMock()
    reader.fetch_all_actionable = AsyncMock(return_value=[_evt(), _evt()])
    reader.delete_completed = AsyncMock()

    storage = MagicMock()
    storage.get_memories_batch = AsyncMock(return_value=[MagicMock(id="m1")])
    graph_sync = MagicMock()
    graph_sync.bulk_merge_memories = AsyncMock(return_value=1)

    settings = MagicMock(
        outbox_poll_interval_seconds=0.01,
        outbox_batch_size=10,
        outbox_max_retries=5,
        outbox_backoff_base_seconds=1.0,
        outbox_backoff_max_seconds=10.0,
    )
    worker = OutboxWorker(
        reader=reader, storage_adapter=storage, graph_sync=graph_sync, settings=settings
    )
    n = await worker.run_catchup()
    assert n == 2
    reader.fetch_all_actionable.assert_awaited_once()
    graph_sync.bulk_merge_memories.assert_awaited()


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
        outbox_poll_interval_seconds=0.01,
        outbox_batch_size=10,
        outbox_max_retries=5,
        outbox_backoff_base_seconds=1.0,
        outbox_backoff_max_seconds=10.0,
    )
    worker = OutboxWorker(
        reader=reader, storage_adapter=storage, graph_sync=graph_sync, settings=settings
    )
    n = await worker.process_pending_once()
    assert n == 1
