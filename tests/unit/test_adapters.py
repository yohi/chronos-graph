"""Task 4.1: Source Adapter のユニットテスト。"""

from __future__ import annotations

import socket
from typing import Any
from unittest.mock import patch, AsyncMock, MagicMock

import httpx
import pytest

from context_store.config import Settings
from context_store.ingestion.adapters import (
    ConversationAdapter,
    ManualAdapter,
    RawContent,
    URLAdapter,
)
from context_store.models.memory import SourceType


# ===========================================================================
# RawContent テスト
# ===========================================================================


def test_raw_content_creation() -> None:
    """RawContent が正しく作成できる。"""
    rc = RawContent(
        content="test content",
        source_type=SourceType.MANUAL,
        metadata={"key": "value"},
    )
    assert rc.content == "test content"
    assert rc.source_type == SourceType.MANUAL
    assert rc.metadata == {"key": "value"}


# ===========================================================================
# ConversationAdapter / ManualAdapter テスト(簡略)
# ===========================================================================


@pytest.mark.asyncio
async def test_conversation_adapter_basic() -> None:
    adapter = ConversationAdapter()
    results = await adapter.adapt("User: 1\nAssistant: 1")
    assert len(results) >= 1


@pytest.mark.asyncio
async def test_manual_adapter_basic() -> None:
    adapter = ManualAdapter()
    results = await adapter.adapt("test")
    assert len(results) == 1


# ===========================================================================
# URLAdapter テスト(主要ロジックに集中)
# ===========================================================================


def _make_settings(**kwargs: Any) -> Settings:
    defaults = {
        "embedding_provider": "local-model",
        "local_model_name": "test-model",
        "storage_backend": "sqlite",
    }
    defaults.update(kwargs)
    return Settings(**defaults, _env_file=None)


@pytest.mark.asyncio
async def test_url_adapter_rejects_private_ips() -> None:
    """プライベートIPの拒否を確認。"""
    adapter = URLAdapter(settings=_make_settings())
    with patch("socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("10.0.0.1", 80))]
        with pytest.raises(ValueError, match=r"[Pp]rivate|[Bb]locked"):
            await adapter.adapt("http://example.com/")


@pytest.mark.asyncio
async def test_url_adapter_rejects_too_many_redirects() -> None:
    """リダイレクト制限。"""
    adapter = URLAdapter(settings=_make_settings(url_max_redirects=1))

    async def mock_fetch(url, ips):
        return 302, httpx.Headers({"location": "http://other.com"}), b""

    with (
        patch.object(adapter, "_resolve_and_validate_ips", return_value=["203.0.113.1"]),
        patch.object(adapter, "_fetch_with_verified_ip", side_effect=mock_fetch),
    ):
        with pytest.raises(ValueError, match=r"[Rr]edirect"):
            await adapter.adapt("http://example.com/")


@pytest.mark.asyncio
async def test_url_adapter_rejects_oversized_response() -> None:
    """サイズ超過(_fetch_with_verified_ip の内部ロジックを直接検証)。

    Note: Validating internal size/IP behavior. This intentional call to the private API 
    maintains coverage of size rejection and must be updated if the private API is refactored.
    """
    adapter = URLAdapter(settings=_make_settings(url_max_response_bytes=10))

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = httpx.Headers({"content-type": "text/plain"})

    # 大量データを返すイテレータ
    async def async_gen():
        yield b"a" * 20

    mock_resp.aiter_bytes.side_effect = async_gen
    mock_resp.aclose = AsyncMock()

    with patch("httpx.AsyncClient.stream") as mock_stream:
        mock_stream.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_stream.return_value.__aexit__ = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match=r"Response size exceeds max limit"):
            await adapter._fetch_with_verified_ip("http://example.com/", ["203.0.113.1"])


@pytest.mark.asyncio
async def test_url_adapter_iterates_all_ips() -> None:
    """複数IPのフォールバック検証。"""
    adapter = URLAdapter(settings=_make_settings())
    ips = ["203.0.113.1", "203.0.113.2"]
    call_count = 0

    async def mock_client_stream(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise httpx.ConnectError("Fail 1")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = httpx.Headers({"content-type": "text/plain"})

        async def async_gen():
            yield b"Success"

        mock_resp.aiter_bytes.side_effect = async_gen
        mock_resp.aclose = AsyncMock()
        return mock_resp

    with patch("httpx.AsyncClient.stream") as mock_stream:
        mock_stream.return_value.__aenter__ = AsyncMock(side_effect=mock_client_stream)
        mock_stream.return_value.__aexit__ = AsyncMock(return_value=None)

        _, _, body = await adapter._fetch_with_verified_ip("http://example.com", ips)
        assert body == b"Success"
        assert call_count == 2


@pytest.mark.asyncio
async def test_url_adapter_early_validation() -> None:
    """絶対URL/スキームの早期バリデーション。"""
    adapter = URLAdapter(settings=_make_settings())
    with pytest.raises(ValueError, match="URL must be absolute"):
        await adapter.adapt("/relative/path")
    with pytest.raises(ValueError, match="Unsupported URL scheme"):
        await adapter.adapt("ftp://example.com")
