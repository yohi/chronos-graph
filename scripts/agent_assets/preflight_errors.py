from __future__ import annotations

from pathlib import Path

from .models import SafeDiagnostic


class PreflightCollisionError(RuntimeError):
    """Base typed collision that carries only a safe path and reason code."""

    path: Path
    code: str

    def __init__(self, path: Path, code: str) -> None:
        self.path = path
        self.code = code
        super().__init__(code)

    def diagnostic(self) -> SafeDiagnostic:
        """Return a deterministic diagnostic without target content."""
        return SafeDiagnostic("preflight", "reject", self.path, self.code)


class SkillCollisionError(PreflightCollisionError):
    """Raised when a requested Skill root is not ChronosGraph-owned."""


class InstructionCollisionError(PreflightCollisionError):
    """Raised when an instruction destination is unsafe to update."""


class LegacySaveAllModeCollision(PreflightCollisionError):
    """Raised when legacy save instructions conflict with all-mode ingestion."""
