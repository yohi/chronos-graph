"""scripts/agent_turn_hook.py の pure helpers (truncate_log / _extract_session_id) の検証。"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest


def _load_hook_module():
    """scripts/agent_turn_hook.py を tests から動的に import するヘルパ。"""
    if "agent_turn_hook" in sys.modules:
        return sys.modules["agent_turn_hook"]
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    script_path = repo_root / "scripts" / "agent_turn_hook.py"
    spec = importlib.util.spec_from_file_location("agent_turn_hook", script_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["agent_turn_hook"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_truncate_log_short_input_returns_unchanged() -> None:
    mod = _load_hook_module()
    text = "hello world"
    out, was_truncated = mod.truncate_log(text, max_bytes=1024)
    assert out == text
    assert was_truncated is False


def test_truncate_log_long_ascii_input_keeps_tail() -> None:
    mod = _load_hook_module()
    text = "a" * 5000
    out, was_truncated = mod.truncate_log(text, max_bytes=1024)
    assert was_truncated is True
    assert len(out.encode("utf-8")) <= 1024
    assert out.endswith("a")
    assert out.startswith("[truncated to last ")


def test_truncate_log_marker_is_prefixed_and_bytes_stay_under_limit() -> None:
    mod = _load_hook_module()
    text = "x" * 10_000
    max_bytes = 200
    out, was_truncated = mod.truncate_log(text, max_bytes=max_bytes)
    assert was_truncated is True
    assert len(out.encode("utf-8")) <= max_bytes
    assert "[truncated to last " in out.splitlines()[0]


def test_truncate_log_multibyte_utf8_does_not_corrupt() -> None:
    """日本語 (3 バイト/文字) を含む長文を切り詰めても、不完全シーケンスを残さない。"""
    mod = _load_hook_module()
    text = "あ" * 1000
    out, was_truncated = mod.truncate_log(text, max_bytes=500)
    assert was_truncated is True
    out.encode("utf-8").decode("utf-8")
    assert len(out.encode("utf-8")) <= 500


def test_truncate_log_exactly_at_limit_is_not_truncated() -> None:
    mod = _load_hook_module()
    text = "y" * 100
    out, was_truncated = mod.truncate_log(text, max_bytes=100)
    assert was_truncated is False
    assert out == text


def test_truncate_log_max_bytes_smaller_than_marker_returns_truncated_marker() -> None:
    """max_bytes がマーカー長より小さい異常ケース。バイト境界で切り詰めて返す。"""
    mod = _load_hook_module()
    text = "z" * 1000
    out, was_truncated = mod.truncate_log(text, max_bytes=5)
    assert was_truncated is True
    assert len(out.encode("utf-8")) <= 5
    out.encode("utf-8").decode("utf-8")


def test_extract_session_id_simple_data_line() -> None:
    """典型的な SSE 1 行から session_id を取り出せること。"""
    mod = _load_hook_module()
    sid = mod._extract_session_id("data: /messages?session_id=abc123")
    assert sid == "abc123"


def test_extract_session_id_ignores_additional_query_params() -> None:
    """Issue 1: 追加クエリパラメータが付いても session_id だけが返ること。"""
    mod = _load_hook_module()
    sid = mod._extract_session_id("data: /messages?session_id=abc123&trace_id=xyz&foo=bar")
    assert sid == "abc123"


def test_extract_session_id_returns_none_for_non_data_line() -> None:
    mod = _load_hook_module()
    assert mod._extract_session_id("event: ping") is None
    assert mod._extract_session_id("") is None


def test_extract_session_id_returns_none_when_param_missing() -> None:
    mod = _load_hook_module()
    assert mod._extract_session_id("data: /messages?foo=bar") is None


def test_truncate_log_max_bytes_non_positive_returns_empty_and_truncated() -> None:
    """max_bytes が 0 または負の値の場合、空文字列と True を返すこと。"""
    mod = _load_hook_module()
    text = "hello world"

    # 0 の場合
    out, was_truncated = mod.truncate_log(text, max_bytes=0)
    assert out == ""
    assert was_truncated is True

    # 負の値の場合
    out, was_truncated = mod.truncate_log(text, max_bytes=-5)
    assert out == ""
    assert was_truncated is True


@pytest.mark.asyncio
async def test_main_async_skips_send_in_selective_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _load_hook_module()
    monkeypatch.delenv("CHRONOS_INGESTION_MODE", raising=False)
    monkeypatch.delenv("MCP_GATEWAY_API_KEY", raising=False)

    async def fail_send(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("_send must not be called unless CHRONOS_INGESTION_MODE=all")

    monkeypatch.setattr(mod, "_send", fail_send)

    assert await mod._main_async("User: hello") is True


@pytest.mark.asyncio
async def test_main_async_sends_in_all_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load_hook_module()
    calls: list[tuple[object, ...]] = []
    monkeypatch.setenv("CHRONOS_INGESTION_MODE", "all")
    monkeypatch.setenv("MCP_GATEWAY_API_KEY", "test-key")

    async def fake_send(*args: object, **_kwargs: object) -> None:
        calls.append(args)

    monkeypatch.setattr(mod, "_send", fake_send)

    assert await mod._main_async("User: hello") is True
    assert len(calls) == 1
