"""`python -m mcp_gateway` entrypoint stub.

This module is a placeholder that will be replaced by the full implementation
in Phase 3 (Task 3.5). The actual entrypoint boots uvicorn with the FastAPI app.
"""

from __future__ import annotations

import sys
import traceback

from mcp_gateway.audit.logger import AuditLogger
from mcp_gateway.server import run_gateway


def main() -> None:
    """Entry point for the chronos-mcp-gateway."""
    try:
        run_gateway()
    except Exception as e:
        audit = AuditLogger()
        audit.log(
            ev="startup_failure",
            level="ERROR",
            error_type=e.__class__.__name__,
            error=str(e),
            stacktrace=traceback.format_exc(),
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
