"""ライフサイクルマネージャー。イベント駆動型レイジークリーンアップを実装するモジュール。"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Protocol, runtime_checkable

from filelock import FileLock, Timeout

from context_store.storage.protocols import MemoryFilters

if TYPE_CHECKING:
    from context_store.config import Settings
    from context_store.lifecycle.archiver import Archiver
    from context_store.lifecycle.consolidator import Consolidator
    from context_store.lifecycle.decay_scorer import DecayScorer
    from context_store.lifecycle.purger import Purger
    from context_store.storage.protocols import StorageAdapter

logger = logging.getLogger(__name__)

# 保存回数のクリーンアップ閾値（デフォルト）
_DEFAULT_SAVE_COUNT_THRESHOLD = 50
# 時間ベースのクリーンアップ間隔（デフォルト: 1日）
_DEFAULT_CLEANUP_INTERVAL_HOURS = 24
# WAL チェックポイントの結果キー
_WAL_RESULT_KEY_BUSY = "busy"
_WAL_RESULT_KEY_LOG = "log"
_WAL_RESULT_KEY_CHECKPOINTED = "checkpointed"


@dataclass
class LifecycleState:
    """ライフサイクルの永続化状態。

    Attributes:
        save_count: 前回クリーンアップ以降の保存回数。
        last_cleanup_at: 最後にクリーンアップを実行した日時（UTC）。
        cleanup_running: クリーンアップが実行中かどうか。
        updated_at: 状態が最後に更新された日時（UTC）。
    """

    save_count: int = 0
    last_cleanup_at: datetime | None = None
    cleanup_running: bool = False
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class WalState:
    """WAL チェックポイントの永続化状態。

    Attributes:
        wal_failure_count: WAL チェックポイントの累積失敗数。
        wal_last_failure_ts: 最後に失敗した日時（UTC）。
        wal_last_checkpoint_result: 最後のチェックポイント結果テキスト。
        wal_last_observed_size_bytes: 最後に観測した WAL ファイルサイズ（バイト）。
        wal_consecutive_passive_failures: PASSIVE モードの連続失敗回数。
        wal_failure_window: スライディングウィンドウ（失敗日時のリスト）。
    """

    wal_failure_count: int = 0
    wal_last_failure_ts: datetime | None = None
    wal_last_checkpoint_result: str | None = None
    wal_last_observed_size_bytes: int | None = None
    wal_consecutive_passive_failures: int = 0
    wal_failure_window: list[datetime] = field(default_factory=list)


@runtime_checkable
class LifecycleStateStore(Protocol):
    """ライフサイクル状態のストアプロトコル。"""

    async def load_state(self) -> LifecycleState:
        """永続化された状態を読み込む。"""
        ...

    async def save_state(self, state: LifecycleState) -> None:
        """状態を永続化する。"""
        ...

    async def acquire_cleanup_lock(self) -> bool:
        """クリーンアップの DB レベルロックを取得する。

        Returns:
            ロック取得に成功した場合 True。既にロックされている場合 False。
        """
        ...

    async def release_cleanup_lock(self) -> None:
        """クリーンアップの DB レベルロックを解放する。"""
        ...

    async def load_wal_state(self) -> WalState:
        """WAL 状態を読み込む。"""
        ...

    async def save_wal_state(self, state: WalState) -> None:
        """WAL 状態を永続化する。"""
        ...


class InMemoryLifecycleStateStore:
    """テスト用のインメモリ状態ストア。

    スタルロック検出のために updated_at を参照する。
    stale_lock_timeout_seconds を超えている場合は強制解放する。
    """

    def __init__(self, stale_lock_timeout_seconds: int = 600) -> None:
        self._state = LifecycleState()
        self._wal_state = WalState()
        self._stale_lock_timeout_seconds = stale_lock_timeout_seconds

    async def load_state(self) -> LifecycleState:
        """インメモリ状態を返す（スタルロック検出付き）。"""
        state = self._state
        # スタルロック検出: cleanup_running=True かつ updated_at が古い場合は強制解放
        if state.cleanup_running:
            now = datetime.now(timezone.utc)
            elapsed = (now - state.updated_at).total_seconds()
            if elapsed >= self._stale_lock_timeout_seconds:
                logger.warning(
                    "Stale cleanup lock detected (elapsed=%.1fs), force releasing.", elapsed
                )
                state = LifecycleState(
                    save_count=state.save_count,
                    last_cleanup_at=state.last_cleanup_at,
                    cleanup_running=False,
                    updated_at=now,
                )
                self._state = state
        return state

    async def save_state(self, state: LifecycleState) -> None:
        """インメモリ状態を更新する。"""
        self._state = state

    async def acquire_cleanup_lock(self) -> bool:
        """クリーンアップロックを取得する。"""
        state = await self.load_state()
        if state.cleanup_running:
            return False
        self._state = LifecycleState(
            save_count=state.save_count,
            last_cleanup_at=state.last_cleanup_at,
            cleanup_running=True,
            updated_at=datetime.now(timezone.utc),
        )
        return True

    async def release_cleanup_lock(self) -> None:
        """クリーンアップロックを解放する。"""
        state = self._state
        self._state = LifecycleState(
            save_count=state.save_count,
            last_cleanup_at=state.last_cleanup_at,
            cleanup_running=False,
            updated_at=datetime.now(timezone.utc),
        )

    async def load_wal_state(self) -> WalState:
        """WAL 状態を返す。"""
        return self._wal_state

    async def save_wal_state(self, state: WalState) -> None:
        """WAL 状態を更新する。"""
        self._wal_state = state


class SQLiteLifecycleStateStore:
    """SQLite を使用した永続化ライフサイクル状態ストア。

    lifecycle_state および lifecycle_wal_state テーブルを管理する。

    Args:
        db_path: SQLite データベースファイルのパス。
        stale_lock_timeout_seconds: スタルロックとみなすタイムアウト秒数。
    """

    def __init__(self, db_path: str, stale_lock_timeout_seconds: int = 600) -> None:
        self._db_path = db_path
        self._stale_lock_timeout_seconds = stale_lock_timeout_seconds

    async def _ensure_tables(self, conn: Any) -> None:
        """必要なテーブルを作成する。"""
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS lifecycle_state (
                id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
                save_count INTEGER NOT NULL DEFAULT 0,
                last_cleanup_at TIMESTAMP,
                cleanup_running INTEGER NOT NULL DEFAULT 0,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS lifecycle_wal_state (
                id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
                wal_failure_count INTEGER NOT NULL DEFAULT 0,
                wal_last_failure_ts TIMESTAMP,
                wal_last_checkpoint_result TEXT,
                wal_last_observed_size_bytes INTEGER,
                wal_consecutive_passive_failures INTEGER NOT NULL DEFAULT 0,
                wal_failure_window TEXT NOT NULL DEFAULT '[]'
            )
        """)
        # 初期レコードが存在しない場合のみ挿入
        await conn.execute("INSERT OR IGNORE INTO lifecycle_state (id) VALUES (1)")
        await conn.execute("INSERT OR IGNORE INTO lifecycle_wal_state (id) VALUES (1)")
        await conn.commit()

    async def load_state(self) -> LifecycleState:
        """SQLite から状態を読み込む（スタルロック検出付き）。"""
        import aiosqlite  # type: ignore[import-untyped]

        async with aiosqlite.connect(self._db_path) as conn:
            await self._ensure_tables(conn)
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT save_count, last_cleanup_at, cleanup_running, updated_at "
                "FROM lifecycle_state WHERE id = 1"
            )
            row = await cursor.fetchone()

        if row is None:
            return LifecycleState()

        last_cleanup_at = None
        if row["last_cleanup_at"] is not None:
            last_cleanup_at = datetime.fromisoformat(row["last_cleanup_at"]).replace(
                tzinfo=timezone.utc
            )

        updated_at_str = row["updated_at"]
        updated_at = datetime.fromisoformat(updated_at_str).replace(tzinfo=timezone.utc)

        cleanup_running = bool(row["cleanup_running"])

        # スタルロック検出
        if cleanup_running:
            now = datetime.now(timezone.utc)
            elapsed = (now - updated_at).total_seconds()
            if elapsed >= self._stale_lock_timeout_seconds:
                logger.warning(
                    "Stale cleanup lock detected (elapsed=%.1fs), force releasing.", elapsed
                )
                cleanup_running = False
                updated_at = now
                # DB を即時更新
                async with aiosqlite.connect(self._db_path) as conn:
                    await conn.execute(
                        "UPDATE lifecycle_state SET cleanup_running = 0, updated_at = ? WHERE id = 1",
                        (now.isoformat(),),
                    )
                    await conn.commit()

        return LifecycleState(
            save_count=row["save_count"],
            last_cleanup_at=last_cleanup_at,
            cleanup_running=cleanup_running,
            updated_at=updated_at,
        )

    async def save_state(self, state: LifecycleState) -> None:
        """状態を SQLite に保存する。"""
        import aiosqlite  # type: ignore[import-untyped]

        last_cleanup_at_str = (
            state.last_cleanup_at.isoformat() if state.last_cleanup_at is not None else None
        )
        async with aiosqlite.connect(self._db_path) as conn:
            await self._ensure_tables(conn)
            await conn.execute(
                """
                UPDATE lifecycle_state
                SET save_count = ?, last_cleanup_at = ?, cleanup_running = ?, updated_at = ?
                WHERE id = 1
                """,
                (
                    state.save_count,
                    last_cleanup_at_str,
                    1 if state.cleanup_running else 0,
                    state.updated_at.isoformat(),
                ),
            )
            await conn.commit()

    async def acquire_cleanup_lock(self) -> bool:
        """クリーンアップロックを取得する（DB レベル）。

        Returns:
            ロック取得成功時は True、既にロック中の場合は False。
        """
        import aiosqlite  # type: ignore[import-untyped]

        async with aiosqlite.connect(self._db_path) as conn:
            await self._ensure_tables(conn)
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT cleanup_running, updated_at FROM lifecycle_state WHERE id = 1"
            )
            row = await cursor.fetchone()
            if row is None:
                return False

            if row["cleanup_running"]:
                # スタルロックチェック
                updated_at = datetime.fromisoformat(row["updated_at"]).replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                elapsed = (now - updated_at).total_seconds()
                if elapsed < self._stale_lock_timeout_seconds:
                    return False
                logger.warning("Stale lock expired, forcing release.")

            now = datetime.now(timezone.utc)
            await conn.execute(
                "UPDATE lifecycle_state SET cleanup_running = 1, updated_at = ? WHERE id = 1",
                (now.isoformat(),),
            )
            await conn.commit()
        return True

    async def release_cleanup_lock(self) -> None:
        """クリーンアップロックを解放する。"""
        import aiosqlite  # type: ignore[import-untyped]

        async with aiosqlite.connect(self._db_path) as conn:
            await self._ensure_tables(conn)
            now = datetime.now(timezone.utc)
            await conn.execute(
                "UPDATE lifecycle_state SET cleanup_running = 0, updated_at = ? WHERE id = 1",
                (now.isoformat(),),
            )
            await conn.commit()

    async def load_wal_state(self) -> WalState:
        """WAL 状態を SQLite から読み込む。"""
        import aiosqlite  # type: ignore[import-untyped]

        async with aiosqlite.connect(self._db_path) as conn:
            await self._ensure_tables(conn)
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT wal_failure_count, wal_last_failure_ts, wal_last_checkpoint_result, "
                "wal_last_observed_size_bytes, wal_consecutive_passive_failures, wal_failure_window "
                "FROM lifecycle_wal_state WHERE id = 1"
            )
            row = await cursor.fetchone()

        if row is None:
            return WalState()

        wal_last_failure_ts = None
        if row["wal_last_failure_ts"] is not None:
            wal_last_failure_ts = datetime.fromisoformat(row["wal_last_failure_ts"]).replace(
                tzinfo=timezone.utc
            )

        wal_failure_window: list[datetime] = []
        window_json = row["wal_failure_window"] or "[]"
        try:
            raw_window = json.loads(window_json)
            wal_failure_window = [
                datetime.fromisoformat(ts).replace(tzinfo=timezone.utc) for ts in raw_window
            ]
        except (json.JSONDecodeError, ValueError):
            wal_failure_window = []

        return WalState(
            wal_failure_count=row["wal_failure_count"],
            wal_last_failure_ts=wal_last_failure_ts,
            wal_last_checkpoint_result=row["wal_last_checkpoint_result"],
            wal_last_observed_size_bytes=row["wal_last_observed_size_bytes"],
            wal_consecutive_passive_failures=row["wal_consecutive_passive_failures"],
            wal_failure_window=wal_failure_window,
        )

    async def save_wal_state(self, state: WalState) -> None:
        """WAL 状態を SQLite に保存する。"""
        import aiosqlite  # type: ignore[import-untyped]

        wal_last_failure_ts_str = (
            state.wal_last_failure_ts.isoformat() if state.wal_last_failure_ts is not None else None
        )
        window_json = json.dumps([ts.isoformat() for ts in state.wal_failure_window])
        async with aiosqlite.connect(self._db_path) as conn:
            await self._ensure_tables(conn)
            await conn.execute(
                """
                UPDATE lifecycle_wal_state
                SET wal_failure_count = ?,
                    wal_last_failure_ts = ?,
                    wal_last_checkpoint_result = ?,
                    wal_last_observed_size_bytes = ?,
                    wal_consecutive_passive_failures = ?,
                    wal_failure_window = ?
                WHERE id = 1
                """,
                (
                    state.wal_failure_count,
                    wal_last_failure_ts_str,
                    state.wal_last_checkpoint_result,
                    state.wal_last_observed_size_bytes,
                    state.wal_consecutive_passive_failures,
                    window_json,
                ),
            )
            await conn.commit()


WalCheckpointFn = Callable[[str], Coroutine[Any, Any, dict[str, int]]]


class LifecycleManager:
    """ライフサイクルマネージャー。イベント駆動型レイジークリーンアップを管理する。

    クリーンアップは以下のトリガーで非同期実行される:
    1. 保存回数が閾値（50回）に達した場合
    2. MCPサーバー起動時に前回から1日以上経過している場合

    OS レベルの排他制御に filelock を使用し、DB レベルのロックと組み合わせる。

    Args:
        state_store: ライフサイクル状態ストア。
        archiver: アーカイバー。
        purger: パージャー。
        consolidator: コンソリデーター。
        decay_scorer: 減衰スコアラー。
        storage: ストレージアダプター（統計収集用）。
        settings: アプリケーション設定。省略時はデフォルト値を使用。
        lock_path: OS レベルのファイルロックパス。
        wal_checkpoint_fn: WAL チェックポイント実行関数。None の場合はスキップ。
    """

    def __init__(
        self,
        state_store: LifecycleStateStore,
        archiver: "Archiver",
        purger: "Purger",
        consolidator: "Consolidator",
        decay_scorer: "DecayScorer",
        storage: "StorageAdapter",
        settings: "Settings | None" = None,
        lock_path: str = ".lifecycle.lock",
        wal_checkpoint_fn: "WalCheckpointFn | None" = None,
    ) -> None:
        self._state_store = state_store
        self._archiver = archiver
        self._purger = purger
        self._consolidator = consolidator
        self._decay_scorer = decay_scorer
        self._storage = storage
        self._lock_path = lock_path
        self._wal_checkpoint_fn = wal_checkpoint_fn

        if settings is not None:
            self._save_count_threshold = settings.cleanup_save_count_threshold
            self._stale_lock_timeout_seconds = settings.stale_lock_timeout_seconds
            self._wal_truncate_size_bytes = settings.wal_truncate_size_bytes
            self._wal_passive_fail_consecutive_threshold = (
                settings.wal_passive_fail_consecutive_threshold
            )
            self._wal_passive_fail_window_seconds = settings.wal_passive_fail_window_seconds
            self._wal_passive_fail_window_count_threshold = (
                settings.wal_passive_fail_window_count_threshold
            )
            self._wal_checkpoint_mode_passive = settings.wal_checkpoint_mode_passive
            self._wal_checkpoint_mode_truncate = settings.wal_checkpoint_mode_truncate
        else:
            self._save_count_threshold = _DEFAULT_SAVE_COUNT_THRESHOLD
            self._stale_lock_timeout_seconds = 600
            self._wal_truncate_size_bytes = 104857600  # 100MB
            self._wal_passive_fail_consecutive_threshold = 3
            self._wal_passive_fail_window_seconds = 600
            self._wal_passive_fail_window_count_threshold = 5
            self._wal_checkpoint_mode_passive = "PASSIVE"
            self._wal_checkpoint_mode_truncate = "TRUNCATE"

        self._active_tasks: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        """MCPサーバー起動時に呼び出す。時間ベースのクリーンアップチェックをスケジュール。

        初回起動時のみ前回クリーンアップからの経過時間を確認し、
        1日以上経過している場合はクリーンアップを非同期でトリガーする。
        """
        task = asyncio.create_task(self._check_time_based_cleanup())
        self._active_tasks.append(task)
        task.add_done_callback(self._active_tasks.remove)

    async def _check_time_based_cleanup(self) -> None:
        """時間ベースのクリーンアップチェック（起動時に1回のみ実行）。"""
        try:
            state = await self._state_store.load_state()
            now = datetime.now(timezone.utc)

            should_run = False
            if state.last_cleanup_at is None:
                should_run = True
            else:
                elapsed = now - state.last_cleanup_at
                if elapsed >= timedelta(hours=_DEFAULT_CLEANUP_INTERVAL_HOURS):
                    should_run = True

            if should_run:
                logger.info(
                    "Time-based cleanup triggered (last_cleanup_at=%s).", state.last_cleanup_at
                )
                await self.run_cleanup()
        except Exception:
            logger.exception("Time-based cleanup check failed.")

    async def on_memory_saved(self) -> None:
        """記憶が保存されるたびに呼び出す。カウンターをインクリメントして閾値チェック。

        カウンターが閾値（50回）に達した場合、クリーンアップを非同期でトリガーする。
        """
        state = await self._state_store.load_state()
        new_count = state.save_count + 1
        new_state = LifecycleState(
            save_count=new_count,
            last_cleanup_at=state.last_cleanup_at,
            cleanup_running=state.cleanup_running,
            updated_at=datetime.now(timezone.utc),
        )
        await self._state_store.save_state(new_state)

        if new_count >= self._save_count_threshold:
            logger.info("Save count threshold reached (%d), triggering cleanup.", new_count)
            task = asyncio.create_task(self.run_cleanup())
            self._active_tasks.append(task)
            task.add_done_callback(self._active_tasks.remove)

    async def run_cleanup(self) -> None:
        """クリーンアップを実行する（filelock + DB ロック排他制御付き）。

        filelock によるプロセス間排他制御と DB レベルのロックを組み合わせて
        同時実行を防ぐ。ロック取得失敗時はサイレントにスキップする。
        """
        # OS レベルの排他ロック（timeout=0 = 非ブロッキング）
        file_lock = FileLock(self._lock_path, timeout=0)
        try:
            with file_lock.acquire():
                await self._run_cleanup_inner()
        except Timeout:
            logger.debug("Cleanup skipped: another process holds the file lock.")
            return

    async def _run_cleanup_inner(self) -> None:
        """クリーンアップ本体（DB ロック取得後に実行）。"""
        # DB レベルのロック取得
        acquired = await self._state_store.acquire_cleanup_lock()
        if not acquired:
            logger.debug("Cleanup skipped: DB lock already acquired.")
            return

        try:
            state = await self._state_store.load_state()
            logger.info("Starting cleanup (save_count=%d).", state.save_count)

            # 1. Decay Scorer (各ジョブは暗黙的にスコアを使用)
            # 2. Archiver
            archiver_result = await self._archiver.run()
            logger.info(
                "Archiver: archived=%d, checked=%d",
                archiver_result.archived_count,
                archiver_result.checked_count,
            )

            # 3. Consolidator
            consolidator_result = await self._consolidator.run(
                last_cleanup_at=state.last_cleanup_at
            )
            logger.info(
                "Consolidator: consolidated=%d, checked=%d",
                consolidator_result.consolidated_count,
                consolidator_result.checked_count,
            )

            # 4. Purger
            purger_result = await self._purger.run()
            logger.info(
                "Purger: purged=%d, checked=%d",
                purger_result.purged_count,
                purger_result.checked_count,
            )

            # 5. Stats Collector
            await self._collect_stats()

            # 6. WAL チェックポイント（SQLite のみ）
            if self._wal_checkpoint_fn is not None:
                await self._run_wal_checkpoint()

            # 状態を更新（カウンターリセット + last_cleanup_at 更新）
            now = datetime.now(timezone.utc)
            new_state = LifecycleState(
                save_count=0,
                last_cleanup_at=now,
                cleanup_running=False,
                updated_at=now,
            )
            await self._state_store.save_state(new_state)

        except Exception:
            logger.exception("Cleanup failed.")
            raise
        finally:
            await self._state_store.release_cleanup_lock()

    async def _collect_stats(self) -> None:
        """統計情報をログに記録する（将来的に DB 保存へ拡張可能）。"""
        try:
            # アクティブ記憶数
            active_memories = await self._storage.list_by_filter(MemoryFilters(archived=None))
            active_count = len(active_memories)
            # アーカイブ済み記憶数
            archived_memories = await self._storage.list_by_filter(MemoryFilters(archived=True))
            archived_count = len(archived_memories)
            logger.info(
                "Stats: active_memories=%d, archived_memories=%d",
                active_count,
                archived_count,
            )
        except Exception:
            logger.exception("Stats collection failed.")

    async def _run_wal_checkpoint(self) -> None:
        """WAL チェックポイントを実行し、必要に応じて TRUNCATE を試みる。"""
        assert self._wal_checkpoint_fn is not None

        wal_state = await self._state_store.load_wal_state()
        now = datetime.now(timezone.utc)

        try:
            result = await self._wal_checkpoint_fn(self._wal_checkpoint_mode_passive)
            busy = result.get(_WAL_RESULT_KEY_BUSY, 0)
            log_size = result.get(_WAL_RESULT_KEY_LOG, 0)
            # WAL サイズを観測値として更新（1ページ ≈ 4096バイトで近似）
            wal_state.wal_last_observed_size_bytes = log_size * 4096

            if busy > 0:
                # PASSIVE チェックポイントが busy ページを持つ場合は失敗とみなす
                wal_state = await self._handle_wal_passive_failure(wal_state, now)
            else:
                # 成功: 連続失敗カウンターをリセット
                wal_state.wal_consecutive_passive_failures = 0
                wal_state.wal_last_checkpoint_result = "PASSIVE_OK"
                logger.debug("WAL PASSIVE checkpoint succeeded.")

        except Exception as exc:
            logger.warning("WAL PASSIVE checkpoint failed: %s", exc)
            wal_state = await self._handle_wal_passive_failure(wal_state, now)

        await self._state_store.save_wal_state(wal_state)

    async def _handle_wal_passive_failure(self, wal_state: WalState, now: datetime) -> WalState:
        """PASSIVE チェックポイント失敗時の処理。

        スライディングウィンドウと連続失敗数に基づいて TRUNCATE を試みる。
        """
        wal_state.wal_failure_count += 1
        wal_state.wal_consecutive_passive_failures += 1
        wal_state.wal_last_failure_ts = now

        # スライディングウィンドウを更新（古いエントリを除去）
        window_cutoff = now - timedelta(seconds=self._wal_passive_fail_window_seconds)
        wal_state.wal_failure_window = [
            ts for ts in wal_state.wal_failure_window if ts >= window_cutoff
        ]
        wal_state.wal_failure_window.append(now)

        # TRUNCATE 判定:
        # (連続失敗数 OR ウィンドウ内失敗数 が閾値超過) かつ WAL ファイルサイズが閾値超過
        consecutive_exceeded = (
            wal_state.wal_consecutive_passive_failures
            >= self._wal_passive_fail_consecutive_threshold
        )
        window_failure_count = len(wal_state.wal_failure_window)
        window_exceeded = window_failure_count >= self._wal_passive_fail_window_count_threshold
        size_exceeded = (
            wal_state.wal_last_observed_size_bytes is not None
            and wal_state.wal_last_observed_size_bytes >= self._wal_truncate_size_bytes
        )

        if (consecutive_exceeded or window_exceeded) and size_exceeded:
            logger.warning(
                "Attempting WAL TRUNCATE checkpoint (consecutive_failures=%d, size=%s).",
                wal_state.wal_consecutive_passive_failures,
                wal_state.wal_last_observed_size_bytes,
            )
            assert self._wal_checkpoint_fn is not None
            try:
                await self._wal_checkpoint_fn(self._wal_checkpoint_mode_truncate)
                wal_state.wal_last_checkpoint_result = "TRUNCATE_OK"
                wal_state.wal_consecutive_passive_failures = 0
                logger.info("WAL TRUNCATE checkpoint succeeded.")
            except Exception as exc:
                logger.error("WAL TRUNCATE checkpoint failed: %s", exc)
                wal_state.wal_last_checkpoint_result = "TRUNCATE_FAIL"
        else:
            wal_state.wal_last_checkpoint_result = "PASSIVE_FAILED"

        return wal_state

    async def graceful_shutdown(self) -> None:
        """進行中のタスクをタイムアウト付きで完了待機する（最大 5 秒）。"""
        if not self._active_tasks:
            return

        tasks = list(self._active_tasks)
        logger.info("Graceful shutdown: waiting for %d task(s)...", len(tasks))
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=5.0,
            )
        except asyncio.TimeoutError:
            logger.warning("Graceful shutdown timed out, cancelling remaining tasks.")
            for task in tasks:
                if not task.done():
                    task.cancel()
