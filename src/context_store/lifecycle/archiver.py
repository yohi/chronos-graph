"""スコアが閾値以下の記憶を Archived 状態に遷移させるモジュール。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine

from context_store.lifecycle.decay_scorer import DecayScorer
from context_store.storage.protocols import MemoryFilters, StorageAdapter


@dataclass
class ArchiverResult:
    """Archiver の実行結果。

    Attributes:
        archived_count: アーカイブした記憶の件数。
        checked_count: チェックした記憶の件数。
    """

    archived_count: int
    checked_count: int


class Archiver:
    """スコアが閾値以下の記憶を Archived 状態に遷移させるクラス。

    Args:
        storage: ストレージアダプター。
        scorer: 減衰スコアを計算するオブジェクト。
    """

    def __init__(self, storage: StorageAdapter, scorer: DecayScorer) -> None:
        self._storage = storage
        self._scorer = scorer

    async def run(
        self,
        project: str | None = None,
        heartbeat_fn: Callable[[], Coroutine[Any, Any, None]] | None = None,
    ) -> ArchiverResult:
        """アクティブ記憶をスキャンして閾値以下のものをアーカイブする。

        Args:
            project: フィルタするプロジェクト名。None の場合は全プロジェクト対象。
            heartbeat_fn: ハートビート用コールバック関数。

        Returns:
            処理結果を格納した ArchiverResult。
        """
        # archived=None はアクティブ記憶のみを取得する（protocols.py MemoryFilters 参照）
        filters = MemoryFilters(project=project, archived=None)
        memories = await self._storage.list_by_filter(filters)

        archived_count = 0
        checked_count = len(memories)

        for i, memory in enumerate(memories):
            if heartbeat_fn and i % 10 == 0:
                await heartbeat_fn()

            if self._scorer.is_below_archive_threshold(memory):
                now = datetime.now(timezone.utc)
                await self._storage.update_memory(str(memory.id), {"archived_at": now})
                archived_count += 1

        return ArchiverResult(archived_count=archived_count, checked_count=checked_count)
