from __future__ import annotations

import json
from typing import cast
from unittest.mock import patch

import httpx
import pytest

from mcp_gateway.policy.memory_client import MemoryClient, MemoryFetchError
from mcp_gateway.policy.models_evaluator import MemoryItem


@pytest.mark.asyncio
async def test_retrieve_returns_memory_items() -> None:
    client = MemoryClient(dashboard_url="http://localhost:9000", top_k=3)
    payload = [
        {
            "id": "1",
            "content": "x",
            "memoryType": "semantic",
            "importance": 0.7,
            "project": "demo",
            "accessCount": 2,
            "createdAt": None,
        }
    ]

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/memories/semantic-search"
        body = cast(object, json.loads(request.content))
        assert body == {"query": "tool:bash command=ls", "project": "demo", "top_k": 3}
        assert request.headers["content-type"] == "application/json"
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    try:
        with patch.object(MemoryClient, "_build_transport", return_value=transport):
            out = await client.retrieve(query="tool:bash command=ls", project="demo")
    finally:
        await client.close()

    assert out == [MemoryItem(content="x", memory_type="semantic", importance=0.7)]


@pytest.mark.asyncio
async def test_retrieve_sends_authorization_header_when_api_key_configured() -> None:
    client = MemoryClient(dashboard_url="http://localhost:9000", _api_key="secret-token")

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer secret-token"
        return httpx.Response(200, json=[])

    transport = httpx.MockTransport(handler)
    try:
        with patch.object(MemoryClient, "_build_transport", return_value=transport):
            out = await client.retrieve(query="x")
    finally:
        await client.close()

    assert out == []


@pytest.mark.asyncio
async def test_retrieve_raises_on_non_200_status() -> None:
    client = MemoryClient(dashboard_url="http://localhost:9000")

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="service unavailable")

    transport = httpx.MockTransport(handler)
    try:
        with patch.object(MemoryClient, "_build_transport", return_value=transport):
            with pytest.raises(MemoryFetchError) as exc_info:
                _ = await client.retrieve(query="x")
        assert "dashboard returned status 503" in str(exc_info.value)
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_retrieve_raises_memory_fetch_error_on_http_error() -> None:
    client = MemoryClient(dashboard_url="http://localhost:9000")

    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed", request=request)

    transport = httpx.MockTransport(handler)
    try:
        with patch.object(MemoryClient, "_build_transport", return_value=transport):
            with pytest.raises(MemoryFetchError) as exc_info:
                _ = await client.retrieve(query="x")
        assert "ConnectError" in str(exc_info.value)
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_retrieve_raises_memory_fetch_error_on_timeout() -> None:
    client = MemoryClient(dashboard_url="http://localhost:9000", timeout_seconds=0.001)

    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("boom", request=request)

    transport = httpx.MockTransport(handler)
    try:
        with patch.object(MemoryClient, "_build_transport", return_value=transport):
            with pytest.raises(MemoryFetchError):
                _ = await client.retrieve(query="x")
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_retrieve_raises_memory_fetch_error_on_invalid_json() -> None:
    client = MemoryClient(dashboard_url="http://localhost:9000")

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json")

    transport = httpx.MockTransport(handler)
    try:
        with patch.object(MemoryClient, "_build_transport", return_value=transport):
            with pytest.raises(MemoryFetchError):
                _ = await client.retrieve(query="x")
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_retrieve_raises_memory_fetch_error_on_non_list_response() -> None:
    client = MemoryClient(dashboard_url="http://localhost:9000")

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"content": "x"})

    transport = httpx.MockTransport(handler)
    try:
        with patch.object(MemoryClient, "_build_transport", return_value=transport):
            with pytest.raises(MemoryFetchError):
                _ = await client.retrieve(query="x")
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_retrieve_skips_malformed_items() -> None:
    client = MemoryClient(dashboard_url="http://localhost:9000")
    payload = [
        {"content": "good", "memoryType": "semantic", "importance": 0.5},
        {"content": 123, "memoryType": "bad_content_type"},  # content must be str
        {"content": "bad_type", "memoryType": ["not", "str"]},  # memoryType must be str
        "not-a-mapping",
    ]

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    try:
        with patch.object(MemoryClient, "_build_transport", return_value=transport):
            out = await client.retrieve(query="x")
    finally:
        await client.close()

    assert len(out) == 1
    assert out[0].content == "good"


def test_from_env_falls_back_to_default_allowed_hosts_on_empty_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CHRONOS_DASHBOARD_URL", "http://localhost:9000")
    monkeypatch.setenv("CHRONOS_DASHBOARD_ALLOWED_HOSTS", ",")
    c = MemoryClient.from_env()
    assert c is not None
    assert c._allowed_hosts == frozenset({"localhost", "127.0.0.1", "::1"})


def test_from_env_returns_none_when_url_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CHRONOS_DASHBOARD_URL", raising=False)
    assert MemoryClient.from_env() is None


def test_from_env_picks_up_url_and_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHRONOS_DASHBOARD_URL", "http://localhost:9000/")
    monkeypatch.setenv("CHRONOS_DASHBOARD_API_KEY", "expected-key")
    c = MemoryClient.from_env()
    assert c is not None
    assert c.dashboard_url == "http://localhost:9000"
    assert c._api_key == "expected-key"


def test_from_env_rejects_unallowed_dashboard_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHRONOS_DASHBOARD_URL", "http://attacker.example:9000")
    with pytest.raises(MemoryFetchError):
        _ = MemoryClient.from_env()


def test_from_env_accepts_explicit_allowed_dashboard_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CHRONOS_DASHBOARD_URL", "https://dashboard.internal")
    monkeypatch.setenv("CHRONOS_DASHBOARD_ALLOWED_HOSTS", "dashboard.internal")
    c = MemoryClient.from_env()
    assert c is not None
    assert c.dashboard_url == "https://dashboard.internal"


def test_from_env_raises_on_invalid_numeric_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHRONOS_DASHBOARD_URL", "http://localhost:9000")

    # Invalid string
    monkeypatch.setenv("CHRONOS_DASHBOARD_TIMEOUT_SECONDS", "abc")
    with pytest.raises(MemoryFetchError, match="invalid numeric value"):
        MemoryClient.from_env()

    # Zero timeout
    monkeypatch.setenv("CHRONOS_DASHBOARD_TIMEOUT_SECONDS", "0")
    with pytest.raises(MemoryFetchError, match="must be > 0"):
        MemoryClient.from_env()

    # Negative top_k
    monkeypatch.setenv("CHRONOS_DASHBOARD_TIMEOUT_SECONDS", "3.0")
    monkeypatch.setenv("CHRONOS_DASHBOARD_TOP_K", "-1")
    with pytest.raises(MemoryFetchError, match="must be 0 < k <= 50"):
        MemoryClient.from_env()

    # Too high top_k
    monkeypatch.setenv("CHRONOS_DASHBOARD_TOP_K", "51")
    with pytest.raises(MemoryFetchError, match="must be 0 < k <= 50"):
        MemoryClient.from_env()


def test_rejects_dashboard_url_with_userinfo() -> None:
    with pytest.raises(MemoryFetchError):
        _ = MemoryClient(dashboard_url="http://token@localhost:9000")


def test_rejects_dashboard_url_with_unsupported_scheme() -> None:
    with pytest.raises(MemoryFetchError):
        _ = MemoryClient(dashboard_url="file:///etc/passwd")


def test_repr_does_not_include_api_key() -> None:
    assert "secret-token" not in repr(
        MemoryClient(dashboard_url="http://localhost", _api_key="secret-token")
    )
