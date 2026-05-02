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

    def remove(self, session_id: str) -> None: ...


class InMemorySessionRegistry:
    """Process-local registry. Replaceable later with a Redis-backed implementation."""

    def __init__(self, ttl_seconds: int, idle_timeout_seconds: int) -> None:
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
        now = _utcnow()
        sid = uuid.uuid4().hex
        rec = SessionRecord(
            session_id=sid,
            agent_id=agent_id,
            intent=intent,
            caps=caps,
            output_filter_profile=output_filter_profile,
            issued_at=now,
            expires_at=now + self._ttl,
        )
        with self._lock:
            self._records[sid] = rec
            self._last_active[sid] = now
        return rec

    def lookup(self, session_id: str) -> SessionRecord:
        now = _utcnow()
        with self._lock:
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
        return rec

    def touch(self, session_id: str) -> None:
        with self._lock:
            if session_id in self._records:
                self._last_active[session_id] = _utcnow()

    def remove(self, session_id: str) -> None:
        with self._lock:
            self._records.pop(session_id, None)
            self._last_active.pop(session_id, None)
