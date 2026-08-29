"""Ingestion guard tests for trust boundary before memory save."""

from __future__ import annotations

import pytest

from context_store.ingestion.guard import (
    ContentRejected,
    inspect_and_reject_if_unsafe,
)


class TestCredentialRejection:
    """Credential-like strings must be rejected before saving."""

    def test_rejects_api_key(self) -> None:
        content = "Here is my OpenAI API key: sk-abcdefghijklmnopqrstuvwxyz1234"
        with pytest.raises(ContentRejected):
            inspect_and_reject_if_unsafe(content)

    def test_rejects_bearer_token(self) -> None:
        content = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        with pytest.raises(ContentRejected):
            inspect_and_reject_if_unsafe(content)

    def test_rejects_password_assignment(self) -> None:
        content = "password = 'SuperSecret123!'"
        with pytest.raises(ContentRejected):
            inspect_and_reject_if_unsafe(content)


class TestPIIRejection:
    """Personal information must be rejected before saving."""

    def test_rejects_email(self) -> None:
        content = "Contact me at alice.smith@example.co.jp for details"
        with pytest.raises(ContentRejected):
            inspect_and_reject_if_unsafe(content)

    def test_rejects_phone_number(self) -> None:
        content = "Call me at 090-1234-5678"
        with pytest.raises(ContentRejected):
            inspect_and_reject_if_unsafe(content)

    def test_rejects_credit_card(self) -> None:
        content = "My card is 4111-1111-1111-1111"
        with pytest.raises(ContentRejected):
            inspect_and_reject_if_unsafe(content)


class TestOptOutRejection:
    """Explicit opt-out / do-not-save markers must be rejected."""

    def test_rejects_do_not_save(self) -> None:
        content = "This is important but do not save it to memory"
        with pytest.raises(ContentRejected):
            inspect_and_reject_if_unsafe(content)

    def test_rejects_japanese_do_not_save(self) -> None:
        content = "これは保存しないでください"
        with pytest.raises(ContentRejected):
            inspect_and_reject_if_unsafe(content)


class TestSafeContentAllowed:
    """Ordinary technical content should pass inspection."""

    def test_allows_plain_technical_content(self) -> None:
        content = "ChronosGraph uses FastMCP as its MCP server framework."
        assert inspect_and_reject_if_unsafe(content) is None

    def test_allows_command_example_without_secrets(self) -> None:
        content = "Run `uv run pytest tests/unit/ -v` to execute unit tests."
        assert inspect_and_reject_if_unsafe(content) is None


class TestEdgeCases:
    """Boundary conditions for the guard."""

    def test_empty_string_allowed(self) -> None:
        assert inspect_and_reject_if_unsafe("") is None

    def test_none_rejected(self) -> None:
        with pytest.raises(ContentRejected):
            inspect_and_reject_if_unsafe(None)  # type: ignore[arg-type]

    def test_long_content_still_checked(self) -> None:
        content = "x" * 10000 + ' password="secret" ' + "y" * 10000
        with pytest.raises(ContentRejected):
            inspect_and_reject_if_unsafe(content)
