from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path
from typing import Final

from .models import (
    AssetBundle,
    PlannedAction,
    PlannedTarget,
    SnapshotKind,
    TargetSnapshot,
)
from .preflight_errors import InstructionCollisionError, SkillCollisionError

OWNER_SENTINEL: Final = b"owner=chronosgraph\nformat=1\n"


def safe_instruction_target(path: Path, root: Path) -> Path:
    """Validate an instruction destination and return its safe write target."""
    for parent in _existing_parent_paths(path, root):
        if stat.S_ISLNK(parent.lstat().st_mode):
            raise InstructionCollisionError(parent, "parent-symlink")

    try:
        leaf_mode = path.lstat().st_mode
    except FileNotFoundError:
        return path

    if not stat.S_ISLNK(leaf_mode):
        if not stat.S_ISREG(leaf_mode):
            raise InstructionCollisionError(path, "instruction-not-regular")
        return path

    try:
        resolved_target = path.resolve(strict=True)
    except FileNotFoundError as error:
        raise InstructionCollisionError(path, "instruction-symlink-broken") from error
    except RuntimeError as error:
        raise InstructionCollisionError(path, "instruction-symlink-cycle") from error

    try:
        resolved_target.relative_to(root.resolve(strict=False))
    except ValueError as error:
        raise InstructionCollisionError(path, "instruction-symlink-external") from error
    if not stat.S_ISREG(resolved_target.stat().st_mode):
        raise InstructionCollisionError(path, "instruction-target-not-regular")
    return resolved_target


def plan_skills(
    bundle: AssetBundle, skills_root: Path
) -> tuple[tuple[PlannedTarget, ...], tuple[TargetSnapshot, ...]]:
    """Validate requested Skill ownership and snapshot unmanaged entries."""
    names = {root.name for root in bundle.skill_roots}
    targets: list[PlannedTarget] = []
    snapshots: list[TargetSnapshot] = []
    if skills_root.exists() or skills_root.is_symlink():
        root_mode = skills_root.lstat().st_mode
        if not stat.S_ISDIR(root_mode):
            raise SkillCollisionError(skills_root, "skills-root-not-directory")
        for entry in sorted(skills_root.rglob("*"), key=lambda item: item.as_posix()):
            relative = entry.relative_to(skills_root)
            if relative.parts[0] not in names:
                snapshots.append(snapshot(entry, skills_root))

    for source_root in bundle.skill_roots:
        target_root = skills_root / source_root.name
        if target_root.exists() or target_root.is_symlink():
            mode = target_root.lstat().st_mode
            if not stat.S_ISDIR(mode) or not _is_owned_skill(target_root):
                raise SkillCollisionError(target_root, "skill-not-owned")
            action = PlannedAction.UPDATE
        else:
            action = PlannedAction.CREATE
        targets.append(PlannedTarget(target_root, action, tuple(snapshots)))
    return tuple(targets), tuple(snapshots)


def snapshot(path: Path, relative_to: Path) -> TargetSnapshot:
    """Capture a non-content fingerprint without dereferencing symlinks."""
    metadata = path.lstat()
    relative = path.relative_to(relative_to)
    if stat.S_ISREG(metadata.st_mode):
        return TargetSnapshot(
            relative, SnapshotKind.FILE, hashlib.sha256(path.read_bytes()).hexdigest()
        )
    if stat.S_ISLNK(metadata.st_mode):
        return TargetSnapshot(
            relative,
            SnapshotKind.SYMLINK,
            hashlib.sha256(os.fsencode(os.readlink(path))).hexdigest(),
        )
    if stat.S_ISDIR(metadata.st_mode):
        return TargetSnapshot(relative, SnapshotKind.DIRECTORY, "present")
    raise SkillCollisionError(path, "unsupported-skill-entry")


def _existing_parent_paths(path: Path, root: Path) -> tuple[Path, ...]:
    """Return existing destination parents up to the approved root."""
    parents: list[Path] = []
    current = path.parent
    while True:
        if current.exists() or current.is_symlink():
            parents.append(current)
        if current == root:
            return tuple(parents)
        if current == current.parent:
            raise InstructionCollisionError(path, "instruction-root-mismatch")
        current = current.parent


def _is_owned_skill(path: Path) -> bool:
    """Return whether a Skill root has the exact ownership sentinel."""
    sentinel = path / ".chronosgraph-managed"
    try:
        mode = sentinel.lstat().st_mode
    except FileNotFoundError:
        return False
    return stat.S_ISREG(mode) and sentinel.read_bytes() == OWNER_SENTINEL
