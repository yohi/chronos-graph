"""Integration-level smoke test for Orchestrator with Prisma backend."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from context_store.config import Settings
from context_store.orchestrator import create_orchestrator


@pytest.mark.asyncio
async def test_orchestrator_initialization_with_prisma(monkeypatch):
    """STORAGE_BACKEND=prisma で create_orchestrator が正常に完了することを確認する。"""
    monkeypatch.setenv("STORAGE_BACKEND", "prisma")
    monkeypatch.setenv("PRISMA_DATABASE_URL", "prisma://accelerate.prisma-data.net/?api_key=test")
    monkeypatch.setenv("GRAPH_ENABLED", "false")

    # .env ファイルを無視して環境変数を優先させる
    settings = Settings(_env_file=None)

    # PrismaStorageAdapter.create をモックして実接続を回避
    mock_storage = AsyncMock()
    # dimension チェックを通すため、get_vector_dimension が 768 を返すように設定
    mock_storage.get_vector_dimension = AsyncMock(return_value=768)
    mock_storage.dispose = AsyncMock()

    with patch(
        "context_store.storage.prisma.PrismaStorageAdapter.create",
        new=AsyncMock(return_value=mock_storage),
    ) as mock_create:
        orchestrator = await create_orchestrator(settings)
        try:
            assert orchestrator._storage is mock_storage
            assert orchestrator._graph is None
            mock_create.assert_called_once_with(settings)
        finally:
            await orchestrator.dispose()
