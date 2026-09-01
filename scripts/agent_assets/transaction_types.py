from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Protocol


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
    """Result of restoring the transaction's owned changes."""

    __slots__: tuple[str, ...] = ("category", "recovery_paths", "succeeded")
    succeeded: bool
    category: str | None
    recovery_paths: tuple[Path, ...]

    def __init__(
        self,
        succeeded: bool,
        category: str | None = None,
        recovery_paths: tuple[Path, ...] = (),
    ) -> None:
        self.succeeded = succeeded
        self.category = category
        self.recovery_paths = recovery_paths

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
