import os
import time

import filelock
import pytest

from context_store.utils.stale_lock import StaleAwareFileLock


def test_normal_acquisition(tmp_path):
    """Normal lock acquisition works."""
    lock_path = tmp_path / "test.lock"
    lock = StaleAwareFileLock(lock_path, stale_timeout_seconds=600)
    with lock:
        assert lock._lock_path.exists()
    assert not lock._lock_path.exists()


def test_stale_lock_recovery(tmp_path):
    """Stale lock file is removed and re-acquired."""
    lock_path = tmp_path / "test.lock"

    # Create a fake stale lock file with old mtime
    lock_path.write_text("fake lock")
    old_time = time.time() - 700  # 700 seconds ago
    os.utime(lock_path, (old_time, old_time))

    # Should remove stale file and acquire successfully
    lock = StaleAwareFileLock(lock_path, stale_timeout_seconds=600)
    lock.acquire(timeout=2.0)
    lock.release()


def test_fresh_lock_not_removed(tmp_path):
    """Fresh lock file is not treated as stale."""
    lock_path = tmp_path / "test.lock"

    # Acquire a real lock (fresh)
    real_lock = filelock.FileLock(str(lock_path), timeout=5)
    real_lock.acquire()

    try:
        # Our lock should NOT remove the fresh lock (would raise Timeout)
        our_lock = StaleAwareFileLock(lock_path, stale_timeout_seconds=600)
        with pytest.raises(filelock.Timeout):
            our_lock.acquire(timeout=0.1)
    finally:
        real_lock.release()
