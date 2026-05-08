"""Reason field sanitizer (control-char strip, whitespace normalize, 256-byte truncate)."""

from __future__ import annotations

import re

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_WHITESPACE_RE = re.compile(r"\s+")
_MAX_BYTES = 256


def sanitize_reason(reason: str | None) -> str | None:
    """Normalize and truncate a free-text approval reason for safe logging."""
    if reason is None:
        return None

    cleaned = _CONTROL_CHARS_RE.sub("", reason)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip()
    if not cleaned:
        return None

    encoded = cleaned.encode("utf-8")
    if len(encoded) <= _MAX_BYTES:
        return cleaned

    truncated = encoded[:_MAX_BYTES]
    return truncated.decode("utf-8", errors="ignore")
