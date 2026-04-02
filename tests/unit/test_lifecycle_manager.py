"""LifecycleManager のユニットテスト。"""
from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_store.lifecycle.manager import (
    InMemoryLifecycleStateStore,
    LifecycleManager,
    LifecycleState,
    WalState,
)
from tests.unit.conftest import make_settings


# ─────────────────────────── ヘルパー ───────────────────────────


def _make_manager(
    *,
    state_store: InMemoryLifecycleStateStore | None = None,
    save_count_threshold: int = 50,
    stale_lock_timeout_seconds: int = 600,
    wal_checkpoint_fn=None,
    lock_path: str | None = None,
) -> tuple[LifecycleManager, InMemoryLifecycleStateStore]:
    """テスト用 LifecycleManager を生成するヘルパー。"""
    if state_store is None:
        state_store = InMemoryLifecycleStateStore(
            stale_lock_timeout_seconds=stale_lock_timeout_seconds
        )

    archiver = AsyncMock()
    archiver.run = AsyncMock(return_value=MagicMock(archived_count=0, checked_count=0))

    purger = AsyncMock()
    purger.run = AsyncMock(return_value=MagicMock(purged_count=0, checked_count=0))

    consolidator = AsyncMock()
    consolidator.run = AsyncMock(
        return_value=MagicMock(consolidated_count=0, checked_count=0)
    )

    decay_scorer = MagicMock()

    storage = AsyncMock()
    storage.list_by_filter = AsyncMock(return_value=[])

    settings = make_settings(stale_lock_timeout_seconds=stale_lock_timeout_seconds)

    with tempfile.NamedTemporaryFile(suffix=".lock", delete=False) as f:
        tmp_lock_path = lock_path or f.name

    manager = LifecycleManager(
        state_store=state_store,
        archiver=archiver,
        purger=purger,
        consolidator=consolidator,
        decay_scorer=decay_scorer,
        storage=storage,
        settings=settings,
        lock_path=tmp_lock_path,
        wal_checkpoint_fn=wal_checkpoint_fn,
    )
    return manager, state_store


# ─────────────────────────── on_memory_saved テスト ───────────────────────────


class TestOnMemorySaved:
    """on_memory_saved() のテスト。"""

    async def test_increments_counter(self):
        """on_memory_saved() がカウンターをインクリメントすること。"""
        manager, store = _make_manager()

        await manager.on_memory_saved()
        state = await store.load_state()
        assert state.save_count == 1

        await manager.on_memory_saved()
        state = await store.load_state()
        assert state.save_count == 2

    async def test_triggers_cleanup_at_threshold(self):
        """閾値到達時に run_cleanup がトリガーされること。"""
        manager, store = _make_manager(save_count_threshold=50)
        # _save_count_threshold を 3 に上書きしてテストを軽くする
        manager._save_count_threshold = 3

        run_cleanup_called = []

        async def fake_cleanup():
            run_cleanup_called.append(True)

        manager.run_cleanup = fake_cleanup  # type: ignore[assignment]

        # 2回保存: 閾値未達
        await manager.on_memory_saved()
        await manager.on_memory_saved()
        assert len(run_cleanup_called) == 0

        # 3回目: 閾値到達
        await manager.on_memory_saved()
        # asyncio.create_task で起動されるので少し待つ
        await asyncio.sleep(0)
        assert len(run_cleanup_called) == 1

    async def test_does_not_trigger_cleanup_below_threshold(self):
        """閾値未満では run_cleanup がトリガーされないこと。"""
        manager, store = _make_manager()
        manager._save_count_threshold = 10

        cleanup_called = []
        original_cleanup = manager.run_cleanup

        async def spy_cleanup():
            cleanup_called.append(True)
            await original_cleanup()

        manager.run_cleanup = spy_cleanup  # type: ignore[assignment]

        for _ in range(9):
            await manager.on_memory_saved()

        await asyncio.sleep(0)
        assert len(cleanup_called) == 0

    async def test_save_count_persisted(self):
        """save_count が状態ストアに永続化されること。"""
        manager, store = _make_manager()

        for _ in range(5):
            await manager.on_memory_saved()

        state = await store.load_state()
        assert state.save_count == 5


# ─────────────────────────── run_cleanup テスト ───────────────────────────


class TestRunCleanup:
    """run_cleanup() のテスト。"""

    async def test_runs_all_jobs(self):
        """run_cleanup() が全ジョブを実行すること。"""
        manager, store = _make_manager()

        await manager.run_cleanup()

        manager._archiver.run.assert_called_once()
        manager._consolidator.run.assert_called_once()
        manager._purger.run.assert_called_once()

    async def test_resets_save_count_after_cleanup(self):
        """クリーンアップ後に save_count がリセットされること。"""
        manager, store = _make_manager()

        # 事前にカウンターを増やす
        for _ in range(5):
            await manager.on_memory_saved()

        # 直接 run_cleanup を実行（閾値を回避）
        manager._save_count_threshold = 100
        # ここでは on_memory_saved() は 5 カウントのまま
        await manager.run_cleanup()

        state = await store.load_state()
        assert state.save_count == 0

    async def test_updates_last_cleanup_at(self):
        """run_cleanup() 後に last_cleanup_at が更新されること。"""
        manager, store = _make_manager()

        before = datetime.now(timezone.utc)
        await manager.run_cleanup()
        after = datetime.now(timezone.utc)

        state = await store.load_state()
        assert state.last_cleanup_at is not None
        assert before <= state.last_cleanup_at <= after

    async def test_idempotent_two_runs(self):
        """2回連続実行しても同じ結果に収束すること（冪等性）。"""
        manager, store = _make_manager()

        await manager.run_cleanup()
        state_after_first = await store.load_state()
        first_cleanup_at = state_after_first.last_cleanup_at
        assert first_cleanup_at is not None

        # 少し時間を置いて2回目
        await asyncio.sleep(0.01)
        await manager.run_cleanup()
        state_after_second = await store.load_state()
        second_cleanup_at = state_after_second.last_cleanup_at
        assert second_cleanup_at is not None

        # 2回目の方が後の時刻であること
        assert second_cleanup_at >= first_cleanup_at
        # save_count はどちらも 0 にリセットされること
        assert state_after_second.save_count == 0

    async def test_skips_when_filelock_acquired(self):
        """filelock が既に取得されている場合にスキップすること。"""
        with tempfile.NamedTemporaryFile(suffix=".lock", delete=False) as f:
            lock_path = f.name

        manager, store = _make_manager(lock_path=lock_path)

        from filelock import FileLock

        outer_lock = FileLock(lock_path, timeout=0)

        # 外部からロックを保持
        with outer_lock.acquire():
            # この間に run_cleanup を呼んでもスキップされる
            await manager.run_cleanup()

        # ジョブが呼ばれていないこと
        manager._archiver.run.assert_not_called()
        manager._purger.run.assert_not_called()
        manager._consolidator.run.assert_not_called()

    async def test_releases_db_lock_after_cleanup(self):
        """クリーンアップ後に DB ロックが解放されること。"""
        manager, store = _make_manager()

        await manager.run_cleanup()

        state = await store.load_state()
        assert state.cleanup_running is False

    async def test_releases_db_lock_on_exception(self):
        """例外発生時でも DB ロックが解放されること。"""
        manager, store = _make_manager()
        manager._archiver.run.side_effect = RuntimeError("archiver failed")

        with pytest.raises(RuntimeError, match="archiver failed"):
            await manager.run_cleanup()

        state = await store.load_state()
        assert state.cleanup_running is False


# ─────────────────────────── スタルロックテスト ───────────────────────────


class TestStaleLock:
    """スタルロックの検出と解放テスト。"""

    async def test_stale_lock_is_force_released(self):
        """古い cleanup_running フラグが強制解放されること。"""
        # stale_lock_timeout_seconds を 1 秒に設定
        store = InMemoryLifecycleStateStore(stale_lock_timeout_seconds=1)

        # 2秒以上前の updated_at で cleanup_running=True を設定
        old_time = datetime.now(timezone.utc) - timedelta(seconds=2)
        stale_state = LifecycleState(
            save_count=0,
            last_cleanup_at=None,
            cleanup_running=True,
            updated_at=old_time,
        )
        store._state = stale_state

        # load_state() がスタルロックを検出して解放すること
        state = await store.load_state()
        assert state.cleanup_running is False

    async def test_recent_lock_is_not_released(self):
        """新しい cleanup_running フラグは解放されないこと。"""
        store = InMemoryLifecycleStateStore(stale_lock_timeout_seconds=600)

        # 最近の updated_at で cleanup_running=True を設定
        recent_time = datetime.now(timezone.utc)
        running_state = LifecycleState(
            save_count=0,
            last_cleanup_at=None,
            cleanup_running=True,
            updated_at=recent_time,
        )
        store._state = running_state

        state = await store.load_state()
        assert state.cleanup_running is True

    async def test_cleanup_skipped_when_db_lock_held(self):
        """DB ロックが保持されている場合はクリーンアップをスキップすること。"""
        manager, store = _make_manager()

        # 手動で cleanup_running=True に設定
        now = datetime.now(timezone.utc)
        store._state = LifecycleState(
            save_count=0,
            last_cleanup_at=None,
            cleanup_running=True,
            updated_at=now,
        )

        # クリーンアップはスキップされる（DB ロックで弾かれる）
        await manager.run_cleanup()

        # ジョブが呼ばれていないこと
        manager._archiver.run.assert_not_called()


# ─────────────────────────── 時間ベースのクリーンアップテスト ───────────────────────────


class TestTimeBasedCleanup:
    """_check_time_based_cleanup() のテスト。"""

    async def test_triggers_cleanup_when_never_run(self):
        """last_cleanup_at が None の場合にクリーンアップがトリガーされること。"""
        manager, store = _make_manager()
        cleanup_called = []

        async def fake_cleanup():
            cleanup_called.append(True)

        manager.run_cleanup = fake_cleanup  # type: ignore[assignment]

        await manager._check_time_based_cleanup()
        assert len(cleanup_called) == 1

    async def test_triggers_cleanup_when_over_24h(self):
        """前回から 24 時間以上経過した場合にクリーンアップがトリガーされること。"""
        store = InMemoryLifecycleStateStore()
        old_time = datetime.now(timezone.utc) - timedelta(hours=25)
        store._state = LifecycleState(
            save_count=0,
            last_cleanup_at=old_time,
            cleanup_running=False,
            updated_at=datetime.now(timezone.utc),
        )
        manager, _ = _make_manager(state_store=store)

        cleanup_called = []

        async def fake_cleanup():
            cleanup_called.append(True)

        manager.run_cleanup = fake_cleanup  # type: ignore[assignment]

        await manager._check_time_based_cleanup()
        assert len(cleanup_called) == 1

    async def test_does_not_trigger_when_recent_cleanup(self):
        """前回から 24 時間未満の場合はクリーンアップがトリガーされないこと。"""
        store = InMemoryLifecycleStateStore()
        recent_time = datetime.now(timezone.utc) - timedelta(hours=1)
        store._state = LifecycleState(
            save_count=0,
            last_cleanup_at=recent_time,
            cleanup_running=False,
            updated_at=datetime.now(timezone.utc),
        )
        manager, _ = _make_manager(state_store=store)

        cleanup_called = []

        async def fake_cleanup():
            cleanup_called.append(True)

        manager.run_cleanup = fake_cleanup  # type: ignore[assignment]

        await manager._check_time_based_cleanup()
        assert len(cleanup_called) == 0

    async def test_start_schedules_time_based_check(self):
        """start() が時間ベースのチェックをスケジュールすること。"""
        manager, store = _make_manager()

        check_called = []

        async def fake_check():
            check_called.append(True)

        manager._check_time_based_cleanup = fake_check  # type: ignore[assignment]

        await manager.start()
        # タスクが実行されるまで待つ
        await asyncio.sleep(0.05)
        assert len(check_called) == 1


# ─────────────────────────── 永続化テスト ───────────────────────────


class TestPersistence:
    """状態の永続化テスト。"""

    async def test_last_cleanup_at_persisted_after_cleanup(self):
        """run_cleanup() 後に last_cleanup_at が DB に永続化されること。"""
        manager, store = _make_manager()
        assert (await store.load_state()).last_cleanup_at is None

        await manager.run_cleanup()

        state = await store.load_state()
        assert state.last_cleanup_at is not None

    async def test_save_count_resets_after_cleanup(self):
        """run_cleanup() 後に save_count が 0 にリセットされ永続化されること。"""
        manager, store = _make_manager()
        manager._save_count_threshold = 100  # 自動トリガーを無効化

        for _ in range(10):
            await manager.on_memory_saved()

        state_before = await store.load_state()
        assert state_before.save_count == 10

        await manager.run_cleanup()

        state_after = await store.load_state()
        assert state_after.save_count == 0

    async def test_wal_state_persisted(self):
        """WAL 状態が永続化されること。"""
        store = InMemoryLifecycleStateStore()
        wal_state = WalState(
            wal_failure_count=3,
            wal_consecutive_passive_failures=2,
        )
        await store.save_wal_state(wal_state)
        loaded = await store.load_wal_state()
        assert loaded.wal_failure_count == 3
        assert loaded.wal_consecutive_passive_failures == 2


# ─────────────────────────── グレースフルシャットダウンテスト ───────────────────────────


class TestGracefulShutdown:
    """graceful_shutdown() のテスト。"""

    async def test_shutdown_with_no_tasks(self):
        """タスクがない場合はシャットダウンが即座に完了すること。"""
        manager, _ = _make_manager()
        # アクティブタスクなし
        assert len(manager._active_tasks) == 0

        # タイムアウトなしで即時完了すること
        await asyncio.wait_for(manager.graceful_shutdown(), timeout=1.0)

    async def test_shutdown_waits_for_running_task(self):
        """実行中タスクの完了を待機すること。"""
        manager, _ = _make_manager()

        completed = []

        async def slow_task():
            await asyncio.sleep(0.1)
            completed.append(True)

        task = asyncio.create_task(slow_task())
        manager._active_tasks.append(task)

        await manager.graceful_shutdown()
        assert len(completed) == 1

    async def test_shutdown_times_out_after_5s(self):
        """5秒以内にシャットダウンが収束すること（タイムアウト発生でもエラーにならない）。"""
        manager, _ = _make_manager()

        async def long_task():
            await asyncio.sleep(10)  # 5秒を超えるタスク

        task = asyncio.create_task(long_task())
        manager._active_tasks.append(task)

        # 5秒タイムアウト付きで完了すること（TimeoutError が内部で処理される）
        await asyncio.wait_for(manager.graceful_shutdown(), timeout=6.0)

        # タスクがキャンセルされていること
        assert task.cancelled()


# ─────────────────────────── WAL チェックポイントテスト ───────────────────────────


class TestWalCheckpoint:
    """WAL チェックポイントのテスト。"""

    async def test_wal_checkpoint_called_when_fn_provided(self):
        """wal_checkpoint_fn が提供された場合に WAL チェックポイントが実行されること。"""
        checkpoint_calls = []

        async def mock_wal_fn() -> dict:
            checkpoint_calls.append(True)
            return {"busy": 0, "log": 10, "checkpointed": 10}

        manager, store = _make_manager(wal_checkpoint_fn=mock_wal_fn)

        await manager.run_cleanup()
        assert len(checkpoint_calls) == 1

    async def test_wal_not_called_when_fn_not_provided(self):
        """wal_checkpoint_fn が None の場合に WAL チェックポイントが実行されないこと。"""
        manager, store = _make_manager(wal_checkpoint_fn=None)

        # _run_wal_checkpoint は呼ばれない（wal_checkpoint_fn=None）
        # クリーンアップ自体は正常完了する
        await manager.run_cleanup()

        state = await store.load_state()
        assert state.last_cleanup_at is not None

    async def test_consecutive_passive_failures_tracked(self):
        """PASSIVE チェックポイント連続失敗がトラッキングされること。"""
        call_count = [0]

        async def failing_wal_fn() -> dict:
            call_count[0] += 1
            return {"busy": 5, "log": 100, "checkpointed": 95}  # busy > 0 = 失敗

        manager, store = _make_manager(wal_checkpoint_fn=failing_wal_fn)

        await manager.run_cleanup()

        wal_state = await store.load_wal_state()
        assert wal_state.wal_consecutive_passive_failures == 1
        assert wal_state.wal_failure_count == 1

    async def test_truncate_triggered_on_consecutive_failure_and_large_wal(self):
        """連続失敗かつ WAL サイズ超過時に TRUNCATE が試みられること。"""
        call_count = [0]

        async def mock_wal_fn() -> dict:
            call_count[0] += 1
            if call_count[0] == 1:
                return {"busy": 5, "log": 100, "checkpointed": 95}  # PASSIVE 失敗
            return {"busy": 0, "log": 100, "checkpointed": 100}  # TRUNCATE 成功

        store = InMemoryLifecycleStateStore()
        # 連続失敗数をしきい値ギリギリに設定 (threshold=3, consecutive=2)
        # → 今回の失敗で 3 になる
        wal_state = WalState(
            wal_consecutive_passive_failures=2,
            wal_last_observed_size_bytes=200 * 1024 * 1024,  # 200MB > 100MB
        )
        await store.save_wal_state(wal_state)

        manager, _ = _make_manager(
            state_store=store,
            wal_checkpoint_fn=mock_wal_fn,
        )
        # wal_truncate_size_bytes を小さく設定
        manager._wal_truncate_size_bytes = 100 * 1024 * 1024  # 100MB

        await manager.run_cleanup()

        # WAL fn が2回呼ばれた（PASSIVE + TRUNCATE）
        assert call_count[0] == 2

        loaded_wal = await store.load_wal_state()
        assert loaded_wal.wal_last_checkpoint_result == "TRUNCATE"
        assert loaded_wal.wal_consecutive_passive_failures == 0


# ─────────────────────────── SQLiteLifecycleStateStore テスト ───────────────────────────


class TestSQLiteLifecycleStateStore:
    """SQLiteLifecycleStateStore のテスト。"""

    async def test_load_default_state(self):
        """初期状態が正しく読み込まれること。"""
        from context_store.lifecycle.manager import SQLiteLifecycleStateStore

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            store = SQLiteLifecycleStateStore(db_path=db_path)
            state = await store.load_state()
            assert state.save_count == 0
            assert state.last_cleanup_at is None
            assert state.cleanup_running is False
        finally:
            os.unlink(db_path)

    async def test_save_and_load_state(self):
        """状態の保存と読み込みが正しく動作すること。"""
        from context_store.lifecycle.manager import SQLiteLifecycleStateStore

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            store = SQLiteLifecycleStateStore(db_path=db_path)
            now = datetime.now(timezone.utc).replace(microsecond=0)  # マイクロ秒を除外
            state = LifecycleState(
                save_count=42,
                last_cleanup_at=now,
                cleanup_running=False,
                updated_at=now,
            )
            await store.save_state(state)

            loaded = await store.load_state()
            assert loaded.save_count == 42
            # タイムスタンプは秒単位で比較
            assert loaded.last_cleanup_at is not None
            assert abs((loaded.last_cleanup_at - now).total_seconds()) < 2
        finally:
            os.unlink(db_path)

    async def test_acquire_and_release_lock(self):
        """DB ロックの取得と解放が正しく動作すること。"""
        from context_store.lifecycle.manager import SQLiteLifecycleStateStore

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            store = SQLiteLifecycleStateStore(db_path=db_path)

            # ロック取得成功
            acquired = await store.acquire_cleanup_lock()
            assert acquired is True

            # 同じロックを再取得しようとすると失敗
            acquired_again = await store.acquire_cleanup_lock()
            assert acquired_again is False

            # ロック解放
            await store.release_cleanup_lock()

            # 解放後は再取得可能
            acquired_after_release = await store.acquire_cleanup_lock()
            assert acquired_after_release is True
            await store.release_cleanup_lock()
        finally:
            os.unlink(db_path)

    async def test_stale_lock_detection_in_sqlite(self):
        """SQLite のスタルロックが検出・解放されること。"""
        from context_store.lifecycle.manager import SQLiteLifecycleStateStore

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            store = SQLiteLifecycleStateStore(
                db_path=db_path, stale_lock_timeout_seconds=1
            )

            # 手動でスタルなロック状態を作る
            import aiosqlite

            old_time = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
            async with aiosqlite.connect(db_path) as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS lifecycle_state (
                        id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
                        save_count INTEGER NOT NULL DEFAULT 0,
                        last_cleanup_at TIMESTAMP,
                        cleanup_running INTEGER NOT NULL DEFAULT 0,
                        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                await conn.execute(
                    "INSERT OR REPLACE INTO lifecycle_state (id, cleanup_running, updated_at) "
                    "VALUES (1, 1, ?)",
                    (old_time,),
                )
                await conn.commit()

            # load_state() がスタルロックを検出して解放すること
            state = await store.load_state()
            assert state.cleanup_running is False
        finally:
            os.unlink(db_path)

    async def test_wal_state_save_and_load(self):
        """WAL 状態の保存と読み込みが正しく動作すること。"""
        from context_store.lifecycle.manager import SQLiteLifecycleStateStore

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            store = SQLiteLifecycleStateStore(db_path=db_path)

            now = datetime.now(timezone.utc).replace(microsecond=0)
            wal_state = WalState(
                wal_failure_count=5,
                wal_last_failure_ts=now,
                wal_last_checkpoint_result="PASSIVE_FAILED",
                wal_last_observed_size_bytes=50 * 1024 * 1024,
                wal_consecutive_passive_failures=3,
                wal_failure_window=[now],
            )
            await store.save_wal_state(wal_state)

            loaded = await store.load_wal_state()
            assert loaded.wal_failure_count == 5
            assert loaded.wal_consecutive_passive_failures == 3
            assert loaded.wal_last_checkpoint_result == "PASSIVE_FAILED"
            assert loaded.wal_last_observed_size_bytes == 50 * 1024 * 1024
            assert len(loaded.wal_failure_window) == 1
        finally:
            os.unlink(db_path)
