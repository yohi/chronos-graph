from __future__ import annotations

from collections.abc import Callable

from .models import SyncPlan
from .transaction_apply import (
    _apply_non_hook_targets,
    _validate_preflight_state,
    install_selected_hooks,
)
from .transaction_journal import TransactionJournal
from .transaction_rollback import rollback_transaction
from .transaction_types import (
    ApplyError,
    FileOperations,
    HookSetupError,
    PostWriteVerificationError,
    RollbackResult,
    SyncResult,
    SystemFileOperations,
)
from .transaction_verify import verify_post_write_state

__all__ = [
    "ApplyError",
    "FileOperations",
    "HookSetupError",
    "PostWriteVerificationError",
    "RollbackResult",
    "SyncResult",
    "SystemFileOperations",
    "apply_sync",
]


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
