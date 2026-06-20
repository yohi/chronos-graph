"""scripts/agent_turn_hook.py の payload adapter 純関数の検証。

検証対象:
- ``extract_payload(client, raw)``: ``--client`` 値に応じた raw 入力解釈
- ``format_transcript_messages(messages)``: JSONL messages 整形
- ``read_jsonl_transcript(path)``: JSONL ファイル読み込み + 整形
- ``_build_parser()``: ``--client`` 引数の choices バリデーション

設計書: SPEC.md §4.1.1 (Hybrid Ingestion Mode)  §11 (AC-8~AC-12)
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
from types import ModuleType

import pytest


def _load_hook_module() -> ModuleType:
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


# ---------------------------------------------------------------------------
# extract_payload: raw モード
# ---------------------------------------------------------------------------


def test_extract_payload_raw_returns_input_unchanged() -> None:
    mod = _load_hook_module()
    text = "User: hello\nAssistant: hi"
    assert mod.extract_payload("raw", text) == text


def test_extract_payload_raw_preserves_json_string() -> None:
    """raw モードでは JSON 文字列も解釈せずそのまま返す。"""
    mod = _load_hook_module()
    raw = json.dumps({"transcript_path": "/var/tmp/raw-mode-fixture"})  # noqa: S108
    assert mod.extract_payload("raw", raw) == raw


def test_extract_payload_empty_input_returns_empty() -> None:
    mod = _load_hook_module()
    assert mod.extract_payload("claude-code", "") == ""
    assert mod.extract_payload("raw", "") == ""


# ---------------------------------------------------------------------------
# extract_payload: フェイルソフト
# ---------------------------------------------------------------------------


def test_extract_payload_invalid_json_falls_back_to_raw() -> None:
    """AC-12: JSON パース失敗時は raw を返してフェイルソフト。"""
    mod = _load_hook_module()
    raw = "this is not json"
    assert mod.extract_payload("claude-code", raw) == raw


def test_extract_payload_non_dict_json_falls_back_to_raw() -> None:
    """JSON が dict でない場合 (list / number / string) は raw を返す。"""
    mod = _load_hook_module()
    raw = json.dumps([1, 2, 3])
    assert mod.extract_payload("claude-code", raw) == raw


def test_extract_payload_missing_transcript_path_falls_back_to_raw(tmp_path: pathlib.Path) -> None:
    """transcript_path が存在しないファイルパスを指す場合は raw を返す。"""
    mod = _load_hook_module()
    missing = tmp_path / "does_not_exist.jsonl"
    payload = json.dumps({"transcript_path": str(missing)})
    assert mod.extract_payload("claude-code", payload) == payload


def test_extract_payload_no_transcript_no_messages_falls_back_to_raw() -> None:
    """transcript_path も messages もない辞書は raw を返す。"""
    mod = _load_hook_module()
    payload = json.dumps({"foo": "bar", "session_id": "abc"})
    assert mod.extract_payload("claude-code", payload) == payload


# ---------------------------------------------------------------------------
# extract_payload: クライアント別解釈
# ---------------------------------------------------------------------------


def test_extract_payload_claude_code_reads_transcript(tmp_path: pathlib.Path) -> None:
    """AC-8: --client claude-code で transcript_path から JSONL を読む。"""
    mod = _load_hook_module()
    transcript = tmp_path / "transcript.jsonl"
    lines = [
        {"type": "user", "message": {"role": "user", "content": "hello"}},
        {"type": "assistant", "message": {"role": "assistant", "content": "hi there"}},
    ]
    transcript.write_text("\n".join(json.dumps(item) for item in lines), encoding="utf-8")
    payload = json.dumps({"transcript_path": str(transcript)})

    text = mod.extract_payload("claude-code", payload)
    assert "User: hello" in text
    assert "Assistant: hi there" in text


def test_extract_payload_codex_reads_transcript(tmp_path: pathlib.Path) -> None:
    """Codex (Claude Code 互換) も transcript_path を解釈する。"""
    mod = _load_hook_module()
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        json.dumps({"role": "user", "content": "codex test"}),
        encoding="utf-8",
    )
    payload = json.dumps({"transcript_path": str(transcript)})

    text = mod.extract_payload("codex", payload)
    assert "User: codex test" in text


def test_extract_payload_cursor_reads_transcript(tmp_path: pathlib.Path) -> None:
    """Cursor も Claude Code 互換の transcript_path を解釈する。"""
    mod = _load_hook_module()
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        json.dumps({"role": "assistant", "content": "cursor test"}),
        encoding="utf-8",
    )
    payload = json.dumps({"transcript_path": str(transcript)})

    text = mod.extract_payload("cursor", payload)
    assert "Assistant: cursor test" in text


def test_extract_payload_antigravity_camelcase(tmp_path: pathlib.Path) -> None:
    """AC-9: --client antigravity で transcriptPath (キャメルケース) を読む。"""
    mod = _load_hook_module()
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        json.dumps({"role": "user", "content": "ag test"}),
        encoding="utf-8",
    )
    payload = json.dumps({"transcriptPath": str(transcript)})

    text = mod.extract_payload("antigravity", payload)
    assert "User: ag test" in text


def test_extract_payload_messages_array_inline() -> None:
    """payload に messages 配列が直接ある場合も解釈できる (transcript_path フォールバック)。"""
    mod = _load_hook_module()
    payload = json.dumps(
        {
            "messages": [
                {"role": "user", "content": "ping"},
                {"role": "assistant", "content": "pong"},
            ],
        }
    )
    text = mod.extract_payload("claude-code", payload)
    assert "User: ping" in text
    assert "Assistant: pong" in text


# ---------------------------------------------------------------------------
# format_transcript_messages: 整形
# ---------------------------------------------------------------------------


def test_format_transcript_messages_simple_string_content() -> None:
    mod = _load_hook_module()
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    text = mod.format_transcript_messages(messages)
    assert text == "User: hi\n\nAssistant: hello"


def test_format_transcript_messages_complex_content_list() -> None:
    """Claude Code の content list 形式 ({type:text, text:...}) を解釈する。"""
    mod = _load_hook_module()
    messages = [
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {"type": "text", "text": "first"},
                    {"type": "text", "text": "second"},
                ],
            },
        },
    ]
    text = mod.format_transcript_messages(messages)
    assert text.startswith("User:")
    assert "first" in text
    assert "second" in text


def test_format_transcript_messages_skips_empty_and_invalid() -> None:
    """空 content / 文字列 / None など壊れたエントリはスキップされる。"""
    mod = _load_hook_module()
    messages = [
        {"role": "user", "content": ""},
        {"role": "assistant", "content": "valid"},
        "not a dict",
        None,
        {"role": "user"},  # content なし
    ]
    text = mod.format_transcript_messages(messages)
    assert "Assistant: valid" in text
    # User の行は (空文字列 + content なし) でスキップされる
    assert "User:" not in text


def test_format_transcript_messages_handles_message_role_priority() -> None:
    """トップレベル role と message.role が両方ある場合、message.role が優先される。"""
    mod = _load_hook_module()
    messages = [
        {
            "type": "user",
            "message": {"role": "assistant", "content": "actually assistant"},
        },
    ]
    text = mod.format_transcript_messages(messages)
    assert text.startswith("Assistant:")


def test_format_transcript_messages_returns_empty_for_empty_list() -> None:
    mod = _load_hook_module()
    assert mod.format_transcript_messages([]) == ""


# ---------------------------------------------------------------------------
# read_jsonl_transcript: ファイル読み込み
# ---------------------------------------------------------------------------


def test_read_jsonl_transcript_skips_unparseable_lines(tmp_path: pathlib.Path) -> None:
    """JSONL のパース不能行はスキップされる (フェイルソフト)。"""
    mod = _load_hook_module()
    transcript = tmp_path / "broken.jsonl"
    transcript.write_text(
        "\n".join(
            [
                json.dumps({"role": "user", "content": "ok"}),
                "this is not json",
                "",  # 空行
                json.dumps({"role": "assistant", "content": "also ok"}),
            ]
        ),
        encoding="utf-8",
    )
    text = mod.read_jsonl_transcript(str(transcript))
    assert "User: ok" in text
    assert "Assistant: also ok" in text


def test_read_jsonl_transcript_empty_file(tmp_path: pathlib.Path) -> None:
    mod = _load_hook_module()
    transcript = tmp_path / "empty.jsonl"
    transcript.write_text("", encoding="utf-8")
    assert mod.read_jsonl_transcript(str(transcript)) == ""


def test_read_jsonl_transcript_japanese_content(tmp_path: pathlib.Path) -> None:
    """マルチバイト (日本語) の content も正しく扱える。"""
    mod = _load_hook_module()
    transcript = tmp_path / "jp.jsonl"
    transcript.write_text(
        json.dumps({"role": "user", "content": "こんにちは"}, ensure_ascii=False),
        encoding="utf-8",
    )
    text = mod.read_jsonl_transcript(str(transcript))
    assert "User: こんにちは" in text


# ---------------------------------------------------------------------------
# _build_parser: --client 引数のバリデーション
# ---------------------------------------------------------------------------


def test_build_parser_default_client_is_raw() -> None:
    mod = _load_hook_module()
    parser = mod._build_parser()
    args = parser.parse_args([])
    assert args.client == "raw"


def test_build_parser_accepts_supported_clients() -> None:
    mod = _load_hook_module()
    parser = mod._build_parser()
    for client in ("raw", "claude-code", "codex", "cursor", "antigravity"):
        args = parser.parse_args(["--client", client])
        assert args.client == client


def test_invalid_client_rejected_via_argparse() -> None:
    """AC-11: --client に不正値を渡すと argparse がエラーで SystemExit する。"""
    mod = _load_hook_module()
    parser = mod._build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--client", "invalid_client"])
