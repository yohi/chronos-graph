from __future__ import annotations

from pathlib import Path

from .models import SafeDiagnostic


class PreflightCollisionError(RuntimeError):
    """Carry only a safe path and reason code for a preflight collision."""

    path: Path
    code: str

    def __init__(self, path: Path, code: str) -> None:
        self.path = path
        self.code = code
        super().__init__(code)

    def diagnostic(self) -> SafeDiagnostic:
        """Return a diagnostic that excludes target content."""
        return SafeDiagnostic("preflight", "reject", self.path, self.code)


class SkillCollisionError(PreflightCollisionError):
    """Report a requested Skill root that is not ChronosGraph-owned."""


class InstructionCollisionError(PreflightCollisionError):
    """Report an instruction destination that is unsafe to update."""


class LegacySaveAllModeCollision(PreflightCollisionError):
    """Report legacy Save instructions that conflict with all-mode ingestion."""
