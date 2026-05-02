from mcp_gateway.audit import audit_logger
from mcp_gateway.config import GatewaySettings


def run_gateway() -> None:
    """
    Main startup routine for the MCP Gateway.
    In a real implementation, this would start the uvicorn server.
    """
    settings = GatewaySettings()
    audit_logger.set_level(settings.audit_log_level)

    audit_logger.log("startup", host=settings.host, port=settings.port)

    # 本来はここで FastAPI アプリを uvicorn で起動する

    # 簡易的な待機処理（実働時は uvicorn がブロックする）
    # asyncio.run(asyncio.sleep(1))
