"""Tests for Local Model (sentence-transformers) Embedding Provider."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from context_store.embedding.protocols import EmbeddingProvider


class TestLocalModelEmbeddingProvider:
    """LocalModelEmbeddingProvider のテスト。"""

    def _make_mock_model(self, dim: int = 768, values: list[float] | None = None) -> MagicMock:
        """Mock SentenceTransformer モデルを作成する (numpy不要)。"""
        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = dim
        # tolist() を持つオブジェクトをシミュレート
        vec = values if values is not None else [0.1] * dim
        mock_embedding = MagicMock()
        mock_embedding.tolist.return_value = vec
        mock_model.encode.return_value = [mock_embedding]
        return mock_model

    def test_implements_protocol(self) -> None:
        from context_store.embedding.local_model import LocalModelEmbeddingProvider

        with patch("context_store.embedding.local_model.SentenceTransformer") as mock_cls:
            mock_cls.return_value = self._make_mock_model()
            provider = LocalModelEmbeddingProvider(model_name="test-model")
            assert isinstance(provider, EmbeddingProvider)

    def test_dimension_property(self) -> None:
        from context_store.embedding.local_model import LocalModelEmbeddingProvider

        with patch("context_store.embedding.local_model.SentenceTransformer") as mock_cls:
            mock_model = self._make_mock_model(dim=768)
            mock_cls.return_value = mock_model
            provider = LocalModelEmbeddingProvider(model_name="test-model")
            assert provider.dimension == 768

    def test_lazy_load_model(self) -> None:
        """モデルが初回利用時に遅延ロードされることを検証。"""
        from context_store.embedding.local_model import LocalModelEmbeddingProvider

        with patch("context_store.embedding.local_model.SentenceTransformer") as mock_cls:
            mock_cls.return_value = self._make_mock_model()
            LocalModelEmbeddingProvider(model_name="test-model")
            # インスタンス作成時点では SentenceTransformer は呼ばれない
            mock_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_embed_single_text(self) -> None:
        from context_store.embedding.local_model import LocalModelEmbeddingProvider

        expected = [0.1] * 768
        mock_model = self._make_mock_model(dim=768, values=expected)

        with patch(
            "context_store.embedding.local_model.SentenceTransformer", return_value=mock_model
        ):
            provider = LocalModelEmbeddingProvider(model_name="test-model")
            result = await provider.embed("Hello world")

        assert len(result) == 768
        assert abs(result[0] - 0.1) < 1e-5

    @pytest.mark.asyncio
    async def test_embed_batch(self) -> None:
        from context_store.embedding.local_model import LocalModelEmbeddingProvider

        texts = ["text_0", "text_1", "text_2"]
        vectors = [[float(i)] * 768 for i in range(3)]

        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 768
        mock_embeddings = []
        for vec in vectors:
            m = MagicMock()
            m.tolist.return_value = vec
            mock_embeddings.append(m)
        mock_model.encode.return_value = mock_embeddings

        with patch(
            "context_store.embedding.local_model.SentenceTransformer", return_value=mock_model
        ):
            provider = LocalModelEmbeddingProvider(model_name="test-model")
            results = await provider.embed_batch(texts)

        assert len(results) == 3
        for i, result in enumerate(results):
            assert abs(result[0] - float(i)) < 1e-5

    @pytest.mark.asyncio
    async def test_embed_batch_empty(self) -> None:
        from context_store.embedding.local_model import LocalModelEmbeddingProvider

        with patch("context_store.embedding.local_model.SentenceTransformer"):
            provider = LocalModelEmbeddingProvider(model_name="test-model")
            results = await provider.embed_batch([])

        assert results == []

    def test_model_name_default(self) -> None:
        from context_store.embedding.local_model import LocalModelEmbeddingProvider

        with patch("context_store.embedding.local_model.SentenceTransformer") as mock_cls:
            mock_cls.return_value = self._make_mock_model()
            provider = LocalModelEmbeddingProvider()
            assert provider._model_name == "cl-nagoya/ruri-v3-310m"
