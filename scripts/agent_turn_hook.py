"""ターン終了時に会話ログを MCP Gateway へ fire-and-forget で送信するフック。

呼び出し例:
    echo "$CONVERSATION_LOG" | python scripts/agent_turn_hook.py &
    # または
    python scripts/agent_turn_hook.py --content "..." &

設計書: docs/superpowers/specs/2026-05-27-hybrid-ingestion-mode-design.md §4.5
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from typing import Final
from urllib.parse import parse_qs, urlparse

import httpx

LOG_FORMAT: Final[str] = "%(asctime)s [%(levelname)s] agent_turn_hook: %(message)s"

DEFAULT_GATEWAY_URL: Final[str] = "http://127.0.0.1:9100"
DEFAULT_INTENT: Final[str] = "memory.ingest"
DEFAULT_TIMEOUT_SECONDS: Final[float] = 2.0
DEFAULT_SSE_TIMEOUT_SECONDS: Final[float] = 1.0
DEFAULT_MAX_LOG_BYTES: Final[int] = 8 * 1024 * 1024
TRUNCATION_MARKER_TEMPLATE: Final[str] = "[truncated to last {n} bytes]\n"


def truncate_log(content: str, max_bytes: int) -> tuple[str, bool]:
    """会話ログを送信前に末尾保持で切り詰める純関数。"""
    if max_bytes <= 0:
        return "", True

    encoded = content.encode("utf-8")
    if len(encoded) <= max_bytes:
        return content, False

    marker = TRUNCATION_MARKER_TEMPLATE.format(n=max_bytes)
    marker_bytes = marker.encode("utf-8")
    tail_budget = max_bytes - len(marker_bytes)
    if tail_budget <= 0:
        return marker_bytes[:max_bytes].decode("utf-8", errors="ignore"), True

    tail = encoded[-tail_budget:].decode("utf-8", errors="ignore")
    return marker + tail, True


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ChronosGraph turn-end memory ingestion hook")
    parser.add_argument(
        "--content",
        default=None,
        help="会話ログ本文。未指定時は stdin から読み取る。",
    )
    return parser


def _read_input(args: argparse.Namespace) -> str:
    content = args.content
    if isinstance(content, str):
        return content
    return sys.stdin.read()


def _extract_session_id(data_line: str) -> str | None:
    """SSE の ``data: /messages?session_id=XXX&...`` 行から session_id を取り出す。"""
    if not data_line.startswith("data: "):
        return None
    payload = data_line[len("data: ") :].strip()
    parsed = urlparse(payload)
    values = parse_qs(parsed.query).get("session_id") or []
    return values[0] if values else None


async def _sse_handshake(
    client: httpx.AsyncClient, gateway_url: str, headers: dict[str, str]
) -> str | None:
    """SSE エンドポイントから最初の session_id を取得して切断する。"""
    async with client.stream("GET", f"{gateway_url}/sse", headers=headers) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if line.startswith("data: ") and "session_id=" in line:
                return _extract_session_id(line)
    return None


async def _post_tools_call(
    client: httpx.AsyncClient,
    gateway_url: str,
    session_id: str,
    payload: str,
    headers: dict[str, str],
) -> None:
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "memory_save",
            "arguments": {"content": payload},
        },
    }
    post_resp = await client.post(
        f"{gateway_url}/messages",
        params={"session_id": session_id},
        json=body,
        headers={"content-type": "application/json", **headers},
    )
    if post_resp.status_code == 413:
        logging.warning(
            "Gateway returned 413 Payload Too Large; "
            "consider lowering MCP_HOOK_MAX_LOG_BYTES (currently %d)",
            int(os.environ.get("MCP_HOOK_MAX_LOG_BYTES", DEFAULT_MAX_LOG_BYTES)),
        )
    elif post_resp.status_code >= 400:
        logging.warning("Gateway returned HTTP %d", post_resp.status_code)


async def _send(
    gateway_url: str,
    api_key: str,
    intent: str,
    payload: str,
    total_timeout: float,
    sse_timeout: float,
) -> None:
    """SSE handshake 後に ``tools/call memory_save`` を送信する。"""
    headers = {
        "authorization": f"Bearer {api_key}",
        "x-mcp-intent": intent,
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(total_timeout, connect=1.0)) as client:
        try:
            session_id = await asyncio.wait_for(
                _sse_handshake(client, gateway_url, headers),
                timeout=sse_timeout,
            )
        except TimeoutError:
            logging.info("SSE handshake timed out after %.2fs", sse_timeout)
            return

        if session_id is None:
            logging.warning("SSE handshake did not yield a session_id")
            return

        await _post_tools_call(client, gateway_url, session_id, payload, headers)


async def _main_async(payload: str) -> None:
    gateway_url = os.environ.get("MCP_GATEWAY_URL", DEFAULT_GATEWAY_URL)
    api_key = os.environ.get("MCP_GATEWAY_API_KEY")
    intent = os.environ.get("MCP_INTENT", DEFAULT_INTENT)
    total_timeout = float(os.environ.get("MCP_HOOK_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))
    sse_timeout = float(os.environ.get("MCP_HOOK_SSE_TIMEOUT_SECONDS", DEFAULT_SSE_TIMEOUT_SECONDS))

    if not api_key:
        logging.error("MCP_GATEWAY_API_KEY is not set; aborting hook (no-op)")
        return

    try:
        await asyncio.wait_for(
            _send(gateway_url, api_key, intent, payload, total_timeout, sse_timeout),
            timeout=total_timeout,
        )
    except TimeoutError as exc:
        logging.info("turn hook timed out (total budget exhausted): %s", exc)
    except httpx.HTTPError as exc:
        logging.warning("turn hook failed (HTTP error): %s", exc)
    except Exception as exc:  # noqa: BLE001 - intentional broad catch
        logging.warning("turn hook failed (unexpected): %s", exc, exc_info=True)


def main() -> int:
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    if log_level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        log_level = "INFO"
    logging.basicConfig(level=log_level, format=LOG_FORMAT, stream=sys.stderr)

    parser = _build_parser()
    args = parser.parse_args()

    try:
        raw = _read_input(args)
    except Exception as exc:  # noqa: BLE001 - intentional broad catch
        logging.warning("failed to read input: %s", exc)
        return 0

    if not raw:
        logging.debug("empty input; skipping hook invocation")
        return 0

    max_bytes = int(os.environ.get("MCP_HOOK_MAX_LOG_BYTES", DEFAULT_MAX_LOG_BYTES))
    payload, was_truncated = truncate_log(raw, max_bytes)
    if was_truncated:
        logging.warning(
            "payload truncated: original=%d bytes, sent=%d bytes",
            len(raw.encode("utf-8")),
            len(payload.encode("utf-8")),
        )

    try:
        asyncio.run(_main_async(payload))
    except Exception as exc:  # noqa: BLE001 - intentional broad catch
        logging.warning("turn hook failed at top level: %s", exc, exc_info=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
