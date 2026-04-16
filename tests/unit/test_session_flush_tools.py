"""session_flush MCP ツールのユニットテスト。"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from context_store.server import ChronosServer


@pytest.fixture
def server_with_mock_orchestrator() -> ChronosServer:
    """Mock Orchestrator を持つ ChronosServer。"""
    server = ChronosServer()
    mock_orchestrator = MagicMock()
    mock_orchestrator.session_flush = AsyncMock(
        return_value={"status": "accepted", "estimated_chunks": 3}
    )
    mock_orchestrator.url_fetch_concurrency = 3
    server._orchestrator = mock_orchestrator
    server._initialized = True
    return server


class TestSessionFlushTool:
    """session_flush MCP ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_session_flush_returns_accepted(
        self, server_with_mock_orchestrator: ChronosServer
    ) -> None:
        """session_flush ツールが accepted を返す。"""
        result_str = await server_with_mock_orchestrator.session_flush(
            conversation_log="User: hello\nAssistant: hi",
        )
        result = json.loads(result_str)
        assert result["status"] == "accepted"
        assert result["estimated_chunks"] == 3

    @pytest.mark.asyncio
    async def test_session_flush_passes_all_args(
        self, server_with_mock_orchestrator: ChronosServer
    ) -> None:
        """session_flush ツールが全引数を Orchestrator に渡す。"""
        await server_with_mock_orchestrator.session_flush(
            conversation_log="User: test\nAssistant: test",
            session_id="test-session",
            project="my-project",
            tags=["tag1", "tag2"],
        )

        mock_orch = server_with_mock_orchestrator._orchestrator
        mock_orch.session_flush.assert_called_once_with(
            conversation_log="User: test\nAssistant: test",
            session_id="test-session",
            project="my-project",
            tags=["tag1", "tag2"],
        )

    @pytest.mark.asyncio
    async def test_session_flush_empty_log_returns_error(
        self, server_with_mock_orchestrator: ChronosServer
    ) -> None:
        """空 conversation_log のエラーが JSON で返る。"""
        mock_orch = server_with_mock_orchestrator._orchestrator
        mock_orch.session_flush = AsyncMock(
            return_value={"error": "conversation_log must not be empty"}
        )

        result_str = await server_with_mock_orchestrator.session_flush(
            conversation_log="",
        )
        result = json.loads(result_str)
        assert "error" in result
