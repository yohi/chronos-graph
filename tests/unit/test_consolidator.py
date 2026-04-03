"""Consolidator のユニットテスト。"""

from __future__ import annotations

import contextlib
import logging
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import UUID, uuid4


from context_store.lifecycle.consolidator import Consolidator, ConsolidatorResult
from context_store.models.memory import Memory, MemorySource, MemoryType, ScoredMemory, SourceType


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------

_SENTINEL = object()


def _make_memory(
    *,
    created_at: datetime | None = None,
    archived_at: datetime | None = None,
    embedding: list[float] | object = _SENTINEL,
    content: str = "テスト記憶",
    project: str | None = None,
    memory_id: UUID | None = None,
) -> Memory:
    """テスト用 Memory を生成するヘルパー。

    embedding=[] を渡した場合は空リストが使われる（falsy チェックを避けるためセンチネルを使用）。
    """
    if embedding is _SENTINEL:
        actual_embedding: list[float] = [0.1, 0.2, 0.3]
    else:
        actual_embedding = embedding  # type: ignore[assignment]
    return Memory(
        id=memory_id or uuid4(),
        content=content,
        memory_type=MemoryType.EPISODIC,
        source_type=SourceType.CONVERSATION,
        embedding=actual_embedding,
        created_at=created_at or datetime.now(timezone.utc),
        archived_at=archived_at,
        project=project,
    )


def _make_scored_memory(memory: Memory, score: float) -> ScoredMemory:
    return ScoredMemory(memory=memory, score=score, source=MemorySource.VECTOR)


def _make_storage(memories: list[Memory] | None = None) -> AsyncMock:
    """StorageAdapter モックを返す。"""
    storage = AsyncMock()

    async def list_by_filter(filters: MemoryFilters) -> list[Memory]:
        mems = memories or []
        # 簡易的なフィルタリング
        if filters.created_after:
            mems = [m for m in mems if m.created_at >= filters.created_after]

        # 安定したソート (ASC)
        mems = sorted(mems, key=lambda x: (x.created_at, x.id))

        if filters.id_after:
            # id_after 以降のデータを取得
            found = False
            filtered = []
            for m in mems:
                if str(m.id) == filters.id_after:
                    found = True
                    continue
                if found:
                    filtered.append(m)
            mems = filtered

        if filters.limit:
            mems = mems[:filters.limit]
        return mems

    storage.list_by_filter.side_effect = list_by_filter
    storage.vector_search.return_value = []
    storage.update_memory.return_value = True
    return storage


# ---------------------------------------------------------------------------
# 1. 重複検出ロジックのテスト
# ---------------------------------------------------------------------------


class TestDeduplicationLogic:
    """重複検出ロジックのテスト。"""

    async def test_detects_high_similarity_pair(self):
        """similarity >= 0.90 のペアを正しく検出してアーカイブすること。"""
        # 古いメモリ（アーカイブ対象）
        older_memory = _make_memory(
            created_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        # 新しいメモリ（ベース）
        newer_memory = _make_memory(
            created_at=datetime.now(timezone.utc),
        )

        storage = _make_storage(memories=[newer_memory])
        # newer_memory の vector_search で older_memory が高スコアで返ってくる
        storage.vector_search.return_value = [
            _make_scored_memory(older_memory, 0.95),
            _make_scored_memory(newer_memory, 1.0),  # 自身
        ]

        consolidator = Consolidator(storage=storage)
        result = await consolidator.run()

        assert result.consolidated_count >= 1
        # older_memory がアーカイブされること
        update_calls = storage.update_memory.call_args_list
        archived_ids = [c.args[0] for c in update_calls if "archived_at" in c.args[1]]
        assert str(older_memory.id) in archived_ids

    async def test_archives_regular_consolidation_candidate(self):
        """0.85 <= similarity < 0.90 の通常統合候補も古い方がアーカイブされること。"""
        target_memory = _make_memory()
        other_memory = _make_memory(
            created_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )

        storage = _make_storage(memories=[target_memory])
        storage.vector_search.return_value = [
            _make_scored_memory(other_memory, 0.88),
            _make_scored_memory(target_memory, 1.0),
        ]

        consolidator = Consolidator(storage=storage)
        result = await consolidator.run()

        # 0.85 <= score < 0.90 は通常統合候補として古い方がアーカイブされる
        update_calls_with_archive = [
            c for c in storage.update_memory.call_args_list if "archived_at" in c.args[1]
        ]
        # older_memory がアーカイブされること
        assert len(update_calls_with_archive) == 1
        assert update_calls_with_archive[0].args[0] == str(other_memory.id)
        assert result.consolidated_count == 1

    async def test_avoids_full_scan_uses_vector_search(self):
        """O(N)のフルスキャンを避けてHNSW経由の vector_search を使うこと。

        スライディングウィンドウ内のN件に対して
        vector_search が N 回(各メモリに1回)だけ呼ばれることを検証。
        全件同士の総当たり比較(O(N^2))は行わない。
        """
        n = 10
        memories = [
            _make_memory(created_at=datetime.now(timezone.utc) - timedelta(minutes=i))
            for i in range(n)
        ]

        storage = _make_storage(memories=memories)
        storage.vector_search.return_value = []

        consolidator = Consolidator(storage=storage)
        await consolidator.run(batch_size=n)

        # vector_search はウィンドウ内の各メモリに対して1回ずつ = N 回
        # O(N^2) = N*(N-1)/2 = 45 回にはならないこと
        assert storage.vector_search.call_count == n

    async def test_vector_search_called_with_top_k_5(self):
        """vector_search が top_k=5 で呼ばれること。"""
        memory = _make_memory(embedding=[0.1, 0.2, 0.3])
        storage = _make_storage(memories=[memory])
        storage.vector_search.return_value = [_make_scored_memory(memory, 1.0)]

        consolidator = Consolidator(storage=storage)
        await consolidator.run()

        call_args = storage.vector_search.call_args
        assert (
            call_args.kwargs.get("top_k", call_args.args[1] if len(call_args.args) > 1 else None)
            == 5
        )

    async def test_skips_memory_without_embedding(self):
        """embedding が空のメモリは vector_search をスキップすること。"""
        memory_with_embedding = _make_memory(embedding=[0.1, 0.2, 0.3])
        memory_without_embedding = _make_memory(embedding=[])

        storage = _make_storage(memories=[memory_with_embedding, memory_without_embedding])
        storage.vector_search.return_value = []

        consolidator = Consolidator(storage=storage)
        await consolidator.run()

        # embedding がある1件のみ vector_search が呼ばれること
        assert storage.vector_search.call_count == 1


# ---------------------------------------------------------------------------
# 2. レースコンディションのシミュレーション（自己修復）
# ---------------------------------------------------------------------------


class TestSelfHealingRaceCondition:
    """レースコンディションによる重複見逃しの事後修復テスト。"""

    async def test_consolidator_fixes_missed_duplicates(self):
        """並行 memory_save で Deduplicator が見逃した重複を Consolidator が事後修復すること。"""
        # 同じ内容が並行保存されてしまった状況をシミュレート
        now = datetime.now(timezone.utc)
        mem_a = _make_memory(
            content="AIエージェントの設計パターン",
            created_at=now - timedelta(seconds=1),
        )
        mem_b = _make_memory(
            content="AIエージェントの設計パターン（重複）",
            created_at=now,
        )

        storage = _make_storage(memories=[mem_a, mem_b])

        # mem_a の検索で mem_b が高スコアで見つかる
        storage.vector_search.side_effect = [
            # mem_a の検索結果
            [
                _make_scored_memory(mem_a, 1.0),  # 自身
                _make_scored_memory(mem_b, 0.93),  # 重複！
            ],
            # mem_b の検索結果（既にアーカイブ済みのためスキップ or 検索後フィルタ）
            [
                _make_scored_memory(mem_b, 1.0),
                _make_scored_memory(mem_a, 0.93),
            ],
        ]

        consolidator = Consolidator(storage=storage)
        result = await consolidator.run()

        # 少なくとも1件がアーカイブされること（事後修復）
        assert result.consolidated_count >= 1
        # update_memory が呼ばれること（アーカイブ処理）
        assert storage.update_memory.call_count >= 1

    async def test_newer_memory_survives_older_archived(self):
        """自己修復時に古い方がアーカイブされ、新しい方が残ること。"""
        older = _make_memory(
            created_at=datetime.now(timezone.utc) - timedelta(hours=5),
        )
        newer = _make_memory(
            created_at=datetime.now(timezone.utc),
        )

        storage = _make_storage(memories=[older, newer])
        storage.vector_search.side_effect = [
            # older の検索結果
            [
                _make_scored_memory(older, 1.0),
                _make_scored_memory(newer, 0.92),
            ],
            # newer の検索結果（older は既にアーカイブ済みとして処理済み）
            [
                _make_scored_memory(newer, 1.0),
            ],
        ]

        consolidator = Consolidator(storage=storage)
        await consolidator.run()

        # older が archived_at 付きでアーカイブされること
        update_calls = storage.update_memory.call_args_list
        archived_ids = {c.args[0] for c in update_calls if "archived_at" in c.args[1]}
        assert str(older.id) in archived_ids
        assert str(newer.id) not in archived_ids

    async def test_already_archived_memory_skipped(self):
        """既にアーカイブ済みのメモリは処理対象に含まれないこと。"""
        active = _make_memory()
        _make_memory(
            archived_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )

        storage = _make_storage(memories=[active])  # list_by_filter はアクティブのみ返す
        storage.vector_search.return_value = [_make_scored_memory(active, 1.0)]

        consolidator = Consolidator(storage=storage)
        result = await consolidator.run()

        assert result.checked_count == 1  # archived は含まない


# ---------------------------------------------------------------------------
# 3. 優先順位テスト（自己修復 >= 0.90 を通常統合 0.85–0.89 より優先）
# ---------------------------------------------------------------------------


class TestPriorityProcessing:
    """優先順位テスト: 自己修復候補を通常統合候補より優先して処理することを検証。"""

    async def test_self_healing_prioritized_over_regular_consolidation(self):
        """0.90以上の自己修復候補が 0.85–0.89 の通常候補より先に処理されること。

        batch_size=1 で1件しか処理できない状況で、
        0.90以上候補のある記憶が先に処理されることを確認。
        """
        now = datetime.now(timezone.utc)

        # mem_high: 0.90以上の重複がある（自己修復対象）
        mem_high_base = _make_memory(created_at=now - timedelta(minutes=5))
        mem_high_dup = _make_memory(created_at=now - timedelta(minutes=10))

        # mem_low: 0.85–0.89 の通常候補
        mem_low_base = _make_memory(created_at=now - timedelta(minutes=1))
        mem_low_dup = _make_memory(created_at=now - timedelta(minutes=2))

        storage = _make_storage(memories=[mem_high_base, mem_low_base])
        storage.vector_search.side_effect = [
            # mem_high_base の検索: 0.92 の重複あり
            [
                _make_scored_memory(mem_high_base, 1.0),
                _make_scored_memory(mem_high_dup, 0.92),
            ],
            # mem_low_base の検索: 0.87 の通常候補
            [
                _make_scored_memory(mem_low_base, 1.0),
                _make_scored_memory(mem_low_dup, 0.87),
            ],
        ]

        consolidator = Consolidator(storage=storage)
        await consolidator.run(batch_size=1)

        # 自己修復が実行されること(archived_at が設定されること)
        update_calls = storage.update_memory.call_args_list
        archived_ids = {c.args[0] for c in update_calls if "archived_at" in c.args[1]}
        # mem_high_dup（古い方）がアーカイブされること
        assert str(mem_high_dup.id) in archived_ids

    async def test_mixed_scores_self_healing_executed(self):
        """0.85–0.89 と ≥0.90 が混在する場合、≥0.90 が自己修復対象となること。"""
        now = datetime.now(timezone.utc)
        base = _make_memory(created_at=now)
        high_dup = _make_memory(created_at=now - timedelta(hours=1))
        low_dup = _make_memory(created_at=now - timedelta(minutes=30))

        storage = _make_storage(memories=[base])
        storage.vector_search.return_value = [
            _make_scored_memory(base, 1.0),
            _make_scored_memory(high_dup, 0.91),  # 自己修復
            _make_scored_memory(low_dup, 0.87),  # 通常統合
        ]

        consolidator = Consolidator(storage=storage)
        await consolidator.run()

        update_calls = storage.update_memory.call_args_list
        archived_ids = {c.args[0] for c in update_calls if "archived_at" in c.args[1]}
        # high_dup のみアーカイブ（自己修復）
        assert str(high_dup.id) in archived_ids


# ---------------------------------------------------------------------------
# 4. パフォーマンステスト（10,000件モック）
# ---------------------------------------------------------------------------


class TestPerformance:
    """パフォーマンステスト: 10,000件のモックデータで O(M log N) であることを検証。"""

    async def test_large_dataset_completes_within_time_limit(self):
        """10,000件のモック環境で、30秒以内に処理が完了すること。

        vector_search はモックのため実際の検索は行わない。
        アルゴリズムが O(N^2) でないことを呼び出し回数で検証。
        batch_size=500 なので checked_count == batch_size であること。
        """
        n = 10_000
        batch_size = 500

        # 10,000件のメモリを生成
        now = datetime.now(timezone.utc)
        memories = [
            _make_memory(
                created_at=now - timedelta(seconds=i),
                embedding=[float(i % 100) / 100.0, 0.1, 0.2],
            )
            for i in range(n)
        ]

        storage = _make_storage(memories=memories)
        storage.vector_search.return_value = []  # マッチなし

        consolidator = Consolidator(storage=storage)

        start = time.monotonic()
        result = await consolidator.run(batch_size=batch_size)
        elapsed = time.monotonic() - start

        assert elapsed < 30.0, f"処理時間が30秒を超えた: {elapsed:.2f}秒"
        # batch_size 件のみ処理する（メモリ枯渇防止のバッチ上限）
        assert result.checked_count == batch_size
        # vector_search の呼び出し回数が batch_size 件 = O(M) であること（O(N) = O(10000) ではない）
        assert storage.vector_search.call_count == batch_size

    async def test_vector_search_call_count_is_not_quadratic(self):
        """vector_search の呼び出し回数が O(N^2) でなく O(N) であること。

        N=100件のウィンドウで vector_search が ~100回(N回)であり、
        N*(N-1)/2 = 4950回にはならないことを確認。
        """
        n = 100
        now = datetime.now(timezone.utc)
        memories = [
            _make_memory(
                created_at=now - timedelta(seconds=i),
                embedding=[float(i) / n, 0.1, 0.2],
            )
            for i in range(n)
        ]

        storage = _make_storage(memories=memories)
        storage.vector_search.return_value = []

        consolidator = Consolidator(storage=storage)
        await consolidator.run(batch_size=n)

        # 各メモリに対して1回ずつ = N 回
        assert storage.vector_search.call_count == n
        # O(N^2) = N*(N-1)/2 = 4950 にはなっていない
        assert storage.vector_search.call_count < n * (n - 1) // 2

    async def test_batch_size_limits_processing(self):
        """batch_size が設定された件数だけ処理すること（メモリ枯渇防止）。"""
        n = 50
        batch_size = 20
        memories = [_make_memory() for _ in range(n)]

        storage = _make_storage(memories=memories)
        storage.vector_search.return_value = []

        consolidator = Consolidator(storage=storage)
        result = await consolidator.run(batch_size=batch_size)

        # batch_size で制限されていること
        assert storage.vector_search.call_count <= batch_size
        assert result.checked_count <= batch_size


# ---------------------------------------------------------------------------
# 5. 監視ログのテスト
# ---------------------------------------------------------------------------


def _capture_logs(logger_name: str) -> list[logging.LogRecord]:
    """指定ロガーのログレコードを一時的にキャプチャするヘルパー。

    propagate=False のカスタムロガーでも動作する。
    """
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Capture()
    log = logging.getLogger(logger_name)
    log.addHandler(handler)
    try:
        yield records
    finally:
        log.removeHandler(handler)


_capture_logs = contextlib.contextmanager(_capture_logs)  # type: ignore[assignment]


class TestMonitoringLogs:
    """自己修復発動時のログ出力テスト。"""

    async def test_self_healing_log_emitted_on_archive(self):
        """自己修復時に INFO/WARNING レベルでログが出力されること。"""
        now = datetime.now(timezone.utc)
        base = _make_memory(created_at=now)
        duplicate = _make_memory(created_at=now - timedelta(hours=1))

        storage = _make_storage(memories=[base])
        storage.vector_search.return_value = [
            _make_scored_memory(base, 1.0),
            _make_scored_memory(duplicate, 0.95),
        ]

        consolidator = Consolidator(storage=storage)

        with _capture_logs("context_store.lifecycle.consolidator") as records:
            await consolidator.run()

        # ログメッセージが出力されていること
        log_messages = [r.getMessage() for r in records]
        assert any("Self-healing" in msg for msg in log_messages), (
            f"Self-healing ログが見つかりません。実際のログ: {log_messages}"
        )

    async def test_self_healing_log_contains_memory_id(self):
        """自己修復ログにメモリIDが含まれること。"""
        now = datetime.now(timezone.utc)
        base = _make_memory(created_at=now)
        dup_id = uuid4()
        duplicate = _make_memory(
            created_at=now - timedelta(hours=1),
            memory_id=dup_id,
        )

        storage = _make_storage(memories=[base])
        storage.vector_search.return_value = [
            _make_scored_memory(base, 1.0),
            _make_scored_memory(duplicate, 0.91),
        ]

        consolidator = Consolidator(storage=storage)

        with _capture_logs("context_store.lifecycle.consolidator") as records:
            await consolidator.run()

        log_messages = " ".join(r.getMessage() for r in records)
        assert str(dup_id) in log_messages, (
            f"メモリID {dup_id} がログに含まれていません。ログ: {log_messages}"
        )

    async def test_self_healing_log_contains_similarity_score(self):
        """自己修復ログに類似度スコアが含まれること。"""
        now = datetime.now(timezone.utc)
        base = _make_memory(created_at=now)
        duplicate = _make_memory(created_at=now - timedelta(hours=1))
        score = 0.93

        storage = _make_storage(memories=[base])
        storage.vector_search.return_value = [
            _make_scored_memory(base, 1.0),
            _make_scored_memory(duplicate, score),
        ]

        consolidator = Consolidator(storage=storage)

        with _capture_logs("context_store.lifecycle.consolidator") as records:
            await consolidator.run()

        log_messages = " ".join(r.getMessage() for r in records)
        assert str(score) in log_messages or f"{score:.2f}" in log_messages, (
            f"スコア {score} がログに含まれていません。ログ: {log_messages}"
        )

    async def test_no_log_when_no_self_healing(self):
        """自己修復が発動しない場合はログが出力されないこと。"""
        memory = _make_memory()

        storage = _make_storage(memories=[memory])
        storage.vector_search.return_value = [
            _make_scored_memory(memory, 1.0),
        ]

        consolidator = Consolidator(storage=storage)

        with _capture_logs("context_store.lifecycle.consolidator") as records:
            await consolidator.run()

        log_messages = [r.getMessage() for r in records]
        assert not any("Self-healing" in msg for msg in log_messages)


# ---------------------------------------------------------------------------
# 6. GraphAdapter / EmbeddingProvider 連携テスト
# ---------------------------------------------------------------------------


class TestGraphAndEmbeddingIntegration:
    """GraphAdapter と EmbeddingProvider との連携テスト。"""

    async def test_supersedes_edge_created_when_graph_provided(self):
        """GraphAdapter が提供されている場合、SUPERSEDES エッジが作成されること。"""
        now = datetime.now(timezone.utc)
        base = _make_memory(created_at=now)
        duplicate = _make_memory(created_at=now - timedelta(hours=1))

        storage = _make_storage(memories=[base])
        storage.vector_search.return_value = [
            _make_scored_memory(base, 1.0),
            _make_scored_memory(duplicate, 0.95),
        ]

        graph = AsyncMock()

        consolidator = Consolidator(storage=storage, graph=graph)
        await consolidator.run()

        # SUPERSEDES エッジが作成されること
        graph.create_edge.assert_called_once()
        call_kwargs = graph.create_edge.call_args
        # from=base(新), to=duplicate(古) または args として呼ばれること
        args = call_kwargs.args if call_kwargs.args else list(call_kwargs.kwargs.values())
        assert "SUPERSEDES" in args

    async def test_no_graph_edge_when_graph_not_provided(self):
        """GraphAdapter が None の場合、エッジ作成が呼ばれないこと。"""
        now = datetime.now(timezone.utc)
        base = _make_memory(created_at=now)
        duplicate = _make_memory(created_at=now - timedelta(hours=1))

        storage = _make_storage(memories=[base])
        storage.vector_search.return_value = [
            _make_scored_memory(base, 1.0),
            _make_scored_memory(duplicate, 0.95),
        ]

        consolidator = Consolidator(storage=storage, graph=None)
        result = await consolidator.run()

        # エラーなく完了すること
        assert result.consolidated_count >= 1

    async def test_embedding_recomputed_when_provider_given(self):
        """EmbeddingProvider が提供されている場合、埋め込みが再計算されること。"""
        now = datetime.now(timezone.utc)
        base = _make_memory(created_at=now, content="新しい記憶")
        duplicate = _make_memory(created_at=now - timedelta(hours=1))

        storage = _make_storage(memories=[base])
        storage.vector_search.return_value = [
            _make_scored_memory(base, 1.0),
            _make_scored_memory(duplicate, 0.92),
        ]

        embedding_provider = AsyncMock()
        embedding_provider.embed.return_value = [0.5, 0.6, 0.7]
        embedding_provider.dimension = 3

        consolidator = Consolidator(storage=storage, embedding_provider=embedding_provider)
        await consolidator.run()

        # embed が呼ばれること(マージ後の内容で再計算)
        # 少なくとも1回は呼ばれること
        assert embedding_provider.embed.call_count >= 1


# ---------------------------------------------------------------------------
# 7. sliding window (last_cleanup_at) テスト
# ---------------------------------------------------------------------------


class TestSlidingWindow:
    """スライディングウィンドウ（last_cleanup_at）のテスト。"""

    async def test_last_cleanup_at_filters_old_memories(self):
        """last_cleanup_at 以前に作成された記憶はウィンドウに含まれないこと。"""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)

        recent_memory = _make_memory(created_at=datetime.now(timezone.utc))
        _make_memory(
            created_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )

        # list_by_filter が recent_memory のみを返すことで
        # フィルタリングをシミュレート
        storage = _make_storage(memories=[recent_memory])
        storage.vector_search.return_value = []

        consolidator = Consolidator(storage=storage)
        result = await consolidator.run(last_cleanup_at=cutoff)

        # recent_memory のみが処理対象
        assert result.checked_count == 1

    async def test_none_last_cleanup_at_processes_all(self):
        """last_cleanup_at=None の場合、全記憶が対象となること。"""
        memories = [_make_memory() for _ in range(5)]

        storage = _make_storage(memories=memories)
        storage.vector_search.return_value = []

        consolidator = Consolidator(storage=storage)
        result = await consolidator.run(last_cleanup_at=None)

        assert result.checked_count == 5

    async def test_list_by_filter_called_with_created_after(self):
        """last_cleanup_at が指定された場合、フィルタが正しく渡されること。"""
        cutoff = datetime(2025, 1, 1, tzinfo=timezone.utc)

        storage = _make_storage(memories=[])

        consolidator = Consolidator(storage=storage)
        await consolidator.run(last_cleanup_at=cutoff)

        # list_by_filter が正しいフィルタ(created_after == cutoff)で呼ばれること
        # Note: 内部で MemoryFilters オブジェクトが渡されるため、属性をチェックするか
        # 呼び出し時の引数をキャプチャして検証します。
        storage.list_by_filter.assert_called_once()
        call_args = storage.list_by_filter.call_args[0][0]
        assert call_args.created_after == cutoff


# ---------------------------------------------------------------------------
# 8. ConsolidatorResult のテスト
# ---------------------------------------------------------------------------


class TestConsolidatorResult:
    """ConsolidatorResult のテスト。"""

    async def test_result_type(self):
        """run() が ConsolidatorResult を返すこと。"""
        storage = _make_storage(memories=[])
        consolidator = Consolidator(storage=storage)
        result = await consolidator.run()

        assert isinstance(result, ConsolidatorResult)

    async def test_result_fields_zero_when_no_memories(self):
        """記憶が0件の場合、カウントが0であること。"""
        storage = _make_storage(memories=[])
        consolidator = Consolidator(storage=storage)
        result = await consolidator.run()

        assert result.consolidated_count == 0
        assert result.checked_count == 0

    async def test_result_counts_match_processing(self):
        """ConsolidatorResult のカウントが実際の処理結果と一致すること。"""
        now = datetime.now(timezone.utc)
        base = _make_memory(created_at=now)
        dup1 = _make_memory(created_at=now - timedelta(hours=1))
        dup2 = _make_memory(created_at=now - timedelta(hours=2))

        storage = _make_storage(memories=[base])
        storage.vector_search.return_value = [
            _make_scored_memory(base, 1.0),
            _make_scored_memory(dup1, 0.92),
            _make_scored_memory(dup2, 0.91),
        ]

        consolidator = Consolidator(storage=storage)
        result = await consolidator.run()

        assert result.checked_count == 1
        assert result.consolidated_count == 2  # dup1 と dup2 の両方がアーカイブ
