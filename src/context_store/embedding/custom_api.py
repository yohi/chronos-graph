"""Custom API embedding provider."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
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
        if not isinstance(endpoint, str) or not endpoint.strip():
            raise ValueError("endpoint must be a non-empty string")
        self._endpoint = endpoint
        self._dimension = dimension
        self._api_key = api_key
        self._chunk_size = chunk_size
        self._timeout = timeout

        if not isinstance(self._chunk_size, int) or self._chunk_size <= 0:
            raise ValueError(f"chunk_size must be an int greater than 0, got {self._chunk_size!r}")
        if not isinstance(self._timeout, (int, float)) or self._timeout <= 0:
            raise ValueError(f"timeout must be a number greater than 0, got {self._timeout!r}")
        if not isinstance(self._dimension, int) or self._dimension <= 0:
            raise ValueError(f"dimension must be an int greater than 0, got {self._dimension!r}")

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
            if not isinstance(response, Mapping):
                raise ValueError(
                    "response must be a mapping containing response[\"embeddings\"]; "
                    f"got {type(response).__name__}"
                )
            embeddings = response.get("embeddings")
            if not isinstance(embeddings, list):
                raise ValueError(
                    'response["embeddings"] must be a list before all_results.extend(...); '
                    f'got {type(embeddings).__name__} in response for len(chunk)={len(chunk)}'
                )
            if len(embeddings) != len(chunk):
                raise ValueError(
                    'len(response["embeddings"]) must equal len(chunk) before '
                    f'all_results.extend(...); got len(response["embeddings"])={len(embeddings)}, '
                    f"len(chunk)={len(chunk)}"
                )
            for index, embedding in enumerate(embeddings):
                if not isinstance(embedding, Iterable) or isinstance(embedding, (str, bytes)):
                    raise ValueError(
                        'Each item in response["embeddings"] must be an iterable with length '
                        f"self._dimension={self._dimension}; invalid response[\"embeddings\"][{index}] "
                        f"for len(chunk)={len(chunk)}"
                    )
                vector = list(embedding)
                for element_index, value in enumerate(vector):
                    if isinstance(value, bool) or not isinstance(value, (int, float)):
                        raise ValueError(
                            'Each value in response["embeddings"] must be an int or float; '
                            f'invalid response["embeddings"][{index}][{element_index}]={value!r} '
                            f"for self._dimension={self._dimension}"
                        )
                if len(vector) != self._dimension:
                    raise ValueError(
                        'Each vector in response["embeddings"] must match '
                        f'self._dimension={self._dimension}; got len(response["embeddings"][{index}])='
                        f"{len(vector)} for len(chunk)={len(chunk)}"
                    )
                embeddings[index] = vector
            all_results.extend(cast(list[list[float]], embeddings))

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
