"""アーカイブ後 N 日経過した記憶を物理削除するモジュール。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Coroutine

from context_store.storage.protocols import GraphAdapter, MemoryFilters, StorageAdapter


@dataclass
class PurgerResult:
    """Purger の実行結果。

    Attributes:
        purged_count: 削除した記憶の件数。
        checked_count: チェックした記憶の件数。
    """

    purged_count: int
    checked_count: int


class Purger:
    """アーカイブ後 N 日経過した記憶を物理削除するクラス。

    Args:
        storage: ストレージアダプター。
        graph: グラフアダプター。None の場合はグラフ削除をスキップする。
        retention_days: アーカイブ後の保持日数。この日数を超えた記憶を削除する。
    """

    def __init__(
        self,
        storage: StorageAdapter,
        graph: GraphAdapter | None,
        retention_days: int,
    ) -> None:
        self._storage = storage
        self._graph = graph
        self._retention_days = retention_days

    async def run(
        self,
        heartbeat_fn: Callable[[], Coroutine[Any, Any, None]] | None = None,
    ) -> PurgerResult:
        """アーカイブ済み記憶をスキャンして期限切れのものを物理削除する。

        Args:
            heartbeat_fn: ハートビート用コールバック関数。

        Returns:
            処理結果を格納した PurgerResult。
        """
        filters = MemoryFilters(archived=True)
        memories = await self._storage.list_by_filter(filters)

        now = datetime.now(timezone.utc)
        expiry_threshold = now - timedelta(days=self._retention_days)

        purged_count = 0
        checked_count = len(memories)

        for i, memory in enumerate(memories):
            if heartbeat_fn and i % 10 == 0:
                await heartbeat_fn()

            # MemoryFilters(archived=True) で取得済みだが、ストレージ実装の保証に依存しないよう防御チェック
            if memory.archived_at is None:
                continue
            if memory.archived_at < expiry_threshold:
                memory_id = str(memory.id)
                await self._storage.delete_memory(memory_id)
                if self._graph is not None:
                    await self._graph.delete_node(memory_id)
                purged_count += 1

        return PurgerResult(purged_count=purged_count, checked_count=checked_count)
