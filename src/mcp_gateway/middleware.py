"""ASGI middlewares for the MCP Gateway."""

from typing import Any

from starlette.types import Message, Receive, Scope, Send


class PayloadTooLargeError(RuntimeError):
    """Raised when the request body exceeds the maximum allowed size."""


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

        # Fast path: Check Content-Length if present
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
        else:
            # Robust path: Eagerly read and buffer up to max_size_bytes + 1
            # to enforce limit even if the app doesn't read the body.
            buffered_messages = []
            count = 0
            while True:
                message = await receive()
                buffered_messages.append(message)
                if message["type"] == "http.request":
                    body = message.get("body", b"")
                    count += len(body)
                    if count > self.max_size_bytes:
                        if not response_started:
                            await self._send_413(send)
                        return
                    if not message.get("more_body", False):
                        break
                elif message["type"] == "http.disconnect":
                    break

            async def buffered_receive() -> Message:
                if buffered_messages:
                    return buffered_messages.pop(0)
                return await receive()

            await self.app(scope, buffered_receive, wrapped_send)
            return

        # Path for requests with valid Content-Length header
        count = 0

        async def wrapped_receive() -> Message:
            nonlocal count
            message = await receive()
            if message["type"] == "http.request":
                body = message.get("body", b"")
                count += len(body)
                if count > self.max_size_bytes:
                    raise PayloadTooLargeError()
            return message

        try:
            await self.app(scope, wrapped_receive, wrapped_send)
        except PayloadTooLargeError:
            if not response_started:
                await self._send_413(send)
                return
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
