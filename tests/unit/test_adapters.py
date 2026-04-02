"""Task 4.1: Source Adapter のユニットテスト。"""

from __future__ import annotations

import socket
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

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


def test_raw_content_default_metadata() -> None:
    """RawContent のデフォルトメタデータは空辞書。"""
    rc = RawContent(content="test", source_type=SourceType.MANUAL)
    assert rc.metadata == {}


# ===========================================================================
# ConversationAdapter テスト
# ===========================================================================


@pytest.mark.asyncio
async def test_conversation_adapter_basic() -> None:
    """ConversationAdapter が会話トランスクリプトを RawContent リストに変換する。"""
    transcript = "User: こんにちは\nAssistant: こんにちは！"
    adapter = ConversationAdapter()
    results = await adapter.adapt(transcript, metadata={"session_id": "s1"})
    assert len(results) >= 1
    for rc in results:
        assert rc.source_type == SourceType.CONVERSATION
        assert rc.content


@pytest.mark.asyncio
async def test_conversation_adapter_multiple_turns() -> None:
    """複数ターンの会話が正しく分割される。"""
    transcript = (
        "User: 質問1\nAssistant: 回答1\n"
        "User: 質問2\nAssistant: 回答2\n"
        "User: 質問3\nAssistant: 回答3\n"
    )
    adapter = ConversationAdapter()
    results = await adapter.adapt(transcript)
    assert len(results) >= 2


@pytest.mark.asyncio
async def test_conversation_adapter_metadata_propagation() -> None:
    """メタデータがすべての RawContent に伝播する。"""
    transcript = "User: test\nAssistant: ok"
    adapter = ConversationAdapter()
    results = await adapter.adapt(transcript, metadata={"project": "proj1"})
    for rc in results:
        assert "project" in rc.metadata


# ===========================================================================
# ManualAdapter テスト
# ===========================================================================


@pytest.mark.asyncio
async def test_manual_adapter_basic() -> None:
    """ManualAdapter がテキストを RawContent に変換する。"""
    adapter = ManualAdapter()
    results = await adapter.adapt("テストテキスト")
    assert len(results) == 1
    assert results[0].content == "テストテキスト"
    assert results[0].source_type == SourceType.MANUAL


@pytest.mark.asyncio
async def test_manual_adapter_metadata() -> None:
    """ManualAdapter がメタデータを正しく設定する。"""
    adapter = ManualAdapter()
    results = await adapter.adapt("テスト", metadata={"author": "user"})
    assert results[0].metadata == {"author": "user"}


# ===========================================================================
# URLAdapter セキュリティテスト
# ===========================================================================


def _make_settings(**kwargs: Any) -> Settings:
    """テスト用 Settings を作成する（embedding_provider は openai 以外を使用）。"""
    defaults = {
        "embedding_provider": "local-model",
        "local_model_name": "test-model",
        "storage_backend": "sqlite",
    }
    defaults.update(kwargs)
    return Settings(**defaults)


@pytest.mark.asyncio
async def test_url_adapter_rejects_loopback_ip() -> None:
    """ループバックIP (127.0.0.1) を拒否する。"""
    settings = _make_settings()
    adapter = URLAdapter(settings=settings)

    with patch("socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 80))]
        with pytest.raises(
            ValueError, match=r"[Pp]rivate|[Ll]oopback|[Bb]locked|[Ss]SRF|[Rr]estricted"
        ):
            await adapter.adapt("http://example.com/")


@pytest.mark.asyncio
async def test_url_adapter_rejects_private_10_x() -> None:
    """プライベートIP (10.x.x.x) を拒否する。"""
    settings = _make_settings()
    adapter = URLAdapter(settings=settings)

    with patch("socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("10.1.2.3", 80))]
        with pytest.raises(ValueError, match=r"[Pp]rivate|[Bb]locked|[Ss]SRF|[Rr]estricted"):
            await adapter.adapt("http://example.com/")


@pytest.mark.asyncio
async def test_url_adapter_rejects_link_local_169() -> None:
    """リンクローカルIP (169.254.169.254) を拒否する。"""
    settings = _make_settings()
    adapter = URLAdapter(settings=settings)

    with patch("socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("169.254.169.254", 80))
        ]
        with pytest.raises(
            ValueError, match=r"[Pp]rivate|[Ll]ink.local|[Bb]locked|[Ss]SRF|[Rr]estricted"
        ):
            await adapter.adapt("http://example.com/")


@pytest.mark.asyncio
async def test_url_adapter_rejects_ipv6_loopback() -> None:
    """IPv6 ループバック (::1) を拒否する。"""
    settings = _make_settings()
    adapter = URLAdapter(settings=settings)

    with patch("socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [(socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("::1", 80, 0, 0))]
        with pytest.raises(
            ValueError, match=r"[Pp]rivate|[Ll]oopback|[Bb]locked|[Ss]SRF|[Rr]estricted"
        ):
            await adapter.adapt("http://example.com/")


@pytest.mark.asyncio
async def test_url_adapter_rejects_ipv6_link_local() -> None:
    """IPv6 リンクローカル (fe80::) を拒否する。"""
    settings = _make_settings()
    adapter = URLAdapter(settings=settings)

    with patch("socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [
            (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("fe80::1", 80, 0, 0))
        ]
        with pytest.raises(
            ValueError, match=r"[Pp]rivate|[Ll]ink.local|[Bb]locked|[Ss]SRF|[Rr]estricted"
        ):
            await adapter.adapt("http://example.com/")


@pytest.mark.asyncio
async def test_url_adapter_rejects_ipv6_multicast() -> None:
    """IPv6 マルチキャスト (ff00::) を拒否する。"""
    settings = _make_settings()
    adapter = URLAdapter(settings=settings)

    with patch("socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [
            (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("ff02::1", 80, 0, 0))
        ]
        with pytest.raises(ValueError, match=r"[Mm]ulticast|[Bb]locked|[Ss]SRF|[Rr]estricted"):
            await adapter.adapt("http://example.com/")


@pytest.mark.asyncio
async def test_url_adapter_rejects_unspecified_0000() -> None:
    """未指定アドレス (0.0.0.0) を拒否する。"""
    settings = _make_settings()
    adapter = URLAdapter(settings=settings)

    with patch("socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("0.0.0.0", 80))]
        with pytest.raises(ValueError, match=r"[Uu]nspecified|[Bb]locked|[Ss]SRF|[Rr]estricted"):
            await adapter.adapt("http://example.com/")


@pytest.mark.asyncio
async def test_url_adapter_rejects_ip_literal_url_loopback() -> None:
    """IPリテラルURL (http://127.0.0.1/) を拒否する。"""
    settings = _make_settings()
    adapter = URLAdapter(settings=settings)

    with pytest.raises(
        ValueError, match=r"[Pp]rivate|[Ll]oopback|[Bb]locked|[Ss]SRF|[Rr]estricted"
    ):
        await adapter.adapt("http://127.0.0.1/")


@pytest.mark.asyncio
async def test_url_adapter_rejects_ip_literal_url_private() -> None:
    """IPリテラルURL (http://192.168.1.1/) を拒否する。"""
    settings = _make_settings()
    adapter = URLAdapter(settings=settings)

    with pytest.raises(ValueError, match=r"[Pp]rivate|[Bb]locked|[Ss]SRF|[Rr]estricted"):
        await adapter.adapt("http://192.168.1.1/")


@pytest.mark.asyncio
async def test_url_adapter_rejects_any_private_in_dns_response() -> None:
    """DNS応答に1件でもプライベートIPが含まれれば拒否する。"""
    settings = _make_settings()
    adapter = URLAdapter(settings=settings)

    # パブリックIPとプライベートIPが混在する場合
    with patch("socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("1.2.3.4", 80)),
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("10.0.0.1", 80)),
        ]
        with pytest.raises(ValueError, match=r"[Pp]rivate|[Bb]locked|[Ss]SRF|[Rr]estricted"):
            await adapter.adapt("http://example.com/")


@pytest.mark.asyncio
async def test_url_adapter_rejects_too_many_redirects() -> None:
    """リダイレクト4回目で失敗する（url_max_redirects=3）。"""
    settings = _make_settings(url_max_redirects=3)
    adapter = URLAdapter(settings=settings)

    redirect_count = 0

    async def mock_get_ips(hostname: str) -> list[str]:
        return ["203.0.113.1"]  # 文書化済みテストIP（RFC 5737）

    async def mock_fetch(url: str, resolved_ips: list[str]) -> httpx.Response:
        nonlocal redirect_count
        redirect_count += 1
        response = MagicMock(spec=httpx.Response)
        response.status_code = 302
        response.headers = httpx.Headers(
            {"location": f"http://other.example.com/redirect{redirect_count}"}
        )
        return response

    with (
        patch.object(adapter, "_resolve_and_validate_ips", new=mock_get_ips),
        patch.object(adapter, "_fetch_with_verified_ip", new=mock_fetch),
    ):
        with pytest.raises((ValueError, Exception), match=r"[Rr]edirect|[Tt]oo many"):
            await adapter.adapt("http://example.com/")


@pytest.mark.asyncio
async def test_url_adapter_rejects_oversized_response() -> None:
    """10MB超のレスポンスを受信途中で即時中断し拒否する。"""
    settings = _make_settings(url_max_response_bytes=100)  # 100バイト制限
    adapter = URLAdapter(settings=settings)

    async def mock_get_ips(hostname: str) -> list[str]:
        return ["203.0.113.1"]

    # 大きなコンテンツを返すモック
    async def aiter_bytes():  # type: ignore[return]
        yield b"x" * 200  # 200バイト（制限の100バイトを超える）

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.headers = httpx.Headers({"content-type": "text/html"})
    mock_response.aiter_bytes = aiter_bytes
    mock_response.aclose = AsyncMock()

    async def mock_fetch(url: str, resolved_ips: list[str]) -> httpx.Response:
        return mock_response

    with (
        patch.object(adapter, "_resolve_and_validate_ips", new=mock_get_ips),
        patch.object(adapter, "_fetch_with_verified_ip", new=mock_fetch),
    ):
        with pytest.raises(ValueError, match=r"[Ss]ize|[Ll]imit|[Tt]oo large|[Mm]ax"):
            await adapter.adapt("http://example.com/")

    # aclose() が呼ばれること（プール汚染防止）
    mock_response.aclose.assert_called()


@pytest.mark.asyncio
async def test_url_adapter_rejects_disallowed_content_type() -> None:
    """許可されていない Content-Type を拒否する。"""
    settings = _make_settings()
    adapter = URLAdapter(settings=settings)

    async def mock_get_ips(hostname: str) -> list[str]:
        return ["203.0.113.1"]

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.headers = httpx.Headers({"content-type": "image/png"})
    mock_response.aclose = AsyncMock()

    async def mock_fetch(url: str, resolved_ips: list[str]) -> httpx.Response:
        return mock_response

    with (
        patch.object(adapter, "_resolve_and_validate_ips", new=mock_get_ips),
        patch.object(adapter, "_fetch_with_verified_ip", new=mock_fetch),
    ):
        with pytest.raises(ValueError, match=r"[Cc]ontent.?[Tt]ype|[Nn]ot allowed|[Dd]isallowed"):
            await adapter.adapt("http://example.com/")

    mock_response.aclose.assert_called()


@pytest.mark.asyncio
async def test_url_adapter_allows_private_urls_when_enabled() -> None:
    """allow_private_urls=True でプライベートURLが許可される。"""
    settings = _make_settings(allow_private_urls=True)
    adapter = URLAdapter(settings=settings)

    async def mock_get_ips_with_bypass(hostname: str) -> list[str]:
        # allow_private_urls=True なのでプライベートIPでも返す
        return ["127.0.0.1"]

    async def aiter_bytes():  # type: ignore[return]
        yield b"<html><body>Hello</body></html>"

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.headers = httpx.Headers({"content-type": "text/html; charset=utf-8"})
    mock_response.aiter_bytes = aiter_bytes
    mock_response.aclose = AsyncMock()

    async def mock_fetch(url: str, resolved_ips: list[str]) -> httpx.Response:
        return mock_response

    with (
        patch.object(adapter, "_resolve_and_validate_ips", new=mock_get_ips_with_bypass),
        patch.object(adapter, "_fetch_with_verified_ip", new=mock_fetch),
    ):
        # プライベートIPでもエラーなく処理できること
        results = await adapter.adapt("http://127.0.0.1/")
        assert len(results) >= 1


@pytest.mark.asyncio
async def test_url_adapter_uses_settings() -> None:
    """URLAdapter が Settings の URL 関連設定を参照する。"""
    settings = _make_settings(
        url_max_redirects=5,
        url_max_response_bytes=5 * 1024 * 1024,
        url_timeout_seconds=10,
    )
    adapter = URLAdapter(settings=settings)

    assert adapter.settings.url_max_redirects == 5
    assert adapter.settings.url_max_response_bytes == 5 * 1024 * 1024
    assert adapter.settings.url_timeout_seconds == 10


@pytest.mark.asyncio
async def test_url_adapter_validates_ip_check_function() -> None:
    """IP検証ロジックが正しく動作することを確認する。"""
    settings = _make_settings()
    adapter = URLAdapter(settings=settings)

    # パブリックIP は通過（Google Public DNS）
    assert adapter._is_restricted_ip("8.8.8.8") is False

    # プライベート/ループバック/リンクローカルは拒否
    assert adapter._is_restricted_ip("127.0.0.1") is True
    assert adapter._is_restricted_ip("10.0.0.1") is True
    assert adapter._is_restricted_ip("172.16.0.1") is True
    assert adapter._is_restricted_ip("192.168.1.1") is True
    assert adapter._is_restricted_ip("169.254.169.254") is True
    assert adapter._is_restricted_ip("0.0.0.0") is True
    assert adapter._is_restricted_ip("::1") is True
    assert adapter._is_restricted_ip("fe80::1") is True
    assert adapter._is_restricted_ip("ff02::1") is True
