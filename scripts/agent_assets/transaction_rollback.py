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
