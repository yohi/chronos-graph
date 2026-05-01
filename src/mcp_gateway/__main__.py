import sys

from mcp_gateway.audit import audit_logger
from mcp_gateway.server import run_gateway


def main() -> None:
    """Entry point for the chronos-mcp-gateway."""
    try:
        run_gateway()
    except Exception as e:
        audit_logger.log("fatal", error=str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
