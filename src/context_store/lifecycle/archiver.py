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
        dry_run: bool = False,
        simulated_archived_ids: set[str] | None = None,
        now: datetime | None = None,
    ) -> ArchiverResult:
        """アクティブ記憶をスキャンして閾値以下のものをアーカイブする。

        Args:
            project: フィルタするプロジェクト名。None の場合は全プロジェクト対象。
            heartbeat_fn: ハートビート用コールバック関数。
            dry_run: True の場合は更新せず対象件数のみをカウント。
            simulated_archived_ids: dry_run 時にアーカイブされたとみなす ID のセット。
            now: 基準時刻。None の場合は現在時刻を使用。

        Returns:
            処理結果を格納した ArchiverResult。
        """
        if now is None:
            now = datetime.now(timezone.utc)

        # archived=None はアクティブ記憶のみを取得する（protocols.py MemoryFilters 参照）
        archived_count = 0
        checked_count = 0
        page_size = 100
        last_id = None
        last_created_at = None

        while True:
            filters = MemoryFilters(
                project=project,
                archived=None,
                limit=page_size,
                order_by="created_at ASC, id ASC",
                created_after=last_created_at,
                id_after=last_id,
            )
            memories = await self._storage.list_by_filter(filters)
            if not memories:
                break

            current_page_len = len(memories)
            checked_count += current_page_len

            for memory in memories:
                memory_id = str(memory.id)
                if self._scorer.is_below_archive_threshold(memory):
                    if not dry_run:
                        if await self._storage.update_memory(memory_id, {"archived_at": now}):
                            archived_count += 1
                    else:
                        archived_count += 1
                        if simulated_archived_ids is not None:
                            simulated_archived_ids.add(memory_id)
                last_id = memory_id
                last_created_at = memory.created_at

            if heartbeat_fn:
                await heartbeat_fn()

            if current_page_len < page_size:
                break

        return ArchiverResult(archived_count=archived_count, checked_count=checked_count)
