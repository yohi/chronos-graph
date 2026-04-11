"""共通テスト fixture。

ルートレベルの conftest.py は全テスト（unit / integration）から参照できる共有 fixture を定義する。
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from context_store.embedding.protocols import EmbeddingProvider


def make_mock_embedding_provider(dim: int = 16) -> EmbeddingProvider:
    """固定ベクトルを返すモック EmbeddingProvider を作成する。"""

    class MockEmbeddingProvider:
        @property
        def dimension(self) -> int:
            return dim

        async def embed(self, text: str) -> list[float]:
            import hashlib

            # テキストのハッシュに基づいた決定論的なベクトルを返す（hash() ではなく hashlib を使用）
            h = hashlib.sha256(text.encode("utf-8")).digest()
            seed = int.from_bytes(h[:4], "little") % (2**31)
            rng = random.Random(seed)  # noqa: S311
            return [rng.uniform(-1, 1) for _ in range(dim)]

        async def embed_batch(self, texts: list[str]) -> list[list[float]]:
            return [await self.embed(t) for t in texts]

        async def close(self) -> None:
            pass

    return MockEmbeddingProvider()  # type: ignore[return-value]


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"
