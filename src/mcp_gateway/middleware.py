"""ASGI middlewares for the MCP Gateway."""

from typing import Any

from starlette.types import Message, Receive, Scope, Send


class MaxBodySizeMiddleware:
    def __init__(self, app: Any, max_size_bytes: int):
        self.app = app
        self.max_size_bytes = max_size_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in ("POST", "PUT", "PATCH", "DELETE"):
            await self.app(scope, receive, send)
            return

        response_started = False

        async def wrapped_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        # Fast path
        headers = dict(scope["headers"])
        if b"content-length" in headers:
            try:
                content_length = int(headers[b"content-length"])
                if content_length < 0:
                    await self._send_400(send)
                    return
                if content_length > self.max_size_bytes:
                    await self._send_413(send)
                    return
            except ValueError:
                await self._send_400(send)
                return

        # Robust path: cumulative counting
        count = 0

        async def wrapped_receive() -> Message:
            nonlocal count
            message = await receive()
            if message["type"] == "http.request":
                body = message.get("body", b"")
                count += len(body)
                if count > self.max_size_bytes:
                    # We can't easily send 413 here because the app might have started sending
                    # but for request phase, we can raise and let middleware catch or just
                    # send 413 if app hasn't started.
                    raise RuntimeError("payload_too_large")
            return message

        try:
            await self.app(scope, wrapped_receive, wrapped_send)
        except RuntimeError as exc:
            if str(exc) == "payload_too_large":
                if not response_started:
                    await self._send_413(send)
                    return
                # If response started, re-raise to let the server handle the error
                # (e.g. by closing the connection or trying to send a 500 if possible)
                raise
            raise

    async def _send_400(self, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 400,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": b'{"error": "invalid_request"}',
            }
        )

    async def _send_413(self, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": b'{"error": "payload_too_large"}',
            }
        )
