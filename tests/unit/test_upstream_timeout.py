from __future__ import annotations

import asyncio

import pytest


def _make_result(text: str) -> object:
    return type("R", (), {"content": [{"type": "text", "text": text}], "isError": False})()


@pytest.mark.asyncio
async def test_tool_call_timeout_is_recoverable_upstream_error() -> None:
    from mcp_gateway.errors import UpstreamError
    from mcp_gateway.upstream.context_store_client import UpstreamClient
    from mcp_gateway.upstream.timeout_client import TimeoutConfig

    client = UpstreamClient(command=["context-store"], env={}, timeout_config=TimeoutConfig())
    client.timeout_config = TimeoutConfig(default_timeout_seconds=0.01)

    async def slow_call(name: str, arguments: dict[str, object]) -> dict[str, object]:
        await asyncio.sleep(1.0)
        return {"name": name, "arguments": arguments}

    client._call_tool_internal = slow_call

    with pytest.raises(UpstreamError) as exc_info:
        await client.call_tool("memory_search", {"query": "test"})

    assert exc_info.value.code == "UPSTREAM_TIMEOUT"
    assert exc_info.value.recoverable is True
    assert "memory_search" in str(exc_info.value)
    assert "0.01" in str(exc_info.value)


@pytest.mark.asyncio
async def test_tool_call_success_within_timeout_preserves_payload_parsing() -> None:
    from unittest.mock import AsyncMock

    from mcp_gateway.upstream.context_store_client import UpstreamClient
    from mcp_gateway.upstream.timeout_client import TimeoutConfig

    fake_session = AsyncMock()
    fake_session.call_tool.return_value = _make_result('{"result":"success"}')

    client = UpstreamClient(command=["context-store"], env={}, timeout_config=TimeoutConfig())
    client._session = fake_session
    client.timeout_config = TimeoutConfig(default_timeout_seconds=5.0)

    result = await client.call_tool("memory_search", {"query": "test"})

    assert result == {"result": "success"}
    fake_session.call_tool.assert_awaited_once_with("memory_search", {"query": "test"})


def test_timeout_config_tool_specific_and_max_clamp() -> None:
    from mcp_gateway.upstream.timeout_client import TimeoutConfig

    config = TimeoutConfig(default_timeout_seconds=30.0, max_timeout_seconds=45.0)
    config.tool_timeouts["slow_tool"] = 120.0

    assert config.get_timeout("memory_save_url") == 40.0
    assert config.get_timeout("memory_search") == 30.0
    assert config.get_timeout("slow_tool") == 45.0
