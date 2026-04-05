"""MCP Server (FastMCP) のユニットテスト。

Orchestrator をモックし、実際の DB には接続しない。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_orchestrator() -> MagicMock:
    """Orchestrator のモック。"""
    orch = MagicMock()
    orch.save = AsyncMock(return_value=[])
    orch.save_url = AsyncMock(return_value=[])
    orch.search = AsyncMock(return_value={"results": [], "total": 0})
    orch.search_graph = AsyncMock(return_value={"results": [], "total": 0})
    orch.delete = AsyncMock(return_value=True)
    orch.prune = AsyncMock(return_value=5)
    orch.stats = AsyncMock(
        return_value={"active_count": 10, "archived_count": 2, "total_count": 12, "project": None}
    )
    orch.dispose = AsyncMock(return_value=None)
    orch.start_lifecycle = AsyncMock(return_value=None)
    orch.url_fetch_concurrency = 3
    return orch


@pytest.fixture
def chronos_server(mock_orchestrator: MagicMock):
    """ChronosServer インスタンスを返す(初期化済み状態に設定)。"""
    from context_store.server import ChronosServer

    server = ChronosServer()
    # テスト用に直接 orchestrator を注入して初期化済み状態にする
    server._orchestrator = mock_orchestrator
    server._initialized = True
    # self._init_lock は __init__ で初期化されるようになった
    server._url_semaphore = asyncio.Semaphore(3)
    return server


# ---------------------------------------------------------------------------
# 初期化テスト
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_initialized_prevents_double_init():
    """初期化が1回だけ実行されることを確認する。"""
    from context_store.server import ChronosServer

    server = ChronosServer()
    call_count = 0

    async def fake_do_initialize():
        nonlocal call_count
        call_count += 1
        orch = MagicMock()
        orch.start_lifecycle = AsyncMock()
        orch.url_fetch_concurrency = 3
        server._orchestrator = orch

    server._do_initialize = fake_do_initialize
    server._url_semaphore = asyncio.Semaphore(3)

    # 複数の並行呼び出し
    await asyncio.gather(
        server._ensure_initialized(),
        server._ensure_initialized(),
        server._ensure_initialized(),
    )

    # 1回だけ初期化される
    assert call_count == 1
    assert server._initialized is True


# ---------------------------------------------------------------------------
# memory_save テスト
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_save_default_source_is_conversation(
    chronos_server, mock_orchestrator: MagicMock
):
    """source を省略すると "conversation" が使われること (回帰テスト)。"""
    await chronos_server.memory_save(content="test content")

    mock_orchestrator.save.assert_called_once()
    call_kwargs = mock_orchestrator.save.call_args

    # source_type が SourceType.CONVERSATION であることを確認
    from context_store.models.memory import SourceType

    # positional または keyword どちらでも確認
    args, kwargs = call_kwargs
    source_type = kwargs.get("source_type", args[1] if len(args) > 1 else None)
    assert source_type == SourceType.CONVERSATION


@pytest.mark.asyncio
async def test_memory_save_explicit_source_manual(chronos_server, mock_orchestrator: MagicMock):
    """source="manual" を明示した場合は "manual" が保持されること。"""
    await chronos_server.memory_save(content="test content", source="manual")

    mock_orchestrator.save.assert_called_once()
    call_kwargs = mock_orchestrator.save.call_args

    from context_store.models.memory import SourceType

    args, kwargs = call_kwargs
    source_type = kwargs.get("source_type", args[1] if len(args) > 1 else None)
    assert source_type == SourceType.MANUAL


@pytest.mark.asyncio
async def test_memory_save_delegates_to_orchestrator(chronos_server, mock_orchestrator: MagicMock):
    """memory_save が orchestrator.save() に委譲されること。"""
    result = await chronos_server.memory_save(
        content="hello",
        source="conversation",
        project="my-project",
        tags=["tag1", "tag2"],
        importance=0.8,
    )

    mock_orchestrator.save.assert_called_once()
    assert result is not None


@pytest.mark.asyncio
async def test_memory_save_tags_none_becomes_empty_list(
    chronos_server, mock_orchestrator: MagicMock
):
    """tags=None の場合は [] として扱われること。"""
    await chronos_server.memory_save(content="test", tags=None)

    mock_orchestrator.save.assert_called_once()
    call_kwargs = mock_orchestrator.save.call_args
    _, kwargs = call_kwargs
    metadata = kwargs.get("metadata", {})
    assert metadata.get("tags") == []


# ---------------------------------------------------------------------------
# memory_search テスト
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_search_delegates_to_orchestrator(
    chronos_server, mock_orchestrator: MagicMock
):
    """memory_search が orchestrator.search() に委譲されること。"""
    result = await chronos_server.memory_search(query="find this")

    mock_orchestrator.search.assert_called_once()
    assert result is not None


@pytest.mark.asyncio
async def test_memory_search_passes_parameters(chronos_server, mock_orchestrator: MagicMock):
    """memory_search がパラメータを正しく渡すこと。"""
    await chronos_server.memory_search(
        query="test",
        project="proj",
        memory_type="episodic",
        top_k=5,
        max_tokens=1000,
    )

    mock_orchestrator.search.assert_called_once_with(
        "test",
        project="proj",
        memory_type="episodic",
        top_k=5,
        max_tokens=1000,
    )


# ---------------------------------------------------------------------------
# memory_search_graph テスト
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_search_graph_delegates_to_orchestrator(
    chronos_server, mock_orchestrator: MagicMock
):
    """memory_search_graph が orchestrator.search_graph() に委譲されること。"""
    result = await chronos_server.memory_search_graph(query="graph query")

    mock_orchestrator.search_graph.assert_called_once()
    assert result is not None


# ---------------------------------------------------------------------------
# memory_delete テスト
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_delete_delegates_to_orchestrator(
    chronos_server, mock_orchestrator: MagicMock
):
    """memory_delete が orchestrator.delete() に委譲されること。"""
    result = await chronos_server.memory_delete(memory_id="abc-123")

    mock_orchestrator.delete.assert_called_once_with("abc-123")
    assert result is not None


# ---------------------------------------------------------------------------
# memory_prune テスト
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_prune_default_dry_run_true(chronos_server, mock_orchestrator: MagicMock):
    """dry_run のデフォルトが True であること。"""
    await chronos_server.memory_prune()

    mock_orchestrator.prune.assert_called_once()
    call_kwargs = mock_orchestrator.prune.call_args
    _, kwargs = call_kwargs
    # dry_run がデフォルトで True
    assert kwargs.get("dry_run", True) is True


@pytest.mark.asyncio
async def test_memory_prune_explicit_dry_run_false(chronos_server, mock_orchestrator: MagicMock):
    """dry_run=False を明示した場合は False が渡されること。"""
    await chronos_server.memory_prune(dry_run=False)

    mock_orchestrator.prune.assert_called_once()
    call_kwargs = mock_orchestrator.prune.call_args
    _, kwargs = call_kwargs
    assert kwargs.get("dry_run") is False


# ---------------------------------------------------------------------------
# memory_stats テスト
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_stats_delegates_to_orchestrator(chronos_server, mock_orchestrator: MagicMock):
    """memory_stats が orchestrator.stats() に委譲されること。"""
    result = await chronos_server.memory_stats()

    mock_orchestrator.stats.assert_called_once()
    assert result is not None


# ---------------------------------------------------------------------------
# memory_save_url テスト
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_save_url_delegates_to_orchestrator(
    chronos_server, mock_orchestrator: MagicMock
):
    """memory_save_url が orchestrator.save_url() に委譲されること。"""
    result = await chronos_server.memory_save_url(url="https://example.com")

    mock_orchestrator.save_url.assert_called_once()
    assert result is not None


@pytest.mark.asyncio
async def test_memory_save_url_uses_semaphore(chronos_server, mock_orchestrator: MagicMock):
    """URL 取得時にセマフォが使われること(並行呼び出しで制限されること)。"""
    # セマフォのカウントを1にして排他制御を確認
    chronos_server._url_semaphore = asyncio.Semaphore(1)

    call_order = []

    async def mock_save_url_slow(url, metadata=None):
        call_order.append("start")
        await asyncio.sleep(0.01)
        call_order.append("end")
        return []

    mock_orchestrator.save_url = mock_save_url_slow

    # 2つの並行呼び出しを実行
    await asyncio.gather(
        chronos_server.memory_save_url(url="https://example1.com"),
        chronos_server.memory_save_url(url="https://example2.com"),
    )

    # セマフォにより順序が保証される: start, end, start, end
    assert call_order == ["start", "end", "start", "end"]


# ---------------------------------------------------------------------------
# MCP ツール登録テスト
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_registers_core_tools():
    """FastMCP インスタンスにツールとリソースが正しく登録されていることを確認する。"""
    from context_store import server as server_module

    mcp = server_module.mcp
    assert mcp is not None

    # ツールの一覧を取得して名前を検証
    tools = await mcp.list_tools()
    tool_names = {t.name for t in tools}
    expected_tools = {
        "memory_save",
        "memory_save_url",
        "memory_search",
        "memory_search_graph",
        "memory_delete",
        "memory_prune",
        "memory_stats",
    }
    for et in expected_tools:
        assert et in tool_names, f"Tool {et} not registered"

    # リソースの一覧を検証
    resources = await mcp.list_resources()
    resource_uris = {str(r.uri) for r in resources}
    expected_resources = {"memory://stats", "memory://projects"}
    for er in expected_resources:
        assert er in resource_uris, f"Resource {er} not registered"
