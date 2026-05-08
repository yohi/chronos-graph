"""Unit tests for approval decision models."""

from __future__ import annotations

import pytest

from mcp_gateway.approval.models import (
    ApprovalDecision,
    DecisionStatus,
    ResolveOutcome,
)


class TestDecisionStatus:
    def test_enum_values(self) -> None:
        assert DecisionStatus.APPROVED.value == "approved"
        assert DecisionStatus.REJECTED.value == "rejected"
        assert DecisionStatus.TIMEOUT.value == "timeout"

    def test_is_str_enum(self) -> None:
        assert isinstance(DecisionStatus.APPROVED, str)


class TestResolveOutcome:
    def test_enum_values(self) -> None:
        assert ResolveOutcome.OK.value == "ok"
        assert ResolveOutcome.NOT_FOUND.value == "not_found"
        assert ResolveOutcome.ALREADY_RESOLVED.value == "already_resolved"
        assert ResolveOutcome.FORBIDDEN.value == "forbidden"


class TestApprovalDecision:
    def test_default_reason_is_none(self) -> None:
        d = ApprovalDecision(status=DecisionStatus.APPROVED)
        assert d.status is DecisionStatus.APPROVED
        assert d.reason is None

    def test_with_reason(self) -> None:
        d = ApprovalDecision(status=DecisionStatus.REJECTED, reason="not authorized")
        assert d.reason == "not authorized"

    def test_is_frozen(self) -> None:
        d = ApprovalDecision(status=DecisionStatus.APPROVED)
        with pytest.raises((AttributeError, Exception)):
            d.status = DecisionStatus.REJECTED  # type: ignore[misc]
