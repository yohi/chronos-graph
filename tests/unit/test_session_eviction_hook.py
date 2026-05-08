"""Unit tests for InMemorySessionRegistry on_session_evicted hook."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from datetime import timedelta
from types import MappingProxyType

import pytest

from mcp_gateway.auth.session import InMemorySessionRegistry
from mcp_gateway.errors import SessionError


def _make_session(reg: InMemorySessionRegistry) -> str:
    rec = reg.create(
        agent_id="agent-a",
        intent="curate_memories",
        caps=["memory.read"],
        guardrails=MappingProxyType({}),
        output_filter_profile="default",
    )
    return rec.session_id


@pytest.mark.asyncio
async def test_eviction_callback_invoked_on_idle_expiry() -> None:
    fired: list[str] = []

    async def hook(sid: str) -> None:
        fired.append(sid)

    reg = InMemorySessionRegistry(ttl_seconds=3600, idle_timeout_seconds=1, on_session_evicted=hook)
    sid = _make_session(reg)
    reg._last_active[sid] -= timedelta(seconds=10)  # type: ignore[attr-defined]

    with pytest.raises(SessionError):
        reg.lookup(sid)

    await asyncio.sleep(0)
    assert fired == [sid]


@pytest.mark.asyncio
async def test_eviction_callback_invoked_on_ttl_expiry() -> None:
    fired: list[str] = []

    async def hook(sid: str) -> None:
        fired.append(sid)

    reg = InMemorySessionRegistry(ttl_seconds=1, idle_timeout_seconds=3600, on_session_evicted=hook)
    sid = _make_session(reg)
    reg._records[sid] = replace(
        reg._records[sid], expires_at=reg._records[sid].issued_at - timedelta(seconds=1)
    )  # type: ignore[attr-defined]

    with pytest.raises(SessionError):
        reg.lookup(sid)

    await asyncio.sleep(0)
    assert fired == [sid]


@pytest.mark.asyncio
async def test_eviction_callback_invoked_on_remove() -> None:
    fired: list[str] = []

    async def hook(sid: str) -> None:
        fired.append(sid)

    reg = InMemorySessionRegistry(
        ttl_seconds=3600, idle_timeout_seconds=3600, on_session_evicted=hook
    )
    sid = _make_session(reg)
    reg.remove(sid)
    await asyncio.sleep(0)
    assert fired == [sid]


@pytest.mark.asyncio
async def test_eviction_callback_invoked_on_purge() -> None:
    fired: list[str] = []

    async def hook(sid: str) -> None:
        fired.append(sid)

    reg = InMemorySessionRegistry(ttl_seconds=1, idle_timeout_seconds=3600, on_session_evicted=hook)
    sid_a = _make_session(reg)
    sid_b = _make_session(reg)
    for sid in (sid_a, sid_b):
        reg._records[sid] = replace(
            reg._records[sid], expires_at=reg._records[sid].issued_at - timedelta(seconds=1)
        )  # type: ignore[attr-defined]

    reg.purge()
    await asyncio.sleep(0)
    assert sorted(fired) == sorted([sid_a, sid_b])


@pytest.mark.asyncio
async def test_eviction_callback_logs_exception_when_callback_raises() -> None:
    from mcp_gateway.auth import session as session_module

    records: list[logging.LogRecord] = []

    class _CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    async def boom(sid: str) -> None:
        raise RuntimeError("explode")

    handler = _CaptureHandler(level=logging.ERROR)
    session_module.logger.addHandler(handler)
    session_module.logger.setLevel(logging.ERROR)
    try:
        reg = InMemorySessionRegistry(
            ttl_seconds=3600, idle_timeout_seconds=3600, on_session_evicted=boom
        )
        sid = _make_session(reg)
        reg.remove(sid)
        for _ in range(10):
            if records:
                break
            await asyncio.sleep(0.01)
    finally:
        session_module.logger.removeHandler(handler)

    assert any(
        record.getMessage().startswith("session_eviction_callback_failed") for record in records
    )


@pytest.mark.asyncio
async def test_eviction_callback_does_not_block_caller() -> None:
    started = asyncio.Event()

    async def slow(sid: str) -> None:
        started.set()
        await asyncio.sleep(0.5)

    reg = InMemorySessionRegistry(
        ttl_seconds=3600, idle_timeout_seconds=3600, on_session_evicted=slow
    )
    sid = _make_session(reg)

    import time

    t0 = time.monotonic()
    reg.remove(sid)
    elapsed = time.monotonic() - t0
    assert elapsed < 0.05
    await asyncio.wait_for(started.wait(), timeout=0.5)
