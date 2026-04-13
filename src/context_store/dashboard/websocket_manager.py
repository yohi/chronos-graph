"""WebSocket connection manager for Dashboard."""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebSocketManager:
    """Manages WebSocket connections with broadcast support."""

    def __init__(self, channel: str, maxsize: int = 100) -> None:
        self.channel = channel
        self._conns: set[WebSocket] = set()
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=maxsize)
        self._loop: asyncio.AbstractEventLoop | None = None

    async def connect(self, ws: WebSocket) -> None:
        """Register a new WebSocket connection."""
        if self._loop is None:
            self._loop = asyncio.get_running_loop()
        await ws.accept()
        self._conns.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        """Remove a WebSocket connection."""
        self._conns.discard(ws)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        """Broadcast a message to all connected clients."""
        if not self._conns:
            return

        # Embed channel into payload
        payload_with_channel = {**payload, "channel": self.channel}

        async def safe_send(ws: WebSocket) -> None:
            try:
                await asyncio.wait_for(ws.send_json(payload_with_channel), timeout=1.0)
            except asyncio.TimeoutError:
                logger.warning("WS send timeout, disconnecting client")
                self.disconnect(ws)
                try:
                    await ws.close()
                except Exception as exc:
                    logger.debug("WS close error during timeout handling: %s", exc)
            except Exception as exc:
                logger.warning("WS send error: %s, disconnecting", exc)
                self.disconnect(ws)
                try:
                    await ws.close()
                except Exception as exc_close:
                    logger.debug("WS close error during exception handling: %s", exc_close)

        await asyncio.gather(
            *(safe_send(ws) for ws in list(self._conns)),
            return_exceptions=True,
        )

    async def start_consumer(self) -> None:
        """Start consuming messages from the queue and broadcasting."""
        self._loop = asyncio.get_running_loop()
        while True:
            try:
                msg = await self._queue.get()
                await self.broadcast(msg)
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

    def put_threadsafe(self, payload: dict[str, Any]) -> None:
        """Thread-safe way to put a message into the queue.

        If the event loop is not running, the message is dropped to ensure
        thread safety. asyncio.Queue is not thread-safe and must only be
        accessed via the loop.
        """
        if self._loop and self._loop.is_running():
            try:
                self._loop.call_soon_threadsafe(self.put, payload)
            except RuntimeError:
                logger.debug("WebSocket loop closed, dropping message")
        else:
            logger.debug("WebSocket loop not running, dropping message")


_wss: dict[str, WebSocketManager] = {}
_wss_lock = threading.Lock()


def get_ws_manager(channel: str = "logs") -> WebSocketManager:
    """Get or create a WebSocket manager for a channel."""
    with _wss_lock:
        if channel not in _wss:
            _wss[channel] = WebSocketManager(channel=channel)
    return _wss[channel]
