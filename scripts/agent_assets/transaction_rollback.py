from __future__ import annotations

import shutil
from pathlib import Path

from .transaction_journal import TransactionJournal
from .transaction_types import FileOperations, RollbackResult
from .transaction_verify import matches_applied


def rollback_transaction(journal: TransactionJournal, operations: FileOperations) -> RollbackResult:
    """Restore entries in reverse order while preserving external changes."""
    journal.cleanup_staging_roots()
    rollback_failed = False
    externally_changed = False
    recovery_paths: list[Path] = []
    for recovery_index, entry in enumerate(reversed(journal.entries)):
        backup_location = entry.backup
        try:
            if not entry.installed:
                if entry.backup is not None:
                    if _target_exists(entry.target.path):
                        externally_changed = True
                        recovery_paths.append(entry.backup)
                    else:
                        operations.move(entry.backup, entry.target.path)
                continue
            if not matches_applied(journal.plan, entry.target):
                externally_changed = True
                if backup_location is not None:
                    recovery_paths.append(backup_location)
                continue
            if entry.backup is None:
                operations.remove(entry.target.path)
                continue
            recovery_root = journal.stage_root_for(entry.target.path.parent)
            recovery_path = recovery_root / f"recovery-{recovery_index}"
            operations.move(entry.backup, recovery_path)
            backup_location = recovery_path
            operations.remove(entry.target.path)
            operations.move(recovery_path, entry.target.path)
        except Exception:  # noqa: BLE001 - continue restoring independent entries
            rollback_failed = True
            if backup_location is not None:
                recovery_paths.append(backup_location)
    if rollback_failed:
        return RollbackResult(False, "rollback-failed", tuple(recovery_paths))
    journal.cleanup_staging_roots()
    if externally_changed:
        return RollbackResult(False, "rollback-external-change", tuple(recovery_paths))
    shutil.rmtree(journal.root, ignore_errors=True)
    return RollbackResult(True)


def _target_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()
