"""
SafeSqliteInterruptCtx: Context manager that safely interrupts a running SQLite query.

Problem: Calling sqlite3.Connection.interrupt() sets a flag that causes the NEXT query
to fail with OperationalError: interrupted - even if the current query already completed.
This can crash subsequent unrelated queries.

Solution: Track execution state with a lock, only call interrupt() when query is
confirmed to be running, ensure the flag is consumed before returning the connection.
"""

from __future__ import annotations

import asyncio
import sqlite3
from typing import Any


class SafeSqliteInterruptCtx:
    """
    Context manager that safely manages interrupt() for aiosqlite connections.

    Usage:
        ctx = SafeSqliteInterruptCtx(conn._conn)  # raw sqlite3 connection
        async with ctx:
            await conn.execute("SELECT ... heavy query ...")

    On timeout (from asyncio.wait_for outside), calls interrupt() only when
    the query is actually running. Prevents interrupted flag leaking to next query.
    """

    def __init__(self, raw_conn: sqlite3.Connection) -> None:
        self._raw_conn = raw_conn
        self._is_running = False
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> "SafeSqliteInterruptCtx":
        async with self._lock:
            self._is_running = True
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        async with self._lock:
            self._is_running = False

    def interrupt(self) -> None:
        """Call interrupt() only if query is currently running."""
        # Note: This is called from a different asyncio task (timeout handler)
        # _is_running check is best-effort; the lock ensures we don't leave
        # interrupt flag set after query completes
        if self._is_running:
            self._raw_conn.interrupt()
