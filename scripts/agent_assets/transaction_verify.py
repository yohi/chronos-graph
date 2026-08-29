from __future__ import annotations

from pathlib import Path
from typing import Final

from .bundle import build_bundle
from .models import PlannedTarget, SyncPlan, TargetSnapshot
from .preflight_files import snapshot

SKILL_FILES: Final = ("SKILL.md", ".chronosgraph-managed")


class UnknownSkillTargetError(RuntimeError):
    """Report an impossible target that is absent from the validated bundle."""


def source_for_target(plan: SyncPlan, target: PlannedTarget) -> Path:
    """Resolve the SSOT Skill matching one planned target."""
    for source in plan.bundle.skill_roots:
        if source.name == target.path.name:
            return source
    raise UnknownSkillTargetError


def snapshots_match(plan: SyncPlan, target: PlannedTarget) -> bool:
    """Compare the current target state with the preflight snapshot."""
    if not target.snapshots:
        return True
    if target.content is not None:
        if target.path.is_symlink() or not target.path.is_file():
            return False
        actual: tuple[TargetSnapshot, ...] = (snapshot(target.path, target.path.parent),)
    else:
        actual = skill_snapshots(plan, target.path.parent)
    return actual == target.snapshots


def matches_applied(plan: SyncPlan, target: PlannedTarget) -> bool:
    """Check whether a target still contains only this transaction's output."""
    if target.content is not None:
        return (
            not target.path.is_symlink()
            and target.path.is_file()
            and target.path.read_bytes() == target.content
        )
    return target.path.is_dir() and not target.path.is_symlink() and skill_matches(plan, target)


def skill_matches(plan: SyncPlan, target: PlannedTarget) -> bool:
    """Check owned Skill files and unmanaged entries after applying a plan."""
    source = source_for_target(plan, target)
    for name in SKILL_FILES:
        candidate = target.path / name
        if (
            candidate.is_symlink()
            or not candidate.is_file()
            or candidate.read_bytes() != (source / name).read_bytes()
        ):
            return False
    return snapshots_match(plan, target)


def skill_snapshots(plan: SyncPlan, skills_root: Path) -> tuple[TargetSnapshot, ...]:
    """Snapshot non-ChronosGraph entries below one Agent's Skills root."""
    names = {root.name for root in plan.bundle.skill_roots}
    if not skills_root.is_dir() or skills_root.is_symlink():
        return ()
    entries = (
        candidate
        for candidate in sorted(skills_root.rglob("*"), key=lambda item: item.as_posix())
        if candidate.relative_to(skills_root).parts[0] not in names
    )
    return tuple(snapshot(candidate, skills_root) for candidate in entries)


def verify_post_write_state(plan: SyncPlan) -> bool:
    """Verify SSOT content and all preflighted unmanaged snapshots."""
    if build_bundle(plan.bundle.root).digest != plan.bundle.digest:
        return False
    for target in plan.targets:
        if target.content is not None:
            if (
                target.path.is_symlink()
                or not target.path.is_file()
                or target.path.read_bytes() != target.content
            ):
                return False
        elif (
            not target.path.is_dir() or target.path.is_symlink() or not skill_matches(plan, target)
        ):
            return False
    return True
