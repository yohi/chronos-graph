"""Tests for Embedding Provider Factory."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from context_store.config import Settings
from context_store.embedding.protocols import EmbeddingProvider


class TestCreateEmbeddingProvider:
    """create_embedding_provider ファクトリ関数のテスト。"""

    def _make_settings(self, **overrides) -> Settings:
        base = {
            "postgres_password": "test",
            "neo4j_password": "test",
        }
        base.update(overrides)
        return Settings(**base)

    def test_creates_openai_provider(self) -> None:
        from context_store.embedding import create_embedding_provider
        from context_store.embedding.openai import OpenAIEmbeddingProvider

        settings = self._make_settings(
            embedding_provider="openai",
            openai_api_key="sk-test",
        )
        provider = create_embedding_provider(settings)
        assert isinstance(provider, OpenAIEmbeddingProvider)
        assert isinstance(provider, EmbeddingProvider)

    def test_creates_local_model_provider(self) -> None:
        from context_store.embedding import create_embedding_provider
        from context_store.embedding.local_model import LocalModelEmbeddingProvider

        settings = self._make_settings(
            embedding_provider="local-model",
            local_model_name="test-model",
        )
        provider = create_embedding_provider(settings)
        assert isinstance(provider, LocalModelEmbeddingProvider)
        assert isinstance(provider, EmbeddingProvider)

    def test_creates_litellm_provider(self) -> None:
        from context_store.embedding import create_embedding_provider
        from context_store.embedding.litellm import LiteLLMEmbeddingProvider

        settings = self._make_settings(
            embedding_provider="litellm",
            litellm_api_base="http://localhost:4000",
        )
        provider = create_embedding_provider(settings)
        assert isinstance(provider, LiteLLMEmbeddingProvider)
        assert isinstance(provider, EmbeddingProvider)

    def test_creates_custom_api_provider(self) -> None:
        from context_store.embedding import create_embedding_provider
        from context_store.embedding.custom_api import CustomAPIEmbeddingProvider

        settings = self._make_settings(
            embedding_provider="custom-api",
            custom_api_endpoint="http://localhost:8080/embeddings",
        )
        provider = create_embedding_provider(settings)
        assert isinstance(provider, CustomAPIEmbeddingProvider)
        assert isinstance(provider, EmbeddingProvider)

    def test_openai_provider_uses_correct_api_key(self) -> None:
        from context_store.embedding import create_embedding_provider
        from context_store.embedding.openai import OpenAIEmbeddingProvider

        settings = self._make_settings(
            embedding_provider="openai",
            openai_api_key="sk-my-key",
        )
        provider = create_embedding_provider(settings)
        assert isinstance(provider, OpenAIEmbeddingProvider)
        assert provider._api_key == "sk-my-key"

    def test_local_model_provider_uses_correct_model_name(self) -> None:
        from context_store.embedding import create_embedding_provider
        from context_store.embedding.local_model import LocalModelEmbeddingProvider

        settings = self._make_settings(
            embedding_provider="local-model",
            local_model_name="my-custom-model",
        )
        provider = create_embedding_provider(settings)
        assert isinstance(provider, LocalModelEmbeddingProvider)
        assert provider._model_name == "my-custom-model"

    def test_litellm_provider_uses_correct_api_base(self) -> None:
        from context_store.embedding import create_embedding_provider
        from context_store.embedding.litellm import LiteLLMEmbeddingProvider

        settings = self._make_settings(
            embedding_provider="litellm",
            litellm_api_base="http://custom-host:5000",
        )
        provider = create_embedding_provider(settings)
        assert isinstance(provider, LiteLLMEmbeddingProvider)
        assert provider._api_base == "http://custom-host:5000"

    def test_custom_api_provider_uses_correct_endpoint(self) -> None:
        from context_store.embedding import create_embedding_provider
        from context_store.embedding.custom_api import CustomAPIEmbeddingProvider

        settings = self._make_settings(
            embedding_provider="custom-api",
            custom_api_endpoint="http://my-server/embed",
        )
        provider = create_embedding_provider(settings)
        assert isinstance(provider, CustomAPIEmbeddingProvider)
        assert provider._endpoint == "http://my-server/embed"

    def test_invalid_provider_raises_error(self) -> None:
        """不正なプロバイダー名で ValueError が発生することを検証。"""
        from context_store.embedding import create_embedding_provider

        settings = self._make_settings(openai_api_key="sk-test")
        # Settings の embedding_provider を直接書き換えてファクトリに渡す
        object.__setattr__(settings, "embedding_provider", "unknown-provider")

        with pytest.raises(ValueError, match="unknown-provider"):
            create_embedding_provider(settings)
