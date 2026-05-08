"""Internal session record + in-memory registry.

The agent never sees this record; it only knows its session_id.
TTL / idle-timeout failures all surface as SessionError so the HTTP layer can
return a uniform 404 + close the SSE stream.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Iterable, Protocol

from mcp_gateway.errors import SessionError

if TYPE_CHECKING:
    from mcp_gateway.policy.models import ToolGuardrail

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class SessionRecord:
    session_id: str
    agent_id: str
    intent: str
    caps: frozenset[str]
    guardrails: MappingProxyType[str, ToolGuardrail]
    output_filter_profile: str
    issued_at: datetime
    expires_at: datetime


class SessionRegistry(Protocol):
    def create(
        self,
        *,
        agent_id: str,
        intent: str,
        caps: Iterable[str],
        guardrails: dict[str, ToolGuardrail] | MappingProxyType[str, ToolGuardrail],
        output_filter_profile: str,
    ) -> SessionRecord: ...

    def lookup(self, session_id: str) -> SessionRecord: ...

    def touch(self, session_id: str) -> None: ...

    def purge(self) -> None: ...

    def remove(self, session_id: str) -> None: ...


class InMemorySessionRegistry:
    """Process-local registry. Replaceable later with a Redis-backed implementation."""

    def __init__(
        self,
        ttl_seconds: int,
        idle_timeout_seconds: int,
        *,
        on_session_evicted: Callable[[str], Coroutine[Any, Any, None]] | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError(f"ttl_seconds must be positive, got {ttl_seconds}")
        if idle_timeout_seconds <= 0:
            raise ValueError(f"idle_timeout_seconds must be positive, got {idle_timeout_seconds}")

        self._ttl = timedelta(seconds=ttl_seconds)
        self._idle = timedelta(seconds=idle_timeout_seconds)
        self._records: dict[str, SessionRecord] = {}
        self._last_active: dict[str, datetime] = {}
        self._lock = threading.Lock()
        self._on_evicted = on_session_evicted

    def _fire_evicted(self, session_id: str) -> None:
        if self._on_evicted is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning(
                "session_eviction_hook_skipped: no running event loop for session %s",
                session_id,
            )
            return
        coro = self._on_evicted(session_id)
        task: asyncio.Task[None] = loop.create_task(coro, name=f"session_evict_{session_id[:8]}")
        task.add_done_callback(self._log_evict_exception)

    @staticmethod
    def _log_evict_exception(task: asyncio.Task[None]) -> None:
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return
        if exc is not None:
            logger.error("session_eviction_callback_failed: %s", exc, exc_info=exc)

    def create(
        self,
        *,
        agent_id: str,
        intent: str,
        caps: Iterable[str],
        guardrails: dict[str, ToolGuardrail] | MappingProxyType[str, ToolGuardrail],
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
                guardrails=MappingProxyType(deepcopy(dict(guardrails))),
                output_filter_profile=output_filter_profile,
                issued_at=now,
                expires_at=now + self._ttl,
            )
            self._records[sid] = rec
            self._last_active[sid] = now
        return rec

    def lookup(self, session_id: str) -> SessionRecord:
        evicted: str | None = None
        try:
            with self._lock:
                now = _utcnow()
                rec = self._records.get(session_id)
                if rec is None:
                    raise SessionError(f"unknown session_id {session_id!r}")

                if now >= rec.expires_at:
                    self._records.pop(session_id, None)
                    self._last_active.pop(session_id, None)
                    evicted = session_id
                    raise SessionError("session expired (ttl)")

                last = self._last_active.get(session_id, rec.issued_at)
                if now - last >= self._idle:
                    self._records.pop(session_id, None)
                    self._last_active.pop(session_id, None)
                    evicted = session_id
                    raise SessionError("session expired (idle)")

                self._last_active[session_id] = now
                return rec
        finally:
            if evicted is not None:
                self._fire_evicted(evicted)

    def touch(self, session_id: str) -> None:
        evicted: str | None = None
        with self._lock:
            now = _utcnow()
            rec = self._records.get(session_id)
            if rec is None:
                return

            if now >= rec.expires_at:
                self._records.pop(session_id, None)
                self._last_active.pop(session_id, None)
                evicted = session_id
            else:
                last = self._last_active.get(session_id, rec.issued_at)
                if now - last >= self._idle:
                    self._records.pop(session_id, None)
                    self._last_active.pop(session_id, None)
                    evicted = session_id
                else:
                    self._last_active[session_id] = now
        if evicted is not None:
            self._fire_evicted(evicted)

    def purge(self) -> None:
        """Remove all expired or idle sessions from the registry."""
        evicted_ids: list[str] = []
        with self._lock:
            now = _utcnow()
            for sid, rec in self._records.items():
                if now >= rec.expires_at:
                    evicted_ids.append(sid)
                    continue
                last = self._last_active.get(sid, rec.issued_at)
                if now - last >= self._idle:
                    evicted_ids.append(sid)

            for sid in evicted_ids:
                self._records.pop(sid, None)
                self._last_active.pop(sid, None)
        for sid in evicted_ids:
            self._fire_evicted(sid)

    def remove(self, session_id: str) -> None:
        existed = False
        with self._lock:
            existed = session_id in self._records
            self._records.pop(session_id, None)
            self._last_active.pop(session_id, None)
        if existed:
            self._fire_evicted(session_id)
