"""
StaleAwareFileLock: filelock wrapper that recovers from stale lock files.

Problem: If a process dies while holding a file lock, the lock file remains.
Subsequent processes wait indefinitely or fail to acquire.

Solution: Check the lock file's mtime. If it's older than stale_timeout_seconds,
force-delete the file and retry acquisition.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import filelock

logger = logging.getLogger(__name__)


class StaleAwareFileLock:
    """
    File lock that automatically removes stale lock files.

    A lock file is considered stale if its mtime is older than
    stale_timeout_seconds (default: from config, 600s).
    """

    def __init__(
        self,
        lock_path: str | Path,
        timeout: float = 10.0,
        stale_timeout_seconds: int = 600,
    ) -> None:
        self._lock_path = Path(lock_path)
        self._timeout = timeout
        self._stale_timeout = stale_timeout_seconds
        self._lock = filelock.FileLock(str(lock_path), timeout=0)

    def _is_stale(self) -> bool:
        """Check if lock file exists and is older than stale_timeout."""
        try:
            mtime = self._lock_path.stat().st_mtime
            age = time.time() - mtime
            return age > self._stale_timeout
        except FileNotFoundError:
            return False

    def _force_remove(self) -> None:
        """Force-remove a stale lock file."""
        try:
            self._lock_path.unlink(missing_ok=True)
        except OSError:
            pass

    def acquire(self, timeout: float | None = None) -> None:
        """Acquire the lock, removing stale files if needed."""
        effective_timeout = timeout if timeout is not None else self._timeout
        deadline = time.monotonic() + effective_timeout

        while time.monotonic() < deadline:
            # Remove stale lock if present
            if self._is_stale():
                self._force_remove()
                # Re-create the lock object pointing to same path
                self._lock = filelock.FileLock(str(self._lock_path), timeout=0)

            try:
                self._lock.acquire(timeout=0)
                return  # Success
            except filelock.Timeout:
                time.sleep(0.05)

        raise filelock.Timeout(str(self._lock_path))

    def release(self) -> None:
        """Release the lock."""
        try:
            self._lock.release()
        except RuntimeError as exc:
            logger.warning("Failed to release file lock %s: %s", self._lock_path, exc)

    def __enter__(self) -> "StaleAwareFileLock":
        self.acquire()
        return self

    def __exit__(self, *args: object) -> None:
        self.release()
