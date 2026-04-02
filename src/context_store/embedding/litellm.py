"""LiteLLM Embedding Provider。"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

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


def _is_retryable(exc: BaseException) -> bool:
    """リトライ対象の例外かどうかを判定する。"""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError)):
        return True
    return False


class LiteLLMEmbeddingProvider:
    """LiteLLM API を利用した Embedding Provider。

    - embed_batch は内部でチャンク分割してリクエスト
    - リトライは tenacity を利用した Exponential Backoff
    - 入力 texts の順序を完全に保持して返す
    """

    def __init__(
        self,
        model: str,
        dimension: int,
        api_base: str | None = None,
        api_key: str | None = None,
        chunk_size: int = _DEFAULT_CHUNK_SIZE,
    ) -> None:
        self._model = model
        self._dimension = dimension
        self._api_base = api_base
        self._api_key = api_key
        self._chunk_size = chunk_size

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

        - 入力を chunk_size ごとに分割して API リクエスト
        - 入力 texts の順序を保持して返す
        """
        if not texts:
            return []

        litellm = _get_litellm()
        all_results: list[list[float]] = []

        retryer = AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=2, max=10),
            retry=retry_if_exception(_is_retryable),
            reraise=True,
        )

        for chunk_start in range(0, len(texts), self._chunk_size):
            chunk = texts[chunk_start : chunk_start + self._chunk_size]
            kwargs: dict[str, Any] = {"model": self._model, "input": chunk}
            if self._api_base:
                kwargs["api_base"] = self._api_base
            if self._api_key:
                kwargs["api_key"] = self._api_key

            async for attempt in retryer:
                with attempt:
                    response = await litellm.aembedding(**kwargs)

            chunk_embeddings = [item.embedding for item in response.data]
            all_results.extend(chunk_embeddings)

        return all_results
