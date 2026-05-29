"""OpenAI Embedding Provider。"""

from __future__ import annotations

import logging
from typing import Any, cast

import httpx

from context_store.embedding.retry_config import (
    EmbeddingRetryPolicy,
    should_retry_embedding,
)

logger = logging.getLogger(__name__)

# Backward compatibility: 旧 `_is_retryable` を should_retry_embedding に統合したため、
# 既存テストの import 互換を保つための再エクスポート。
_is_retryable = should_retry_embedding

# モデル別のデフォルト次元数
_MODEL_DIMENSIONS: dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
    "text-embedding-4-small": 1536,
    "text-embedding-4-large": 3072,
}

_DEFAULT_CHUNK_SIZE = 100
_OPENAI_EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"


class OpenAIEmbeddingProvider:
    """OpenAI API を利用した Embedding Provider。

    - ``embed_batch`` は内部でチャンク分割してリクエスト
    - 429 / 5xx / タイムアウト時に統一リトライポリシー (EmbeddingRetryPolicy) でリトライ
    - レスポンスの ``Retry-After`` ヘッダを尊重 (上限クランプあり)
    - 1 試行あたり ``retry_policy.per_attempt_timeout_seconds`` でタイムアウト
    - 入力 ``texts`` の順序を完全に保持して返す
    """

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-small",
        chunk_size: int = _DEFAULT_CHUNK_SIZE,
        timeout: float = 60.0,
        retry_policy: EmbeddingRetryPolicy | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._chunk_size = chunk_size
        self._timeout = timeout
        self._client = http_client or httpx.AsyncClient(timeout=self._timeout)
        self._dimension_warning_emitted = False
        # retry_policy が未指定の場合は env から読み込む (fail-soft)
        self.retry_policy = retry_policy or EmbeddingRetryPolicy.from_env()

    @property
    def dimension(self) -> int:
        """埋め込みベクトルの次元数を返す。"""
        dimension = _MODEL_DIMENSIONS.get(self._model)
        if dimension is not None:
            return dimension
        if not self._dimension_warning_emitted:
            logger.warning(
                "Unknown OpenAI embedding model '%s'; using fallback=1536. "
                "Add the model to _MODEL_DIMENSIONS if its dimension is known.",
                self._model,
            )
            self._dimension_warning_emitted = True
        return 1536

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

        all_embeddings: list[tuple[int, list[float]]] = []

        for chunk_start in range(0, len(texts), self._chunk_size):
            chunk = texts[chunk_start : chunk_start + self._chunk_size]
            response = await self._post(
                _OPENAI_EMBEDDINGS_URL,
                {"model": self._model, "input": chunk},
            )
            for item in response["data"]:
                global_index = chunk_start + item["index"]
                all_embeddings.append((global_index, item["embedding"]))

        all_embeddings.sort(key=lambda x: x[0])
        return [emb for _, emb in all_embeddings]

    async def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        """OpenAI API にリトライ付きで POST する。

        - ``retry_policy`` で設定された最大試行回数までリトライ
        - 各試行は ``per_attempt_timeout_seconds`` でタイムアウト
        - 429 レスポンスの ``Retry-After`` ヘッダを尊重 (``max_wait_seconds`` でクランプ)
        """
        retrying = self.retry_policy.get_async_retrying()
        async for attempt in retrying:
            with attempt:
                return await self._post_once(endpoint, payload)
        # AsyncRetrying は ``reraise=True`` のため最終試行で例外が伝搬する。
        # ここに到達することはないが、型チェッカ向けに明示的にエラーを上げておく。
        raise RuntimeError("AsyncRetrying loop exited without success or exception")

    async def _post_once(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        """OpenAI API への単発 POST (リトライなし)。"""
        response = await self._client.post(
            endpoint,
            json=payload,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            timeout=self.retry_policy.per_attempt_timeout_seconds,
        )
        response.raise_for_status()
        return cast(dict[str, Any], response.json())

    async def close(self) -> None:
        """内部 ``AsyncClient`` をクローズする。"""
        await self._client.aclose()


__all__ = ["OpenAIEmbeddingProvider"]
