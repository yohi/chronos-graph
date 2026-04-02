"""Tests for LiteLLM and Custom API Embedding Providers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import tenacity

from context_store.embedding.protocols import EmbeddingProvider


class TestLiteLLMEmbeddingProvider:
    """LiteLLMEmbeddingProvider のテスト。"""

    @pytest.fixture
    def provider(self):
        from context_store.embedding.litellm import LiteLLMEmbeddingProvider

        return LiteLLMEmbeddingProvider(model="text-embedding-3-small", dimension=1536)

    def test_implements_protocol(self, provider) -> None:
        assert isinstance(provider, EmbeddingProvider)

    def test_dimension_property(self, provider) -> None:
        assert provider.dimension == 1536

    @pytest.mark.asyncio
    async def test_embed_single_text(self, provider) -> None:
        expected = [0.1] * 1536
        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=expected)]

        mock_litellm = MagicMock()
        mock_litellm.aembedding = AsyncMock(return_value=mock_response)

        with patch("context_store.embedding.litellm._get_litellm", return_value=mock_litellm):
            result = await provider.embed("Hello world")

        assert result == expected

    @pytest.mark.asyncio
    async def test_embed_batch_preserves_order(self, provider) -> None:
        texts = [f"text_{i}" for i in range(5)]
        vectors = [[float(i)] * 1536 for i in range(5)]

        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=vec) for vec in vectors]

        mock_litellm = MagicMock()
        mock_litellm.aembedding = AsyncMock(return_value=mock_response)

        with patch("context_store.embedding.litellm._get_litellm", return_value=mock_litellm):
            results = await provider.embed_batch(texts)

        assert len(results) == 5
        for i, (result, expected) in enumerate(zip(results, vectors, strict=True)):
            assert result == expected, f"Order mismatch at index {i}"

    @pytest.mark.asyncio
    async def test_embed_batch_chunks_large_input(self, provider) -> None:
        """100件超の入力がチャンク分割されることを検証。"""
        texts = [f"text_{i}" for i in range(150)]
        call_count = 0

        async def mock_aembedding(**kwargs):
            nonlocal call_count
            call_count += 1
            input_texts = kwargs.get("input", [])
            mock_resp = MagicMock()
            mock_resp.data = [MagicMock(embedding=[float(call_count)] * 1536) for _ in input_texts]
            return mock_resp

        mock_litellm = MagicMock()
        mock_litellm.aembedding = mock_aembedding

        with patch("context_store.embedding.litellm._get_litellm", return_value=mock_litellm):
            results = await provider.embed_batch(texts)

        assert call_count == 2
        assert len(results) == 150

    @pytest.mark.asyncio
    async def test_embed_batch_empty(self, provider) -> None:
        results = await provider.embed_batch([])
        assert results == []

    def test_is_retryable_rate_limit(self, provider) -> None:
        from context_store.embedding.litellm import _is_retryable

        exc = httpx.HTTPStatusError(
            "Rate limit",
            request=MagicMock(),
            response=MagicMock(status_code=429),
        )
        assert _is_retryable(exc) is True

    def test_is_retryable_timeout(self, provider) -> None:
        from context_store.embedding.litellm import _is_retryable

        assert _is_retryable(httpx.TimeoutException("timeout")) is True

    def test_is_retryable_custom_exception_with_status_code(self, provider) -> None:
        """status_code 属性を持つ汎用的な例外が正しく判定されることを検証。"""
        from context_store.embedding.litellm import _is_retryable

        class MockLiteLLMError(Exception):
            def __init__(self, status_code: int):
                self.status_code = status_code

        assert _is_retryable(MockLiteLLMError(429)) is True
        assert _is_retryable(MockLiteLLMError(500)) is True
        assert _is_retryable(MockLiteLLMError(400)) is False

    def test_is_not_retryable_value_error(self, provider) -> None:
        from context_store.embedding.litellm import _is_retryable

        assert _is_retryable(ValueError("bad input")) is False

    @pytest.mark.asyncio
    async def test_embed_batch_retries_on_rate_limit(self, provider) -> None:
        """Rate limit (429) エラー時にリトライが行われ、成功することを検証。"""
        texts = ["Hello world"]
        expected = [[0.1] * 1536]

        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=expected[0])]

        call_count = 0

        async def mock_aembedding(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                # 1, 2回目は 429 エラー
                raise httpx.HTTPStatusError(
                    "Rate limit",
                    request=MagicMock(),
                    response=MagicMock(status_code=429),
                )
            return mock_response

        mock_litellm = MagicMock()
        mock_litellm.aembedding = mock_aembedding

        with patch("context_store.embedding.litellm._get_litellm", return_value=mock_litellm):
            # min=2 の exponential backoff のためテストに少し時間がかかる
            results = await provider.embed_batch(texts)

        assert call_count == 3
        assert results == expected

    @pytest.mark.asyncio
    async def test_embed_batch_fails_after_max_retries(self, provider) -> None:
        """最大リトライ回数を超えた場合は例外が送出されることを検証。"""
        texts = ["Hello world"]

        call_count = 0

        async def mock_aembedding(**kwargs):
            nonlocal call_count
            call_count += 1
            raise httpx.HTTPStatusError(
                "Rate limit",
                request=MagicMock(),
                response=MagicMock(status_code=429),
            )

        mock_litellm = MagicMock()
        mock_litellm.aembedding = mock_aembedding

        with patch("context_store.embedding.litellm._get_litellm", return_value=mock_litellm):
            with pytest.raises(tenacity.RetryError):
                await provider.embed_batch(texts)

        assert call_count == 5


class TestCustomAPIEmbeddingProvider:
    """CustomAPIEmbeddingProvider のテスト。"""

    @pytest.fixture
    def provider(self):
        from context_store.embedding.custom_api import CustomAPIEmbeddingProvider

        return CustomAPIEmbeddingProvider(
            endpoint="http://localhost:8080/embeddings",
            dimension=768,
        )

    def test_implements_protocol(self, provider) -> None:
        assert isinstance(provider, EmbeddingProvider)

    def test_dimension_property(self, provider) -> None:
        assert provider.dimension == 768

    @pytest.mark.asyncio
    async def test_embed_single_text(self, provider) -> None:
        expected = [0.1] * 768
        mock_response_data = {"embeddings": [expected]}

        with patch.object(provider, "_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response_data
            result = await provider.embed("Hello world")

        assert result == expected

    @pytest.mark.asyncio
    async def test_embed_batch_preserves_order(self, provider) -> None:
        texts = [f"text_{i}" for i in range(5)]
        vectors = [[float(i)] * 768 for i in range(5)]
        mock_response_data = {"embeddings": vectors}

        with patch.object(provider, "_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response_data
            results = await provider.embed_batch(texts)

        assert len(results) == 5
        for i, (result, expected) in enumerate(zip(results, vectors, strict=True)):
            assert result == expected, f"Order mismatch at index {i}"

    @pytest.mark.parametrize("endpoint", ["", "   "])
    def test_init_rejects_blank_endpoint(self, endpoint: str) -> None:
        from context_store.embedding.custom_api import CustomAPIEmbeddingProvider

        with pytest.raises(ValueError, match="endpoint must be a non-empty string"):
            CustomAPIEmbeddingProvider(
                endpoint=endpoint,
                dimension=768,
            )

    @pytest.mark.asyncio
    async def test_embed_batch_chunks_large_input(self, provider) -> None:
        """100件超の入力がチャンク分割されることを検証。"""
        texts = [f"text_{i}" for i in range(150)]
        call_count = 0

        async def mock_post(payload: dict) -> dict:
            nonlocal call_count
            call_count += 1
            n = len(payload["texts"])
            return {"embeddings": [[float(call_count)] * 768 for _ in range(n)]}

        with patch.object(provider, "_post", side_effect=mock_post):
            results = await provider.embed_batch(texts)

        assert call_count == 2
        assert len(results) == 150

    @pytest.mark.asyncio
    async def test_embed_batch_empty(self, provider) -> None:
        results = await provider.embed_batch([])
        assert results == []

    def test_is_retryable_rate_limit(self, provider) -> None:
        from context_store.embedding.custom_api import _is_retryable

        exc = httpx.HTTPStatusError(
            "Rate limit",
            request=MagicMock(),
            response=MagicMock(status_code=429),
        )
        assert _is_retryable(exc) is True

    def test_is_retryable_server_error(self, provider) -> None:
        from context_store.embedding.custom_api import _is_retryable

        for status in (500, 502, 503, 504):
            exc = httpx.HTTPStatusError(
                f"Server error {status}",
                request=MagicMock(),
                response=MagicMock(status_code=status),
            )
            assert _is_retryable(exc) is True

    def test_is_not_retryable_client_error(self, provider) -> None:
        from context_store.embedding.custom_api import _is_retryable

        exc = httpx.HTTPStatusError(
            "Bad request",
            request=MagicMock(),
            response=MagicMock(status_code=400),
        )
        assert _is_retryable(exc) is False

    @pytest.mark.parametrize(
        ("chunk_size", "timeout", "dimension", "message"),
        [
            (0, 60.0, 768, "chunk_size"),
            (100, 0.0, 768, "timeout"),
            (100, 60.0, 0, "dimension"),
        ],
    )
    def test_init_validates_parameters(self, chunk_size, timeout, dimension, message) -> None:
        from context_store.embedding.custom_api import CustomAPIEmbeddingProvider

        with pytest.raises(ValueError, match=message):
            CustomAPIEmbeddingProvider(
                endpoint="http://localhost:8080/embeddings",
                dimension=dimension,
                chunk_size=chunk_size,
                timeout=timeout,
            )

    @pytest.mark.asyncio
    async def test_embed_batch_rejects_non_list_embeddings(self, provider) -> None:
        with patch.object(provider, "_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"embeddings": "invalid"}
            with pytest.raises(ValueError, match=r'response\["embeddings"\].*list'):
                await provider.embed_batch(["a"])

    @pytest.mark.asyncio
    async def test_embed_batch_rejects_non_mapping_response(self, provider) -> None:
        with patch.object(provider, "_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = ["invalid"]
            with pytest.raises(ValueError, match=r"response must be a mapping"):
                await provider.embed_batch(["a"])

    @pytest.mark.asyncio
    async def test_embed_batch_rejects_length_mismatch(self, provider) -> None:
        with patch.object(provider, "_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"embeddings": [[0.1] * 768]}
            with pytest.raises(ValueError, match=r'len\(response\["embeddings"\]\).*len\(chunk\)'):
                await provider.embed_batch(["a", "b"])

    @pytest.mark.asyncio
    async def test_embed_batch_rejects_dimension_mismatch(self, provider) -> None:
        with patch.object(provider, "_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"embeddings": [[0.1] * 767]}
            with pytest.raises(ValueError, match=r"dimension=768"):
                await provider.embed_batch(["a"])

    @pytest.mark.asyncio
    async def test_embed_batch_rejects_non_numeric_embedding_values(self, provider) -> None:
        with patch.object(provider, "_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"embeddings": [[0.1] * 767 + ["bad"]]}
            with pytest.raises(ValueError, match=r'response\["embeddings"\]\[0\]\[767\]'):
                await provider.embed_batch(["a"])
