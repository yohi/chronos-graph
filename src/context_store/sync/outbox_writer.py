"""OutboxWriter: Storage TX 内で graph_sync_outbox に INSERT する。"""

from __future__ import annotations

import json
import uuid
from typing import Any, Protocol, get_args

from context_store.storage.postgres_helpers import _json_default
from context_store.sync.models import EventType

_ALLOWED_EVENT_TYPES = frozenset(get_args(EventType))


def _validate_event_type(event_type: str) -> None:
    if event_type not in _ALLOWED_EVENT_TYPES:
        raise ValueError(
            f"Invalid event_type={event_type!r}. Allowed: {sorted(_ALLOWED_EVENT_TYPES)}"
        )


class OutboxWriter(Protocol):
    """Outbox 書き込みプロトコル。

    各 StorageAdapter のトランザクション内で呼び出される。
    Postgres は asyncpg.Connection、SQLite は aiosqlite.Connection を期待する。

    Note:
        書き込み時の重複チェック (dedup-at-insert) は意図的に行わない。
        同一 memory_id への複数 SYNC_MEMORY は許容され、Worker 側の
        「最新状態フェッチ + MERGE」で収束する（dedup-at-convergence 方針）。
    """

    async def enqueue_sync(
        self,
        conn: Any,
        memory_id: str,
        event_type: EventType,
        payload: dict[str, Any] | None = None,
    ) -> None: ...


class PostgresOutboxWriter:
    """asyncpg.Connection の TX 内で INSERT する。

    Note:
        Postgres 側はマイグレーションで id カラムに `DEFAULT gen_random_uuid()` が
        設定されているため、INSERT クエリから id を省略して自動生成に依存しています。
    """

    _SQL = (
        "INSERT INTO graph_sync_outbox (event_type, memory_id, payload) "
        "VALUES ($1, $2::uuid, $3::jsonb)"
    )

    async def enqueue_sync(
        self,
        conn: Any,
        memory_id: str,
        event_type: EventType,
        payload: dict[str, Any] | None = None,
    ) -> None:
        _validate_event_type(event_type)
        await conn.execute(
            self._SQL,
            event_type,
            memory_id,
            json.dumps(payload or {}, default=_json_default),
        )


class SqliteOutboxWriter:
    """aiosqlite.Connection の TX 内で INSERT する。

    Note:
        SQLite 側は標準で組み込みの UUID 自動生成デフォルト値を持たないため、
        アプリケーション層で明示的に uuid.uuid4() を生成して挿入しています。
    """

    _SQL = "INSERT INTO graph_sync_outbox (id, event_type, memory_id, payload) VALUES (?, ?, ?, ?)"

    async def enqueue_sync(
        self,
        conn: Any,
        memory_id: str,
        event_type: EventType,
        payload: dict[str, Any] | None = None,
    ) -> None:
        _validate_event_type(event_type)
        await conn.execute(
            self._SQL,
            (
                str(uuid.uuid4()),
                event_type,
                memory_id,
                json.dumps(payload or {}, default=_json_default),
            ),
        )
