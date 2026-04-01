import asyncio
from unittest.mock import MagicMock

from context_store.utils.sqlite_interrupt import SafeSqliteInterruptCtx


def test_interrupt_called_when_running():
    """interrupt() is called when context is active."""
    mock_conn = MagicMock()
    ctx = SafeSqliteInterruptCtx(mock_conn)

    async def run():
        async with ctx:
            assert ctx._is_running
            ctx.interrupt()
        assert not ctx._is_running

    asyncio.run(run())
    mock_conn.interrupt.assert_called_once()


def test_interrupt_not_effective_after_exit():
    """After context exits, _is_running is False so interrupt won't fire."""
    mock_conn = MagicMock()
    ctx = SafeSqliteInterruptCtx(mock_conn)

    async def run():
        async with ctx:
            pass
        # Call interrupt after context has exited
        ctx.interrupt()

    asyncio.run(run())
    mock_conn.interrupt.assert_not_called()


def test_context_manager_sets_running_state():
    """Test that _is_running is properly set/unset."""
    mock_conn = MagicMock()
    ctx = SafeSqliteInterruptCtx(mock_conn)
    assert not ctx._is_running

    async def run():
        async with ctx:
            assert ctx._is_running
        assert not ctx._is_running

    asyncio.run(run())
