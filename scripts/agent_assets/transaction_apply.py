from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

from .models import PlannedAction, PlannedTarget, SyncPlan
from .transaction_journal import TransactionJournal
from .transaction_types import FileOperations, PreflightStateChangedError
from .transaction_verify import snapshots_match, source_for_target


def _apply_non_hook_targets(
    plan: SyncPlan, journal: TransactionJournal, operations: FileOperations
) -> None:
    for target in plan.targets:
        if not _is_hook_target(plan, target):
            _apply_target(plan, target, journal, operations)


def install_selected_hooks(
    plan: SyncPlan, journal: TransactionJournal, operations: FileOperations
) -> None:
    """Apply hook targets after Skills and instructions have been staged."""
    for target in plan.targets:
        if _is_hook_target(plan, target):
            _apply_target(plan, target, journal, operations)


def _is_hook_target(plan: SyncPlan, target: PlannedTarget) -> bool:
    return target.path.parent == plan.request.repo_root / "scripts" or (
        target.path.name == "opencode.json"
    )


def _validate_preflight_state(plan: SyncPlan) -> None:
    for target in plan.targets:
        match target.action:
            case PlannedAction.CREATE:
                if _target_exists(target.path) or not snapshots_match(plan, target):
                    raise PreflightStateChangedError(target.path)
            case PlannedAction.UPDATE:
                if not _target_exists(target.path) or not snapshots_match(plan, target):
                    raise PreflightStateChangedError(target.path)
            case PlannedAction.UNCHANGED:
                continue
            case PlannedAction.CONFLICT:
                raise PreflightStateChangedError(target.path)


def _apply_target(
    plan: SyncPlan, target: PlannedTarget, journal: TransactionJournal, operations: FileOperations
) -> None:
    match target.action:
        case PlannedAction.UNCHANGED:
            return
        case PlannedAction.CREATE | PlannedAction.UPDATE:
            pass
        case PlannedAction.CONFLICT:
            raise PreflightStateChangedError(target.path)

    target.path.parent.mkdir(parents=True, exist_ok=True)
    existed = _target_exists(target.path)
    stage_root = journal.stage_root_for(target.path.parent)
    stage = stage_root / f"stage-{len(journal.entries)}"
    if target.content is None:
        source = source_for_target(plan, target)
        _stage_skill(source, target.path if existed else None, stage)
    else:
        _ = stage.write_bytes(target.content)
        is_posix_wrapper = (
            os.name != "nt"
            and target.path == plan.request.repo_root / "scripts" / "chronos-turn-hook.sh"
        )
        stage_mode = stat.S_IMODE((target.path if existed else stage).stat().st_mode)
        if is_posix_wrapper:
            stage_mode |= stat.S_IXUSR
        if existed or is_posix_wrapper:
            stage.chmod(stage_mode)

    backup = journal.root / f"backup-{len(journal.entries)}" if existed else None
    if backup is not None:
        operations.move(target.path, backup)
    entry = journal.new_entry(target, existed, backup)
    operations.replace(stage, target.path)
    entry.installed = True


def _stage_skill(source: Path, existing: Path | None, stage: Path) -> None:
    if existing is None:
        _ = shutil.copytree(source, stage, symlinks=True)
        return
    _ = shutil.copytree(existing, stage, symlinks=True)
    for name in ("SKILL.md", ".chronosgraph-managed"):
        _ = shutil.copy2(source / name, stage / name)


def _target_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()
