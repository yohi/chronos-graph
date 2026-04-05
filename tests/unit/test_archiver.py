"""Archiver のユニットテスト。"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock


from context_store.lifecycle.archiver import Archiver, ArchiverResult
from context_store.models.memory import Memory, MemoryType, SourceType
from context_store.storage.protocols import MemoryFilters


def _make_memory(
    *,
    archived_at: datetime | None = None,
    semantic_relevance: float = 0.5,
    importance_score: float = 0.5,
    project: str | None = None,
) -> Memory:
    """テスト用 Memory を生成するヘルパー。"""
    return Memory(
        content="テスト記憶",
        memory_type=MemoryType.EPISODIC,
        source_type=SourceType.CONVERSATION,
        semantic_relevance=semantic_relevance,
        importance_score=importance_score,
        archived_at=archived_at,
        project=project,
    )


class TestArchiverBasic:
    """Archiver の基本動作テスト。"""

    async def test_archives_memory_below_threshold(self):
        """スコアが閾値以下の記憶がアーカイブされること。"""
        storage = AsyncMock()
        scorer = MagicMock()

        low_score_memory = _make_memory()
        storage.list_by_filter.return_value = [low_score_memory]
        scorer.is_below_archive_threshold.return_value = True
        storage.update_memory.return_value = True

        archiver = Archiver(storage=storage, scorer=scorer)
        result = await archiver.run()

        assert result.archived_count == 1
        assert result.checked_count == 1
        storage.update_memory.assert_called_once()

    async def test_skips_memory_above_threshold(self):
        """スコアが閾値より高い記憶はアーカイブされないこと。"""
        storage = AsyncMock()
        scorer = MagicMock()

        high_score_memory = _make_memory()
        storage.list_by_filter.return_value = [high_score_memory]
        scorer.is_below_archive_threshold.return_value = False

        archiver = Archiver(storage=storage, scorer=scorer)
        result = await archiver.run()

        assert result.archived_count == 0
        assert result.checked_count == 1
        storage.update_memory.assert_not_called()

    async def test_archived_at_is_set_correctly(self):
        """アーカイブ時に archived_at が現在時刻に設定されること。"""
        storage = AsyncMock()
        scorer = MagicMock()

        memory = _make_memory()
        storage.list_by_filter.return_value = [memory]
        scorer.is_below_archive_threshold.return_value = True
        storage.update_memory.return_value = True

        before = datetime.now(timezone.utc)
        archiver = Archiver(storage=storage, scorer=scorer)
        await archiver.run()
        after = datetime.now(timezone.utc)

        call_args = storage.update_memory.call_args
        updates = call_args[0][1]
        assert "archived_at" in updates
        archived_at = updates["archived_at"]
        assert before <= archived_at <= after

    async def test_uses_active_filter(self):
        """list_by_filter でアクティブ記憶のみ（archived=None）が取得されること。"""
        storage = AsyncMock()
        scorer = MagicMock()

        storage.list_by_filter.return_value = []

        archiver = Archiver(storage=storage, scorer=scorer)
        await archiver.run()

        call_args = storage.list_by_filter.call_args
        filters: MemoryFilters = call_args[0][0]
        # archived=None はアクティブ記憶のみを示す
        assert filters.archived is None

    async def test_multiple_memories_partial_archive(self):
        """複数記憶のうち閾値以下のものだけアーカイブされること。"""
        storage = AsyncMock()
        scorer = MagicMock()

        mem1 = _make_memory()
        mem2 = _make_memory()
        mem3 = _make_memory()
        storage.list_by_filter.return_value = [mem1, mem2, mem3]
        scorer.is_below_archive_threshold.side_effect = [True, False, True]
        storage.update_memory.return_value = True

        archiver = Archiver(storage=storage, scorer=scorer)
        result = await archiver.run()

        assert result.archived_count == 2
        assert result.checked_count == 3
        assert storage.update_memory.call_count == 2

    async def test_empty_memory_list(self):
        """記憶が0件の場合に正常終了すること。"""
        storage = AsyncMock()
        scorer = MagicMock()

        storage.list_by_filter.return_value = []

        archiver = Archiver(storage=storage, scorer=scorer)
        result = await archiver.run()

        assert result.archived_count == 0
        assert result.checked_count == 0
        storage.update_memory.assert_not_called()


class TestArchiverProjectFilter:
    """Archiver のプロジェクトフィルタテスト。"""

    async def test_project_filter_is_passed_to_storage(self):
        """project パラメータが MemoryFilters に正しく渡されること。"""
        storage = AsyncMock()
        scorer = MagicMock()

        storage.list_by_filter.return_value = []

        archiver = Archiver(storage=storage, scorer=scorer)
        await archiver.run(project="my-project")

        call_args = storage.list_by_filter.call_args
        filters: MemoryFilters = call_args[0][0]
        assert filters.project == "my-project"

    async def test_no_project_filter_passes_none(self):
        """project 未指定の場合、MemoryFilters.project が None であること。"""
        storage = AsyncMock()
        scorer = MagicMock()

        storage.list_by_filter.return_value = []

        archiver = Archiver(storage=storage, scorer=scorer)
        await archiver.run()

        call_args = storage.list_by_filter.call_args
        filters: MemoryFilters = call_args[0][0]
        assert filters.project is None


class TestArchiverResult:
    """ArchiverResult のテスト。"""

    async def test_result_type_is_archiver_result(self):
        """run() の戻り値が ArchiverResult 型であること。"""
        storage = AsyncMock()
        scorer = MagicMock()

        storage.list_by_filter.return_value = []

        archiver = Archiver(storage=storage, scorer=scorer)
        result = await archiver.run()

        assert isinstance(result, ArchiverResult)

    async def test_result_fields_match_processing(self):
        """ArchiverResult のフィールドが処理結果と一致すること。"""
        storage = AsyncMock()
        scorer = MagicMock()

        memories = [_make_memory() for _ in range(5)]
        storage.list_by_filter.return_value = memories
        scorer.is_below_archive_threshold.side_effect = [True, False, True, False, True]
        storage.update_memory.return_value = True

        archiver = Archiver(storage=storage, scorer=scorer)
        result = await archiver.run()

        assert result.archived_count == 3
        assert result.checked_count == 5


class TestArchiverPagination:
    """Archiver のページネーションテスト。"""

    async def test_pagination_multiple_pages(self):
        """101件以上の記憶がある場合、ページ分割して全件処理されること。"""
        storage = AsyncMock()
        scorer = MagicMock()

        # 120件の記憶を作成
        all_memories = [_make_memory() for _ in range(120)]
        # ID と作成日時をユニークにする（カーソル用）
        import uuid
        from datetime import timedelta

        base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for i, m in enumerate(all_memories):
            m.id = uuid.uuid4()
            m.created_at = base_time + timedelta(seconds=i)

        # list_by_filter の戻り値をシミュレート（100件, 20件, 0件）
        storage.list_by_filter.side_effect = [
            all_memories[:100],
            all_memories[100:120],
            [],
        ]
        # 全てアーカイブ対象外とする
        scorer.is_below_archive_threshold.return_value = False

        archiver = Archiver(storage=storage, scorer=scorer)
        result = await archiver.run()

        # 合計 120 件がチェックされたことを確認
        assert result.checked_count == 120
        assert result.archived_count == 0
        # 3回（データ取得用2回 + 終了確認用1回）呼び出されたことを確認
        # ※ 実装によっては current_page_len < page_size で break するため 2 回になる可能性あり
        assert storage.list_by_filter.call_count in (2, 3)

        # 2回目の呼び出しで正しいカーソルが渡されているか確認
        # list_by_filter.call_args_list[1] = (filters,)
        filters_page2 = storage.list_by_filter.call_args_list[1][0][0]
        assert filters_page2.limit == 100
        assert filters_page2.order_by == "created_at ASC, id ASC"
        # 1ページ目の最後の要素 (index 99) の値がセットされているはず
        assert filters_page2.id_after == str(all_memories[99].id)
        assert filters_page2.created_after == all_memories[99].created_at

    async def test_pagination_stops_correctly_on_exact_page_size(self):
        """ちょうどページサイズ（100件）の場合、1ページで終了すること。"""
        storage = AsyncMock()
        scorer = MagicMock()

        memories = [_make_memory() for _ in range(100)]
        storage.list_by_filter.side_effect = [memories, []]
        scorer.is_below_archive_threshold.return_value = False

        archiver = Archiver(storage=storage, scorer=scorer)
        result = await archiver.run()

        assert result.checked_count == 100
        assert storage.list_by_filter.call_count == 2
