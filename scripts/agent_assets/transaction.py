from __future__ import annotations

import os
import shutil
import stat
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from .models import PlannedAction, PlannedTarget, SyncPlan
from .transaction_verify import (
    matches_applied,
    snapshots_match,
    source_for_target,
    verify_post_write_state,
)


class FileOperations(Protocol):
    """Filesystem operations used by the synchronizer and its tests."""

    def replace(self, source: Path, destination: Path) -> None:
        """Atomically replace one destination path."""

    def move(self, source: Path, destination: Path) -> None:
        """Move an owned path into or out of the transaction journal."""

    def remove(self, path: Path) -> None:
        """Remove a path created by the current transaction."""


class SystemFileOperations:
    """Filesystem implementation used by production synchronization."""

    def replace(self, source: Path, destination: Path) -> None:
        os.replace(source, destination)

    def move(self, source: Path, destination: Path) -> None:
        _ = shutil.move(str(source), str(destination))

    def remove(self, path: Path) -> None:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)


class PreflightStateChangedError(RuntimeError):
    """Report a target that changed after the no-write preflight."""

    def __init__(self, path: Path) -> None:
        self.path: Path = path
        super().__init__("preflight-state-changed")


class HookSetupError(RuntimeError):
    """Report a hook installation failure after transaction mutation."""


class PostWriteVerificationError(RuntimeError):
    """Report a failed or raised post-write verifier."""


class RollbackResult:
    """Redacted result of restoring the transaction's owned changes."""

    __slots__: tuple[str, ...] = ("succeeded", "category")
    succeeded: bool
    category: str | None

    def __init__(self, succeeded: bool, category: str | None = None) -> None:
        self.succeeded = succeeded
        self.category = category

    @classmethod
    def failure(cls, _error: Exception) -> RollbackResult:
        """Return a result that does not expose filesystem error details."""
        return cls(False, "rollback-failed")


class ApplyError(RuntimeError):
    """Report an apply failure together with its rollback result."""

    __slots__: tuple[str, ...] = ("category", "rollback")
    category: str
    rollback: RollbackResult

    def __init__(self, category: str, rollback: RollbackResult) -> None:
        self.category = category
        self.rollback = rollback
        super().__init__(category)

    @classmethod
    def from_failure(cls, error: Exception, rollback: RollbackResult) -> ApplyError:
        """Convert an internal exception into a redacted apply error."""
        return cls(type(error).__name__.lower(), rollback)


class SyncResult:
    """Paths changed by a successfully committed synchronization."""

    __slots__: tuple[str, ...] = ("paths",)
    paths: tuple[Path, ...]

    def __init__(self, paths: tuple[Path, ...]) -> None:
        self.paths = paths


class _AppliedEntry:
    """Mutable journal state needed while a replacement is in progress."""

    __slots__: tuple[str, ...] = ("target", "existed", "backup", "installed")
    target: PlannedTarget
    existed: bool
    backup: Path | None
    installed: bool

    def __init__(self, target: PlannedTarget, existed: bool, backup: Path | None) -> None:
        self.target = target
        self.existed = existed
        self.backup = backup
        self.installed = False


class TransactionJournal:
    """Own temporary staging and backup paths until commit or rollback."""

    plan: SyncPlan
    root: Path
    entries: list[_AppliedEntry]
    staging_roots: dict[Path, Path]

    def __init__(self, plan: SyncPlan, root: Path) -> None:
        self.plan = plan
        self.root = root
        self.entries = []
        self.staging_roots = {}

    @classmethod
    def create(cls, plan: SyncPlan) -> TransactionJournal:
        """Create a private temporary area for one synchronization."""
        return cls(plan, Path(tempfile.mkdtemp(prefix="chronosgraph-sync-")))

    def stage_root_for(self, parent: Path) -> Path:
        """Create or return a staging root on the target's filesystem."""
        root = self.staging_roots.get(parent)
        if root is None:
            root = Path(
                tempfile.mkdtemp(
                    prefix="chronosgraph-stage-",
                    dir=parent,
                )
            )
            self.staging_roots[parent] = root
        return root

    def cleanup_staging_roots(self) -> None:
        """Remove all target-local staging roots owned by this transaction."""
        for root in self.staging_roots.values():
            shutil.rmtree(root, ignore_errors=True)
        self.staging_roots.clear()

    def commit(self) -> SyncResult:
        """Discard private transaction artifacts after successful verification."""
        paths = tuple(entry.target.path for entry in self.entries)
        self.cleanup_staging_roots()
        shutil.rmtree(self.root, ignore_errors=True)
        return SyncResult(paths)


def apply_sync(
    plan: SyncPlan,
    operations: FileOperations,
    verify: Callable[[SyncPlan], bool] | None = None,
) -> SyncResult:
    """Apply one preflighted plan or restore every owned change made by this call."""
    journal = TransactionJournal.create(plan)
    try:
        _validate_preflight_state(plan)
        _apply_non_hook_targets(plan, journal, operations)
        install_selected_hooks(plan, journal, operations)
        journal.cleanup_staging_roots()
        verifier = verify or verify_post_write_state
        try:
            verified = verifier(plan)
        except Exception as error:  # noqa: BLE001 - normalize verifier failures
            raise PostWriteVerificationError("verification-exception") from error
        if not verified:
            raise PostWriteVerificationError("verification-failed")
    except Exception as error:  # noqa: BLE001 - transaction boundary rollback
        try:
            rollback = rollback_transaction(journal, operations)
        except Exception as rollback_error:  # noqa: BLE001 - redact rollback details
            rollback = RollbackResult.failure(rollback_error)
        raise ApplyError.from_failure(error, rollback) from error
    return journal.commit()


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
        if existed:
            stage.chmod(stat.S_IMODE(target.path.stat().st_mode))

    backup = journal.root / f"backup-{len(journal.entries)}" if existed else None
    if backup is not None:
        operations.move(target.path, backup)
    entry = _AppliedEntry(target, existed, backup)
    journal.entries.append(entry)
    operations.replace(stage, target.path)
    entry.installed = True


def _stage_skill(source: Path, existing: Path | None, stage: Path) -> None:
    if existing is None:
        _ = shutil.copytree(source, stage, symlinks=True)
        return
    _ = shutil.copytree(existing, stage, symlinks=True)
    for name in ("SKILL.md", ".chronosgraph-managed"):
        _ = shutil.copy2(source / name, stage / name)


def rollback_transaction(journal: TransactionJournal, operations: FileOperations) -> RollbackResult:
    """Restore entries in reverse order while preserving external changes."""
    journal.cleanup_staging_roots()
    rollback_failed = False
    externally_changed = False
    for entry in reversed(journal.entries):
        try:
            if not entry.installed:
                if entry.backup is not None and not _target_exists(entry.target.path):
                    operations.move(entry.backup, entry.target.path)
                continue
            if not matches_applied(journal.plan, entry.target):
                externally_changed = True
                continue
            operations.remove(entry.target.path)
            if entry.backup is not None:
                operations.move(entry.backup, entry.target.path)
        except Exception:  # noqa: BLE001 - continue restoring independent entries
            rollback_failed = True
    if rollback_failed:
        return RollbackResult(False, "rollback-failed")
    if externally_changed:
        return RollbackResult(False, "rollback-external-change")
    shutil.rmtree(journal.root, ignore_errors=True)
    return RollbackResult(True)


def _target_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()
