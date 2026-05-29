"""LiteLLM Embedding Provider。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from context_store.embedding.retry_config import (
    EmbeddingRetryPolicy,
    should_retry_embedding,
)

logger = logging.getLogger(__name__)

# Backward compatibility: 旧 `_is_retryable` を should_retry_embedding に統合したため、
# 既存テストの import 互換を保つための再エクスポート。
_is_retryable = should_retry_embedding

_DEFAULT_CHUNK_SIZE = 100


def _get_litellm() -> Any:
    """litellm モジュールを遅延ロードする (テストでパッチ可能)。"""
    try:
        import litellm as _litellm  # type: ignore[import]

        return _litellm
    except ImportError as e:
        raise ImportError(
            "litellm が未インストールです。"
            "pip install 'context-store-mcp[embedding-litellm]' でインストールしてください。"
        ) from e


class LiteLLMEmbeddingProvider:
    """LiteLLM API を利用した Embedding Provider。

    - ``embed_batch`` は内部でチャンク分割してリクエスト
    - 統一リトライポリシー (EmbeddingRetryPolicy) で 429 / 5xx / タイムアウト時にリトライ
    - 1 試行あたり ``retry_policy.per_attempt_timeout_seconds`` で ``asyncio.wait_for`` 制限
    - 入力 ``texts`` の順序を完全に保持して返す
    """

    def __init__(
        self,
        model: str,
        dimension: int,
        api_base: str | None = None,
        api_key: str | None = None,
        chunk_size: int = _DEFAULT_CHUNK_SIZE,
        retry_policy: EmbeddingRetryPolicy | None = None,
    ) -> None:
        self._model = model
        self._dimension = dimension
        self._api_base = api_base
        self._api_key = api_key
        self._chunk_size = chunk_size
        # retry_policy が未指定の場合は env から読み込む (fail-soft)
        self.retry_policy = retry_policy or EmbeddingRetryPolicy.from_env()

    @property
    def dimension(self) -> int:
        """埋め込みベクトルの次元数を返す。"""
        return self._dimension

    async def embed(self, text: str) -> list[float]:
        """単一テキストを埋め込みベクトルに変換する。"""
        results = await self.embed_batch([text])
        return results[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """複数テキストを埋め込みベクトルに変換する。

        - 入力を ``chunk_size`` ごとに分割して API リクエスト
        - 入力 ``texts`` の順序を保持して返す
        """
        if not texts:
            return []

        all_results: list[list[float]] = []

        for chunk_start in range(0, len(texts), self._chunk_size):
            chunk = texts[chunk_start : chunk_start + self._chunk_size]
            kwargs: dict[str, Any] = {"model": self._model, "input": chunk}
            if self._api_base:
                kwargs["api_base"] = self._api_base
            if self._api_key:
                kwargs["api_key"] = self._api_key

            response = await self._aembedding_with_retry(**kwargs)

            chunk_embeddings = [item.embedding for item in response.data]
            all_results.extend(chunk_embeddings)

        return all_results

    async def _aembedding_with_retry(self, **kwargs: Any) -> Any:
        """LiteLLM ``aembedding`` をリトライ付きで呼び出す。

        - ``retry_policy`` で設定された最大試行回数までリトライ
        - 各試行は ``per_attempt_timeout_seconds`` で ``asyncio.wait_for`` ガード
        - 429 レスポンスの ``Retry-After`` ヘッダ尊重 (LiteLLM が status_code 属性を返す場合)
        """
        retrying = self.retry_policy.get_async_retrying()
        async for attempt in retrying:
            with attempt:
                return await self._aembedding_once(**kwargs)
        # AsyncRetrying は ``reraise=True`` のため最終試行で例外が伝搬する。
        # ここに到達することはないが、型チェッカ向けに明示的にエラーを上げておく。
        raise RuntimeError("AsyncRetrying loop exited without success or exception")

    async def _aembedding_once(self, **kwargs: Any) -> Any:
        """LiteLLM ``aembedding`` への単発呼び出し (リトライなし、per-attempt timeout 付き)。"""
        litellm = _get_litellm()
        return await asyncio.wait_for(
            litellm.aembedding(**kwargs),
            timeout=self.retry_policy.per_attempt_timeout_seconds,
        )

    async def close(self) -> None:
        """リソースを解放する (LiteLLM では特に無し)。"""
        pass


__all__ = ["LiteLLMEmbeddingProvider"]
