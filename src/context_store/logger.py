import json
import logging
import sys
import threading
from collections import deque
from contextvars import ContextVar
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

# ContextVars for request/operation context
_context: ContextVar[dict[str, Any] | None] = ContextVar("_log_context", default=None)
_RESERVED_FIELDS = frozenset({"exception", "level", "logger", "message", "timestamp"})
logger_init_lock = threading.Lock()

# Circular buffer for dashboard logs
_log_buffer: deque[dict[str, Any]] = deque(maxlen=1000)
_buffer_lock = threading.Lock()


def _serialize_context_value(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return str(value)


class StructuredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ctx = _context.get() or {}
        ctx_filtered = {key: value for key, value in ctx.items() if key not in _RESERVED_FIELDS}
        data = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            **ctx_filtered,
        }
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False, default=_serialize_context_value)


class MemoryHandler(logging.Handler):
    """Logging handler that stores records in a circular buffer."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            ctx = _context.get() or {}
            ctx_filtered = {key: value for key, value in ctx.items() if key not in _RESERVED_FIELDS}
            entry = {
                "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                **ctx_filtered,
            }
            if record.exc_info:
                entry["exception"] = logging.Formatter().formatException(record.exc_info)

            with _buffer_lock:
                _log_buffer.append(entry)
        except Exception:
            self.handleError(record)


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        with logger_init_lock:
            if not logger.handlers:
                # stdout for DEBUG/INFO, stderr for WARNING and above
                stdout_handler = logging.StreamHandler(sys.stdout)
                stdout_handler.setLevel(logging.DEBUG)
                stdout_handler.setFormatter(StructuredFormatter())
                stdout_handler.addFilter(lambda r: r.levelno < logging.WARNING)

                stderr_handler = logging.StreamHandler(sys.stderr)
                stderr_handler.setLevel(logging.WARNING)
                stderr_handler.setFormatter(StructuredFormatter())

                # Memory handler for dashboard
                memory_handler = MemoryHandler()
                memory_handler.setLevel(logging.DEBUG)

                logger.addHandler(stdout_handler)
                logger.addHandler(stderr_handler)
                logger.addHandler(memory_handler)
                logger.setLevel(logging.DEBUG)
                logger.propagate = False
    return logger


def get_recent_logs(limit: int = 100) -> list[dict[str, Any]]:
    """Retrieve recent logs from the circular buffer."""
    with _buffer_lock:
        logs = list(_log_buffer)
    return logs[-limit:] if limit > 0 else []


def set_context(**kwargs: Any) -> None:
    """Set context variables (request_id, agent_id, memory_id, etc.) via ContextVar."""
    current = _context.get() or {}
    _context.set({**current, **kwargs})


def clear_context() -> None:
    """Clear all context variables."""
    _context.set(None)
