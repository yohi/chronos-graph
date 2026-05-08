"""Unit tests for sanitize_reason."""

from __future__ import annotations

from mcp_gateway.approval.sanitize import sanitize_reason


class TestSanitizeReason:
    def test_returns_none_for_none(self) -> None:
        assert sanitize_reason(None) is None

    def test_returns_none_for_empty_string(self) -> None:
        assert sanitize_reason("") is None

    def test_returns_none_for_whitespace_only(self) -> None:
        assert sanitize_reason("   \t  ") is None

    def test_strips_ascii_control_chars_except_newline(self) -> None:
        assert sanitize_reason("a\x00b\x07c") == "abc"

    def test_collapses_consecutive_whitespace(self) -> None:
        assert sanitize_reason("hello    world\t\tfoo") == "hello world foo"

    def test_trims_outer_whitespace(self) -> None:
        assert sanitize_reason("  reason text  ") == "reason text"

    def test_truncates_to_256_bytes_utf8(self) -> None:
        long = "あ" * 100
        out = sanitize_reason(long)
        assert out is not None
        assert len(out.encode("utf-8")) <= 256
        assert "あ" in out

    def test_preserves_short_ascii(self) -> None:
        assert sanitize_reason("ok") == "ok"

    def test_preserves_unicode_letters(self) -> None:
        assert sanitize_reason("理由: テスト") == "理由: テスト"
