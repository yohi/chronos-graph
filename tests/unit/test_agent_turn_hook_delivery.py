import json

import httpx
import pytest

from scripts import agent_turn_hook


@pytest.mark.asyncio
async def test_strict_delivery_fails_when_api_key_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CHRONOS_INGESTION_MODE", "all")
    monkeypatch.delenv("MCP_GATEWAY_API_KEY", raising=False)
    assert not await agent_turn_hook._main_async("User: hello", strict_delivery=True)


@pytest.mark.asyncio
async def test_strict_delivery_redacts_transport_error(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("CHRONOS_INGESTION_MODE", "all")
    monkeypatch.setenv("MCP_GATEWAY_API_KEY", "fixture-token")

    async def fail_send(*args: object, **kwargs: object) -> bool:
        raise httpx.ConnectError("fixture-token leaked")

    monkeypatch.setattr(agent_turn_hook, "_send", fail_send)
    assert not await agent_turn_hook._main_async("User: hello", strict_delivery=True)
    assert "fixture-token" not in caplog.text


@pytest.mark.asyncio
async def test_opencode_delivery_forwards_project_to_memory_save() -> None:
    requests: list[httpx.Request] = []

    async def receive(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(202)

    async with httpx.AsyncClient(transport=httpx.MockTransport(receive)) as client:
        await agent_turn_hook._post_tools_call(
            client, "http://gateway", "session", "User: hello", {}, "demo-project"
        )

    assert requests[0].url.path == "/messages"
    assert requests[0].url.params["session_id"] == "session"
    assert json.loads(requests[0].content)["params"]["arguments"]["project"] == "demo-project"


@pytest.mark.asyncio
async def test_strict_delivery_does_not_accept_json_rpc_tool_error() -> None:
    async def receive(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "error": {"code": -1}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(receive)) as client:
        with pytest.raises(RuntimeError, match="memory_save tool call failed"):
            await agent_turn_hook._post_tools_call(
                client, "http://gateway", "session", "User: hello", {}
            )


@pytest.mark.asyncio
async def test_delivery_rejects_redirect_without_gateway_acceptance() -> None:
    async def receive(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://gateway/other"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(receive)) as client:
        with pytest.raises(RuntimeError, match="gateway did not accept memory_save"):
            await agent_turn_hook._post_tools_call(
                client, "http://gateway", "session", "User: hello", {}
            )
