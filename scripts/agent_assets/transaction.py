from __future__ import annotations

import os
import shutil
import stat
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .bundle import build_bundle
from .models import PlannedAction, PlannedTarget, SyncPlan


class FileOperations(Protocol):
    def replace(self, source: Path, destination: Path) -> None: ...

    def move(self, source: Path, destination: Path) -> None: ...

    def remove(self, path: Path) -> None: ...


class SystemFileOperations:
    def replace(self, source: Path, destination: Path) -> None:
        os.replace(source, destination)

    def move(self, source: Path, destination: Path) -> None:
        shutil.move(str(source), str(destination))

    def remove(self, path: Path) -> None:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)


class HookSetupError(RuntimeError):
    pass


class PostWriteVerificationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RollbackResult:
    succeeded: bool
    category: str | None = None

    @classmethod
    def failure(cls, _: Exception) -> RollbackResult:
        return cls(False, "rollback-failed")


class ApplyError(RuntimeError):
    def __init__(self, category: str, rollback: RollbackResult) -> None:
        self.category = category
        self.rollback = rollback
        super().__init__(category)

    @classmethod
    def from_failure(cls, error: Exception, rollback: RollbackResult) -> ApplyError:
        return cls(type(error).__name__.lower(), rollback)


@dataclass(frozen=True, slots=True)
class TransactionJournalEntry:
    target: PlannedTarget
    existed: bool


@dataclass(slots=True)
class _AppliedEntry:
    entry: TransactionJournalEntry
    backup: Path | None
    expected: bytes | None


@dataclass(slots=True)
class TransactionJournal:
    root: Path
    entries: list[_AppliedEntry] = field(default_factory=list)

    @classmethod
    def create(cls, plan: SyncPlan) -> TransactionJournal:
        return cls(Path(tempfile.mkdtemp(prefix="chronosgraph-sync-")))

    def commit(self) -> SyncResult:
        shutil.rmtree(self.root, ignore_errors=True)
        return SyncResult(tuple(applied.entry.target.path for applied in self.entries))


@dataclass(frozen=True, slots=True)
class SyncResult:
    paths: tuple[Path, ...]


def apply_sync(
    plan: SyncPlan,
    operations: FileOperations,
    verify: Callable[[SyncPlan], bool] | None = None,
) -> SyncResult:
    journal = TransactionJournal.create(plan)
    verifier = verify or verify_post_write_state
    try:
        _apply_non_hook_targets(plan, journal, operations)
        install_selected_hooks(plan, journal, operations)
        try:
            verified = verifier(plan)
        except Exception as error:
            raise PostWriteVerificationError("verification-exception") from error
        if not verified:
            raise PostWriteVerificationError("verification-failed")
    except Exception as error:
        try:
            rollback = rollback_transaction(journal, operations)
        except Exception as rollback_error:
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
    for target in plan.targets:
        if _is_hook_target(plan, target):
            _apply_target(plan, target, journal, operations)


def _is_hook_target(plan: SyncPlan, target: PlannedTarget) -> bool:
    return (
        target.path.parent == plan.request.repo_root / "scripts"
        or target.path.name == "opencode.json"
    )


def _apply_target(
    plan: SyncPlan, target: PlannedTarget, journal: TransactionJournal, operations: FileOperations
) -> None:
    if target.action is PlannedAction.UNCHANGED:
        return
    target.path.parent.mkdir(parents=True, exist_ok=True)
    existed = target.path.exists() or target.path.is_symlink()
    entry = TransactionJournalEntry(target, existed)
    stage = journal.root / f"stage-{len(journal.entries)}"
    expected = target.content
    if target.content is None:
        source = next(root for root in plan.bundle.skill_roots if root.name == target.path.name)
        _stage_skill(source, target.path if existed else None, stage)
        expected = None
    else:
        stage.write_bytes(target.content)
        if existed:
            stage.chmod(stat.S_IMODE(target.path.stat().st_mode))
    backup = journal.root / f"backup-{len(journal.entries)}" if existed else None
    if backup is not None:
        operations.move(target.path, backup)
    try:
        operations.replace(stage, target.path)
    except Exception:
        if backup is not None and backup.exists():
            operations.move(backup, target.path)
        raise
    journal.entries.append(_AppliedEntry(entry, backup, expected))


def _stage_skill(source: Path, existing: Path | None, stage: Path) -> None:
    if existing is None:
        shutil.copytree(source, stage, symlinks=True)
        return
    shutil.copytree(existing, stage, symlinks=True)
    for name in ("SKILL.md", ".chronosgraph-managed"):
        shutil.copy2(source / name, stage / name)


def rollback_transaction(journal: TransactionJournal, operations: FileOperations) -> RollbackResult:
    externally_changed = False
    try:
        for applied in reversed(journal.entries):
            path = applied.entry.target.path
            if not _matches_applied(path, applied.expected):
                externally_changed = True
                continue
            operations.remove(path)
            if applied.backup is not None:
                operations.move(applied.backup, path)
    except Exception as error:
        return RollbackResult.failure(error)
    if externally_changed:
        return RollbackResult(False, "rollback-external-change")
    shutil.rmtree(journal.root, ignore_errors=True)
    return RollbackResult(True)


def _matches_applied(path: Path, expected: bytes | None) -> bool:
    if expected is not None:
        return path.exists() and path.read_bytes() == expected
    return path.is_dir() and (path / ".chronosgraph-managed").exists()


def verify_post_write_state(plan: SyncPlan) -> bool:
    if build_bundle(plan.bundle.root).digest != plan.bundle.digest:
        return False
    for target in plan.targets:
        if target.content is not None and target.path.read_bytes() != target.content:
            return False
        if target.content is None:
            source = next(root for root in plan.bundle.skill_roots if root.name == target.path.name)
            for name in ("SKILL.md", ".chronosgraph-managed"):
                if (target.path / name).read_bytes() != (source / name).read_bytes():
                    return False
    return True
