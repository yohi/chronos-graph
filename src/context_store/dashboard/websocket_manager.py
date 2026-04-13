"""WebSocket connection manager for Dashboard."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebSocketManager:
    """Manages WebSocket connections with broadcast support."""

    def __init__(self, maxsize: int = 100) -> None:
        self._conns: set[WebSocket] = set()
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=maxsize)

    async def connect(self, ws: WebSocket) -> None:
        """Register a new WebSocket connection."""
        await ws.accept()
        self._conns.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        """Remove a WebSocket connection."""
        self._conns.discard(ws)

    async def broadcast(self, channel: str, payload: dict[str, Any]) -> None:
        """Broadcast a message to all connected clients."""
        if not self._conns:
            return

        # Embed channel into payload
        payload_with_channel = {**payload, "channel": channel}

        async def safe_send(ws: WebSocket) -> None:
            try:
                await asyncio.wait_for(ws.send_json(payload_with_channel), timeout=1.0)
            except asyncio.TimeoutError:
                logger.warning("WS send timeout, disconnecting client")
                self.disconnect(ws)
                try:
                    await ws.close()
                except Exception:
                    pass
            except Exception as exc:
                logger.warning("WS send error: %s, disconnecting", exc)
                self.disconnect(ws)
                try:
                    await ws.close()
                except Exception:
                    pass

        await asyncio.gather(
            *(safe_send(ws) for ws in list(self._conns)),
            return_exceptions=True,
        )

    async def start_consumer(self) -> None:
        """Start consuming messages from the queue and broadcasting."""
        while True:
            try:
                msg = await self._queue.get()
                await self.broadcast("logs", msg)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("WS consumer error: %s", exc)

    def put(self, payload: dict[str, Any]) -> bool:
        """Add a message to the queue. Returns False if queue is full."""
        try:
            self._queue.put_nowait(payload)
            return True
        except asyncio.QueueFull:
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(payload)
                return True
            except asyncio.QueueEmpty:
                return False


_wss: dict[str, WebSocketManager] = {}


def get_ws_manager(channel: str = "logs") -> WebSocketManager:
    """Get or create a WebSocket manager for a channel."""
    if channel not in _wss:
        _wss[channel] = WebSocketManager()
    return _wss[channel]
