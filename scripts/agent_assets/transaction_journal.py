from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from .models import PlannedTarget, SyncPlan
from .transaction_types import SyncResult


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

    def new_entry(self, target: PlannedTarget, existed: bool, backup: Path | None) -> _AppliedEntry:
        """Append a mutable entry for a target being applied."""
        entry = _AppliedEntry(target, existed, backup)
        self.entries.append(entry)
        return entry
    def cleanup_staging_roots(self) -> None:
        """Remove all target-local staging roots owned by this transaction."""
        for root in self.staging_roots.values():
            shutil.rmtree(root, ignore_errors=True)
        self.staging_roots.clear()

    def commit(self) -> SyncResult:

        paths = tuple(entry.target.path for entry in self.entries)
        self.cleanup_staging_roots()
        shutil.rmtree(self.root, ignore_errors=True)
        return SyncResult(paths)
