"""Logging Handler with thread-safe ring buffer for Dashboard."""

from __future__ import annotations

import logging
import threading
from collections import deque
from datetime import datetime, timezone

from context_store.dashboard.schemas import LogEntry


class LogCollectorHandler(logging.Handler):
    """logging.Handler that buffers records in a thread-safe ring buffer."""

    def __init__(self, maxlen: int = 1000) -> None:
        super().__init__()
        self._buffer: deque[LogEntry] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        """Add a log record to the buffer (thread-safe)."""
        try:
            msg = self.format(record)
            entry = LogEntry(
                timestamp=datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
                level=record.levelname,
                logger=record.name,
                message=msg,
            )
            with self._lock:
                self._buffer.append(entry)
        except Exception:
            self.handleError(record)

    def get_recent(self, limit: int = 100) -> list[LogEntry]:
        """Get the most recent log entries."""
        with self._lock:
            return list(self._buffer)[-limit:]

    def clear(self) -> None:
        """Clear the buffer."""
        with self._lock:
            self._buffer.clear()


def get_log_handler() -> LogCollectorHandler:
    """Get or create the log handler."""
    root = logging.getLogger()
    for h in root.handlers:
        if isinstance(h, LogCollectorHandler):
            return h
    handler = LogCollectorHandler()
    root.addHandler(handler)
    return handler
