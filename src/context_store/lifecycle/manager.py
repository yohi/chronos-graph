"""ライフサイクルマネージャー。イベント駆動型レイジークリーンアップを実装するモジュール。"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Protocol, runtime_checkable

from filelock import FileLock, Timeout

from context_store.lifecycle.consolidator import CONSOLIDATION_BATCH_SIZE
from context_store.storage.protocols import MemoryFilters

if TYPE_CHECKING:
    from context_store.config import Settings
    from context_store.ingestion.task_registry import TaskRegistry
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


class LockLostError(Exception):
    """クリーンアップロックを喪失したことを示す例外。"""


@dataclass
class LifecycleState:
    """ライフサイクルの永続化状態。

    Attributes:
        save_count: 前回クリーンアップ以降の保存回数。
        last_cleanup_at: 最後にクリーンアップが「完全に成功」した日時（UTC）。
        last_cleanup_cursor_at: クリーンアップのページング用カーソル日時。
        last_cleanup_id: クリーンアップのページング用カーソル ID。
        cleanup_lock_owner: クリーンアップロックの保持者トークン。
        cleanup_lock_touched_at: クリーンアップロックの最終更新日時（UTC）。
        updated_at: 状態が最後に更新された日時（UTC）。
    """

    save_count: int = 0
    last_cleanup_at: datetime | None = None
    last_cleanup_cursor_at: datetime | None = None
    last_cleanup_id: str | None = None
    cleanup_lock_owner: str | None = None
    cleanup_lock_touched_at: datetime | None = None
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class WalState:
    """WAL チェックポイントの永続化状態。

    Attributes:
        wal_failure_count: WAL チェックポイントの累積失敗数。
        wal_last_failure_ts: 最後に失敗した日時（UTC）。
        wal_last_checkpoint_result: 最後のチェックポイント結果テキスト。
        wal_last、observed_size_bytes: 最後に観測した WAL ファイルサイズ（バイト）。
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

    async def save_state(self, state: LifecycleState, token: str | None = None) -> bool:
        """状態を永続化する。"""
        ...

    async def increment_save_count(self, threshold: int) -> bool:
        """save_count を 1 増やし、閾値をちょうど超えたかどうかを返す。

        原子的に更新する必要がある。

        Returns:
            インクリメント後に閾値をちょうど超えた(または等しくなった)場合に True。
            既に超えていた場合や、まだ達していない場合は False。
        """
        ...

    async def acquire_cleanup_lock(self, token: str) -> bool:
        """クリーンアップの DB レベルロックを取得する。

        Args:
            token: ロック取得者を識別するユニークなトークン。

        Returns:
            ロック取得に成功した場合 True。既にロックされている場合 False。
        """
        ...

    async def release_cleanup_lock(self, token: str) -> None:
        """クリーンアップの DB レベルロックを解放する。

        Args:
            token: ロック取得時に使用したトークン。
        """
        ...

    async def heartbeat_cleanup_lock(self, token: str) -> None:
        """クリーンアップロックの生存確認（ハートビート）を更新する。

        Args:
            token: ロック取得時に使用したトークン。
        """
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
        self._lock = asyncio.Lock()

    async def load_state(self) -> LifecycleState:
        """インメモリ状態を返す。"""
        async with self._lock:
            return self._state

    async def save_state(self, state: LifecycleState, token: str | None = None) -> bool:
        """インメモリ状態を更新する。"""
        async with self._lock:
            if token is not None and self._state.cleanup_lock_owner != token:
                return False
            self._state = state
            return True

    async def increment_save_count(self, threshold: int) -> bool:
        """インメモリでのインクリメントと閾値チェック。"""
        async with self._lock:
            state = self._state
            new_count = state.save_count + 1
            threshold_just_reached = new_count == threshold

            self._state = LifecycleState(
                save_count=new_count,
                last_cleanup_at=state.last_cleanup_at,
                last_cleanup_cursor_at=state.last_cleanup_cursor_at,
                last_cleanup_id=state.last_cleanup_id,
                cleanup_lock_owner=state.cleanup_lock_owner,
                cleanup_lock_touched_at=state.cleanup_lock_touched_at,
                updated_at=datetime.now(timezone.utc),
            )
            return threshold_just_reached

    async def acquire_cleanup_lock(self, token: str) -> bool:
        """クリーンアップロックを取得する（スタルロック検出付き）。"""
        async with self._lock:
            state = self._state
            # スタルロック検出: cleanup_lock_owner が設定されている場合は touched_at を確認
            if state.cleanup_lock_owner is not None:
                now = datetime.now(timezone.utc)
                if state.cleanup_lock_touched_at:
                    elapsed = (now - state.cleanup_lock_touched_at).total_seconds()
                    if elapsed < self._stale_lock_timeout_seconds:
                        return False
                    logger.warning(
                        "Stale cleanup lock detected (owner=%s, elapsed=%.1fs), force releasing.",
                        state.cleanup_lock_owner,
                        elapsed,
                    )

            self._state = LifecycleState(
                save_count=state.save_count,
                last_cleanup_at=state.last_cleanup_at,
                last_cleanup_cursor_at=state.last_cleanup_cursor_at,
                last_cleanup_id=state.last_cleanup_id,
                cleanup_lock_owner=token,
                cleanup_lock_touched_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            return True

    async def release_cleanup_lock(self, token: str) -> None:
        """クリーンアップロックを解放する。"""
        async with self._lock:
            state = self._state
            if state.cleanup_lock_owner == token:
                self._state = LifecycleState(
                    save_count=state.save_count,
                    last_cleanup_at=state.last_cleanup_at,
                    last_cleanup_cursor_at=state.last_cleanup_cursor_at,
                    last_cleanup_id=state.last_cleanup_id,
                    cleanup_lock_owner=None,
                    cleanup_lock_touched_at=None,
                    updated_at=datetime.now(timezone.utc),
                )

    async def heartbeat_cleanup_lock(self, token: str) -> None:
        """クリーンアップロックの生存確認を更新する。"""
        async with self._lock:
            state = self._state
            if state.cleanup_lock_owner == token:
                self._state = LifecycleState(
                    save_count=state.save_count,
                    last_cleanup_at=state.last_cleanup_at,
                    last_cleanup_cursor_at=state.last_cleanup_cursor_at,
                    last_cleanup_id=state.last_cleanup_id,
                    cleanup_lock_owner=token,
                    cleanup_lock_touched_at=datetime.now(timezone.utc),
                    updated_at=state.updated_at,
                )

    async def load_wal_state(self) -> WalState:
        """WAL 状態を返す。"""
        async with self._lock:
            return self._wal_state

    async def save_wal_state(self, state: WalState) -> None:
        """WAL 状態を更新する。"""
        async with self._lock:
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
                last_cleanup_cursor_at TIMESTAMP,
                last_cleanup_id TEXT,
                cleanup_lock_owner TEXT,
                cleanup_lock_touched_at TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # カラムが存在しない場合は追加 (移行用)
        cursor = await conn.execute("PRAGMA table_info('lifecycle_state')")
        columns = await cursor.fetchall()
        column_names = [col[1] for col in columns]
        if "last_cleanup_id" not in column_names:
            await conn.execute("ALTER TABLE lifecycle_state ADD COLUMN last_cleanup_id TEXT")
        if "last_cleanup_cursor_at" not in column_names:
            await conn.execute(
                "ALTER TABLE lifecycle_state ADD COLUMN last_cleanup_cursor_at TIMESTAMP"
            )
        if "cleanup_lock_owner" not in column_names:
            await conn.execute("ALTER TABLE lifecycle_state ADD COLUMN cleanup_lock_owner TEXT")
        if "cleanup_lock_touched_at" not in column_names:
            await conn.execute(
                "ALTER TABLE lifecycle_state ADD COLUMN cleanup_lock_touched_at TIMESTAMP"
            )

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
        """SQLite から状態を読み込む。"""
        import aiosqlite  # type: ignore[import-untyped]

        async with aiosqlite.connect(self._db_path) as conn:
            await self._ensure_tables(conn)
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT save_count, last_cleanup_at, last_cleanup_cursor_at, last_cleanup_id, "
                "cleanup_lock_owner, cleanup_lock_touched_at, updated_at "
                "FROM lifecycle_state WHERE id = 1"
            )
            row = await cursor.fetchone()

        if row is None:
            return LifecycleState()

        def _parse_ts(val: str | None) -> datetime | None:
            if val is None:
                return None
            return datetime.fromisoformat(val).replace(tzinfo=timezone.utc)

        return LifecycleState(
            save_count=row["save_count"],
            last_cleanup_at=_parse_ts(row["last_cleanup_at"]),
            last_cleanup_cursor_at=_parse_ts(row["last_cleanup_cursor_at"]),
            last_cleanup_id=row["last_cleanup_id"],
            cleanup_lock_owner=row["cleanup_lock_owner"],
            cleanup_lock_touched_at=_parse_ts(row["cleanup_lock_touched_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]).replace(tzinfo=timezone.utc),
        )

    async def save_state(self, state: LifecycleState, token: str | None = None) -> bool:
        """状態を SQLite に保存する。"""
        import aiosqlite  # type: ignore[import-untyped]

        def _fmt_ts(dt: datetime | None) -> str | None:
            return dt.isoformat() if dt is not None else None

        async with aiosqlite.connect(self._db_path) as conn:
            await self._ensure_tables(conn)
            query = """
                UPDATE lifecycle_state
                SET save_count = ?, last_cleanup_at = ?, last_cleanup_cursor_at = ?,
                    last_cleanup_id = ?, cleanup_lock_owner = ?,
                    cleanup_lock_touched_at = ?, updated_at = ?
                WHERE id = 1
            """
            params = [
                state.save_count,
                _fmt_ts(state.last_cleanup_at),
                _fmt_ts(state.last_cleanup_cursor_at),
                state.last_cleanup_id,
                state.cleanup_lock_owner,
                _fmt_ts(state.cleanup_lock_touched_at),
                state.updated_at.isoformat(),
            ]

            if token is not None:
                query += " AND cleanup_lock_owner = ?"
                params.append(token)

            cursor = await conn.execute(query, params)
            updated_count: int = cursor.rowcount
            await conn.commit()
            return updated_count > 0

    async def increment_save_count(self, threshold: int) -> bool:
        """SQLite でのアトミックなインクリメント。"""
        import aiosqlite  # type: ignore[import-untyped]

        async with aiosqlite.connect(self._db_path) as conn:
            await self._ensure_tables(conn)
            now = datetime.now(timezone.utc).isoformat()

            await conn.execute("BEGIN IMMEDIATE")
            try:
                # UPSERT (INSERT or UPDATE) + RETURNING でアトミックに実行
                async with conn.execute(
                    """
                    INSERT INTO lifecycle_state (id, save_count, updated_at)
                    VALUES (1, 1, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        save_count = lifecycle_state.save_count + 1,
                        updated_at = excluded.updated_at
                    RETURNING save_count
                    """,
                    (now,),
                ) as cursor:
                    row = await cursor.fetchone()
                    new_count = row[0] if row else 0
                await conn.commit()
            except Exception:
                await conn.execute("ROLLBACK")
                raise

        # 閾値を「ちょうど」超えた場合に True を返すことで、
        # 同時実行時の重複トリガーを防ぐ。
        return new_count == threshold

    async def acquire_cleanup_lock(self, token: str) -> bool:
        """クリーンアップロックを取得する（DB レベル）。

        Returns:
            ロック取得成功時は True、既にロック中の場合は False。
        """
        import aiosqlite  # type: ignore[import-untyped]

        async with aiosqlite.connect(self._db_path) as conn:
            await self._ensure_tables(conn)
            now = datetime.now(timezone.utc)

            # 1. 通常の取得試行（ロックされていない場合のみ取得）
            sql_update = (
                "UPDATE lifecycle_state "
                "SET cleanup_lock_owner = ?, cleanup_lock_touched_at = ?, updated_at = ? "
                "WHERE id = 1 AND cleanup_lock_owner IS NULL"
            )
            cursor = await conn.execute(
                sql_update,
                (token, now.isoformat(), now.isoformat()),
            )
            await conn.commit()
            if cursor.rowcount > 0:
                return True

            # 2. 取得失敗時、スタルロックのチェックと強制解放を試行
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT cleanup_lock_owner, cleanup_lock_touched_at "
                "FROM lifecycle_state WHERE id = 1"
            )
            row = await cursor.fetchone()
            if row is None or row["cleanup_lock_owner"] is None:
                return False  # 既に他者が解放したか、行が存在しない

            touched_at_str = row["cleanup_lock_touched_at"]
            if touched_at_str is None:
                # touched_at が NULL の場合は、古いスキーマからの移行直後などの
                # 可能性があるため updated_at を代替として使用することを検討するが、
                # ここではシンプルに強制解放対象とする
                elapsed = float(self._stale_lock_timeout_seconds + 1)
            else:
                touched_at = datetime.fromisoformat(touched_at_str).replace(tzinfo=timezone.utc)
                elapsed = (now - touched_at).total_seconds()

            if elapsed >= self._stale_lock_timeout_seconds:
                logger.warning(
                    "Stale lock detected (owner=%s, elapsed=%.1fs), forcing release.",
                    row["cleanup_lock_owner"],
                    elapsed,
                )
                # CAS (Compare-And-Swap) 方式で安全に上書き取得
                sql_takeover = (
                    "UPDATE lifecycle_state "
                    "SET cleanup_lock_owner = ?, cleanup_lock_touched_at = ?, updated_at = ? "
                    "WHERE id = 1 AND cleanup_lock_owner = ? "
                    "AND (cleanup_lock_touched_at = ? OR cleanup_lock_touched_at IS NULL)"
                )
                cursor = await conn.execute(
                    sql_takeover,
                    (
                        token,
                        now.isoformat(),
                        now.isoformat(),
                        row["cleanup_lock_owner"],
                        touched_at_str,
                    ),
                )
                await conn.commit()
                if cursor.rowcount > 0:
                    return True

        return False

    async def release_cleanup_lock(self, token: str) -> None:
        """クリーンアップロックを解放する。"""
        import aiosqlite  # type: ignore[import-untyped]

        async with aiosqlite.connect(self._db_path) as conn:
            await self._ensure_tables(conn)
            now = datetime.now(timezone.utc)
            sql_release = (
                "UPDATE lifecycle_state "
                "SET cleanup_lock_owner = NULL, cleanup_lock_touched_at = NULL, updated_at = ? "
                "WHERE id = 1 AND cleanup_lock_owner = ?"
            )
            await conn.execute(
                sql_release,
                (now.isoformat(), token),
            )
            await conn.commit()

    async def heartbeat_cleanup_lock(self, token: str) -> None:
        """クリーンアップロックの生存確認を更新する。"""
        import aiosqlite  # type: ignore[import-untyped]

        async with aiosqlite.connect(self._db_path) as conn:
            await self._ensure_tables(conn)
            now = datetime.now(timezone.utc)
            sql_hb = (
                "UPDATE lifecycle_state SET cleanup_lock_touched_at = ? "
                "WHERE id = 1 AND cleanup_lock_owner = ?"
            )
            await conn.execute(
                sql_hb,
                (now.isoformat(), token),
            )
            await conn.commit()

    async def load_wal_state(self) -> WalState:
        """WAL 状態を SQLite から読み込む。"""
        import aiosqlite  # type: ignore[import-untyped]

        async with aiosqlite.connect(self._db_path) as conn:
            await self._ensure_tables(conn)
            conn.row_factory = aiosqlite.Row
            sql_load = (
                "SELECT wal_failure_count, wal_last_failure_ts, "
                "wal_last_checkpoint_result, wal_last_observed_size_bytes, "
                "wal_consecutive_passive_failures, wal_failure_window "
                "FROM lifecycle_wal_state WHERE id = 1"
            )
            cursor = await conn.execute(sql_load)
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
        task_registry: バックグラウンドタスクレジストリ。
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
        task_registry: "TaskRegistry",
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
        self._task_registry = task_registry
        self._lock_path = lock_path
        self._wal_checkpoint_fn = wal_checkpoint_fn

        self._shutting_down = False

        if settings is None:
            from context_store.config import Settings

            settings = Settings.model_construct()

        self._settings = settings
        self._save_count_threshold = settings.cleanup_save_count_threshold
        self._cleanup_interval_hours = settings.cleanup_interval_hours
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

    async def start(self) -> None:
        """MCPサーバー起動時に呼び出す。時間ベースのクリーンアップチェックをスケジュール。

        初回起動時のみ前回クリーンアップからの経過時間を確認し、
        1日以上経過している場合はクリーンアップを非同期でトリガーする。
        """
        self._spawn_background_task(self._check_time_based_cleanup)

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
                if elapsed >= timedelta(hours=self._cleanup_interval_hours):
                    should_run = True

            if should_run:
                logger.info(
                    "Time-based cleanup triggered (last_cleanup_at=%s).", state.last_cleanup_at
                )
                await self.run_cleanup()
        except Exception:
            logger.exception("Time-based cleanup check failed.")

    def _spawn_background_task(self, factory: Callable[[], Coroutine[Any, Any, Any]]) -> None:
        """TaskRegistry を使用してバックグラウンドタスクを開始する。"""
        if self._shutting_down:
            return

        task = asyncio.create_task(factory())
        self._task_registry.register(task)

    async def _check_lock_integrity(self, token: str) -> None:
        """現在のロック所有者が自身であることを確認する。

        一致しない場合は LockLostError を送出する。
        """
        state = await self._state_store.load_state()
        if state.cleanup_lock_owner != token:
            raise LockLostError(
                f"Cleanup lock lost (expected {token}, got {state.cleanup_lock_owner})"
            )

    async def on_memory_saved(self) -> None:
        """記憶が保存されるたびに呼び出す。カウンターをインクリメント。

        アトミックにカウンターを更新し、閾値にちょうど達した場合のみクリーンアップを開始。
        これにより同時実行時の重複トリガーを防止する。
        """
        threshold_just_reached = await self._state_store.increment_save_count(
            self._save_count_threshold
        )

        if threshold_just_reached:
            logger.info("Save count threshold reached, triggering cleanup.")
            self._spawn_background_task(self.run_cleanup)

    async def run_cleanup(
        self,
        older_than_days: int | None = None,
        dry_run: bool = False,
    ) -> int:
        """クリーンアップを実行する(filelock + DB ロック排他制御付き)。

        filelock によるプロセス間排他制御と DB レベルのロックを組み合わせて
        同時実行を防ぐ。ロック取得失敗時はサイレントにスキップする。

        InMemoryLifecycleStateStore の場合は非永続的(共有されない)ため
        クリーンアップをスキップする。

        Args:
            older_than_days: 保持期間(日数)。None の場合はデフォルト設定を使用。
            dry_run: True の場合は更新せず対象件数のみをカウント。

        Returns:
            削除またはアーカイブされたアイテムの総数。
        """
        # バリデーション
        if older_than_days is not None:
            if not isinstance(older_than_days, int) or isinstance(older_than_days, bool):
                raise TypeError(
                    f"older_than_days must be an int, got {type(older_than_days).__name__}"
                )
            if older_than_days < 0:
                raise ValueError(f"older_than_days must be non-negative, got {older_than_days}")

        if self._settings.storage_backend != "sqlite":
            logger.debug(
                "Cleanup skipped: lifecycle cleanup is not supported for backend '%s'.",
                self._settings.storage_backend,
            )
            return 0

        # 全工程で共通のタイムスタンプを使用
        now = datetime.now(timezone.utc)

        if dry_run:
            # dry_run の場合はロックを取得せずに実行
            _, total_count = await self._run_cleanup_inner(
                older_than_days=older_than_days, dry_run=True, now=now
            )
            return total_count

        # OS レベルの排他ロック（timeout=0 = 非ブロッキング）
        file_lock = FileLock(self._lock_path, timeout=0)
        should_schedule_followup = False
        total_count = 0
        try:
            with file_lock.acquire():
                should_schedule_followup, total_count = await self._run_cleanup_inner(
                    older_than_days=older_than_days, dry_run=False, now=now
                )
        except Timeout:
            logger.debug("Cleanup skipped: another process holds the file lock.")
            return 0

        # ロック解放後に、必要に応じてフォローアップをスケジュール
        if should_schedule_followup:
            logger.info("Scheduling follow-up cleanup.")
            self._spawn_background_task(self.run_cleanup)

        return total_count

    async def _run_cleanup_inner(
        self,
        older_than_days: int | None = None,
        dry_run: bool = False,
        now: datetime | None = None,
    ) -> tuple[bool, int]:
        """クリーンアップ本体（DB ロック取得後に実行）。

        Args:
            older_than_days: 保持期間（日数）。
            dry_run: True の場合は更新せず対象件数のみをカウント。
            now: 基準時刻。None の場合は現在時刻を使用。

        Returns:
            (should_schedule_followup, total_items_count)
            should_schedule_followup: 未処理の保存が残っており、
                次回のクリーンアップを即座にスケジュールすべきか。
            total_items_count: 削除またはアーカイブされたアイテムの総数。
        """
        if now is None:
            now = datetime.now(timezone.utc)

        # DB レベルのロック取得
        token = str(uuid.uuid4())
        if not dry_run:
            acquired = await self._state_store.acquire_cleanup_lock(token)
            if not acquired:
                logger.debug("Cleanup skipped: DB lock already acquired.")
                return False, 0
        else:
            # dry_run の場合はロックをスキップ
            pass

        should_schedule_followup = False
        total_count = 0
        simulated_archived_ids: set[str] = set()

        try:
            state = await self._state_store.load_state()
            # クリーンアップ開始時のカウントをキャプチャ。
            # concurrent saves があった場合に、その分まで差し引かないようにする。
            cleanup_start_save_count = state.save_count
            if not dry_run:
                logger.info("Starting cleanup (save_count=%d).", cleanup_start_save_count)
            else:
                logger.info("Starting cleanup preview.")

            async def heartbeat_fn() -> None:
                if not dry_run:
                    await self._state_store.heartbeat_cleanup_lock(token)
                    await self._check_lock_integrity(token)

            # 1. Decay Scorer (各ジョブは暗黙的にスコアを使用)
            # 2. Archiver
            archiver_result = await self._archiver.run(
                heartbeat_fn=heartbeat_fn,
                dry_run=dry_run,
                simulated_archived_ids=simulated_archived_ids if dry_run else None,
                now=now,
            )
            total_count += archiver_result.archived_count
            logger.info(
                "Archiver: archived=%d, checked=%d",
                archiver_result.archived_count,
                archiver_result.checked_count,
            )

            # 3. Consolidator
            # カーソル (timestamp + ID) を渡して、安定したページングを実現。
            consolidator_result = await self._consolidator.run(
                last_cleanup_at=state.last_cleanup_cursor_at,
                last_cleanup_id=state.last_cleanup_id,
                batch_size=CONSOLIDATION_BATCH_SIZE,
                heartbeat_fn=heartbeat_fn,
                dry_run=dry_run,
                simulated_archived_ids=simulated_archived_ids if dry_run else None,
                now=now,
            )
            total_count += consolidator_result.consolidated_count
            logger.info(
                "Consolidator: consolidated=%d, checked=%d",
                consolidator_result.consolidated_count,
                consolidator_result.checked_count,
            )

            # 4. Purger
            purger_result = await self._purger.run(
                heartbeat_fn=heartbeat_fn,
                retention_days=older_than_days,
                dry_run=dry_run,
                simulated_archived_ids=simulated_archived_ids if dry_run else None,
                now=now,
            )
            total_count += purger_result.purged_count
            logger.info(
                "Purger: purged=%d, checked=%d",
                purger_result.purged_count,
                purger_result.checked_count,
            )

            if dry_run:
                return False, total_count

            # 5. Stats Collector
            await self._collect_stats()

            # 6. WAL チェックポイント（SQLite のみ）
            if self._wal_checkpoint_fn is not None:
                await self._run_wal_checkpoint()
            await self._state_store.heartbeat_cleanup_lock(token)
            await self._check_lock_integrity(token)

            # 状態を更新（カウンターリセット + last_cleanup_at 更新）
            # ページングカーソル (last_processed_at/id) を保存
            # last_cleanup_at は「全ジョブ成功時」に現在時刻で更新
            # now は開始時の基準時刻を使用（ただし updated_at などには最新時刻を使う場合もある）
            current_state = await self._state_store.load_state()

            next_cursor_at = (
                consolidator_result.last_processed_at or current_state.last_cleanup_cursor_at
            )
            next_cursor_id = consolidator_result.last_processed_id

            # 開始時のカウント(今回処理対象とした分)だけ引く
            remaining_count = max(0, current_state.save_count - cleanup_start_save_count)
            new_state = LifecycleState(
                save_count=remaining_count,
                last_cleanup_at=now,  # 全工程成功につき更新（基準時刻 now を使用）
                last_cleanup_cursor_at=next_cursor_at,
                last_cleanup_id=next_cursor_id,
                cleanup_lock_owner=token,  # finally で release_cleanup_lock を呼ぶまで保持
                cleanup_lock_touched_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            saved = await self._state_store.save_state(new_state, token=token)
            if not saved:
                raise LockLostError("Final state save failed: lock lost")

            # 未処理の保存がまだ残っているか、Consolidator に次ページがある場合は、
            # フォローアップを要求
            if remaining_count >= self._save_count_threshold or consolidator_result.has_more:
                logger.info(
                    "Follow-up cleanup requested (remaining=%d, has_more=%s).",
                    remaining_count,
                    consolidator_result.has_more,
                )
                should_schedule_followup = True

        except LockLostError as exc:
            logger.warning("Cleanup aborted: %s", exc)
        except Exception:
            logger.exception("Cleanup failed.")
            # カウンターを閾値未満にリセットして、無限ループを防ぎつつ次のサイクルを待つ
            try:
                state = await self._state_store.load_state()
                await self._state_store.save_state(
                    LifecycleState(
                        save_count=min(state.save_count, self._save_count_threshold - 1),
                        last_cleanup_at=state.last_cleanup_at,
                        last_cleanup_cursor_at=state.last_cleanup_cursor_at,
                        last_cleanup_id=state.last_cleanup_id,
                        cleanup_lock_owner=token,  # finally で release_cleanup_lock を呼ぶまで保持
                        cleanup_lock_touched_at=state.cleanup_lock_touched_at,
                        updated_at=datetime.now(timezone.utc),
                    ),
                    token=token,
                )
            except Exception:
                logger.exception("Failed to reset save_count after cleanup failure.")
            raise
        finally:
            if not dry_run:
                await self._state_store.release_cleanup_lock(token)

        return should_schedule_followup, total_count

    async def _collect_stats(self) -> None:
        """統計情報をログに記録する（将来的に DB 保存へ拡張可能）。"""
        try:
            # アクティブ記憶数
            active_count = await self._storage.count_by_filter(MemoryFilters(archived=None))
            # アーカイブ済み記憶数
            archived_count = await self._storage.count_by_filter(MemoryFilters(archived=True))
            logger.info(
                "Stats: active_memories=%d, archived_memories=%d",
                active_count,
                archived_count,
            )
        except Exception:
            logger.exception("Stats collection failed.")

    async def _run_wal_checkpoint(self) -> None:
        """WAL チェックポイントを実行し、必要に応じて TRUNCATE を試みる。"""
        if self._wal_checkpoint_fn is None:
            raise RuntimeError("WAL checkpoint function is not configured")

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
            if self._wal_checkpoint_fn is None:
                raise RuntimeError(
                    "WAL checkpoint function is not configured in _handle_wal_passive_failure."
                )
            try:
                result = await self._wal_checkpoint_fn(self._wal_checkpoint_mode_truncate)
                busy = result.get(_WAL_RESULT_KEY_BUSY, 0) if result else 0
                if busy == 0:
                    wal_state.wal_last_checkpoint_result = "TRUNCATE_OK"
                    wal_state.wal_consecutive_passive_failures = 0
                    logger.info("WAL TRUNCATE checkpoint succeeded.")
                else:
                    wal_state.wal_last_checkpoint_result = "TRUNCATE_BUSY"
                    logger.warning("WAL TRUNCATE checkpoint busy.")
            except Exception as exc:
                logger.error("WAL TRUNCATE checkpoint failed: %s", exc)
                wal_state.wal_last_checkpoint_result = "TRUNCATE_FAIL"
        else:
            wal_state.wal_last_checkpoint_result = "PASSIVE_FAILED"

        return wal_state

    async def graceful_shutdown(self) -> None:
        """進行中のタスクをタイムアウト付きで完了待機する。タイムアウト時は強制キャンセルする。"""
        self._shutting_down = True
        # まずは完了を待機
        await self._task_registry.wait_all(timeout=5.0)
        # それでも残っている場合はキャンセル
        if len(self._task_registry) > 0:
            await self._task_registry.cancel_all(timeout=1.0)
