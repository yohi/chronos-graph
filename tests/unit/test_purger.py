"""Purger のユニットテスト。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from context_store.lifecycle.purger import Purger, PurgerResult
from context_store.models.memory import Memory, MemoryType, SourceType
from context_store.storage.protocols import MemoryFilters


class TestPurgerValidation:
    """Purger のバリデーションテスト。"""

    def test_init_raises_on_negative_retention(self):
        """初期化時に負の retention_days が渡された場合に ValueError を投げること。"""
        storage = AsyncMock()
        with pytest.raises(ValueError, match="retention_days must be non-negative"):
            Purger(storage=storage, graph=None, retention_days=-1)

    async def test_run_raises_on_negative_retention(self):
        """run 実行時に負の retention_days が渡された場合に ValueError を投げること。"""
        storage = AsyncMock()
        purger = Purger(storage=storage, graph=None, retention_days=90)
        with pytest.raises(ValueError, match="retention_days must be non-negative"):
            await purger.run(retention_days=-1)


def _make_archived_memory(
    *,
    archived_days_ago: float = 0,
    project: str | None = None,
) -> Memory:
    """アーカイブ済みテスト用 Memory を生成するヘルパー。"""
    now = datetime.now(timezone.utc)
    archived_at = now - timedelta(days=archived_days_ago)
    return Memory(
        content="テスト記憶",
        memory_type=MemoryType.EPISODIC,
        source_type=SourceType.CONVERSATION,
        archived_at=archived_at,
        project=project,
    )


def _make_active_memory() -> Memory:
    """アクティブ（未アーカイブ）テスト用 Memory を生成するヘルパー。"""
    return Memory(
        content="アクティブ記憶",
        memory_type=MemoryType.EPISODIC,
        source_type=SourceType.CONVERSATION,
        archived_at=None,
    )


class TestPurgerBasic:
    """Purger の基本動作テスト。"""

    async def test_purges_expired_archived_memory(self):
        """retention_days 経過したアーカイブ記憶が削除されること。"""
        storage = AsyncMock()
        graph = AsyncMock()

        retention_days = 90
        old_memory = _make_archived_memory(archived_days_ago=retention_days + 1)
        storage.list_by_filter.return_value = [old_memory]
        storage.delete_memory.return_value = True

        purger = Purger(storage=storage, graph=graph, retention_days=retention_days)
        result = await purger.run()

        assert result.purged_count == 1
        assert result.checked_count == 1
        storage.delete_memory.assert_called_once_with(str(old_memory.id))

    async def test_skips_recent_archived_memory(self):
        """retention_days 未満のアーカイブ記憶は削除されないこと。"""
        storage = AsyncMock()
        graph = AsyncMock()

        retention_days = 90
        recent_memory = _make_archived_memory(archived_days_ago=retention_days - 1)
        storage.list_by_filter.return_value = [recent_memory]

        purger = Purger(storage=storage, graph=graph, retention_days=retention_days)
        result = await purger.run()

        assert result.purged_count == 0
        assert result.checked_count == 1
        storage.delete_memory.assert_not_called()

    async def test_skips_memory_with_none_archived_at(self):
        """archived_at が None の記憶（アクティブ）はスキップされること。"""
        storage = AsyncMock()
        graph = AsyncMock()

        active_memory = _make_active_memory()
        storage.list_by_filter.return_value = [active_memory]

        purger = Purger(storage=storage, graph=graph, retention_days=90)
        result = await purger.run()

        assert result.purged_count == 0
        assert result.checked_count == 1
        storage.delete_memory.assert_not_called()

    async def test_empty_memory_list(self):
        """記憶が0件の場合に正常終了すること。"""
        storage = AsyncMock()
        graph = AsyncMock()

        storage.list_by_filter.return_value = []

        purger = Purger(storage=storage, graph=graph, retention_days=90)
        result = await purger.run()

        assert result.purged_count == 0
        assert result.checked_count == 0
        storage.delete_memory.assert_not_called()

    async def test_uses_archived_filter(self):
        """list_by_filter でアーカイブ済み記憶のみ（archived=True）が取得されること。"""
        storage = AsyncMock()
        graph = AsyncMock()

        storage.list_by_filter.return_value = []

        purger = Purger(storage=storage, graph=graph, retention_days=90)
        await purger.run()

        call_args = storage.list_by_filter.call_args
        filters: MemoryFilters = call_args[0][0]
        assert filters.archived is True


class TestPurgerGraphIntegration:
    """Purger のグラフ連動テスト。"""

    async def test_deletes_graph_node_when_graph_provided(self):
        """GraphAdapter が提供されている場合、グラフノードも削除されること。"""
        storage = AsyncMock()
        graph = AsyncMock()

        retention_days = 90
        old_memory = _make_archived_memory(archived_days_ago=retention_days + 1)
        storage.list_by_filter.return_value = [old_memory]
        storage.delete_memory.return_value = True

        purger = Purger(storage=storage, graph=graph, retention_days=retention_days)
        await purger.run()

        graph.delete_node.assert_called_once_with(str(old_memory.id))

    async def test_works_without_graph_adapter(self):
        """GraphAdapter が None の場合でも物理削除が正常に動作すること。"""
        storage = AsyncMock()

        retention_days = 90
        old_memory = _make_archived_memory(archived_days_ago=retention_days + 1)
        storage.list_by_filter.return_value = [old_memory]
        storage.delete_memory.return_value = True

        purger = Purger(storage=storage, graph=None, retention_days=retention_days)
        result = await purger.run()

        assert result.purged_count == 1
        storage.delete_memory.assert_called_once_with(str(old_memory.id))

    async def test_no_graph_deletion_when_not_expired(self):
        """期限切れでない記憶のグラフノードは削除されないこと。"""
        storage = AsyncMock()
        graph = AsyncMock()

        retention_days = 90
        recent_memory = _make_archived_memory(archived_days_ago=retention_days - 1)
        storage.list_by_filter.return_value = [recent_memory]

        purger = Purger(storage=storage, graph=graph, retention_days=retention_days)
        await purger.run()

        graph.delete_node.assert_not_called()


class TestPurgerBoundaryConditions:
    """Purger の境界値テスト。"""

    async def test_exactly_at_retention_boundary_is_not_purged(self):
        """ちょうど retention_days 日後の記憶は削除されないこと。"""
        storage = AsyncMock()
        graph = AsyncMock()

        retention_days = 90
        now = datetime.now(timezone.utc)
        # ちょうど retention_days 日前より 1 秒新しい → 削除されない
        boundary_at = now - timedelta(days=retention_days) + timedelta(seconds=1)
        boundary_memory = Memory(
            content="境界テスト記憶",
            memory_type=MemoryType.EPISODIC,
            source_type=SourceType.CONVERSATION,
            archived_at=boundary_at,
        )
        storage.list_by_filter.return_value = [boundary_memory]

        purger = Purger(storage=storage, graph=graph, retention_days=retention_days)
        result = await purger.run()

        assert result.purged_count == 0

    async def test_multiple_memories_partial_purge(self):
        """複数記憶のうち期限切れのものだけ削除されること。"""
        storage = AsyncMock()
        graph = AsyncMock()

        retention_days = 90
        expired1 = _make_archived_memory(archived_days_ago=retention_days + 10)
        recent = _make_archived_memory(archived_days_ago=retention_days - 10)
        expired2 = _make_archived_memory(archived_days_ago=retention_days + 5)
        storage.list_by_filter.return_value = [expired1, recent, expired2]
        storage.delete_memory.return_value = True

        purger = Purger(storage=storage, graph=graph, retention_days=retention_days)
        result = await purger.run()

        assert result.purged_count == 2
        assert result.checked_count == 3
        assert storage.delete_memory.call_count == 2
        assert graph.delete_node.call_count == 2


class TestPurgerResult:
    """PurgerResult のテスト。"""

    async def test_result_type_is_purger_result(self):
        """run() の戻り値が PurgerResult 型であること。"""
        storage = AsyncMock()

        storage.list_by_filter.return_value = []

        purger = Purger(storage=storage, graph=None, retention_days=90)
        result = await purger.run()

        assert isinstance(result, PurgerResult)

    async def test_result_fields_match_processing(self):
        """PurgerResult のフィールドが処理結果と一致すること。"""
        storage = AsyncMock()
        graph = AsyncMock()

        retention_days = 90
        memories = [
            _make_archived_memory(archived_days_ago=retention_days + 1),
            _make_archived_memory(archived_days_ago=retention_days - 1),
            _make_archived_memory(archived_days_ago=retention_days + 2),
        ]
        storage.list_by_filter.return_value = memories
        storage.delete_memory.return_value = True

        purger = Purger(storage=storage, graph=graph, retention_days=retention_days)
        result = await purger.run()

        assert result.purged_count == 2
        assert result.checked_count == 3
