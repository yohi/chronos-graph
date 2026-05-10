"""ASGI middlewares for the MCP Gateway."""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class MaxBodySizeMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_size_bytes: int):
        super().__init__(app)
        self.max_size_bytes = max_size_bytes

    async def dispatch(self, request: Request, call_next):
        if "content-length" in request.headers:
            try:
                content_length = int(request.headers["content-length"])
            except ValueError:
                return JSONResponse({"error": "invalid_request"}, status_code=400)
            if content_length > self.max_size_bytes:
                return JSONResponse({"error": "payload_too_large"}, status_code=413)
        return await call_next(request)
