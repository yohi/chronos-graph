from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from .bundle import render_managed_block
from .hooks import plan_hook_targets
from .models import (
    AssetBundle,
    IngestionMode,
    PlannedAction,
    PlannedTarget,
    SafeDiagnostic,
    SyncPlan,
    SyncRequest,
    TargetSnapshot,
    adapter_for,
    resolve_codex_home,
)
from .preflight_errors import (
    InstructionCollisionError,
    LegacySaveAllModeCollision,
    PreflightCollisionError,
    SkillCollisionError,
)
from .preflight_files import plan_skills, safe_instruction_target, snapshot

BEGIN_MARKER: Final = b"<!-- BEGIN CHRONOSGRAPH MANAGED: agent-memory -->"
END_MARKER: Final = b"<!-- END CHRONOSGRAPH MANAGED: agent-memory -->"
LEGACY_SAVE_SHA256: Final = "e7641028c918c614d42cf548f67e4a810e02fa204f641e2cd0b8fd3a3c7ebfb1"
LEGACY_RECALL_SHA256: Final = "171c000346a5880f4c8a846f1ab34147708ff9a3f25baf7f3ee051504b0bfca5"
LEGACY_SAVE_HEADING: Final = b"# Memory Save \xe2\x80\x94 Agent System Prompt Template"
LEGACY_RECALL_HEADING: Final = b"# Memory Recall \xe2\x80\x94 Agent System Prompt Template"
LEGACY_SAVE_BYTE_LENGTH: Final = 5273
LEGACY_RECALL_BYTE_LENGTH: Final = 5238

__all__ = (
    "BEGIN_MARKER",
    "END_MARKER",
    "InstructionCollisionError",
    "InstructionSections",
    "LegacyKind",
    "LegacySaveAllModeCollision",
    "LegacySignature",
    "MarkerError",
    "PreflightCollisionError",
    "SkillCollisionError",
    "detect_legacy_prompts",
    "parse_instruction_sections",
    "preflight",
    "safe_diagnostic",
)


@dataclass(frozen=True, slots=True)
class InstructionSections:
    prefix: bytes
    managed: bytes | None
    suffix: bytes


class MarkerError(RuntimeError):
    """Report malformed managed instruction markers by reason code."""

    code: str

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class LegacyKind(StrEnum):
    SAVE = "save"
    RECALL = "recall"


@dataclass(frozen=True, slots=True)
class LegacySignature:
    kind: LegacyKind
    heading: bytes
    digest: str
    byte_length: int


LEGACY_SIGNATURES: Final = (
    LegacySignature(
        LegacyKind.SAVE,
        LEGACY_SAVE_HEADING,
        LEGACY_SAVE_SHA256,
        LEGACY_SAVE_BYTE_LENGTH,
    ),
    LegacySignature(
        LegacyKind.RECALL,
        LEGACY_RECALL_HEADING,
        LEGACY_RECALL_SHA256,
        LEGACY_RECALL_BYTE_LENGTH,
    ),
)


def parse_instruction_sections(original: bytes) -> InstructionSections:
    """Split one valid managed block from immutable surrounding bytes."""
    begin_count = original.count(BEGIN_MARKER)
    end_count = original.count(END_MARKER)
    if begin_count == 0 and end_count == 0:
        return InstructionSections(prefix=original, managed=None, suffix=b"")
    if begin_count != 1 or end_count != 1:
        raise MarkerError("marker-count")

    begin = original.index(BEGIN_MARKER)
    end_start = original.index(END_MARKER)
    if end_start < begin:
        raise MarkerError("marker-order")
    end = end_start + len(END_MARKER)
    return InstructionSections(
        prefix=original[:begin],
        managed=original[begin:end],
        suffix=original[end:],
    )


def detect_legacy_prompts(
    instruction: bytes, signatures: tuple[LegacySignature, ...]
) -> tuple[LegacySignature, ...]:
    """Return matching legacy signatures without retaining instruction text."""
    matches: list[LegacySignature] = []
    for signature in signatures:
        start = instruction.find(signature.heading)
        if start < 0:
            continue
        candidate = instruction[start : start + signature.byte_length]
        if hashlib.sha256(candidate).hexdigest() == signature.digest:
            matches.append(signature)
    return tuple(matches)


def safe_diagnostic(signature: LegacySignature, path: Path) -> SafeDiagnostic:
    """Build a redacted legacy warning from its kind and target path."""
    return SafeDiagnostic(
        phase="preflight",
        action="warn",
        path=path,
        mismatch=f"legacy-{signature.kind}-manual-removal",
    )


def preflight(request: SyncRequest, bundle: AssetBundle) -> SyncPlan:
    """Build a no-write plan after validating every selected target."""
    targets: list[PlannedTarget] = []
    snapshots: list[TargetSnapshot] = []
    diagnostics: list[SafeDiagnostic] = []
    resolved_instruction_targets: set[Path] = set()
    rendered_block = render_managed_block(bundle, request.ingestion_mode).removesuffix(b"\n")

    for agent_id in request.agent_ids:
        adapter = adapter_for(
            agent_id,
            request.home,
            request.codex_home or resolve_codex_home(request.home),
        )
        instruction_path = safe_instruction_target(
            adapter.instructions_path, adapter.instructions_root
        )
        resolved_instruction_path = instruction_path.resolve(strict=False)
        if resolved_instruction_path in resolved_instruction_targets:
            raise InstructionCollisionError(adapter.instructions_path, "instruction-symlink-shared")
        resolved_instruction_targets.add(resolved_instruction_path)
        instruction_snapshots: tuple[TargetSnapshot, ...] = ()
        if instruction_path.exists():
            original = instruction_path.read_bytes()
            sections = parse_instruction_sections(original)
            replacement = sections.prefix + rendered_block + sections.suffix
            action = PlannedAction.UNCHANGED if replacement == original else PlannedAction.UPDATE
            instruction_snapshot = snapshot(instruction_path, instruction_path.parent)
            instruction_snapshots = (instruction_snapshot,)
            snapshots.append(instruction_snapshot)
            detected = detect_legacy_prompts(original, LEGACY_SIGNATURES)
            for signature in detected:
                if (
                    request.ingestion_mode is IngestionMode.ALL
                    and signature.kind is LegacyKind.SAVE
                ):
                    raise LegacySaveAllModeCollision(instruction_path, "legacy-save-all")
                diagnostics.append(safe_diagnostic(signature, instruction_path))
        else:
            action = PlannedAction.CREATE
            replacement = rendered_block
        targets.append(
            PlannedTarget(
                path=instruction_path,
                action=action,
                snapshots=instruction_snapshots,
                content=replacement,
            )
        )
        skill_targets, skill_snapshots = plan_skills(bundle, adapter.skills_root)
        targets.extend(skill_targets)
        snapshots.extend(skill_snapshots)

    hook_targets = plan_hook_targets(request)
    targets.extend(hook_targets)
    for target in hook_targets:
        snapshots.extend(target.snapshots)

    return SyncPlan(
        request=request,
        bundle=bundle,
        targets=tuple(targets),
        diagnostics=tuple(diagnostics),
        snapshots=tuple(snapshots),
    )
