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
        # retention_days のバリデーション: 厳密に 0 以上の整数であることを要求
        if isinstance(retention_days, bool) or not isinstance(retention_days, int):
            raise TypeError(f"retention_days must be an int, got {type(retention_days).__name__}")

        val = retention_days
        if val < 0:
            raise ValueError(f"retention_days must be non-negative, got {val}")

        self._storage = storage
        self._graph = graph
        self._retention_days = val

    async def run(
        self,
        heartbeat_fn: Callable[[], Coroutine[Any, Any, None]] | None = None,
        retention_days: int | None = None,
        dry_run: bool = False,
        simulated_archived_ids: set[str] | None = None,
    ) -> PurgerResult:
        """アーカイブ済み記憶をスキャンして期限切れのものを物理削除する。

        Args:
            heartbeat_fn: ハートビート用コールバック関数。
            retention_days: 保持期間 (日数)。None の場合はデフォルト設定を使用。
            dry_run: True の場合は削除せず対象件数のみをカウント。
            simulated_archived_ids: dry_run 時にアーカイブされたとみなす ID のセット。

        Returns:
            処理結果を格納した PurgerResult。
        """
        if retention_days is not None and retention_days < 0:
            raise ValueError(f"retention_days must be non-negative, got {retention_days}")

        now = datetime.now(timezone.utc)
        target_retention = retention_days if retention_days is not None else self._retention_days
        expiry_threshold = now - timedelta(days=target_retention)

        purged_count = 0
        checked_count = 0
        page_size = 100
        last_id = None
        last_archived_at = None

        while True:
            # 安定したページングのために (archived_at, id) ASC で取得
            filters = MemoryFilters(
                archived=True,
                limit=page_size,
                order_by="archived_at ASC, id ASC",
                archived_after=last_archived_at,
                id_after=last_id,
            )
            memories = await self._storage.list_by_filter(filters)
            if not memories:
                break
            current_page_len = len(memories)

            for memory in memories:
                checked_count += 1
                if heartbeat_fn and checked_count % 10 == 0:
                    await heartbeat_fn()

                # MemoryFilters(archived=True) で取得済みだが、ストレージ実装の保証に依存しないよう防御チェック
                if memory.archived_at is None:
                    continue
                if memory.archived_at < expiry_threshold:
                    if not dry_run:
                        memory_id = str(memory.id)
                        await self._storage.delete_memory(memory_id)
                        if self._graph is not None:
                            await self._graph.delete_node(memory_id)
                    purged_count += 1

                last_id = str(memory.id)
                last_archived_at = memory.archived_at

            if current_page_len < page_size:
                break

        # no-op: simulated_archived_ids にあるものは今アーカイブされたばかり (archived_at = now) なので、
        # 常に expiry_threshold (now - N days) より新しいため除外対象にはなりません。
        # manager.py との API 互換性のために引数として保持しています。

        return PurgerResult(purged_count=purged_count, checked_count=checked_count)
