"""Embedding Provider and Token Counter protocols."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingProvider(Protocol):
    """埋め込みベクトルを生成するプロバイダーの抽象インターフェース。"""

    async def embed(self, text: str) -> list[float]:
        """単一テキストを埋め込みベクトルに変換する。"""
        ...

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """複数テキストを一括して埋め込みベクトルに変換する。

        Returns:
            入力 texts と同じ順序のベクトルリスト。
        """
        ...

    @property
    def dimension(self) -> int:
        """埋め込みベクトルの次元数。"""
        ...


@runtime_checkable
class TokenCounter(Protocol):
    """テキストのトークン数を計算するインターフェース。

    PostProcessorのmax_tokens制限やフォールバック用として利用する。
    """

    def count_tokens(self, text: str) -> int:
        """テキストのトークン数を返す。"""
        ...
