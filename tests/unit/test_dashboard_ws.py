"""Unit tests for LogCollectorHandler and WebSocketManager (PR 8)."""

from __future__ import annotations

import logging

import pytest

from context_store.dashboard.log_collector import LogCollectorHandler
from context_store.dashboard.websocket_manager import WebSocketManager


@pytest.fixture
def log_handler():
    handler = LogCollectorHandler(maxlen=10)
    return handler


def test_log_collector_handler_emit(log_handler):
    """LogCollectorHandler should buffer records."""
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="test message",
        args=(),
        exc_info=None,
    )
    log_handler.emit(record)
    entries = log_handler.get_recent(limit=1)
    assert len(entries) == 1
    assert entries[0].message == "test message"


def test_log_collector_ring_buffer(log_handler):
    """LogCollectorHandler should drop old entries when full."""
    for i in range(15):
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg=f"msg{i}",
            args=(),
            exc_info=None,
        )
        log_handler.emit(record)
    entries = log_handler.get_recent(limit=10)
    assert len(entries) == 10


@pytest.mark.asyncio
async def test_ws_manager_connect():
    """WebSocketManager should manage connections."""
    from unittest.mock import AsyncMock

    manager = WebSocketManager()
    ws = AsyncMock()
    await manager.connect(ws)
    assert ws in manager._conns
    ws.accept.assert_called_once()


@pytest.mark.asyncio
async def test_ws_manager_broadcast():
    """WebSocketManager should broadcast to connections."""
    from unittest.mock import AsyncMock

    manager = WebSocketManager()
    ws1 = AsyncMock()
    ws2 = AsyncMock()
    manager._conns.add(ws1)
    manager._conns.add(ws2)
    await manager.broadcast("logs", {"message": "test"})
    ws1.send_json.assert_called_once()
    ws2.send_json.assert_called_once()
