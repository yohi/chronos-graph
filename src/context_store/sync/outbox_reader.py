"""OutboxReader: graph_sync_outbox の読み取り/状態遷移操作。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

import aiosqlite

from context_store.sync.models import EventStatus, OutboxEvent


class OutboxReader(Protocol):
    async def fetch_pending(self, limit: int) -> list[OutboxEvent]: ...
    async def delete_completed(self, event_ids: list[str]) -> None: ...
    async def mark_failed(self, event_id: str, error_message: str) -> None: ...
    async def reset_to_pending(
        self, event_id: str, retry_count: int, next_retry_at: datetime, error_message: str
    ) -> None: ...
    async def fetch_all_actionable(self) -> list[OutboxEvent]: ...
    async def reset_stuck_processing(
        self, threshold_seconds: int = 300, max_retries: int = 10
    ) -> int: ...


class SqliteOutboxReader:
    """SQLite バックエンド向け OutboxReader 実装。"""

    def __init__(self, *, db_path: str) -> None:
        self._db_path = db_path

    async def fetch_pending(self, limit: int) -> list[OutboxEvent]:
        async with aiosqlite.connect(self._db_path) as conn:
            conn.row_factory = aiosqlite.Row
            await conn.execute("BEGIN IMMEDIATE")
            try:
                rows = await (
                    await conn.execute(
                        "SELECT id, event_type, memory_id, payload, retry_count, "
                        "next_retry_at, created_at, updated_at, error_message "
                        "FROM graph_sync_outbox "
                        "WHERE status = 'PENDING' "
                        "AND next_retry_at <= strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                        "ORDER BY next_retry_at ASC LIMIT ?",
                        (limit,),
                    )
                ).fetchall()
                ids = [r["id"] for r in rows]
                for eid in ids:
                    await conn.execute(
                        "UPDATE graph_sync_outbox "
                        "SET status = 'PROCESSING', "
                        "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                        "WHERE id = ? AND status = 'PENDING'",
                        (eid,),
                    )
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise
        return [_row_to_event(r, status="PROCESSING") for r in rows]

    async def delete_completed(self, event_ids: list[str]) -> None:
        if not event_ids:
            return
        placeholders = ",".join("?" for _ in event_ids)
        sql = f"DELETE FROM graph_sync_outbox WHERE id IN ({placeholders})"  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query # noqa: S608, E501
        async with aiosqlite.connect(self._db_path) as conn:
            await conn.execute(sql, event_ids)
            await conn.commit()

    async def mark_failed(self, event_id: str, error_message: str) -> None:
        async with aiosqlite.connect(self._db_path) as conn:
            await conn.execute(
                "UPDATE graph_sync_outbox "
                "SET status = 'FAILED', error_message = ?, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE id = ?",
                (error_message, event_id),
            )
            await conn.commit()

    async def reset_to_pending(
        self,
        event_id: str,
        retry_count: int,
        next_retry_at: datetime,
        error_message: str,
    ) -> None:
        async with aiosqlite.connect(self._db_path) as conn:
            await conn.execute(
                "UPDATE graph_sync_outbox SET status = 'PENDING', retry_count = ?, "
                "next_retry_at = ?, error_message = ?, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE id = ?",
                (retry_count, next_retry_at.isoformat(), error_message, event_id),
            )
            await conn.commit()

    async def fetch_all_actionable(self) -> list[OutboxEvent]:
        async with aiosqlite.connect(self._db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(
                "SELECT id, event_type, memory_id, payload, status, retry_count, "
                "next_retry_at, created_at, updated_at, error_message "
                "FROM graph_sync_outbox "
                "WHERE status IN ('PENDING', 'PROCESSING', 'FAILED')"
            ) as cur:
                rows = await cur.fetchall()
        return [_row_to_event(r, status=r["status"]) for r in rows]

    async def reset_stuck_processing(
        self, threshold_seconds: int = 300, max_retries: int = 10
    ) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=threshold_seconds)).isoformat()
        async with aiosqlite.connect(self._db_path) as conn:
            conn.row_factory = aiosqlite.Row
            await conn.execute("BEGIN IMMEDIATE")
            try:
                rows = await (
                    await conn.execute(
                        "SELECT id, retry_count FROM graph_sync_outbox "
                        "WHERE status = 'PROCESSING' AND updated_at <= ?",
                        (cutoff,),
                    )
                ).fetchall()
                count = 0
                for r in rows:
                    new_retry = r["retry_count"] + 1
                    if new_retry > max_retries:
                        await conn.execute(
                            "UPDATE graph_sync_outbox SET status = 'FAILED', "
                            "error_message = 'Recovered from stuck PROCESSING (max retries)', "
                            "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
                            (r["id"],),
                        )
                    else:
                        await conn.execute(
                            "UPDATE graph_sync_outbox SET status = 'PENDING', "
                            "retry_count = ?, "
                            "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                            "WHERE id = ?",
                            (new_retry, r["id"]),
                        )
                    count += 1
                await conn.commit()
                return count
            except Exception:
                await conn.rollback()
                raise


class PostgresOutboxReader:
    """PostgreSQL バックエンド向け OutboxReader 実装。"""

    _FETCH_SQL = """
    UPDATE graph_sync_outbox
    SET status = 'PROCESSING', updated_at = NOW()
    WHERE id IN (
        SELECT id FROM graph_sync_outbox
        WHERE status = 'PENDING' AND next_retry_at <= NOW()
        ORDER BY next_retry_at ASC
        LIMIT $1
        FOR UPDATE SKIP LOCKED
    )
    RETURNING id, event_type, memory_id::text AS memory_id, payload, retry_count,
              next_retry_at, created_at, updated_at, error_message
    """

    def __init__(self, *, pool: Any) -> None:
        self._pool = pool

    async def fetch_pending(self, limit: int) -> list[OutboxEvent]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(self._FETCH_SQL, limit)
        return [
            OutboxEvent(
                id=str(r["id"]),
                event_type=r["event_type"],
                memory_id=r["memory_id"],
                payload=dict(r["payload"]) if r["payload"] else {},
                status="PROCESSING",
                retry_count=r["retry_count"],
                next_retry_at=r["next_retry_at"],
                error_message=r["error_message"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
            for r in rows
        ]

    async def delete_completed(self, event_ids: list[str]) -> None:
        if not event_ids:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM graph_sync_outbox WHERE id = ANY($1::uuid[])", event_ids
            )

    async def mark_failed(self, event_id: str, error_message: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE graph_sync_outbox SET status='FAILED', error_message=$2, "
                "updated_at=NOW() WHERE id=$1::uuid",
                event_id,
                error_message,
            )

    async def reset_to_pending(
        self,
        event_id: str,
        retry_count: int,
        next_retry_at: datetime,
        error_message: str,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE graph_sync_outbox SET status='PENDING', retry_count=$2, "
                "next_retry_at=$3, error_message=$4, updated_at=NOW() WHERE id=$1::uuid",
                event_id,
                retry_count,
                next_retry_at,
                error_message,
            )

    async def fetch_all_actionable(self) -> list[OutboxEvent]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, event_type, memory_id::text AS memory_id, payload, status, "
                "retry_count, next_retry_at, created_at, updated_at, error_message "
                "FROM graph_sync_outbox WHERE status IN ('PENDING','PROCESSING','FAILED')"
            )
        return [
            OutboxEvent(
                id=str(r["id"]),
                event_type=r["event_type"],
                memory_id=r["memory_id"],
                payload=dict(r["payload"]) if r["payload"] else {},
                status=r["status"],
                retry_count=r["retry_count"],
                next_retry_at=r["next_retry_at"],
                error_message=r["error_message"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
            for r in rows
        ]

    async def reset_stuck_processing(
        self, threshold_seconds: int = 300, max_retries: int = 10
    ) -> int:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                failed_rows = await conn.fetch(
                    "UPDATE graph_sync_outbox "
                    "SET status='FAILED', "
                    "error_message='Recovered from stuck PROCESSING (max retries)', "
                    "updated_at=NOW() "
                    "WHERE status='PROCESSING' "
                    "AND updated_at < NOW() - ($1 || ' seconds')::interval "
                    "AND retry_count + 1 > $2 "
                    "RETURNING id",
                    str(threshold_seconds),
                    max_retries,
                )
                pending_rows = await conn.fetch(
                    "UPDATE graph_sync_outbox "
                    "SET status='PENDING', retry_count = retry_count + 1, updated_at=NOW() "
                    "WHERE status='PROCESSING' "
                    "AND updated_at < NOW() - ($1 || ' seconds')::interval "
                    "RETURNING id",
                    str(threshold_seconds),
                )

        return len(failed_rows) + len(pending_rows)


class SupabaseOutboxReader:
    """Supabase バックエンド向け OutboxReader 実装。"""

    def __init__(self, *, client: Any) -> None:
        self._client = client

    async def fetch_pending(self, limit: int) -> list[OutboxEvent]:
        result = await self._client.rpc("fetch_pending_outbox", {"p_limit": limit}).execute()
        rows = result.data or []
        return [_supabase_row_to_event(r) for r in rows]

    async def delete_completed(self, event_ids: list[str]) -> None:
        if not event_ids:
            return
        await self._client.table("graph_sync_outbox").delete().in_("id", event_ids).execute()

    async def mark_failed(self, event_id: str, error_message: str) -> None:
        await (
            self._client.table("graph_sync_outbox")
            .update({"status": "FAILED", "error_message": error_message})
            .eq("id", event_id)
            .execute()
        )

    async def reset_to_pending(
        self,
        event_id: str,
        retry_count: int,
        next_retry_at: datetime,
        error_message: str,
    ) -> None:
        await (
            self._client.table("graph_sync_outbox")
            .update(
                {
                    "status": "PENDING",
                    "retry_count": retry_count,
                    "next_retry_at": next_retry_at.isoformat(),
                    "error_message": error_message,
                }
            )
            .eq("id", event_id)
            .execute()
        )

    async def fetch_all_actionable(self) -> list[OutboxEvent]:
        result = await (
            self._client.table("graph_sync_outbox")
            .select(
                "id,event_type,memory_id,payload,status,retry_count,"
                "next_retry_at,created_at,updated_at,error_message"
            )
            .in_("status", ["PENDING", "PROCESSING", "FAILED"])
            .execute()
        )
        rows = result.data or []
        return [_supabase_row_to_event(r) for r in rows]

    async def reset_stuck_processing(
        self, threshold_seconds: int = 300, max_retries: int = 10
    ) -> int:
        result = await self._client.rpc(
            "reset_stuck_processing_outbox",
            {
                "p_threshold_seconds": threshold_seconds,
                "p_max_retries": max_retries,
            },
        ).execute()
        return int(result.data) if result.data is not None else 0


def _row_to_event(row: Any, *, status: EventStatus) -> OutboxEvent:
    return OutboxEvent(
        id=row["id"],
        event_type=row["event_type"],
        memory_id=row["memory_id"],
        payload=json.loads(row["payload"]) if row["payload"] else {},
        status=status,
        retry_count=row["retry_count"],
        next_retry_at=_parse_dt(row["next_retry_at"]),
        error_message=row["error_message"],
        created_at=_parse_dt(row["created_at"]),
        updated_at=_parse_dt(row["updated_at"]),
    )


def _supabase_row_to_event(row: dict[str, Any]) -> OutboxEvent:
    payload_raw = row.get("payload") or {}
    return OutboxEvent(
        id=row["id"],
        event_type=row["event_type"],
        memory_id=row["memory_id"],
        payload=payload_raw if isinstance(payload_raw, dict) else json.loads(payload_raw),
        status=row["status"],
        retry_count=row["retry_count"],
        next_retry_at=_parse_dt(row.get("next_retry_at")),
        error_message=row.get("error_message"),
        created_at=_parse_dt(row.get("created_at")),
        updated_at=_parse_dt(row.get("updated_at")),
    )


def _parse_dt(s: str | None) -> datetime:
    if not s:
        raise ValueError("Datetime string cannot be None or empty")
    return datetime.fromisoformat(s.replace("Z", "+00:00"))
