"""Approval decision models shared between registry, server, and notifier."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DecisionStatus(str, Enum):
    """Final state of a single approval entry."""

    APPROVED = "approved"
    REJECTED = "rejected"
    TIMEOUT = "timeout"


class ResolveOutcome(str, Enum):
    """Result of attempting to resolve an approval through the registry."""

    OK = "ok"
    NOT_FOUND = "not_found"
    ALREADY_RESOLVED = "already_resolved"
    FORBIDDEN = "forbidden"
    INVALID_STATUS = "invalid_status"


@dataclass(frozen=True, slots=True)
class ApprovalDecision:
    """Resolved decision returned to the suspended caller."""

    status: DecisionStatus
    reason: str | None = None
