"""Ingestion guard: reject unsafe content before embedding and storage.

Inspects incoming content for credential-like strings, personally
identifiable information (PII), and explicit opt-out markers. Raises
``ContentRejected`` when any of these are detected.
"""

from __future__ import annotations

import re


class ContentRejected(Exception):
    """Raised when content is rejected by the ingestion trust boundary."""


def inspect_and_reject_if_unsafe(content: str | None) -> None:
    """Inspect content and raise ``ContentRejected`` if it should not be saved.

    Args:
        content: Raw text content intended for memory storage.

    Raises:
        ContentRejected: If the content contains credentials, PII, or an
            explicit opt-out marker.
    """
    if content is None:
        raise ContentRejected("content is required")

    if _contains_opt_out(content):
        raise ContentRejected("content contains an explicit opt-out marker")

    if _contains_credential(content):
        raise ContentRejected("content contains a credential-like string")

    if _contains_pii(content):
        raise ContentRejected("content contains personal information")


def _contains_opt_out(content: str) -> bool:
    """Detect explicit requests not to save the content."""
    markers = [
        r"\bdo not save\b",
        r"\bdon't save\b",
        r"保存しない",
        r"記憶に保存しない",
        r"忘れて",
    ]
    flags = re.IGNORECASE
    return any(re.search(pattern, content, flags) for pattern in markers)


def _contains_credential(content: str) -> bool:
    """Detect common credential-like patterns."""
    patterns = [
        # API keys (sk-... or api_key=...)
        r"\bsk-[a-zA-Z0-9]{16,}\b",
        r"\bapi[_-]?key\s*[:=]\s*['\"]?[a-zA-Z0-9_\-]{16,}['\"]?",
        r"\b[a-z]+_[a-z]+_key\s*[:=]\s*['\"]?[a-zA-Z0-9_\-]{16,}['\"]?",
        # Bearer / JWT / tokens
        r"\bBearer\s+[A-Za-z0-9_\-\.]+",
        r"\btoken\s*[:=]\s*['\"]?[a-zA-Z0-9]{16,}['\"]?",
        # Passwords / secrets
        r"\bpassword\s*[:=]\s*['\"][^'\"]{4,}['\"]",
        r"\bsecret\s*[:=]\s*['\"][^'\"]{8,}['\"]",
        # AWS / generic long credentials
        r"\bAKIA[0-9A-Z]{16}\b",
        r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36}\b",
    ]
    flags = re.IGNORECASE
    return any(re.search(pattern, content, flags) for pattern in patterns)


def _contains_pii(content: str) -> bool:
    """Detect common PII patterns."""
    patterns = [
        # Email addresses
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        # Phone numbers (JP and common international)
        r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{2,4}[-.\s]?\d{3,4}",
        # Credit card (simplified)
        r"(?:\d{4}[-\s]?){3}\d{4}",
    ]
    return any(re.search(pattern, content) for pattern in patterns)
