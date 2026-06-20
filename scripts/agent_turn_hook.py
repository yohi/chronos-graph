"""ターン終了時に会話ログを ChronosGate へ fire-and-forget で送信するフック。

呼び出し例:
    # 生のテキストを stdin で渡す (汎用)
    echo "$CONVERSATION_LOG" | python scripts/agent_turn_hook.py &

    # --content 引数で渡す
    python scripts/agent_turn_hook.py --content "..." &

    # Claude Code / Codex / Cursor / Antigravity の Stop hook から JSON payload を渡す
    # (transcript_path / transcriptPath フィールドが自動的に解釈される)
    python scripts/agent_turn_hook.py --client claude-code &

設計書: docs/superpowers/specs/2026-05-27-hybrid-ingestion-mode-design.md
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Final, Mapping
from urllib.parse import parse_qs, urlparse

import httpx

try:
    from chronos_shared.ingestion_mode import (
        CHRONOS_INGESTION_MODE_ENV,  # type: ignore[misc]
        DEFAULT_INGESTION_MODE,  # type: ignore[misc]
    )
except ModuleNotFoundError:
    CHRONOS_INGESTION_MODE_ENV = "CHRONOS_INGESTION_MODE"  # type: ignore[misc]
    DEFAULT_INGESTION_MODE = "selective"  # type: ignore[misc]

LOG_FORMAT: Final[str] = "%(asctime)s [%(levelname)s] agent_turn_hook: %(message)s"

DEFAULT_GATEWAY_URL: Final[str] = "http://127.0.0.1:9100"
DEFAULT_INTENT: Final[str] = "memory.ingest"
DEFAULT_TIMEOUT_SECONDS: Final[float] = 2.0
DEFAULT_SSE_TIMEOUT_SECONDS: Final[float] = 1.0
DEFAULT_MAX_LOG_BYTES: Final[int] = 8 * 1024 * 1024
TRUNCATION_MARKER_TEMPLATE: Final[str] = "[truncated to last {n} bytes]\n"

# サポートする ``--client`` の値。
# - ``raw``: 生のテキストとしてそのまま送信 (既存の後方互換動作)。
# - ``claude-code`` / ``codex`` / ``cursor``: stdin の JSON から ``transcript_path``
#   フィールドを取り出し、JSONL transcript を読み込んで会話ログ文字列に整形する。
# - ``antigravity``: ``transcriptPath`` (キャメルケース) からも読み込む。
SUPPORTED_CLIENTS: Final[tuple[str, ...]] = (
    "raw",
    "claude-code",
    "codex",
    "cursor",
    "antigravity",
)


def _is_all_ingestion_mode(env: Mapping[str, str | None]) -> bool:
    mode = env.get(CHRONOS_INGESTION_MODE_ENV) or DEFAULT_INGESTION_MODE
    return mode.strip().lower() == "all"


# ---------------------------------------------------------------------------
# 純関数: 切り詰め
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# 純関数: クライアント別 payload からの会話ログ抽出
# ---------------------------------------------------------------------------


def _coerce_text_content(content: Any) -> str:
    """Claude Code 形式の content (list of {type, text}) 等を平文に正規化する。"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                # Claude Code: {"type": "text", "text": "..."}
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
                    continue
                # Generic: {"role": ..., "content": "..."} の入れ子
                inner = item.get("content")
                if inner:
                    parts.append(_coerce_text_content(inner))
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(p for p in parts if p)
    if isinstance(content, dict):
        text = content.get("text")
        if isinstance(text, str):
            return text
        return ""
    return str(content)


def format_transcript_messages(messages: list[Any]) -> str:
    """JSONL transcript の messages 配列を ``Role: text`` の連結文字列に整形する。

    Claude Code の transcript は 1 行 1 オブジェクトの JSONL で、各行は
    ``{"type": "user"|"assistant", "message": {"role": ..., "content": ...}}``
    のような形を取る (バージョンにより微差あり)。本関数はベストエフォートで
    主要なフィールド形を吸収する純関数。
    """
    lines: list[str] = []
    for entry in messages:
        if not isinstance(entry, dict):
            continue

        # role 抽出: トップレベル role / type、message.role の順で見る
        role = entry.get("role") or entry.get("type")
        message = entry.get("message")
        if isinstance(message, dict):
            role = message.get("role") or role
            content_source: Any = message.get("content")
        else:
            content_source = entry.get("content")

        text = _coerce_text_content(content_source).strip()
        if not text:
            continue
        if not role:
            role = "unknown"

        # role を表示用に正規化 (user → User, assistant → Assistant)
        role_label = str(role).strip().capitalize() if str(role).islower() else str(role)
        lines.append(f"{role_label}: {text}")
    return "\n\n".join(lines)


def is_safe_path(path_str: str) -> bool:
    """パスが安全な場所（ホームディレクトリ、カレントディレクトリ、または一時ディレクトリ配下）にあり、

    かつ拡張子が .jsonl であることを検証する。
    """
    try:
        path = Path(path_str).expanduser().resolve()
        if path.suffix != ".jsonl":
            return False

        home = Path.home().resolve()
        cwd = Path.cwd().resolve()
        temp_dir = Path(tempfile.gettempdir()).resolve()

        is_under_home = False
        try:
            path.relative_to(home)
            is_under_home = True
        except ValueError:
            pass

        is_under_cwd = False
        try:
            path.relative_to(cwd)
            is_under_cwd = True
        except ValueError:
            pass

        is_under_temp = False
        try:
            path.relative_to(temp_dir)
            is_under_temp = True
        except ValueError:
            pass

        return is_under_home or is_under_cwd or is_under_temp
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as e:
        logging.error("Path validation failed: %s", e)
        return False


def read_jsonl_transcript(path: str) -> str:
    """JSONL transcript ファイルを読み込み、整形済みの会話ログ文字列を返す。

    パース不能な行はスキップする (フェイルソフト)。
    """
    if not is_safe_path(path):
        logging.warning("Prevented reading unsafe path: %r", path)
        raise PermissionError(f"Unsafe path access blocked: {path}")

    messages: list[Any] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            messages.append(obj)
    return format_transcript_messages(messages)


def extract_payload(client: str, raw: str) -> str:
    """``--client`` の値に応じて raw 入力から会話ログ文字列を抽出する純関数。

    - ``raw``: そのまま返す。
    - ``claude-code`` / ``codex`` / ``cursor`` / ``antigravity``:
      raw を JSON としてパースし、``transcript_path`` または ``transcriptPath``
      フィールドのファイルを読み込んで整形する。失敗時は raw をそのまま返す。
    """
    if client == "raw" or not raw:
        return raw

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # クライアント指定なのに JSON でなかった場合は、raw として扱ってフェイルソフト
        return raw

    if not isinstance(data, dict):
        return raw

    transcript_path = data.get("transcript_path") or data.get("transcriptPath")
    if isinstance(transcript_path, str) and transcript_path:
        try:
            text = read_jsonl_transcript(transcript_path)
            if text:
                return text
        except (OSError, PermissionError) as exc:
            logging.warning("failed to read transcript at %r: %s", transcript_path, exc)

    # 一部のクライアントは payload に直接 messages 配列を含める可能性がある
    messages = data.get("messages")
    if isinstance(messages, list):
        text = format_transcript_messages(messages)
        if text:
            return text

    # 何も抽出できない: raw を返してフェイルソフト
    return raw


# ---------------------------------------------------------------------------
# CLI ラッパ
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ChronosGraph turn-end memory ingestion hook")
    parser.add_argument(
        "--content",
        default=None,
        help="会話ログ本文。未指定時は stdin から読み取る。",
    )
    parser.add_argument(
        "--client",
        default="raw",
        choices=SUPPORTED_CLIENTS,
        help=(
            "stdin に渡される入力の解釈方法。"
            "raw=生テキスト, claude-code/codex/cursor/antigravity=JSON payload を解釈。"
        ),
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
        post_resp.raise_for_status()
    elif post_resp.status_code >= 400:
        logging.warning("Gateway returned HTTP %d", post_resp.status_code)
        post_resp.raise_for_status()


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


async def _main_async(payload: str) -> bool:
    if not _is_all_ingestion_mode(os.environ):
        logging.info(
            "%s is not 'all'; skipping turn-end ingestion",
            CHRONOS_INGESTION_MODE_ENV,
        )
        return True

    gateway_url = os.environ.get("MCP_GATEWAY_URL", DEFAULT_GATEWAY_URL)
    api_key = os.environ.get("MCP_GATEWAY_API_KEY")
    intent = os.environ.get("MCP_INTENT", DEFAULT_INTENT)
    try:
        total_timeout = float(
            os.environ.get("MCP_HOOK_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))
        )
    except ValueError as exc:
        logging.warning(
            "Failed to parse MCP_HOOK_TIMEOUT_SECONDS, falling back to default: %s", exc
        )
        total_timeout = DEFAULT_TIMEOUT_SECONDS

    try:
        sse_timeout = float(
            os.environ.get("MCP_HOOK_SSE_TIMEOUT_SECONDS", str(DEFAULT_SSE_TIMEOUT_SECONDS))
        )
    except ValueError as exc:
        logging.warning(
            "Failed to parse MCP_HOOK_SSE_TIMEOUT_SECONDS, falling back to default: %s", exc
        )
        sse_timeout = DEFAULT_SSE_TIMEOUT_SECONDS

    if not api_key:
        logging.error("MCP_GATEWAY_API_KEY is not set; aborting hook")
        return True

    try:
        await asyncio.wait_for(
            _send(gateway_url, api_key, intent, payload, total_timeout, sse_timeout),
            timeout=total_timeout,
        )
        return True
    except TimeoutError as exc:
        logging.error("turn hook timed out (total budget exhausted): %s", exc)
        return False
    except httpx.HTTPError as exc:
        logging.error("turn hook failed (HTTP error): %s", exc)
        return False
    except Exception as exc:  # noqa: BLE001 - intentional broad catch
        logging.error("turn hook failed (unexpected): %s", exc, exc_info=True)
        return False


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
        return 1

    if not raw:
        logging.debug("empty input; skipping hook invocation")
        return 0

    # クライアント別の payload 解釈 (raw 以外は JSON → transcript 変換を試みる)
    try:
        extracted = extract_payload(args.client, raw)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        logging.warning("payload extraction failed (%s); falling back to raw input", exc)
        extracted = raw

    if not extracted:
        logging.debug("payload extraction yielded empty content; skipping hook invocation")
        return 0

    try:
        max_bytes = int(os.environ.get("MCP_HOOK_MAX_LOG_BYTES", str(DEFAULT_MAX_LOG_BYTES)))
    except ValueError as exc:
        logging.warning("Failed to parse MCP_HOOK_MAX_LOG_BYTES, falling back to default: %s", exc)
        max_bytes = DEFAULT_MAX_LOG_BYTES
    payload, was_truncated = truncate_log(extracted, max_bytes)
    if was_truncated:
        logging.warning(
            "payload truncated: original=%d bytes, sent=%d bytes",
            len(extracted.encode("utf-8")),
            len(payload.encode("utf-8")),
        )
    if not payload:
        logging.debug("payload is empty after truncation; skipping hook invocation")
        return 0

    try:
        success = asyncio.run(_main_async(payload))
        if not success:
            return 1
    except Exception as exc:  # noqa: BLE001 - intentional broad catch
        logging.warning("turn hook failed at top level: %s", exc, exc_info=True)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
