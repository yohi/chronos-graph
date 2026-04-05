"""Tests for Embedding Provider Protocol and OpenAI implementation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from context_store.embedding.openai import OpenAIEmbeddingProvider
from context_store.embedding.protocols import EmbeddingProvider


class TestEmbeddingProtocol:
    """EmbeddingProvider Protocol のテスト。"""

    def test_openai_provider_implements_protocol(self) -> None:
        provider = OpenAIEmbeddingProvider(api_key="test-key", model="text-embedding-3-small")
        assert isinstance(provider, EmbeddingProvider)

    def test_dimension_property(self) -> None:
        provider = OpenAIEmbeddingProvider(api_key="test-key", model="text-embedding-3-small")
        assert provider.dimension == 1536

    def test_dimension_large_model(self) -> None:
        provider = OpenAIEmbeddingProvider(api_key="test-key", model="text-embedding-3-large")
        assert provider.dimension == 3072

    def test_dimension_ada_model(self) -> None:
        provider = OpenAIEmbeddingProvider(api_key="test-key", model="text-embedding-ada-002")
        assert provider.dimension == 1536

    def test_dimension_unknown_model_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        provider = OpenAIEmbeddingProvider(api_key="test-key", model="text-embedding-unknown")

        with caplog.at_level("WARNING"):
            assert provider.dimension == 1536

        assert "fallback=1536" in caplog.text
        assert "text-embedding-unknown" in caplog.text


class TestOpenAIEmbeddingProvider:
    """OpenAIEmbeddingProvider のテスト。"""

    @pytest.fixture
    def provider(self) -> OpenAIEmbeddingProvider:
        return OpenAIEmbeddingProvider(
            api_key="test-key",
            model="text-embedding-3-small",
        )

    @pytest.mark.asyncio
    async def test_embed_single_text(self, provider: OpenAIEmbeddingProvider) -> None:
        expected_vector = [0.1] * 1536
        mock_response = {
            "data": [{"embedding": expected_vector, "index": 0}],
            "model": "text-embedding-3-small",
            "usage": {"prompt_tokens": 5, "total_tokens": 5},
        }

        with patch.object(provider, "_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            result = await provider.embed("Hello world")

        assert result == expected_vector
        mock_post.assert_called_once()

    @pytest.mark.asyncio
    async def test_embed_batch_preserves_order(self, provider: OpenAIEmbeddingProvider) -> None:
        texts = [f"text_{i}" for i in range(5)]
        vectors = [[float(i)] * 1536 for i in range(5)]

        # API returns in different order to test order preservation
        shuffled_data = [{"embedding": vectors[i], "index": i} for i in range(4, -1, -1)]
        mock_response = {
            "data": shuffled_data,
            "model": "text-embedding-3-small",
            "usage": {"prompt_tokens": 25, "total_tokens": 25},
        }

        with patch.object(provider, "_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            results = await provider.embed_batch(texts)

        assert len(results) == 5
        for i, (result, expected) in enumerate(zip(results, vectors, strict=True)):
            assert result == expected, f"Order mismatch at index {i}"

    @pytest.mark.asyncio
    async def test_embed_batch_chunks_large_input(self, provider: OpenAIEmbeddingProvider) -> None:
        """100件超の入力が正しくチャンク分割されることを検証。"""
        texts = [f"text_{i}" for i in range(150)]

        call_count = 0
        call_inputs: list[list[str]] = []

        async def mock_post(endpoint: str, payload: dict) -> dict:
            nonlocal call_count
            input_texts = payload["input"]
            call_inputs.append(input_texts)
            call_count += 1
            start_idx = sum(len(c) for c in call_inputs[:-1])
            return {
                "data": [
                    {"embedding": [float(start_idx + j)] * 1536, "index": j}
                    for j in range(len(input_texts))
                ],
                "model": "text-embedding-3-small",
                "usage": {
                    "prompt_tokens": 5 * len(input_texts),
                    "total_tokens": 5 * len(input_texts),
                },
            }

        with patch.object(provider, "_post", side_effect=mock_post):
            results = await provider.embed_batch(texts)

        assert call_count == 2  # 150 texts / chunk_size=100 = 2 calls
        assert len(results) == 150

        # 順序が保持されていることを確認
        for i, result in enumerate(results):
            assert result[0] == float(i), (
                f"Order mismatch at index {i}: expected {float(i)}, got {result[0]}"
            )

    def test_is_retryable_rate_limit(self) -> None:
        """429エラーがリトライ対象として判定されることを検証。"""
        from context_store.embedding.openai import _is_retryable

        exc = httpx.HTTPStatusError(
            "Rate limit exceeded",
            request=MagicMock(),
            response=MagicMock(status_code=429),
        )
        assert _is_retryable(exc) is True

    def test_is_retryable_server_error(self) -> None:
        """5xx エラーがリトライ対象として判定されることを検証。"""
        from context_store.embedding.openai import _is_retryable

        for status in (500, 502, 503, 504):
            exc = httpx.HTTPStatusError(
                f"Server error {status}",
                request=MagicMock(),
                response=MagicMock(status_code=status),
            )
            assert _is_retryable(exc) is True

    def test_is_retryable_timeout(self) -> None:
        """タイムアウトエラーがリトライ対象として判定されることを検証。"""
        from context_store.embedding.openai import _is_retryable

        exc = httpx.TimeoutException("timeout")
        assert _is_retryable(exc) is True

    def test_is_not_retryable_client_error(self) -> None:
        """4xx (429以外) エラーがリトライ非対象として判定されることを検証。"""
        from context_store.embedding.openai import _is_retryable

        exc = httpx.HTTPStatusError(
            "Bad request",
            request=MagicMock(),
            response=MagicMock(status_code=400),
        )
        assert _is_retryable(exc) is False

    @pytest.mark.asyncio
    async def test_embed_batch_empty_list(self, provider: OpenAIEmbeddingProvider) -> None:
        """空リストの場合は空リストを返すことを検証。"""
        results = await provider.embed_batch([])
        assert results == []

    @pytest.mark.asyncio
    async def test_embed_batch_single_text(self, provider: OpenAIEmbeddingProvider) -> None:
        """1件のみのバッチ処理が正常に動作することを検証。"""
        expected_vector = [0.1] * 1536
        mock_response = {
            "data": [{"embedding": expected_vector, "index": 0}],
            "model": "text-embedding-3-small",
            "usage": {"prompt_tokens": 5, "total_tokens": 5},
        }

        with patch.object(provider, "_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            results = await provider.embed_batch(["Hello"])

        assert len(results) == 1
        assert results[0] == expected_vector

    @pytest.mark.asyncio
    async def test_close_closes_shared_client(self, provider: OpenAIEmbeddingProvider) -> None:
        provider._client.aclose = AsyncMock()

        await provider.close()

        provider._client.aclose.assert_awaited_once()
