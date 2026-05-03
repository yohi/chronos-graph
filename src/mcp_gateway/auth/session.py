"""Internal session record + in-memory registry.

The agent never sees this record; it only knows its session_id.
TTL / idle-timeout failures all surface as SessionError so the HTTP layer can
return a uniform 404 + close the SSE stream.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from mcp_gateway.errors import SessionError


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class SessionRecord:
    session_id: str
    agent_id: str
    intent: str
    caps: frozenset[str]
    output_filter_profile: str
    issued_at: datetime
    expires_at: datetime


class SessionRegistry(Protocol):
    def create(
        self,
        *,
        agent_id: str,
        intent: str,
        caps: frozenset[str],
        output_filter_profile: str,
    ) -> SessionRecord: ...

    def lookup(self, session_id: str) -> SessionRecord: ...

    def touch(self, session_id: str) -> None: ...

    def purge(self) -> None: ...

    def remove(self, session_id: str) -> None: ...


class InMemorySessionRegistry:
    """Process-local registry. Replaceable later with a Redis-backed implementation."""

    def __init__(self, ttl_seconds: int, idle_timeout_seconds: int) -> None:
        if ttl_seconds <= 0:
            raise ValueError(f"ttl_seconds must be positive, got {ttl_seconds}")
        if idle_timeout_seconds <= 0:
            raise ValueError(f"idle_timeout_seconds must be positive, got {idle_timeout_seconds}")

        self._ttl = timedelta(seconds=ttl_seconds)
        self._idle = timedelta(seconds=idle_timeout_seconds)
        self._records: dict[str, SessionRecord] = {}
        self._last_active: dict[str, datetime] = {}
        self._lock = threading.Lock()

    def create(
        self,
        *,
        agent_id: str,
        intent: str,
        caps: frozenset[str],
        output_filter_profile: str,
    ) -> SessionRecord:
        with self._lock:
            now = _utcnow()
            sid = uuid.uuid4().hex
            rec = SessionRecord(
                session_id=sid,
                agent_id=agent_id,
                intent=intent,
                caps=frozenset(caps),
                output_filter_profile=output_filter_profile,
                issued_at=now,
                expires_at=now + self._ttl,
            )
            self._records[sid] = rec
            self._last_active[sid] = now
        return rec

    def lookup(self, session_id: str) -> SessionRecord:
        with self._lock:
            now = _utcnow()
            rec = self._records.get(session_id)
            if rec is None:
                raise SessionError(f"unknown session_id {session_id!r}")

            if now >= rec.expires_at:
                self._records.pop(session_id, None)
                self._last_active.pop(session_id, None)
                raise SessionError("session expired (ttl)")

            last = self._last_active.get(session_id, rec.issued_at)
            if now - last >= self._idle:
                self._records.pop(session_id, None)
                self._last_active.pop(session_id, None)
                raise SessionError("session expired (idle)")

            # Update idle timer on successful lookup
            self._last_active[session_id] = now
            return rec

    def touch(self, session_id: str) -> None:
        with self._lock:
            now = _utcnow()
            rec = self._records.get(session_id)
            if rec is None:
                return

            # Check TTL
            if now >= rec.expires_at:
                self._records.pop(session_id, None)
                self._last_active.pop(session_id, None)
                return

            # Check Idle
            last = self._last_active.get(session_id, rec.issued_at)
            if now - last >= self._idle:
                self._records.pop(session_id, None)
                self._last_active.pop(session_id, None)
                return

            self._last_active[session_id] = now

    def purge(self) -> None:
        """Remove all expired or idle sessions from the registry."""
        with self._lock:
            now = _utcnow()
            expired_ids = []
            for sid, rec in self._records.items():
                if now >= rec.expires_at:
                    expired_ids.append(sid)
                    continue
                last = self._last_active.get(sid, rec.issued_at)
                if now - last >= self._idle:
                    expired_ids.append(sid)

            for sid in expired_ids:
                self._records.pop(sid, None)
                self._last_active.pop(sid, None)

    def remove(self, session_id: str) -> None:
        with self._lock:
            self._records.pop(session_id, None)
            self._last_active.pop(session_id, None)
