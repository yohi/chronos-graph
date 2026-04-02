"""OpenAI Embedding Provider。"""

from __future__ import annotations

import logging
from typing import Any, cast

import httpx
import tenacity

logger = logging.getLogger(__name__)

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


def _is_retryable(exc: BaseException) -> bool:
    """リトライ対象の例外かどうかを判定する。"""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError)):
        return True
    return False


class OpenAIEmbeddingProvider:
    """OpenAI API を利用した Embedding Provider。

    - embed_batch は内部でチャンク分割してリクエスト
    - 429/5xx/タイムアウト時に Exponential Backoff でリトライ
    - 入力 texts の順序を完全に保持して返す
    """

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-small",
        chunk_size: int = _DEFAULT_CHUNK_SIZE,
        timeout: float = 60.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._chunk_size = chunk_size
        self._timeout = timeout
        self._client = httpx.AsyncClient(timeout=self._timeout)
        self._dimension_warning_emitted = False

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

        - 入力を chunk_size ごとに分割して API リクエスト
        - 入力 texts の順序を保持して返す
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

    @tenacity.retry(
        retry=tenacity.retry_if_exception(_is_retryable),
        wait=tenacity.wait_exponential(multiplier=1, min=1, max=60),
        stop=tenacity.stop_after_attempt(5),
        before_sleep=tenacity.before_sleep_log(logger, logging.WARNING),
    )
    async def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        """OpenAI API にPOSTリクエストを送信する。"""
        response = await self._client.post(
            endpoint,
            json=payload,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )
        response.raise_for_status()
        return cast(dict[str, Any], response.json())

    async def close(self) -> None:
        """内部 AsyncClient をクローズする。"""
        await self._client.aclose()
