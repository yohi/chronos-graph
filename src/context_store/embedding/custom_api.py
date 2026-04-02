"""Custom API Embedding Provider。"""

from __future__ import annotations

import logging
from typing import Any, cast

import httpx
import tenacity

logger = logging.getLogger(__name__)

_DEFAULT_CHUNK_SIZE = 100


def _is_retryable(exc: BaseException) -> bool:
    """リトライ対象の例外かどうかを判定する。"""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError)):
        return True
    return False


class CustomAPIEmbeddingProvider:
    """カスタム HTTP API を利用した Embedding Provider。

    エンドポイントは {"texts": [...]} を受け取り、
    {"embeddings": [[...]]} を返すことを想定。

    - embed_batch は内部でチャンク分割してリクエスト
    - 429/5xx/タイムアウト時に Exponential Backoff でリトライ
    - 入力 texts の順序を完全に保持して返す
    """

    def __init__(
        self,
        endpoint: str,
        dimension: int,
        api_key: str | None = None,
        chunk_size: int = _DEFAULT_CHUNK_SIZE,
        timeout: float = 60.0,
    ) -> None:
        self._endpoint = endpoint
        self._dimension = dimension
        self._api_key = api_key
        self._chunk_size = chunk_size
        self._timeout = timeout

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

        all_results: list[list[float]] = []

        for chunk_start in range(0, len(texts), self._chunk_size):
            chunk = texts[chunk_start : chunk_start + self._chunk_size]
            response = await self._post({"texts": chunk})
            all_results.extend(response["embeddings"])

        return all_results

    @tenacity.retry(
        retry=tenacity.retry_if_exception(_is_retryable),
        wait=tenacity.wait_exponential(multiplier=1, min=1, max=60),
        stop=tenacity.stop_after_attempt(5),
        before_sleep=tenacity.before_sleep_log(logger, logging.WARNING),
    )
    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        """カスタム API エンドポイントに POST リクエストを送信する。"""
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                self._endpoint,
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            return cast(dict[str, Any], response.json())
