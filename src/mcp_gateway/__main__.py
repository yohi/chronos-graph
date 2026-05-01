import sys

from pydantic import ValidationError

from mcp_gateway.audit import emit_startup_failure
from mcp_gateway.errors import GatewayError
from mcp_gateway.server import run_gateway


def main() -> None:
    """Entry point for the chronos-mcp-gateway."""
    try:
        run_gateway()
    except (GatewayError, ValidationError, Exception) as e:
        emit_startup_failure(e)
        sys.exit(1)


if __name__ == "__main__":
    main()
