import json
import logging
import sys
import threading
from contextvars import ContextVar
from datetime import date, datetime
from typing import Any
from uuid import UUID

# ContextVars for request/operation context
_context: ContextVar[dict[str, Any] | None] = ContextVar("_log_context", default=None)
_RESERVED_FIELDS = frozenset({"exception", "level", "logger", "message"})
logger_init_lock = threading.Lock()


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
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            **ctx_filtered,
        }
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False, default=_serialize_context_value)


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

                logger.addHandler(stdout_handler)
                logger.addHandler(stderr_handler)
                logger.setLevel(logging.DEBUG)
                logger.propagate = False
    return logger


def set_context(**kwargs: Any) -> None:
    """Set context variables (request_id, agent_id, memory_id, etc.) via ContextVar."""
    current = _context.get() or {}
    _context.set({**current, **kwargs})


def clear_context() -> None:
    """Clear all context variables."""
    _context.set(None)
