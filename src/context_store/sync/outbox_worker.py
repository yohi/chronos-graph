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
        try:
            recovered = await self._reader.reset_stuck_processing(
                threshold_seconds=300,
                max_retries=self._settings.outbox_max_retries,
            )
            if recovered:
                logger.info("OutboxWorker: recovered %d stuck PROCESSING events", recovered)
        except Exception as exc:
            logger.warning("OutboxWorker: reset_stuck_processing failed: %s", exc)

        while not self._stop_event.is_set():
            try:
                events = await self._reader.fetch_pending(limit=self._settings.outbox_batch_size)
                if events:
                    await self._process_batch(events)
            except Exception as exc:
                logger.exception("OutboxWorker: poll cycle failed: %s", exc)

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._settings.outbox_poll_interval_seconds,
                )
                return
            except asyncio.TimeoutError:
                continue

    async def stop(self) -> None:
        self._stop_event.set()

    async def process_pending_once(self) -> int:
        """1 サイクル分の PENDING を取得して処理する。"""
        events = await self._reader.fetch_pending(limit=self._settings.outbox_batch_size)
        if not events:
            return 0
        await self._process_batch(events)
        return len(events)

    async def run_catchup(self, *, dry_run: bool = False) -> int:
        """Outbox の全 actionable を 1 度だけ処理する。"""
        events = await self._reader.fetch_all_actionable()
        if dry_run:
            logger.info("Catchup dry run: would process %d events", len(events))
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
                memories = await self._storage.get_memories_batch(mids)  # type: ignore[attr-defined]
                found_ids = {str(m.id) for m in memories}
                orphan_ids = [e.id for e in sync_events if e.memory_id not in found_ids]
                if memories:
                    await self._graph_sync.bulk_merge_memories(memories)
                completed_ids.extend(orphan_ids)
                completed_ids.extend(e.id for e in sync_events if e.memory_id in found_ids)
            except Exception as exc:
                await self._apply_backoff(sync_events, exc)
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

    async def _apply_backoff(self, events: list[OutboxEvent], exc: Exception) -> None:
        base = self._settings.outbox_backoff_base_seconds
        max_s = self._settings.outbox_backoff_max_seconds
        max_retries = self._settings.outbox_max_retries
        for e in events:
            new_retry = e.retry_count + 1
            if new_retry > max_retries:
                await self._reader.mark_failed(e.id, str(exc))
                logger.error("OutboxWorker: event %s exceeded max retries", e.id)
                continue
            backoff = min(base * (2**new_retry), max_s)
            next_at = datetime.now(timezone.utc) + timedelta(seconds=backoff)
            await self._reader.reset_to_pending(
                event_id=e.id,
                retry_count=new_retry,
                next_retry_at=next_at,
                error_message=str(exc),
            )
