"""Embedding Provider パッケージ。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from context_store.embedding.protocols import EmbeddingProvider, TokenCounter

if TYPE_CHECKING:
    from context_store.config import Settings


def create_embedding_provider(settings: "Settings") -> EmbeddingProvider:
    """Settings に基づいて適切な EmbeddingProvider インスタンスを返す。

    Args:
        settings: アプリケーション設定。

    Returns:
        EmbeddingProvider の実装インスタンス。

    Raises:
        ValueError: 未知の embedding_provider が指定された場合。
    """
    provider_name = settings.embedding_provider

    if provider_name == "openai":
        from context_store.embedding.openai import OpenAIEmbeddingProvider
        return OpenAIEmbeddingProvider(
            api_key=settings.openai_api_key.get_secret_value(),
        )

    if provider_name == "local-model":
        from context_store.embedding.local_model import LocalModelEmbeddingProvider
        return LocalModelEmbeddingProvider(
            model_name=settings.local_model_name,
        )

    if provider_name == "litellm":
        from context_store.embedding.litellm import LiteLLMEmbeddingProvider
        return LiteLLMEmbeddingProvider(
            model=settings.local_model_name,
            dimension=1536,
            api_base=settings.litellm_api_base or None,
        )

    if provider_name == "custom-api":
        from context_store.embedding.custom_api import CustomAPIEmbeddingProvider
        return CustomAPIEmbeddingProvider(
            endpoint=settings.custom_api_endpoint,
            dimension=1536,
        )

    raise ValueError(
        f"不明な embedding_provider: '{provider_name}'。"
        "有効な値: 'openai', 'local-model', 'litellm', 'custom-api'"
    )


__all__ = ["EmbeddingProvider", "TokenCounter", "create_embedding_provider"]
