import json
import logging
import sys
from datetime import datetime
from typing import Any


class AuditLogger:
    def __init__(self, level: str = "INFO") -> None:
        self.logger = logging.getLogger("mcp_gateway.audit")
        self.logger.setLevel(level)

        # stdout 汚染を避けるため stderr に出力
        handler = logging.StreamHandler(sys.stderr)
        formatter = logging.Formatter("%(message)s")
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)

    def log(self, ev: str, **kwargs: Any) -> None:
        entry = {"ts": datetime.utcnow().isoformat() + "Z", "ev": ev, **kwargs}
        self.logger.info(json.dumps(entry))


audit_logger = AuditLogger()
