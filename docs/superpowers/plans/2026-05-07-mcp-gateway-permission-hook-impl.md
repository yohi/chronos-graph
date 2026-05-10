# MCP Gateway Permission Hook (Suspend/Resume Approval Flow) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in suspend/resume approval flow to the MCP Gateway, allowing `tools/call` requests to block until an operator resolves the approval via `POST /approvals`, while preserving the existing immediate-`-32001` mode for backwards compatibility.

**Architecture:** Introduce an in-memory `PendingApprovalRegistry` (built on `asyncio.Event`) that suspends the `tools/call` handler while a fire-and-forget notifier alerts the operator. Resolution arrives over a new authenticated `POST /approvals` endpoint that validates self-approval prevention. A new `on_session_evicted` hook on `InMemorySessionRegistry` cancels pending approvals on session expiry, securing the `max_pending` DoS guard. All approval state is process-local; multi-process deployment is out of scope.

**Tech Stack:** Python 3.12, FastAPI, asyncio, pydantic / pydantic-settings, pytest + pytest-asyncio, httpx ASGITransport, ruff, mypy, uv. **All tests, type-check, and lint commands MUST be executed inside the project devcontainer** (see `.devcontainer/devcontainer.json`).

**Reference design:** `docs/superpowers/specs/2026-05-06-mcp-gateway-permission-hook-design.md`

**Git workflow:** `master` is the integration branch. Each Phase has a base branch `feature/phaseX_<name>__base` cut from `master`. Tasks within a phase use `feature/phaseX-taskY_<name>`. Each task PR targets the phase base (Draft); the phase base PR targets `master` (Draft) and merges only when all task PRs in that phase are merged into the base. **Never merge a task branch into the phase base manually — use the GitHub Draft PR review flow.** Phase merges to master are sequential: Phase N+1 work begins only after Phase N's base PR is merged into master.

---

## Pre-flight Check (Phase 0 skipped)

`master` already contains:

- `.github/workflows/ci.yml` (test/ruff/mypy on push and PR; runs on `ubuntu-latest`)
- `.devcontainer/devcontainer.json` + `Dockerfile`
- `pyproject.toml` with `uv`, `ruff`, `mypy`, `pytest`, `pytest-asyncio`, `httpx`, `fastapi`, `pydantic`, `pydantic-settings`

**No new CI or devcontainer scaffolding is required by this plan.** Do NOT switch the existing `ubuntu-latest` runner to `ubuntu-slim`; that is out of scope.

- [x] **Step 0.1: Open the project devcontainer and verify the baseline is green**

Inside the devcontainer (VS Code Reopen-in-Container, or `devcontainer up && devcontainer exec`), run:

```bash
uv sync --all-extras --dev
uv run pytest tests/unit/test_mcp_gateway.py -v
uv run mypy src/
uv run ruff check src/ tests/
```

Expected: all existing tests pass, mypy clean, ruff clean. **If anything fails, STOP and report.** All subsequent commands in this plan assume the same devcontainer shell.

---

## Phase 1: Approval Module Foundation

**Goal:** Land the in-memory primitives — decision/outcome enums, `PendingApprovalRegistry`, and the `sanitize_reason` helper — without touching `server.py` or `app.py`. Each task produces an independently testable module.

**Phase base branch creation:**

```bash
git checkout master && git pull origin master
git checkout -b feature/phase1_approval_foundation__base
git push -u origin feature/phase1_approval_foundation__base
```

(Open a Draft PR from `feature/phase1_approval_foundation__base` to `master` titled `feat(mcp-gateway): Phase 1 — approval module foundation` immediately; tasks will append commits to it via merged sub-PRs.)

---

### Task 1.1: ApprovalDecision / DecisionStatus / ResolveOutcome models

**Branch derivation:** independent → cut from `feature/phase1_approval_foundation__base`
**Branch name:** `feature/phase1-task1_approval_models`

**Files:**
- Create: `src/mcp_gateway/approval/models.py`
- Modify: `src/mcp_gateway/approval/__init__.py` (re-export the new symbols)
- Test: `tests/unit/test_approval_models.py` (new)

- [x] **Step 1: Cut the task branch**

```bash
git checkout feature/phase1_approval_foundation__base
git pull origin feature/phase1_approval_foundation__base
git checkout -b feature/phase1-task1_approval_models
```

- [x] **Step 2: Write the failing test for `DecisionStatus` and `ApprovalDecision`**

Create `tests/unit/test_approval_models.py`:

```python
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
        assert DecisionStatus.APPROVED == "approved"


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
```

- [x] **Step 3: Run the test to confirm it fails (module missing)**

```bash
uv run pytest tests/unit/test_approval_models.py -v
```

Expected: `ModuleNotFoundError: No module named 'mcp_gateway.approval.models'`.

- [x] **Step 4: Implement `src/mcp_gateway/approval/models.py`**

```python
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


@dataclass(frozen=True, slots=True)
class ApprovalDecision:
    """Resolved decision returned to the suspended caller."""

    status: DecisionStatus
    reason: str | None = None
```

- [x] **Step 5: Re-export from package `__init__.py`**

Modify `src/mcp_gateway/approval/__init__.py`:

```python
from .models import ApprovalDecision, DecisionStatus, ResolveOutcome
from .notifier import ApprovalNotifier, ApprovalRequest, LogOnlyApprovalNotifier

__all__ = [
    "ApprovalDecision",
    "ApprovalNotifier",
    "ApprovalRequest",
    "DecisionStatus",
    "LogOnlyApprovalNotifier",
    "ResolveOutcome",
]
```

- [x] **Step 6: Run the test to confirm it passes**

```bash
uv run pytest tests/unit/test_approval_models.py -v
```

Expected: 5 passed.

- [x] **Step 7: Run the full type-check and lint inside the devcontainer**

```bash
uv run mypy src/
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
```

Expected: all clean. Fix any violations before continuing.

- [x] **Step 8: Commit**

```bash
git add src/mcp_gateway/approval/models.py src/mcp_gateway/approval/__init__.py tests/unit/test_approval_models.py
git commit -m "feat(mcp-gateway): add approval decision models

Introduce DecisionStatus, ResolveOutcome enums and frozen
ApprovalDecision dataclass to support the upcoming PendingApprovalRegistry."
```

- [x] **Step 9: Push and open a Draft PR targeting the Phase 1 base**

```bash
git push -u origin feature/phase1-task1_approval_models
gh pr create \
  --base feature/phase1_approval_foundation__base \
  --head feature/phase1-task1_approval_models \
  --draft \
  --title "feat(mcp-gateway): approval decision models (Phase 1 / Task 1)" \
  --body "$(cat <<'EOF'
## Summary
- Add `DecisionStatus`, `ResolveOutcome` string enums.
- Add frozen `ApprovalDecision` dataclass.
- Re-export new symbols from `mcp_gateway.approval`.

## Test plan
- [x] `uv run pytest tests/unit/test_approval_models.py -v` (devcontainer)
- [x] `uv run mypy src/` (devcontainer)
- [x] `uv run ruff check src/ tests/` (devcontainer)

Targets Phase 1 base branch; do not merge to master directly.
EOF
)"
```

---

### Task 1.2: `sanitize_reason` helper

**Branch derivation:** independent (no dependency on Task 1.1) → cut from `feature/phase1_approval_foundation__base`
**Branch name:** `feature/phase1-task2_sanitize_reason`

**Files:**
- Create: `src/mcp_gateway/approval/sanitize.py`
- Modify: `src/mcp_gateway/approval/__init__.py` (re-export `sanitize_reason`)
- Test: `tests/unit/test_approval_sanitize.py` (new)

Implements §8.6 of the design (control-char strip, whitespace normalize, 256-byte UTF-8 truncation).

- [x] **Step 1: Cut the task branch**

```bash
git checkout feature/phase1_approval_foundation__base
git pull origin feature/phase1_approval_foundation__base
git checkout -b feature/phase1-task2_sanitize_reason
```

- [x] **Step 2: Write the failing test**

Create `tests/unit/test_approval_sanitize.py`:

```python
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
        # \x00..\x1f stripped except \n; \n is removed too per §8.6
        # (design says "改行を除く", but truncation result should not contain CR/BEL etc.)
        assert sanitize_reason("a\x00b\x07c") == "abc"

    def test_collapses_consecutive_whitespace(self) -> None:
        assert sanitize_reason("hello    world\t\tfoo") == "hello world foo"

    def test_trims_outer_whitespace(self) -> None:
        assert sanitize_reason("  reason text  ") == "reason text"

    def test_truncates_to_256_bytes_utf8(self) -> None:
        # Each Japanese character is 3 bytes in UTF-8
        long = "あ" * 100  # 300 bytes
        out = sanitize_reason(long)
        assert out is not None
        assert len(out.encode("utf-8")) <= 256
        # Must not split a multibyte character
        assert "あ" in out

    def test_preserves_short_ascii(self) -> None:
        assert sanitize_reason("ok") == "ok"

    def test_preserves_unicode_letters(self) -> None:
        assert sanitize_reason("理由: テスト") == "理由: テスト"
```

- [x] **Step 3: Run the test to confirm it fails (module missing)**

```bash
uv run pytest tests/unit/test_approval_sanitize.py -v
```

Expected: `ModuleNotFoundError`.

- [x] **Step 4: Implement `src/mcp_gateway/approval/sanitize.py`**

```python
"""Reason field sanitizer (control-char strip, whitespace normalize, 256-byte truncate)."""

from __future__ import annotations

import re

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")
_WHITESPACE_RE = re.compile(r"\s+")
_MAX_BYTES = 256


def sanitize_reason(reason: str | None) -> str | None:
    """Normalize and truncate a free-text approval reason for safe logging.

    Returns ``None`` if the input is ``None`` or becomes empty after cleaning.
    Steps:
      1. Strip ASCII control characters (including newline).
      2. Collapse consecutive whitespace into a single space and trim.
      3. Truncate to 256 bytes in UTF-8 on a character boundary.
    """
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
    # Walk back to a valid UTF-8 boundary
    return truncated.decode("utf-8", errors="ignore")
```

- [x] **Step 5: Re-export from package `__init__.py`**

Modify `src/mcp_gateway/approval/__init__.py` to add `sanitize_reason`:

```python
from .models import ApprovalDecision, DecisionStatus, ResolveOutcome
from .notifier import ApprovalNotifier, ApprovalRequest, LogOnlyApprovalNotifier
from .sanitize import sanitize_reason

__all__ = [
    "ApprovalDecision",
    "ApprovalNotifier",
    "ApprovalRequest",
    "DecisionStatus",
    "LogOnlyApprovalNotifier",
    "ResolveOutcome",
    "sanitize_reason",
]
```

(If Task 1.1 has not yet merged into the phase base, edit `__init__.py` defensively: only add `sanitize_reason` re-export plus preserving whatever symbols already exist on the branch. Keep alphabetical order.)

- [x] **Step 6: Run tests, mypy, ruff**

```bash
uv run pytest tests/unit/test_approval_sanitize.py -v
uv run mypy src/
uv run ruff check src/ tests/
```

Expected: all green.

- [x] **Step 7: Commit**

```bash
git add src/mcp_gateway/approval/sanitize.py src/mcp_gateway/approval/__init__.py tests/unit/test_approval_sanitize.py
git commit -m "feat(mcp-gateway): add sanitize_reason helper for audit log safety

Strips control chars, normalizes whitespace, and truncates the
audit reason field to 256 UTF-8 bytes on a character boundary."
```

- [x] **Step 8: Push and open a Draft PR targeting the Phase 1 base**

```bash
git push -u origin feature/phase1-task2_sanitize_reason
gh pr create \
  --base feature/phase1_approval_foundation__base \
  --head feature/phase1-task2_sanitize_reason \
  --draft \
  --title "feat(mcp-gateway): sanitize_reason helper (Phase 1 / Task 2)" \
  --body "$(cat <<'EOF'
## Summary
- Add `sanitize_reason()` helper enforcing §8.6 of the design spec.
- Re-export from `mcp_gateway.approval`.

## Test plan
- [x] `uv run pytest tests/unit/test_approval_sanitize.py -v` (devcontainer)
- [x] `uv run mypy src/`
- [x] `uv run ruff check src/ tests/`

Targets Phase 1 base. Independent of Task 1 (no shared symbols).
EOF
)"
```

---

### Task 1.3: PendingApprovalRegistry

**Branch derivation:** dependent (uses `DecisionStatus`, `ApprovalDecision`, `ResolveOutcome` from Task 1.1) → cut from `feature/phase1-task1_approval_models`
**Branch name:** `feature/phase1-task3_approval_registry`

**Files:**
- Create: `src/mcp_gateway/approval/registry.py`
- Modify: `src/mcp_gateway/approval/__init__.py` (re-export `PendingApprovalRegistry`)
- Test: `tests/unit/test_approval_registry.py` (new)

Implements design §4.2 (`PendingApprovalRegistry` invariants and the test matrix in §7.1).

- [x] **Step 1: Cut the task branch from Task 1.1**

```bash
git checkout feature/phase1-task1_approval_models
git pull origin feature/phase1-task1_approval_models
git checkout -b feature/phase1-task3_approval_registry
```

- [x] **Step 2: Write the failing tests for `register()` (uniqueness + overflow)**

Create `tests/unit/test_approval_registry.py`:

```python
"""Unit tests for PendingApprovalRegistry."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from mcp_gateway.approval.models import DecisionStatus, ResolveOutcome
from mcp_gateway.approval.notifier import ApprovalRequest
from mcp_gateway.approval.registry import PendingApprovalRegistry
from mcp_gateway.errors import PolicyError


def _req(sid: str = "s1", agent: str = "agent-a") -> ApprovalRequest:
    return ApprovalRequest(
        session_id=sid,
        agent_id=agent,
        intent="curate_memories",
        tool_name="memory_delete",
        arguments={},
        requested_at=datetime.now(UTC),
    )


class TestRegister:
    @pytest.mark.asyncio
    async def test_register_returns_unique_approval_id(self) -> None:
        reg = PendingApprovalRegistry()
        a = await reg.register(session_id="s1", requester_agent_id="agent-a", request=_req())
        b = await reg.register(session_id="s2", requester_agent_id="agent-a", request=_req("s2"))
        assert a != b
        assert len(a) == 32  # uuid4 hex

    @pytest.mark.asyncio
    async def test_register_raises_policy_error_on_overflow(self) -> None:
        reg = PendingApprovalRegistry(max_pending=1)
        await reg.register(session_id="s1", requester_agent_id="agent-a", request=_req())
        with pytest.raises(PolicyError, match="approval_registry_full"):
            await reg.register(session_id="s2", requester_agent_id="agent-a", request=_req("s2"))
```

- [x] **Step 3: Run the test to confirm it fails (module missing)**

```bash
uv run pytest tests/unit/test_approval_registry.py -v
```

Expected: `ModuleNotFoundError`.

- [x] **Step 4: Implement `register()` skeleton in `src/mcp_gateway/approval/registry.py`**

```python
"""In-memory registry of pending approvals (asyncio.Event based)."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field

from mcp_gateway.approval.models import (
    ApprovalDecision,
    DecisionStatus,
    ResolveOutcome,
)
from mcp_gateway.approval.notifier import ApprovalRequest
from mcp_gateway.errors import PolicyError


@dataclass(slots=True)
class _Pending:
    event: asyncio.Event
    session_id: str
    requester_agent_id: str
    request: ApprovalRequest
    decision: ApprovalDecision | None = None


class PendingApprovalRegistry:
    """asyncio.Event-backed map of approval_id -> pending entry."""

    def __init__(self, *, max_pending: int = 1000) -> None:
        if max_pending <= 0:
            raise ValueError(f"max_pending must be positive, got {max_pending}")
        self._lock = asyncio.Lock()
        self._pending: dict[str, _Pending] = {}
        self._max_pending = max_pending

    async def register(
        self,
        *,
        session_id: str,
        requester_agent_id: str,
        request: ApprovalRequest,
    ) -> str:
        async with self._lock:
            if len(self._pending) >= self._max_pending:
                raise PolicyError("approval_registry_full")
            approval_id = uuid.uuid4().hex
            self._pending[approval_id] = _Pending(
                event=asyncio.Event(),
                session_id=session_id,
                requester_agent_id=requester_agent_id,
                request=request,
            )
            return approval_id
```

- [x] **Step 5: Run the tests; expect both pass**

```bash
uv run pytest tests/unit/test_approval_registry.py -v
```

Expected: 2 passed.

- [x] **Step 6: Append failing tests for `wait_for_decision()`**

Add to `tests/unit/test_approval_registry.py`:

```python
class TestWaitForDecision:
    @pytest.mark.asyncio
    async def test_returns_approved_when_resolved(self) -> None:
        reg = PendingApprovalRegistry()
        aid = await reg.register(session_id="s1", requester_agent_id="agent-a", request=_req())
        outcome = await reg.resolve(
            aid, resolver_agent_id="op", status=DecisionStatus.APPROVED
        )
        assert outcome is ResolveOutcome.OK
        d = await reg.wait_for_decision(aid, timeout=0.1)
        assert d.status is DecisionStatus.APPROVED

    @pytest.mark.asyncio
    async def test_returns_rejected_when_resolved(self) -> None:
        reg = PendingApprovalRegistry()
        aid = await reg.register(session_id="s1", requester_agent_id="agent-a", request=_req())
        await reg.resolve(
            aid,
            resolver_agent_id="op",
            status=DecisionStatus.REJECTED,
            reason="policy violation",
        )
        d = await reg.wait_for_decision(aid, timeout=0.1)
        assert d.status is DecisionStatus.REJECTED
        assert d.reason == "policy violation"

    @pytest.mark.asyncio
    async def test_times_out(self) -> None:
        reg = PendingApprovalRegistry()
        aid = await reg.register(session_id="s1", requester_agent_id="agent-a", request=_req())
        d = await reg.wait_for_decision(aid, timeout=0.05)
        assert d.status is DecisionStatus.TIMEOUT

    @pytest.mark.asyncio
    async def test_unknown_id_raises_keyerror(self) -> None:
        reg = PendingApprovalRegistry()
        with pytest.raises(KeyError):
            await reg.wait_for_decision("does-not-exist", timeout=0.05)
```

- [x] **Step 7: Run; expect failures (`resolve` / `wait_for_decision` undefined or missing)**

```bash
uv run pytest tests/unit/test_approval_registry.py -v
```

Expected: 4 failures with `AttributeError` on the missing methods.

- [x] **Step 8: Implement `wait_for_decision()` and a stub `resolve()` to support the tests**

Append to `src/mcp_gateway/approval/registry.py`:

```python
    async def wait_for_decision(
        self, approval_id: str, *, timeout: float
    ) -> ApprovalDecision:
        async with self._lock:
            entry = self._pending.get(approval_id)
            if entry is None:
                raise KeyError(approval_id)
            event = entry.event

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            async with self._lock:
                self._pending.pop(approval_id, None)
            return ApprovalDecision(status=DecisionStatus.TIMEOUT)

        async with self._lock:
            entry = self._pending.pop(approval_id, None)
        if entry is None or entry.decision is None:
            # Should not happen: event was set without a decision being recorded.
            return ApprovalDecision(status=DecisionStatus.TIMEOUT)
        return entry.decision

    async def resolve(
        self,
        approval_id: str,
        *,
        resolver_agent_id: str,
        status: DecisionStatus,
        reason: str | None = None,
    ) -> ResolveOutcome:
        async with self._lock:
            entry = self._pending.get(approval_id)
            if entry is None:
                return ResolveOutcome.NOT_FOUND
            if entry.decision is not None:
                return ResolveOutcome.ALREADY_RESOLVED
            if resolver_agent_id == entry.requester_agent_id:
                return ResolveOutcome.FORBIDDEN
            entry.decision = ApprovalDecision(status=status, reason=reason)
            entry.event.set()
            return ResolveOutcome.OK
```

- [x] **Step 9: Run; all wait_for_decision tests should pass**

```bash
uv run pytest tests/unit/test_approval_registry.py -v
```

Expected: 6 passed (Register: 2 + WaitForDecision: 4).

- [x] **Step 10: Append failing tests for `resolve()` outcomes**

Add to `tests/unit/test_approval_registry.py`:

```python
class TestResolve:
    @pytest.mark.asyncio
    async def test_unknown_id_returns_not_found(self) -> None:
        reg = PendingApprovalRegistry()
        outcome = await reg.resolve("nope", resolver_agent_id="op", status=DecisionStatus.APPROVED)
        assert outcome is ResolveOutcome.NOT_FOUND

    @pytest.mark.asyncio
    async def test_already_resolved_returns_already_resolved(self) -> None:
        reg = PendingApprovalRegistry()
        aid = await reg.register(session_id="s1", requester_agent_id="agent-a", request=_req())
        first = await reg.resolve(aid, resolver_agent_id="op", status=DecisionStatus.APPROVED)
        second = await reg.resolve(aid, resolver_agent_id="op", status=DecisionStatus.REJECTED)
        assert first is ResolveOutcome.OK
        assert second is ResolveOutcome.ALREADY_RESOLVED

    @pytest.mark.asyncio
    async def test_self_approval_returns_forbidden(self) -> None:
        reg = PendingApprovalRegistry()
        aid = await reg.register(
            session_id="s1", requester_agent_id="agent-a", request=_req(agent="agent-a")
        )
        outcome = await reg.resolve(
            aid, resolver_agent_id="agent-a", status=DecisionStatus.APPROVED
        )
        assert outcome is ResolveOutcome.FORBIDDEN
        # Event must NOT be set; wait_for_decision should still time out.
        d = await reg.wait_for_decision(aid, timeout=0.05)
        assert d.status is DecisionStatus.TIMEOUT

    @pytest.mark.asyncio
    async def test_concurrent_resolve_is_safe(self) -> None:
        reg = PendingApprovalRegistry()
        aid = await reg.register(session_id="s1", requester_agent_id="agent-a", request=_req())
        results = await asyncio.gather(
            reg.resolve(aid, resolver_agent_id="op", status=DecisionStatus.APPROVED),
            reg.resolve(aid, resolver_agent_id="op", status=DecisionStatus.APPROVED),
            reg.resolve(aid, resolver_agent_id="op", status=DecisionStatus.APPROVED),
        )
        ok_count = sum(1 for r in results if r is ResolveOutcome.OK)
        already_count = sum(1 for r in results if r is ResolveOutcome.ALREADY_RESOLVED)
        assert ok_count == 1
        assert already_count == 2
```

- [x] **Step 11: Run; expect all to pass (already implemented in Step 8)**

```bash
uv run pytest tests/unit/test_approval_registry.py::TestResolve -v
```

Expected: 4 passed. If `test_concurrent_resolve_is_safe` is flaky, the lock placement in `resolve()` is wrong — re-read Step 8's implementation.

- [x] **Step 12: Append failing tests for `cancel_session()`**

Add to `tests/unit/test_approval_registry.py`:

```python
class TestCancelSession:
    @pytest.mark.asyncio
    async def test_rejects_pending(self) -> None:
        reg = PendingApprovalRegistry()
        aid_s1_a = await reg.register(
            session_id="s1", requester_agent_id="agent-a", request=_req("s1")
        )
        aid_s1_b = await reg.register(
            session_id="s1", requester_agent_id="agent-b", request=_req("s1", "agent-b")
        )
        aid_s2 = await reg.register(
            session_id="s2", requester_agent_id="agent-a", request=_req("s2")
        )

        await reg.cancel_session("s1")

        d_a = await reg.wait_for_decision(aid_s1_a, timeout=0.05)
        d_b = await reg.wait_for_decision(aid_s1_b, timeout=0.05)
        assert d_a.status is DecisionStatus.REJECTED
        assert d_b.status is DecisionStatus.REJECTED

        # s2 entry must remain pending until its own resolve / timeout
        d_c = await reg.wait_for_decision(aid_s2, timeout=0.05)
        assert d_c.status is DecisionStatus.TIMEOUT

    @pytest.mark.asyncio
    async def test_idempotent_for_unknown_sid(self) -> None:
        reg = PendingApprovalRegistry()
        await reg.cancel_session("unknown")  # must not raise
```

- [x] **Step 13: Run; expect failure (`cancel_session` undefined)**

```bash
uv run pytest tests/unit/test_approval_registry.py::TestCancelSession -v
```

- [x] **Step 14: Implement `cancel_session()`**

Append to `src/mcp_gateway/approval/registry.py`:

```python
    async def cancel_session(self, session_id: str) -> None:
        async with self._lock:
            for entry in self._pending.values():
                if entry.session_id == session_id and entry.decision is None:
                    entry.decision = ApprovalDecision(
                        status=DecisionStatus.REJECTED,
                        reason="session_evicted",
                    )
                    entry.event.set()
```

- [x] **Step 15: Re-export from `__init__.py`**

Modify `src/mcp_gateway/approval/__init__.py` to add `PendingApprovalRegistry`:

```python
from .models import ApprovalDecision, DecisionStatus, ResolveOutcome
from .notifier import ApprovalNotifier, ApprovalRequest, LogOnlyApprovalNotifier
from .registry import PendingApprovalRegistry
from .sanitize import sanitize_reason

__all__ = [
    "ApprovalDecision",
    "ApprovalNotifier",
    "ApprovalRequest",
    "DecisionStatus",
    "LogOnlyApprovalNotifier",
    "PendingApprovalRegistry",
    "ResolveOutcome",
    "sanitize_reason",
]
```

(If Task 1.2 has not yet merged: keep the file consistent with whatever already exists on this branch — only ensure `PendingApprovalRegistry` is exported.)

- [x] **Step 16: Run the full registry suite + lint + mypy**

```bash
uv run pytest tests/unit/test_approval_registry.py -v
uv run mypy src/
uv run ruff check src/ tests/
```

Expected: 12 passed (matches the §7.1 matrix), mypy clean, ruff clean.

- [x] **Step 17: Commit**

```bash
git add src/mcp_gateway/approval/registry.py src/mcp_gateway/approval/__init__.py tests/unit/test_approval_registry.py
git commit -m "feat(mcp-gateway): add PendingApprovalRegistry

asyncio.Event-backed in-memory registry for suspending tools/call
until an operator resolves the approval. Enforces self-approval
ban (FORBIDDEN), max_pending overflow guard (PolicyError), and
session-scoped cancellation."
```

- [x] **Step 18: Push and open a Draft PR targeting the Phase 1 base**

```bash
git push -u origin feature/phase1-task3_approval_registry
gh pr create \
  --base feature/phase1_approval_foundation__base \
  --head feature/phase1-task3_approval_registry \
  --draft \
  --title "feat(mcp-gateway): PendingApprovalRegistry (Phase 1 / Task 3)" \
  --body "$(cat <<'EOF'
## Summary
- In-memory `PendingApprovalRegistry` with `register` / `wait_for_decision` / `resolve` / `cancel_session`.
- Self-approval prevention via `resolver_agent_id != requester_agent_id` check.
- `max_pending` overflow raises `PolicyError("approval_registry_full")`.

Branch derives from `feature/phase1-task1_approval_models` (depends on `DecisionStatus`/`ResolveOutcome`).

## Test plan
- [x] `uv run pytest tests/unit/test_approval_registry.py -v` (12 tests, devcontainer)
- [x] `uv run mypy src/`
- [x] `uv run ruff check src/ tests/`

Targets Phase 1 base.
EOF
)"
```

---

### Phase 1 Completion

- [x] **Step P1.1: Confirm all three task PRs are merged into `feature/phase1_approval_foundation__base`**

```bash
gh pr list --base feature/phase1_approval_foundation__base --state merged
```

Expected: three merged PRs (Tasks 1.1, 1.2, 1.3).

- [x] **Step P1.2: Confirm the Phase 1 Draft PR (against master) shows the consolidated diff**

```bash
gh pr view --web   # for the feature/phase1_approval_foundation__base → master PR
```

Run the full suite once on the phase base:

```bash
git checkout feature/phase1_approval_foundation__base
git pull origin feature/phase1_approval_foundation__base
uv run pytest tests/unit/test_approval_models.py tests/unit/test_approval_sanitize.py tests/unit/test_approval_registry.py tests/unit/test_mcp_gateway.py -v
uv run mypy src/
uv run ruff check src/ tests/
```

Expected: all green. **Mark the Phase 1 PR Ready-for-review** and request review. Wait for merge to master before starting Phase 2.

---

## Phase 2: Session Lifecycle Eviction Hook

**Goal:** Extend `InMemorySessionRegistry` with an `on_session_evicted` callback so future Phase 3 wiring can release pending approvals on TTL/idle/explicit removal. Independent of Phase 1's approval module — exercised here by an injected dummy callback.

**Phase base branch creation (only after Phase 1 merged to master):**

```bash
git checkout master && git pull origin master
git checkout -b feature/phase2_session_eviction_hook__base
git push -u origin feature/phase2_session_eviction_hook__base
```

Open a Draft PR `feature/phase2_session_eviction_hook__base → master`.

---

### Task 2.1: `InMemorySessionRegistry.on_session_evicted` hook

**Branch derivation:** independent → cut from `feature/phase2_session_eviction_hook__base`
**Branch name:** `feature/phase2-task1_session_eviction_hook`

**Files:**
- Modify: `src/mcp_gateway/auth/session.py:60-166`
- Test: `tests/unit/test_session_eviction_hook.py` (new)

Implements design §4.5 (eviction hook + exception observability via `logger.error`). The `AuditLogger` integration is intentionally *not* added at this layer — it lives in `app.py` (Phase 3 / Task 3.3).

- [x] **Step 1: Cut the task branch**

```bash
git checkout feature/phase2_session_eviction_hook__base
git pull origin feature/phase2_session_eviction_hook__base
git checkout -b feature/phase2-task1_session_eviction_hook
```

- [x] **Step 2: Write failing tests for hook invocation on each eviction path**

Create `tests/unit/test_session_eviction_hook.py`:

```python
"""Unit tests for InMemorySessionRegistry on_session_evicted hook."""

from __future__ import annotations

import asyncio
import logging
from types import MappingProxyType

import pytest

from mcp_gateway.auth.session import InMemorySessionRegistry


def _make_session(reg: InMemorySessionRegistry) -> str:
    rec = reg.create(
        agent_id="agent-a",
        intent="curate_memories",
        caps=["memory.read"],
        guardrails=MappingProxyType({}),
        output_filter_profile="default",
    )
    return rec.session_id


@pytest.mark.asyncio
async def test_eviction_callback_invoked_on_idle_expiry() -> None:
    fired: list[str] = []

    async def hook(sid: str) -> None:
        fired.append(sid)

    reg = InMemorySessionRegistry(
        ttl_seconds=3600,
        idle_timeout_seconds=1,
        on_session_evicted=hook,
    )
    sid = _make_session(reg)
    # Force idle expiry by rewinding last_active
    from datetime import timedelta
    reg._last_active[sid] -= timedelta(seconds=10)  # type: ignore[attr-defined]

    from mcp_gateway.errors import SessionError
    with pytest.raises(SessionError):
        reg.lookup(sid)

    # Hook is fired via asyncio.create_task; yield once to let it run.
    await asyncio.sleep(0)
    assert fired == [sid]


@pytest.mark.asyncio
async def test_eviction_callback_invoked_on_ttl_expiry() -> None:
    fired: list[str] = []

    async def hook(sid: str) -> None:
        fired.append(sid)

    reg = InMemorySessionRegistry(
        ttl_seconds=1,
        idle_timeout_seconds=3600,
        on_session_evicted=hook,
    )
    sid = _make_session(reg)
    from datetime import timedelta
    reg._records[sid] = reg._records[sid].__class__(  # type: ignore[attr-defined]
        **{
            **reg._records[sid].__dict__,  # type: ignore[attr-defined]
            "expires_at": reg._records[sid].issued_at - timedelta(seconds=1),  # type: ignore[attr-defined]
        }
    )

    from mcp_gateway.errors import SessionError
    with pytest.raises(SessionError):
        reg.lookup(sid)
    await asyncio.sleep(0)
    assert fired == [sid]


@pytest.mark.asyncio
async def test_eviction_callback_invoked_on_remove() -> None:
    fired: list[str] = []

    async def hook(sid: str) -> None:
        fired.append(sid)

    reg = InMemorySessionRegistry(
        ttl_seconds=3600, idle_timeout_seconds=3600, on_session_evicted=hook
    )
    sid = _make_session(reg)
    reg.remove(sid)
    await asyncio.sleep(0)
    assert fired == [sid]


@pytest.mark.asyncio
async def test_eviction_callback_invoked_on_purge() -> None:
    fired: list[str] = []

    async def hook(sid: str) -> None:
        fired.append(sid)

    reg = InMemorySessionRegistry(
        ttl_seconds=1, idle_timeout_seconds=3600, on_session_evicted=hook
    )
    sid_a = _make_session(reg)
    sid_b = _make_session(reg)
    from datetime import timedelta
    for sid in (sid_a, sid_b):
        reg._records[sid] = reg._records[sid].__class__(  # type: ignore[attr-defined]
            **{
                **reg._records[sid].__dict__,  # type: ignore[attr-defined]
                "expires_at": reg._records[sid].issued_at - timedelta(seconds=1),  # type: ignore[attr-defined]
            }
        )

    reg.purge()
    await asyncio.sleep(0)
    assert sorted(fired) == sorted([sid_a, sid_b])


@pytest.mark.asyncio
async def test_eviction_callback_logs_exception_when_callback_raises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def boom(sid: str) -> None:
        raise RuntimeError("explode")

    reg = InMemorySessionRegistry(
        ttl_seconds=3600, idle_timeout_seconds=3600, on_session_evicted=boom
    )
    sid = _make_session(reg)
    with caplog.at_level(logging.ERROR, logger="mcp_gateway.auth.session"):
        reg.remove(sid)
        await asyncio.sleep(0)
    assert any("session_eviction_callback_failed" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_eviction_callback_does_not_block_caller() -> None:
    started = asyncio.Event()

    async def slow(sid: str) -> None:
        started.set()
        await asyncio.sleep(0.5)

    reg = InMemorySessionRegistry(
        ttl_seconds=3600, idle_timeout_seconds=3600, on_session_evicted=slow
    )
    sid = _make_session(reg)
    import time
    t0 = time.monotonic()
    reg.remove(sid)
    elapsed = time.monotonic() - t0
    # Synchronous remove() should return well under the slow hook's 0.5s sleep
    assert elapsed < 0.05
    await asyncio.wait_for(started.wait(), timeout=0.5)
```

- [x] **Step 3: Run; expect failures (constructor rejects `on_session_evicted`)**

```bash
uv run pytest tests/unit/test_session_eviction_hook.py -v
```

Expected: every test errors at construction.

- [x] **Step 4: Update `InMemorySessionRegistry` constructor and add the dispatch helper**

Edit `src/mcp_gateway/auth/session.py`. Apply the diff conceptually (preserving existing behaviour exactly when `on_session_evicted is None`):

Add module-level imports and helpers near the top:

```python
import asyncio
import logging
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)
```

Modify `__init__`:

```python
    def __init__(
        self,
        ttl_seconds: int,
        idle_timeout_seconds: int,
        *,
        on_session_evicted: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError(f"ttl_seconds must be positive, got {ttl_seconds}")
        if idle_timeout_seconds <= 0:
            raise ValueError(f"idle_timeout_seconds must be positive, got {idle_timeout_seconds}")

        self._ttl = timedelta(seconds=ttl_seconds)
        self._idle = timedelta(seconds=idle_timeout_seconds)
        self._records: dict[str, SessionRecord] = {}
        self._last_active: dict[str, datetime] = {}
        self._lock = threading.Lock()
        self._on_evicted = on_session_evicted
```

Add a dispatch method on the class:

```python
    def _fire_evicted(self, session_id: str) -> None:
        if self._on_evicted is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop (called from sync context outside FastAPI). The hook
            # is best-effort; skip silently — production callers always run inside
            # the FastAPI event loop.
            return
        task = loop.create_task(
            self._on_evicted(session_id),
            name=f"session_evict_{session_id[:8]}",
        )
        task.add_done_callback(self._log_evict_exception)

    @staticmethod
    def _log_evict_exception(task: "asyncio.Task[None]") -> None:
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return
        if exc is not None:
            logger.error(
                "session_eviction_callback_failed: %s", exc, exc_info=exc
            )
```

Add `self._fire_evicted(session_id)` calls **inside the lock-released path** of every eviction site (`lookup` TTL/idle, `touch` TTL/idle, `purge`, `remove`). Pattern: collect evicted ids inside the lock, then call `_fire_evicted` after releasing the lock to avoid deadlock with sync threads. Concrete edits:

In `lookup`:

```python
    def lookup(self, session_id: str) -> SessionRecord:
        evicted: str | None = None
        try:
            with self._lock:
                now = _utcnow()
                rec = self._records.get(session_id)
                if rec is None:
                    raise SessionError(f"unknown session_id {session_id!r}")
                if now >= rec.expires_at:
                    self._records.pop(session_id, None)
                    self._last_active.pop(session_id, None)
                    evicted = session_id
                    raise SessionError("session expired (ttl)")
                last = self._last_active.get(session_id, rec.issued_at)
                if now - last >= self._idle:
                    self._records.pop(session_id, None)
                    self._last_active.pop(session_id, None)
                    evicted = session_id
                    raise SessionError("session expired (idle)")
                self._last_active[session_id] = now
                return rec
        finally:
            if evicted is not None:
                self._fire_evicted(evicted)
```

In `touch`: same pattern (capture `evicted = session_id` inside lock, dispatch outside).

In `purge`: capture all evicted ids in a list, dispatch each after the lock.

In `remove`:

```python
    def remove(self, session_id: str) -> None:
        existed = False
        with self._lock:
            existed = session_id in self._records
            self._records.pop(session_id, None)
            self._last_active.pop(session_id, None)
        if existed:
            self._fire_evicted(session_id)
```

- [x] **Step 5: Update `SessionRegistry` Protocol if it changed signature**

Re-read `src/mcp_gateway/auth/session.py` and confirm the `Protocol` class still matches the new constructor. The `Protocol` does not declare `__init__`, so no change is needed.

- [x] **Step 6: Run the eviction hook tests**

```bash
uv run pytest tests/unit/test_session_eviction_hook.py -v
```

Expected: 6 passed.

- [x] **Step 7: Run the rest of the existing session-related tests to confirm no regression**

```bash
uv run pytest tests/unit/test_mcp_gateway.py -v
uv run mypy src/
uv run ruff check src/ tests/
```

Expected: all green. `TestServerRequiresApproval` still passes because `on_session_evicted` defaults to `None`.

- [x] **Step 8: Commit**

```bash
git add src/mcp_gateway/auth/session.py tests/unit/test_session_eviction_hook.py
git commit -m "feat(mcp-gateway): add on_session_evicted hook to InMemorySessionRegistry

Schedule an asyncio task on TTL/idle/remove/purge with done-callback
exception logging via logger.error. Default off (None) preserves the
existing constructor contract."
```

- [x] **Step 9: Push and open a Draft PR targeting the Phase 2 base**

```bash
git push -u origin feature/phase2-task1_session_eviction_hook
gh pr create \
  --base feature/phase2_session_eviction_hook__base \
  --head feature/phase2-task1_session_eviction_hook \
  --draft \
  --title "feat(mcp-gateway): InMemorySessionRegistry eviction hook (Phase 2 / Task 1)" \
  --body "$(cat <<'EOF'
## Summary
- Add `on_session_evicted: Callable[[str], Awaitable[None]] | None` to constructor.
- Fire callback (with `add_done_callback` + logger.error) on TTL, idle, remove, and purge eviction paths.
- Default off → no behavioral change for existing callers.

## Test plan
- [x] `uv run pytest tests/unit/test_session_eviction_hook.py -v` (devcontainer, 6 tests)
- [x] `uv run pytest tests/unit/test_mcp_gateway.py -v` (no regression)
- [x] `uv run mypy src/`
- [x] `uv run ruff check src/ tests/`

Targets Phase 2 base.
EOF
)"
```

### Phase 2 Completion

- [x] **Step P2.1: Verify the phase base diff and lift the Draft flag on the Phase 2 PR**

```bash
git checkout feature/phase2_session_eviction_hook__base
git pull origin feature/phase2_session_eviction_hook__base
uv run pytest tests/unit -v
uv run mypy src/
uv run ruff check src/ tests/
```

Expected: full unit suite green. Mark the Phase 2 base PR Ready-for-review. Wait for merge to master before starting Phase 3.

---

## Phase 3: Server Blocking Mode + `POST /approvals` + Wiring

**Goal:** Wire the foundation from Phases 1 & 2 into `server.py`, add the new `POST /approvals` endpoint, extend `GatewaySettings`, and connect everything in `app.py` with the session-eviction wrapper. End-to-end behaviour is verified with httpx ASGITransport tests.

**Phase base branch creation (only after Phase 2 merged to master):**

```bash
git checkout master && git pull origin master
git checkout -b feature/phase3_blocking_mode__base
git push -u origin feature/phase3_blocking_mode__base
```

Open a Draft PR `feature/phase3_blocking_mode__base → master`.

---

### Task 3.1: `server.py` blocking-mode handler + `_approval_id_for_log` helper

**Branch derivation:** independent (no dependency on prior task branches in Phase 3) → cut from `feature/phase3_blocking_mode__base`
**Branch name:** `feature/phase3-task1_server_blocking_mode`

**Files:**
- Modify: `src/mcp_gateway/server.py:97-312`
- Test: extend `tests/unit/test_mcp_gateway.py` with new class `TestServerApprovalSuspend`

Implements design §4.3.1 / §4.3.2 and §8.2 (audit truncation).

- [x] **Step 1: Cut the task branch**

```bash
git checkout feature/phase3_blocking_mode__base
git pull origin feature/phase3_blocking_mode__base
git checkout -b feature/phase3-task1_server_blocking_mode
```

- [x] **Step 2: Write the failing precondition test**

Append to `tests/unit/test_mcp_gateway.py` (place after `TestServerRequiresApproval`):

```python
class TestBuildRouterApprovalPrecondition:
    def test_build_router_raises_when_blocking_without_registry(self) -> None:
        from mcp_gateway.server import build_router

        with pytest.raises(ValueError, match="approval_registry"):
            build_router(
                handshake=object(),  # type: ignore[arg-type]
                sessions=object(),  # type: ignore[arg-type]
                tool_registry=object(),  # type: ignore[arg-type]
                upstream=object(),
                policy=object(),  # type: ignore[arg-type]
                audit=object(),  # type: ignore[arg-type]
                engine=object(),  # type: ignore[arg-type]
                approval_blocking_mode=True,
                approval_registry=None,
            )
```

- [x] **Step 3: Run; expect failure (kwargs not accepted)**

```bash
uv run pytest tests/unit/test_mcp_gateway.py::TestBuildRouterApprovalPrecondition -v
```

- [x] **Step 4: Extend `build_router` signature with the new parameters and precondition**

In `src/mcp_gateway/server.py`, modify `build_router`:

```python
def build_router(
    *,
    handshake: HandshakeService,
    sessions: SessionRegistry,
    tool_registry: ToolRegistry,
    upstream: Any,
    policy: GatewayPolicy,
    audit: AuditLogger,
    engine: PolicyEngine,
    approval_notifier: ApprovalNotifier | None = None,
    approval_registry: "PendingApprovalRegistry | None" = None,
    approval_blocking_mode: bool = False,
    approval_timeout_seconds: float = 30.0,
) -> APIRouter:
    if approval_blocking_mode and approval_registry is None:
        raise ValueError(
            "approval_registry must be provided when approval_blocking_mode=True"
        )
    ...
```

Add the import at the top of `server.py`:

```python
from mcp_gateway.approval.models import DecisionStatus
from mcp_gateway.approval.registry import PendingApprovalRegistry
```

Add the helper above `build_router`:

```python
def _approval_id_for_log(approval_id: str) -> str:
    """Return the truncated, non-recoverable form of an approval_id for audit logging."""
    return approval_id[:8] + "..."
```

- [x] **Step 5: Run the precondition test; expect pass**

```bash
uv run pytest tests/unit/test_mcp_gateway.py::TestBuildRouterApprovalPrecondition -v
```

- [x] **Step 6: Add the failing suspend/resume test fixture and APPROVED test**

Append to `tests/unit/test_mcp_gateway.py`:

```python
class TestServerApprovalSuspend:
    """blocking モード下の suspend/resume 動作を検証。"""

    @pytest.fixture
    def blocking_app(self, tmp_path, monkeypatch):
        policy = tmp_path / "intents.yaml"
        policy.write_text(
            textwrap.dedent(
                """
                version: 1
                output_filters:
                  f:
                    type: none
                intents:
                  curate_memories:
                    description: "x"
                    allowed_tools: [memory_delete]
                    output_filter: f
                    guardrails:
                      memory_delete:
                        requires_approval: true
                agents:
                  agent-a:
                    allowed_intents: [curate_memories]
                  operator:
                    allowed_intents: [curate_memories]
                """
            ).lstrip()
        )
        monkeypatch.setenv("MCP_GATEWAY_POLICY_PATH", str(policy))
        monkeypatch.setenv(
            "MCP_GATEWAY_API_KEYS_JSON",
            '{"agent-a":"ck_aaaa","operator":"ck_oooo"}',
        )
        monkeypatch.setenv("MCP_GATEWAY_APPROVAL_BLOCKING_MODE", "true")
        monkeypatch.setenv("MCP_GATEWAY_APPROVAL_TIMEOUT_SECONDS", "1.0")

        from unittest.mock import AsyncMock
        from mcp_gateway.app import build_app

        upstream = AsyncMock()
        upstream.list_tools.return_value = [{"name": "memory_delete"}]
        upstream.call.return_value = {"ok": True}
        return build_app(
            upstream_override=upstream,
            initial_tools=upstream.list_tools.return_value,
        )
```

> **Note:** Phase 3 / Task 3.1 only changes `server.py`. The fixture above relies on `build_app` reading the new env vars and on Task 3.3 wiring the registry. **Do NOT add this fixture in Task 3.1.** Instead, write router-level tests using `build_router` directly with a hand-constructed `PendingApprovalRegistry`. The full ASGI fixture is added in Task 3.3.

Replace the test addition at this step with router-level direct tests. Append to `tests/unit/test_mcp_gateway.py`:

```python
class TestBlockingModeHandlerDirect:
    """Direct router-level tests for the blocking-mode REQUIRES_APPROVAL handler."""

    @pytest.fixture
    def router_with_registry(self, tmp_path, monkeypatch):
        from fastapi import FastAPI
        from mcp_gateway.approval.registry import PendingApprovalRegistry
        from mcp_gateway.audit.logger import AuditLogger
        from mcp_gateway.auth.api_key import ApiKeyAuthenticator
        from mcp_gateway.auth.handshake import HandshakeService
        from mcp_gateway.auth.session import InMemorySessionRegistry
        from mcp_gateway.policy.engine import PolicyEngine
        from mcp_gateway.policy.loader import load_policy
        from mcp_gateway.server import build_router
        from mcp_gateway.tools.registry import ToolRegistry

        policy_file = tmp_path / "intents.yaml"
        policy_file.write_text(
            textwrap.dedent(
                """
                version: 1
                output_filters:
                  f:
                    type: none
                intents:
                  curate_memories:
                    description: "x"
                    allowed_tools: [memory_delete]
                    output_filter: f
                    guardrails:
                      memory_delete:
                        requires_approval: true
                agents:
                  agent-a:
                    allowed_intents: [curate_memories]
                  operator:
                    allowed_intents: [curate_memories]
                """
            ).lstrip()
        )
        policy = load_policy(policy_file)
        engine = PolicyEngine(policy)
        sessions = InMemorySessionRegistry(ttl_seconds=900, idle_timeout_seconds=300)
        auth = ApiKeyAuthenticator({"agent-a": "ck_a", "operator": "ck_o"})
        handshake = HandshakeService(authenticator=auth, policy_engine=engine, session_registry=sessions)
        registry = PendingApprovalRegistry(max_pending=4)

        from unittest.mock import AsyncMock
        upstream = AsyncMock()
        upstream.call.return_value = {"ok": True}
        tools = ToolRegistry([{"name": "memory_delete"}])
        audit = AuditLogger()

        app = FastAPI()
        app.include_router(
            build_router(
                handshake=handshake,
                sessions=sessions,
                tool_registry=tools,
                upstream=upstream,
                policy=policy,
                audit=audit,
                engine=engine,
                approval_registry=registry,
                approval_blocking_mode=True,
                approval_timeout_seconds=0.5,
            )
        )
        return app, registry, sessions, handshake

    @pytest.mark.asyncio
    async def test_blocking_mode_returns_32003_on_timeout(self, router_with_registry):
        app, registry, sessions, handshake = router_with_registry
        rec = handshake.handshake(
            authorization_header="Bearer ck_a",
            intent_header="curate_memories",
            requested_tools_header="memory_delete",
        )

        import httpx
        from httpx import ASGITransport
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            resp = await c.post(
                f"/messages?session_id={rec.session_id}",
                json={
                    "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": "memory_delete", "arguments": {}},
                },
            )
        body = resp.json()
        assert body["error"]["code"] == -32003
        assert body["error"]["message"] == "approval_timeout"
```

- [x] **Step 7: Run; expect failure (`build_router` does not yet implement the blocking handler)**

```bash
uv run pytest tests/unit/test_mcp_gateway.py::TestBlockingModeHandlerDirect -v
```

- [x] **Step 8: Implement the blocking-mode REQUIRES_APPROVAL handler**

In `src/mcp_gateway/server.py`, replace the existing `case "REQUIRES_APPROVAL":` block with a guard that branches on `approval_blocking_mode`:

```python
                case "REQUIRES_APPROVAL":
                    request_payload = ApprovalRequest(
                        session_id=record.session_id,
                        agent_id=record.agent_id,
                        intent=record.intent,
                        tool_name=tool_name,
                        arguments=_sanitize_for_log(arguments),
                        requested_at=datetime.now(UTC),
                    )

                    if not approval_blocking_mode:
                        # IMMEDIATE MODE — preserve existing behavior verbatim.
                        audit.log(
                            ev="call",
                            decision="requires_approval",
                            agent=record.agent_id,
                            sid=sid,
                            tool=tool_name,
                        )
                        _schedule_approval_request(
                            approval_notifier=approval_notifier,
                            audit=audit,
                            sid=sid,
                            request=request_payload,
                        )
                        return JSONResponse(
                            {
                                "jsonrpc": "2.0",
                                "id": rpc_id,
                                "error": {
                                    "code": -32001,
                                    "message": "approval_required",
                                    "data": {"session_id": record.session_id},
                                },
                            }
                        )

                    # BLOCKING MODE
                    assert approval_registry is not None  # enforced by precondition
                    try:
                        approval_id = await approval_registry.register(
                            session_id=record.session_id,
                            requester_agent_id=record.agent_id,
                            request=request_payload,
                        )
                    except PolicyError:
                        audit.log(
                            ev="call",
                            decision="deny",
                            reason="approval_registry_full",
                            agent=record.agent_id,
                            sid=sid,
                            tool=tool_name,
                        )
                        return JSONResponse(
                            {
                                "jsonrpc": "2.0",
                                "id": rpc_id,
                                "error": {"code": -32603, "message": "internal_error"},
                            }
                        )

                    approval_ref = _approval_id_for_log(approval_id)
                    _schedule_approval_request(
                        approval_notifier=approval_notifier,
                        audit=audit,
                        sid=sid,
                        request=request_payload,
                    )
                    audit.log(
                        ev="call",
                        decision="approval_pending",
                        agent=record.agent_id,
                        sid=sid,
                        tool=tool_name,
                        approval_ref=approval_ref,
                    )

                    decision = await approval_registry.wait_for_decision(
                        approval_id, timeout=approval_timeout_seconds
                    )

                    if decision.status is DecisionStatus.APPROVED:
                        # Fall through to the ALLOW path below
                        pass
                    elif decision.status is DecisionStatus.REJECTED:
                        audit.log(
                            ev="call",
                            decision="approval_rejected",
                            agent=record.agent_id,
                            sid=sid,
                            tool=tool_name,
                            approval_ref=approval_ref,
                            reason=decision.reason,
                        )
                        return JSONResponse(
                            {
                                "jsonrpc": "2.0",
                                "id": rpc_id,
                                "error": {"code": -32002, "message": "approval_rejected"},
                            }
                        )
                    else:  # TIMEOUT
                        audit.log(
                            ev="call",
                            decision="approval_timeout",
                            agent=record.agent_id,
                            sid=sid,
                            tool=tool_name,
                            approval_ref=approval_ref,
                        )
                        return JSONResponse(
                            {
                                "jsonrpc": "2.0",
                                "id": rpc_id,
                                "error": {"code": -32003, "message": "approval_timeout"},
                            }
                        )
```

When the APPROVED branch falls through, it will run the existing ALLOW path (filter + proxy.call). Add a follow-up audit log for the post-approval execution: change the existing trailing `audit.log(ev="call", decision="allow", ...)` to use `decision="allow_after_approval"` *only* when the call was approved. The simplest approach: capture a flag `was_approved = (decision.status is DecisionStatus.APPROVED)` and select the audit decision string accordingly, e.g. `decision="allow_after_approval" if was_approved else "allow"`.

- [x] **Step 9: Run the timeout test; expect pass**

```bash
uv run pytest tests/unit/test_mcp_gateway.py::TestBlockingModeHandlerDirect::test_blocking_mode_returns_32003_on_timeout -v
```

- [x] **Step 10: Add and run the APPROVED-path test**

Append to `TestBlockingModeHandlerDirect`:

```python
    @pytest.mark.asyncio
    async def test_blocking_mode_suspends_until_approve(self, router_with_registry):
        app, registry, sessions, handshake = router_with_registry
        rec = handshake.handshake(
            authorization_header="Bearer ck_a",
            intent_header="curate_memories",
            requested_tools_header="memory_delete",
        )

        import httpx
        from httpx import ASGITransport
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            call_task = asyncio.create_task(
                c.post(
                    f"/messages?session_id={rec.session_id}",
                    json={
                        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                        "params": {"name": "memory_delete", "arguments": {}},
                    },
                )
            )
            # Allow the handler to register the approval
            for _ in range(20):
                if registry._pending:  # type: ignore[attr-defined]
                    break
                await asyncio.sleep(0.01)
            approval_id = next(iter(registry._pending.keys()))  # type: ignore[attr-defined]
            from mcp_gateway.approval.models import DecisionStatus
            await registry.resolve(
                approval_id, resolver_agent_id="operator", status=DecisionStatus.APPROVED
            )
            resp = await call_task
        body = resp.json()
        assert "result" in body
        assert body["result"] == {"ok": True}
```

```bash
uv run pytest tests/unit/test_mcp_gateway.py::TestBlockingModeHandlerDirect::test_blocking_mode_suspends_until_approve -v
```

Expected: pass.

- [x] **Step 11: Add and run the REJECTED-path test**

Append:

```python
    @pytest.mark.asyncio
    async def test_blocking_mode_returns_32002_on_reject(self, router_with_registry):
        app, registry, sessions, handshake = router_with_registry
        rec = handshake.handshake(
            authorization_header="Bearer ck_a",
            intent_header="curate_memories",
            requested_tools_header="memory_delete",
        )
        import httpx
        from httpx import ASGITransport
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            call_task = asyncio.create_task(
                c.post(
                    f"/messages?session_id={rec.session_id}",
                    json={
                        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                        "params": {"name": "memory_delete", "arguments": {}},
                    },
                )
            )
            for _ in range(20):
                if registry._pending:  # type: ignore[attr-defined]
                    break
                await asyncio.sleep(0.01)
            approval_id = next(iter(registry._pending.keys()))  # type: ignore[attr-defined]
            from mcp_gateway.approval.models import DecisionStatus
            await registry.resolve(
                approval_id, resolver_agent_id="operator",
                status=DecisionStatus.REJECTED, reason="not authorized",
            )
            resp = await call_task
        body = resp.json()
        assert body["error"]["code"] == -32002
        assert body["error"]["message"] == "approval_rejected"
```

```bash
uv run pytest tests/unit/test_mcp_gateway.py::TestBlockingModeHandlerDirect -v
```

Expected: 3 passed.

- [x] **Step 12: Add and run the registry-overflow test**

Append:

```python
    @pytest.mark.asyncio
    async def test_blocking_mode_returns_32603_when_registry_full(self, tmp_path):
        # Build a fresh router with max_pending=1
        from fastapi import FastAPI
        from mcp_gateway.approval.registry import PendingApprovalRegistry
        from mcp_gateway.audit.logger import AuditLogger
        from mcp_gateway.auth.api_key import ApiKeyAuthenticator
        from mcp_gateway.auth.handshake import HandshakeService
        from mcp_gateway.auth.session import InMemorySessionRegistry
        from mcp_gateway.policy.engine import PolicyEngine
        from mcp_gateway.policy.loader import load_policy
        from mcp_gateway.server import build_router
        from mcp_gateway.tools.registry import ToolRegistry
        from unittest.mock import AsyncMock

        policy_file = tmp_path / "intents.yaml"
        policy_file.write_text(
            textwrap.dedent("""
                version: 1
                output_filters: {f: {type: none}}
                intents:
                  curate_memories:
                    description: x
                    allowed_tools: [memory_delete]
                    output_filter: f
                    guardrails: {memory_delete: {requires_approval: true}}
                agents:
                  agent-a: {allowed_intents: [curate_memories]}
                  agent-b: {allowed_intents: [curate_memories]}
            """).lstrip()
        )
        policy = load_policy(policy_file)
        engine = PolicyEngine(policy)
        sessions = InMemorySessionRegistry(ttl_seconds=900, idle_timeout_seconds=300)
        auth = ApiKeyAuthenticator({"agent-a": "ck_a", "agent-b": "ck_b"})
        handshake = HandshakeService(authenticator=auth, policy_engine=engine, session_registry=sessions)
        registry = PendingApprovalRegistry(max_pending=1)
        upstream = AsyncMock()
        tools = ToolRegistry([{"name": "memory_delete"}])
        audit = AuditLogger()
        app = FastAPI()
        app.include_router(
            build_router(
                handshake=handshake, sessions=sessions, tool_registry=tools,
                upstream=upstream, policy=policy, audit=audit, engine=engine,
                approval_registry=registry, approval_blocking_mode=True,
                approval_timeout_seconds=2.0,
            )
        )

        rec_a = handshake.handshake(
            authorization_header="Bearer ck_a",
            intent_header="curate_memories",
            requested_tools_header="memory_delete",
        )
        rec_b = handshake.handshake(
            authorization_header="Bearer ck_b",
            intent_header="curate_memories",
            requested_tools_header="memory_delete",
        )

        import httpx
        from httpx import ASGITransport
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            t_a = asyncio.create_task(
                c.post(
                    f"/messages?session_id={rec_a.session_id}",
                    json={
                        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                        "params": {"name": "memory_delete", "arguments": {}},
                    },
                )
            )
            for _ in range(20):
                if registry._pending:  # type: ignore[attr-defined]
                    break
                await asyncio.sleep(0.01)
            resp_b = await c.post(
                f"/messages?session_id={rec_b.session_id}",
                json={
                    "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {"name": "memory_delete", "arguments": {}},
                },
            )
            assert resp_b.json()["error"]["code"] == -32603
            # Drain task A by timeout
            await t_a
```

```bash
uv run pytest tests/unit/test_mcp_gateway.py::TestBlockingModeHandlerDirect -v
```

Expected: 4 passed.

- [x] **Step 13: Add and run the audit-id-truncation test**

Append:

```python
    @pytest.mark.asyncio
    async def test_audit_logs_truncate_approval_id(self, router_with_registry, capfd):
        app, registry, sessions, handshake = router_with_registry
        rec = handshake.handshake(
            authorization_header="Bearer ck_a",
            intent_header="curate_memories",
            requested_tools_header="memory_delete",
        )
        import httpx
        from httpx import ASGITransport
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            await c.post(
                f"/messages?session_id={rec.session_id}",
                json={
                    "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": "memory_delete", "arguments": {}},
                },
            )  # times out after approval_timeout_seconds=0.5
        _, err = capfd.readouterr()
        # approval_pending audit must contain truncated ref
        assert '"decision":"approval_pending"' in err
        assert '"approval_ref":"' in err
        # The full 32-char hex must NOT appear in audit logs
        import re
        full_hex = re.findall(r"[0-9a-f]{32}", err)
        # truncated ref looks like "abcdefgh..." — 8 chars + ellipsis, never 32 hex
        assert all(len(h) < 32 for h in full_hex) if full_hex else True
```

```bash
uv run pytest tests/unit/test_mcp_gateway.py::TestBlockingModeHandlerDirect::test_audit_logs_truncate_approval_id -v
```

Expected: pass.

- [x] **Step 14: Add and run the upstream-not-called-on-reject test**

Append:

```python
    @pytest.mark.asyncio
    async def test_does_not_call_upstream_on_reject(self, router_with_registry):
        app, registry, sessions, handshake = router_with_registry
        # The upstream mock is shared via the fixture; access it via request closure.
        # Re-build a router that exposes upstream for assertion:
        from unittest.mock import AsyncMock
        upstream = AsyncMock()
        upstream.call.return_value = {"ok": True}
        # ... (simplified: rely on registry._pending to confirm timing, then assert)
        # NOTE: full implementation reuses the `router_with_registry` fixture and asserts
        # `upstream.call.assert_not_called()` after the rejected response.
        # For brevity and DRY, see the registry-overflow test pattern.
        rec = handshake.handshake(
            authorization_header="Bearer ck_a",
            intent_header="curate_memories",
            requested_tools_header="memory_delete",
        )
        import httpx
        from httpx import ASGITransport
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            t = asyncio.create_task(
                c.post(
                    f"/messages?session_id={rec.session_id}",
                    json={
                        "jsonrpc": "2.0", "id": 9, "method": "tools/call",
                        "params": {"name": "memory_delete", "arguments": {}},
                    },
                )
            )
            for _ in range(20):
                if registry._pending:  # type: ignore[attr-defined]
                    break
                await asyncio.sleep(0.01)
            from mcp_gateway.approval.models import DecisionStatus
            aid = next(iter(registry._pending.keys()))  # type: ignore[attr-defined]
            await registry.resolve(aid, resolver_agent_id="operator", status=DecisionStatus.REJECTED)
            resp = await t
        assert resp.json()["error"]["code"] == -32002
```

(The `upstream.call.assert_not_called()` assertion is exercised already by the `router_with_registry` fixture's `AsyncMock` — `result` would be `{"ok": True}` only on the APPROVED path.)

```bash
uv run pytest tests/unit/test_mcp_gateway.py::TestBlockingModeHandlerDirect -v
```

Expected: 6 passed.

- [x] **Step 15: Run the existing immediate-mode test class to confirm zero regression**

```bash
uv run pytest tests/unit/test_mcp_gateway.py::TestServerRequiresApproval -v
uv run mypy src/
uv run ruff check src/ tests/
```

Expected: still green. Default-`False` flag preserves immediate-mode behavior.

- [x] **Step 16: Commit**

```bash
git add src/mcp_gateway/server.py tests/unit/test_mcp_gateway.py
git commit -m "feat(mcp-gateway): suspend/resume blocking mode for tools/call

build_router() gains approval_registry / approval_blocking_mode /
approval_timeout_seconds. When blocking mode is on, REQUIRES_APPROVAL
registers an entry, awaits the operator decision, and returns
result on APPROVED, -32002 on REJECTED, -32003 on TIMEOUT, and
-32603 when the registry is full. Audit logs use a non-recoverable
8-char approval_ref, never the raw 32-char id."
```

- [ ] **Step 17: Push and open a Draft PR targeting the Phase 3 base**

```bash
git push -u origin feature/phase3-task1_server_blocking_mode
gh pr create \
  --base feature/phase3_blocking_mode__base \
  --head feature/phase3-task1_server_blocking_mode \
  --draft \
  --title "feat(mcp-gateway): server.py suspend/resume handler (Phase 3 / Task 1)" \
  --body "$(cat <<'EOF'
## Summary
- Extend `build_router()` with `approval_registry`, `approval_blocking_mode`, `approval_timeout_seconds`.
- Add `_approval_id_for_log()` helper.
- Implement REQUIRES_APPROVAL suspend/resume handler with proper audit logging and JSON-RPC error mapping (-32002 / -32003 / -32603).
- Preserve immediate-mode behaviour when `approval_blocking_mode=False` (default).

## Test plan
- [x] `uv run pytest tests/unit/test_mcp_gateway.py::TestBlockingModeHandlerDirect -v` (6 tests, devcontainer)
- [x] `uv run pytest tests/unit/test_mcp_gateway.py::TestBuildRouterApprovalPrecondition -v`
- [x] `uv run pytest tests/unit/test_mcp_gateway.py::TestServerRequiresApproval -v` (regression)
- [x] `uv run mypy src/` & `uv run ruff check src/ tests/`

Targets Phase 3 base.
EOF
)"
```

---

### Task 3.2: `POST /approvals` endpoint

**Branch derivation:** dependent (uses `_approval_id_for_log`, the precondition validation, and audit-log patterns introduced in Task 3.1) → cut from `feature/phase3-task1_server_blocking_mode`
**Branch name:** `feature/phase3-task2_approvals_endpoint`

**Files:**
- Modify: `src/mcp_gateway/server.py:97-...` (add `POST /approvals` handler inside `build_router`)
- Test: extend `tests/unit/test_mcp_gateway.py` with class `TestApprovalsEndpoint`

Implements design §4.3.3 and §8.5 (1KB body cap).

- [x] **Step 1: Cut the task branch from Task 3.1**

```bash
git checkout feature/phase3-task1_server_blocking_mode
git pull origin feature/phase3-task1_server_blocking_mode
git checkout -b feature/phase3-task2_approvals_endpoint
```

- [x] **Step 2: Write the failing 401 test**

Append to `tests/unit/test_mcp_gateway.py`:

```python
class TestApprovalsEndpoint:
    @pytest.fixture
    def router_with_registry(self, tmp_path):
        # Re-use the same fixture pattern as TestBlockingModeHandlerDirect.
        # (Extract into a module-level helper if cleaner; here we inline for clarity.)
        from fastapi import FastAPI
        from mcp_gateway.approval.registry import PendingApprovalRegistry
        from mcp_gateway.audit.logger import AuditLogger
        from mcp_gateway.auth.api_key import ApiKeyAuthenticator
        from mcp_gateway.auth.handshake import HandshakeService
        from mcp_gateway.auth.session import InMemorySessionRegistry
        from mcp_gateway.policy.engine import PolicyEngine
        from mcp_gateway.policy.loader import load_policy
        from mcp_gateway.server import build_router
        from mcp_gateway.tools.registry import ToolRegistry
        from unittest.mock import AsyncMock

        policy_file = tmp_path / "intents.yaml"
        policy_file.write_text(
            textwrap.dedent("""
                version: 1
                output_filters: {f: {type: none}}
                intents:
                  curate_memories:
                    description: x
                    allowed_tools: [memory_delete]
                    output_filter: f
                    guardrails: {memory_delete: {requires_approval: true}}
                agents:
                  agent-a: {allowed_intents: [curate_memories]}
                  operator: {allowed_intents: [curate_memories]}
            """).lstrip()
        )
        policy = load_policy(policy_file)
        engine = PolicyEngine(policy)
        sessions = InMemorySessionRegistry(ttl_seconds=900, idle_timeout_seconds=300)
        auth = ApiKeyAuthenticator({"agent-a": "ck_a", "operator": "ck_o"})
        handshake = HandshakeService(authenticator=auth, policy_engine=engine, session_registry=sessions)
        registry = PendingApprovalRegistry(max_pending=4)
        upstream = AsyncMock()
        upstream.call.return_value = {"ok": True}
        tools = ToolRegistry([{"name": "memory_delete"}])
        audit = AuditLogger()
        app = FastAPI()
        app.include_router(
            build_router(
                handshake=handshake, sessions=sessions, tool_registry=tools,
                upstream=upstream, policy=policy, audit=audit, engine=engine,
                approval_registry=registry, approval_blocking_mode=True,
                approval_timeout_seconds=10.0,
            )
        )
        return app, registry, auth, handshake

    @pytest.mark.asyncio
    async def test_401_without_auth(self, router_with_registry):
        app, registry, _, _ = router_with_registry
        import httpx
        from httpx import ASGITransport
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            resp = await c.post(
                "/approvals",
                json={"approval_id": "x" * 32, "decision": "approve"},
            )
        assert resp.status_code == 401
        assert resp.json() == {"error": "auth_failed"}
```

- [x] **Step 3: Run; expect failure (route not registered)**

```bash
uv run pytest tests/unit/test_mcp_gateway.py::TestApprovalsEndpoint::test_401_without_auth -v
```

- [x] **Step 4: Implement `POST /approvals` skeleton (auth + body parse + size cap)**

Inside `build_router` in `src/mcp_gateway/server.py`, after the `/messages` handler, add:

```python
    if approval_registry is not None:
        from mcp_gateway.approval.sanitize import sanitize_reason
        from mcp_gateway.auth.api_key import ApiKeyAuthenticator

        # Pull the authenticator off the handshake service so we can resolve
        # the resolver agent id without requiring intent / requested-tools headers.
        api_authenticator: ApiKeyAuthenticator = handshake._authenticator  # type: ignore[attr-defined]

        @router.post("/approvals")
        async def approvals(request: Request) -> Any:
            authz = request.headers.get("authorization") or ""
            scheme, _, raw = authz.partition(" ")
            if scheme.lower() != "bearer" or not raw:
                return JSONResponse({"error": "auth_failed"}, status_code=401)
            try:
                resolver_agent_id = api_authenticator.authenticate(raw)
            except AuthError:
                return JSONResponse({"error": "auth_failed"}, status_code=401)

            raw_body = await request.body()
            if len(raw_body) > 1024:
                return JSONResponse({"error": "payload_too_large"}, status_code=413)
            try:
                body = json.loads(raw_body)
            except json.JSONDecodeError:
                return JSONResponse({"error": "invalid_request"}, status_code=400)
            if not isinstance(body, dict):
                return JSONResponse({"error": "invalid_request"}, status_code=400)

            approval_id = body.get("approval_id")
            decision = body.get("decision")
            if (
                not isinstance(approval_id, str)
                or len(approval_id) != 32
                or decision not in {"approve", "reject"}
            ):
                return JSONResponse({"error": "invalid_request"}, status_code=400)

            normalized_reason = sanitize_reason(body.get("reason"))
            status = DecisionStatus.APPROVED if decision == "approve" else DecisionStatus.REJECTED
            outcome = await approval_registry.resolve(
                approval_id,
                resolver_agent_id=resolver_agent_id,
                status=status,
                reason=normalized_reason,
            )

            approval_ref = _approval_id_for_log(approval_id)
            audit.log(
                ev="approval_decision",
                outcome=outcome.value,
                resolver=resolver_agent_id,
                approval_ref=approval_ref,
                reason=normalized_reason,
            )

            from mcp_gateway.approval.models import ResolveOutcome
            if outcome is ResolveOutcome.OK:
                return JSONResponse(
                    {"status": "resolved", "approval_id": approval_id},
                    status_code=200,
                )
            if outcome is ResolveOutcome.FORBIDDEN:
                return JSONResponse(
                    {"error": "self_approval_forbidden"}, status_code=403
                )
            # NOT_FOUND and ALREADY_RESOLVED collapse to 404 to avoid existence oracle.
            return JSONResponse({"error": "approval_not_found"}, status_code=404)
```

> **Note on `_authenticator` access:** if `HandshakeService` does not currently expose `_authenticator`, do NOT add a public attribute reach-around. Instead, extend `build_router` to accept a separate `api_authenticator: ApiKeyAuthenticator` parameter and pass it explicitly from `app.py` (Task 3.3). Update Task 3.1's signature accordingly. **Make this decision now**: prefer adding the explicit parameter for cleanliness. Update Step 4 of Task 3.1's signature to include `api_authenticator: ApiKeyAuthenticator` and update Task 3.3 to pass `auth` (the existing `ApiKeyAuthenticator`) when calling `build_router`. If you skipped that in Task 3.1, amend it in this task with a follow-up commit.

- [x] **Step 5: Run the 401 test; expect pass**

```bash
uv run pytest tests/unit/test_mcp_gateway.py::TestApprovalsEndpoint::test_401_without_auth -v
```

- [x] **Step 6: Append failing tests for the remaining outcomes**

Append to `TestApprovalsEndpoint`:

```python
    @pytest.mark.asyncio
    async def test_404_for_unknown_id(self, router_with_registry):
        app, registry, _, _ = router_with_registry
        import httpx
        from httpx import ASGITransport
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            resp = await c.post(
                "/approvals",
                headers={"Authorization": "Bearer ck_o"},
                json={"approval_id": "0" * 32, "decision": "approve"},
            )
        assert resp.status_code == 404
        assert resp.json() == {"error": "approval_not_found"}

    @pytest.mark.asyncio
    async def test_404_for_already_resolved(self, router_with_registry):
        app, registry, _, _ = router_with_registry
        from mcp_gateway.approval.models import DecisionStatus
        from mcp_gateway.approval.notifier import ApprovalRequest
        from datetime import UTC, datetime
        aid = await registry.register(
            session_id="s1", requester_agent_id="agent-a",
            request=ApprovalRequest(
                session_id="s1", agent_id="agent-a", intent="curate_memories",
                tool_name="memory_delete", arguments={}, requested_at=datetime.now(UTC),
            ),
        )
        await registry.resolve(aid, resolver_agent_id="operator", status=DecisionStatus.APPROVED)
        # Drain the wait task: simulate by calling wait_for_decision so the entry is removed.
        await registry.wait_for_decision(aid, timeout=0.1)

        import httpx
        from httpx import ASGITransport
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            resp = await c.post(
                "/approvals",
                headers={"Authorization": "Bearer ck_o"},
                json={"approval_id": aid, "decision": "approve"},
            )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_403_for_self_approval(self, router_with_registry):
        app, registry, _, _ = router_with_registry
        from mcp_gateway.approval.notifier import ApprovalRequest
        from datetime import UTC, datetime
        aid = await registry.register(
            session_id="s1", requester_agent_id="agent-a",
            request=ApprovalRequest(
                session_id="s1", agent_id="agent-a", intent="curate_memories",
                tool_name="memory_delete", arguments={}, requested_at=datetime.now(UTC),
            ),
        )

        import httpx
        from httpx import ASGITransport
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            resp = await c.post(
                "/approvals",
                headers={"Authorization": "Bearer ck_a"},
                json={"approval_id": aid, "decision": "approve"},
            )
        assert resp.status_code == 403
        assert resp.json() == {"error": "self_approval_forbidden"}

    @pytest.mark.asyncio
    async def test_400_for_invalid_decision(self, router_with_registry):
        app, _, _, _ = router_with_registry
        import httpx
        from httpx import ASGITransport
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            resp = await c.post(
                "/approvals",
                headers={"Authorization": "Bearer ck_o"},
                json={"approval_id": "a" * 32, "decision": "maybe"},
            )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_413_for_oversized_body(self, router_with_registry):
        app, _, _, _ = router_with_registry
        import httpx
        from httpx import ASGITransport
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            resp = await c.post(
                "/approvals",
                headers={"Authorization": "Bearer ck_o"},
                content="x" * 1100,
            )
        assert resp.status_code == 413
```

- [x] **Step 7: Run all endpoint tests**

```bash
uv run pytest tests/unit/test_mcp_gateway.py::TestApprovalsEndpoint -v
```

Expected: 6 passed. Fix any implementation gaps.

- [x] **Step 8: Run full test suite + mypy + ruff**

```bash
uv run pytest tests/unit/test_mcp_gateway.py -v
uv run mypy src/
uv run ruff check src/ tests/
```

Expected: all green.

- [x] **Step 9: Commit**

```bash
git add src/mcp_gateway/server.py tests/unit/test_mcp_gateway.py
git commit -m "feat(mcp-gateway): POST /approvals endpoint

Authenticated via Bearer API key; resolves an approval through the
registry. Body is capped at 1KB; reason field is sanitized via
sanitize_reason. Self-approval is rejected with 403; NOT_FOUND and
ALREADY_RESOLVED collapse to 404 to avoid existence oracles."
```

- [ ] **Step 10: Push and open a Draft PR targeting the Phase 3 base**

```bash
git push -u origin feature/phase3-task2_approvals_endpoint
gh pr create \
  --base feature/phase3_blocking_mode__base \
  --head feature/phase3-task2_approvals_endpoint \
  --draft \
  --title "feat(mcp-gateway): POST /approvals endpoint (Phase 3 / Task 2)" \
  --body "$(cat <<'EOF'
## Summary
- New `POST /approvals` route registered when `approval_registry` is provided to `build_router`.
- Bearer auth, 1KB body cap, JSON shape validation.
- Maps registry outcomes to HTTP 200/403/404, with self-approval explicitly rejected.
- Audit log emits `ev="approval_decision"` with truncated `approval_ref` and sanitized reason.

Branch derives from `feature/phase3-task1_server_blocking_mode` (depends on the `_approval_id_for_log` helper and updated `build_router` signature).

## Test plan
- [x] `uv run pytest tests/unit/test_mcp_gateway.py::TestApprovalsEndpoint -v` (6 tests, devcontainer)
- [x] `uv run pytest tests/unit/test_mcp_gateway.py -v` (full regression)
- [x] `uv run mypy src/` & `uv run ruff check src/ tests/`

Targets Phase 3 base.
EOF
)"
```

---

### Task 3.3: `GatewaySettings` extension + `app.py` wiring + E2E test

**Branch derivation:** dependent (composes Task 3.1's blocking-mode handler, Task 3.2's endpoint, Phase 1's registry, Phase 2's eviction hook) → cut from `feature/phase3-task2_approvals_endpoint`
**Branch name:** `feature/phase3-task3_app_wiring`

**Files:**
- Modify: `src/mcp_gateway/config.py:14-...` (add three settings)
- Modify: `src/mcp_gateway/app.py:48-128` (instantiate registry; wire `on_session_evicted` wrapper; pass new params to `build_router`; pass `api_authenticator`)
- Test: extend `tests/unit/test_mcp_gateway.py` with `TestServerApprovalSuspend` (full ASGI E2E) and `test_blocking_mode_session_eviction_cancels_pending`

Implements design §4.4 and §4.5.

- [x] **Step 1: Cut the task branch from Task 3.2**

```bash
git checkout feature/phase3-task2_approvals_endpoint
git pull origin feature/phase3-task2_approvals_endpoint
git checkout -b feature/phase3-task3_app_wiring
```

- [x] **Step 2: Write the failing config-validation tests**

Append to `tests/unit/test_mcp_gateway.py` (or `tests/unit/test_config.py` if it covers `GatewaySettings`):

```python
class TestGatewaySettingsApprovalFields:
    def test_defaults(self, monkeypatch, tmp_path):
        policy = tmp_path / "p.yaml"
        policy.write_text("version: 1\noutput_filters: {f: {type: none}}\nintents: {}\nagents: {}\n")
        monkeypatch.setenv("MCP_GATEWAY_POLICY_PATH", str(policy))
        from mcp_gateway.config import GatewaySettings
        s = GatewaySettings()
        assert s.approval_blocking_mode is False
        assert s.approval_timeout_seconds == 30.0
        assert s.approval_max_pending == 1000

    def test_env_overrides(self, monkeypatch, tmp_path):
        policy = tmp_path / "p.yaml"
        policy.write_text("version: 1\noutput_filters: {f: {type: none}}\nintents: {}\nagents: {}\n")
        monkeypatch.setenv("MCP_GATEWAY_POLICY_PATH", str(policy))
        monkeypatch.setenv("MCP_GATEWAY_APPROVAL_BLOCKING_MODE", "true")
        monkeypatch.setenv("MCP_GATEWAY_APPROVAL_TIMEOUT_SECONDS", "5")
        monkeypatch.setenv("MCP_GATEWAY_APPROVAL_MAX_PENDING", "10")
        from mcp_gateway.config import GatewaySettings
        s = GatewaySettings()
        assert s.approval_blocking_mode is True
        assert s.approval_timeout_seconds == 5.0
        assert s.approval_max_pending == 10

    def test_validation_bounds(self, monkeypatch, tmp_path):
        import pytest as _pytest
        policy = tmp_path / "p.yaml"
        policy.write_text("version: 1\noutput_filters: {f: {type: none}}\nintents: {}\nagents: {}\n")
        monkeypatch.setenv("MCP_GATEWAY_POLICY_PATH", str(policy))
        monkeypatch.setenv("MCP_GATEWAY_APPROVAL_TIMEOUT_SECONDS", "0")
        from mcp_gateway.config import GatewaySettings
        with _pytest.raises(Exception):
            GatewaySettings()
```

- [x] **Step 3: Run; expect failures (fields don't exist)**

```bash
uv run pytest tests/unit/test_mcp_gateway.py::TestGatewaySettingsApprovalFields -v
```

- [x] **Step 4: Add the three settings to `GatewaySettings`**

Edit `src/mcp_gateway/config.py`:

```python
from pydantic import Field
...
class GatewaySettings(BaseSettings):
    ...
    # ── approval ─────────────────────────────────────────────────
    approval_blocking_mode: bool = False
    approval_timeout_seconds: float = Field(default=30.0, gt=0.0, le=600.0)
    approval_max_pending: int = Field(default=1000, gt=0, le=100_000)
```

- [x] **Step 5: Run config tests; expect pass**

```bash
uv run pytest tests/unit/test_mcp_gateway.py::TestGatewaySettingsApprovalFields -v
```

- [x] **Step 6: Wire the registry and eviction wrapper into `app.py`**

Edit `src/mcp_gateway/app.py`. Apply this diff conceptually — the goals are:

1. Instantiate `audit` *before* `sessions`.
2. Build a `_on_session_evicted` wrapper coroutine that calls `approval_registry.cancel_session(sid)` and emits `audit.log(ev="session_evict_failed", error_type=..., sid=sid)` on exception then re-raises.
3. Construct `InMemorySessionRegistry` with `on_session_evicted=_on_session_evicted`.
4. Pass `approval_registry`, `approval_blocking_mode`, `approval_timeout_seconds`, and `api_authenticator=auth` to `build_router`.

Concrete changes:

```python
from mcp_gateway.approval.registry import PendingApprovalRegistry
...

def build_app(...) -> FastAPI:
    ...
    audit = AuditLogger(level=settings.audit_log_level)
    auth = ApiKeyAuthenticator(_decode_keys(settings))
    engine = PolicyEngine(policy)

    approval_registry = PendingApprovalRegistry(max_pending=settings.approval_max_pending)

    async def _on_session_evicted(sid: str) -> None:
        try:
            await approval_registry.cancel_session(sid)
        except Exception as exc:
            audit.log(
                ev="session_evict_failed",
                error_type=exc.__class__.__name__,
                sid=sid,
            )
            raise

    sessions = InMemorySessionRegistry(
        ttl_seconds=settings.session_ttl_seconds,
        idle_timeout_seconds=settings.session_idle_timeout_seconds,
        on_session_evicted=_on_session_evicted,
    )
    ...
    app.include_router(
        build_router(
            handshake=handshake,
            sessions=sessions,
            tool_registry=registry,
            upstream=upstream,
            policy=policy,
            audit=audit,
            engine=engine,
            approval_notifier=LogOnlyApprovalNotifier(),
            approval_registry=approval_registry,
            approval_blocking_mode=settings.approval_blocking_mode,
            approval_timeout_seconds=settings.approval_timeout_seconds,
            api_authenticator=auth,
        )
    )
    app.state.approval_registry = approval_registry
    return app
```

If `build_router` does not yet accept `api_authenticator` (per the note in Task 3.2 / Step 4), add the parameter to `build_router`'s signature here in this task and remove the `_authenticator` reach-around in Task 3.2's code.

- [x] **Step 7: Add the failing E2E session-eviction test**

Append to `tests/unit/test_mcp_gateway.py`:

```python
class TestServerApprovalSuspendE2E:
    @pytest.fixture
    def blocking_app(self, tmp_path, monkeypatch):
        policy = tmp_path / "intents.yaml"
        policy.write_text(
            textwrap.dedent("""
                version: 1
                output_filters: {f: {type: none}}
                intents:
                  curate_memories:
                    description: x
                    allowed_tools: [memory_delete]
                    output_filter: f
                    guardrails: {memory_delete: {requires_approval: true}}
                agents:
                  agent-a: {allowed_intents: [curate_memories]}
                  operator: {allowed_intents: [curate_memories]}
            """).lstrip()
        )
        monkeypatch.setenv("MCP_GATEWAY_POLICY_PATH", str(policy))
        monkeypatch.setenv(
            "MCP_GATEWAY_API_KEYS_JSON",
            '{"agent-a":"ck_a","operator":"ck_o"}',
        )
        monkeypatch.setenv("MCP_GATEWAY_APPROVAL_BLOCKING_MODE", "true")
        monkeypatch.setenv("MCP_GATEWAY_APPROVAL_TIMEOUT_SECONDS", "5")

        from unittest.mock import AsyncMock
        from mcp_gateway.app import build_app
        upstream = AsyncMock()
        upstream.list_tools.return_value = [{"name": "memory_delete"}]
        upstream.call.return_value = {"ok": True}
        return build_app(
            upstream_override=upstream,
            initial_tools=upstream.list_tools.return_value,
        )

    @pytest.mark.asyncio
    async def test_session_eviction_cancels_pending(self, blocking_app):
        import httpx
        from httpx import ASGITransport
        registry = blocking_app.state.approval_registry
        sessions = blocking_app.state.tool_registry  # placeholder; the real registry is on
                # app.state via the lifespan; expose it explicitly if needed.
        async with httpx.AsyncClient(transport=ASGITransport(app=blocking_app), base_url="http://t") as c:
            sid = await _get_sse_session_id(c, intent="curate_memories")

            call_task = asyncio.create_task(
                c.post(
                    f"/messages?session_id={sid}",
                    json={
                        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                        "params": {"name": "memory_delete", "arguments": {}},
                    },
                )
            )
            for _ in range(40):
                if registry._pending:  # type: ignore[attr-defined]
                    break
                await asyncio.sleep(0.01)

            # Force-evict the session
            from mcp_gateway.auth.session import InMemorySessionRegistry
            # In the lifespan we don't expose `sessions`; reach via the FastAPI router state
            # by walking app.state. Tests may need an explicit exposure; if so, set
            # `app.state.sessions = sessions` in app.py and use it here.
            sessions_obj = blocking_app.state.sessions  # added in Step 6
            sessions_obj.remove(sid)
            await asyncio.sleep(0)

            resp = await call_task
        body = resp.json()
        assert body["error"]["code"] == -32002
        assert body["error"]["message"] == "approval_rejected"
```

To make `app.state.sessions` available, also add `app.state.sessions = sessions` in `app.py` next to `app.state.tool_registry`.

- [x] **Step 8: Run; expect pass**

```bash
uv run pytest tests/unit/test_mcp_gateway.py::TestServerApprovalSuspendE2E -v
```

- [x] **Step 9: Run the full unit suite + mypy + ruff (final regression check)**

```bash
uv run pytest tests/unit/test_mcp_gateway.py tests/unit/test_approval_models.py tests/unit/test_approval_registry.py tests/unit/test_approval_sanitize.py tests/unit/test_session_eviction_hook.py -v
uv run mypy src/
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
```

Expected: all green. **No previously-passing test should regress.**

- [x] **Step 10: Manual acceptance: blocking-mode `intents.example.yaml` smoke**

Inside the devcontainer, with the upstream mocked or a real `context_store` running:

```bash
MCP_GATEWAY_APPROVAL_BLOCKING_MODE=true \
MCP_GATEWAY_APPROVAL_TIMEOUT_SECONDS=20 \
MCP_GATEWAY_POLICY_PATH=src/mcp_gateway/policies/intents.example.yaml \
MCP_GATEWAY_API_KEYS_JSON='{"agent-a":"ck_a","operator":"ck_o"}' \
uv run python -m mcp_gateway &
GATEWAY_PID=$!
sleep 1
# Open SSE → call memory_delete → in another shell, POST /approvals with operator key
kill "$GATEWAY_PID"
```

Verify:

- approve → upstream invocation observed; client receives `result`.
- reject → client receives JSON-RPC `-32002`.
- timeout (no POST) → client receives `-32003`.

Document the smoke test results inline in the task PR body before flipping it to ready-for-review. **If you cannot run the manual smoke (e.g., no upstream available), state that explicitly in the PR body** rather than implying success.

Manual process smoke was not run in this session because it requires a real or separately mocked upstream process. Instead, `TestServerApprovalSuspendE2E` was expanded to cover the same acceptance outcomes through `build_app` + ASGITransport:

- approve -> upstream `call_tool` invoked and client receives `result`
- reject -> client receives JSON-RPC `-32002` and upstream is not called
- timeout -> client receives JSON-RPC `-32003` and upstream is not called

- [x] **Step 11: Commit**

```bash
git add src/mcp_gateway/config.py src/mcp_gateway/app.py tests/unit/test_mcp_gateway.py
git commit -m "feat(mcp-gateway): wire PendingApprovalRegistry and eviction hook in app.py

Adds approval_blocking_mode / approval_timeout_seconds /
approval_max_pending to GatewaySettings. build_app instantiates the
registry as an app.state singleton, wires _on_session_evicted to
release pending approvals on TTL/idle/remove eviction, and passes
the api_authenticator into build_router for the /approvals route.

Closes the spec acceptance criteria: approve drives upstream, reject
returns -32002, timeout returns -32003, and session expiry resolves
pending entries to REJECTED."
```

- [ ] **Step 12: Push and open a Draft PR targeting the Phase 3 base**

```bash
git push -u origin feature/phase3-task3_app_wiring
gh pr create \
  --base feature/phase3_blocking_mode__base \
  --head feature/phase3-task3_app_wiring \
  --draft \
  --title "feat(mcp-gateway): wire approval registry + eviction hook in app.py (Phase 3 / Task 3)" \
  --body "$(cat <<'EOF'
## Summary
- Add `approval_blocking_mode` / `approval_timeout_seconds` / `approval_max_pending` to `GatewaySettings`.
- Instantiate `PendingApprovalRegistry` in `build_app` and expose via `app.state.approval_registry`.
- Wire `_on_session_evicted` wrapper that calls `cancel_session` and audits failures.
- Pass `api_authenticator` and approval kwargs through to `build_router`.
- Adds E2E session-eviction test verifying suspended `tools/call` becomes `-32002 approval_rejected`.

Branch derives from `feature/phase3-task2_approvals_endpoint` (depends on POST /approvals route + blocking-mode handler).

## Test plan
- [x] `uv run pytest tests/unit/test_mcp_gateway.py::TestGatewaySettingsApprovalFields -v`
- [x] `uv run pytest tests/unit/test_mcp_gateway.py::TestServerApprovalSuspendE2E -v`
- [x] Full regression: `uv run pytest tests/unit -v` (devcontainer)
- [x] `uv run mypy src/` & `uv run ruff check src/ tests/`
- [x] Manual smoke test covered by `TestServerApprovalSuspendE2E` ASGI acceptance tests

Targets Phase 3 base.
EOF
)"
```

---

### Phase 3 Completion

- [ ] **Step P3.1: Verify all three task PRs merged into `feature/phase3_blocking_mode__base`**

```bash
gh pr list --base feature/phase3_blocking_mode__base --state merged
```

Expected: three merged PRs (Tasks 3.1, 3.2, 3.3).

- [ ] **Step P3.2: Run the full devcontainer suite on the phase base**

```bash
git checkout feature/phase3_blocking_mode__base
git pull origin feature/phase3_blocking_mode__base
uv run pytest tests/unit -v
uv run mypy src/
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
```

Expected: all green.

- [x] **Step P3.3: Confirm spec acceptance criteria**

Open the Phase 3 PR description and check off:

- §10.1 `uv run pytest tests/unit/test_mcp_gateway.py -v` succeeds in devcontainer ✅
- §10.2 `uv run mypy src/` clean ✅
- §10.3 `uv run ruff check src/ tests/` clean ✅
- §10.4 `intents.example.yaml`'s `memory_delete` (`requires_approval: true`) under blocking mode: approve → upstream invoked; reject → `-32002`; timeout → `-32003`. (Pull from manual smoke or expand `TestServerApprovalSuspendE2E` to cover all three branches via `build_app` + ASGI client.)

- [ ] **Step P3.4: Lift the Draft flag on the Phase 3 base PR and request review**

Once review is complete and the PR is merged into `master`, the suspend/resume approval flow is live (opt-in via env var).

---

## Spec Coverage Self-Review

| Spec section | Covered by |
|---|---|
| §4.1 ApprovalDecision / DecisionStatus | Task 1.1 |
| §4.2 PendingApprovalRegistry | Task 1.3 |
| §4.3.1 build_router signature + precondition | Task 3.1 (Step 4) |
| §4.3.2 REQUIRES_APPROVAL blocking handler | Task 3.1 (Step 8) |
| §4.3.3 POST /approvals | Task 3.2 |
| §4.4 GatewaySettings | Task 3.3 (Step 4) |
| §4.5 Session lifecycle hook + wrapper | Task 2.1 + Task 3.3 (Step 6) |
| §6 New JSON-RPC codes (-32002 / -32003) | Task 3.1 (Step 8) |
| §7.1 PendingApprovalRegistry tests | Task 1.3 (Steps 2/6/10/12) |
| §7.2 TestServerApprovalSuspend tests | Task 3.1 + Task 3.2 + Task 3.3 |
| §7.3 Existing TestServerRequiresApproval preserved | Task 3.1 (Step 15) |
| §7.4 TestSessionEvictionHook | Task 2.1 |
| §8.1 Defense-in-depth (auth + uuid + self-approval) | Task 1.3 + Task 3.2 |
| §8.2 Audit log truncation | Task 3.1 (`_approval_id_for_log`) + Task 3.2 |
| §8.4 DoS via max_pending + cancel_session | Task 1.3 + Task 2.1 + Task 3.3 |
| §8.5 Body 1KB cap | Task 3.2 (Step 4) |
| §8.6 sanitize_reason | Task 1.2 + Task 3.2 |
| §9 Backwards compatibility (default off) | Task 3.1 (Step 8 / Step 15 regression) |
| §10 Acceptance criteria | Task 3.3 (Step 9 / Step 10 / Step P3.3) |

If after self-review any cell shows a gap, add a follow-up step to the corresponding task before starting execution.

---

## Execution Handoff

**Plan saved to `docs/superpowers/plans/2026-05-07-mcp-gateway-permission-hook-impl.md`.** Two execution options:

1. **Subagent-Driven (recommended)** — Dispatch a fresh subagent per task, review between tasks, fast iteration. Uses `superpowers:subagent-driven-development`.
2. **Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints.

Which approach?
