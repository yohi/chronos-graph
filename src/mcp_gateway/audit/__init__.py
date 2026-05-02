import json
import logging
import sys
import traceback
from datetime import datetime, timezone
from typing import Any


class AuditLogger:
    def __init__(self, level: str = "INFO") -> None:
        self.logger = logging.getLogger("mcp_gateway.audit")
        self.logger.setLevel(level)
        self.logger.propagate = False

        # stdout 汚染を避けるため stderr に出力。重複追加を防ぐ
        if not self.logger.handlers:
            handler = logging.StreamHandler(sys.stderr)
            formatter = logging.Formatter("%(message)s")
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)

    def set_level(self, level: str) -> None:
        """Update the logging level dynamically."""
        self.logger.setLevel(level)

    def log(self, ev: str, **kwargs: Any) -> None:
        # datetime.utcnow() is deprecated in Python 3.12+
        ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        entry = {"ts": ts, "ev": ev, **kwargs}
        self.logger.info(json.dumps(entry))


audit_logger = AuditLogger()


def emit_startup_failure(e: Exception) -> None:
    """Unify startup-failure auditing with structured payload and stacktrace."""
    audit_logger.log(
        "fatal",
        error=str(e),
        error_type=e.__class__.__name__,
        stacktrace=traceback.format_exc(),
    )
