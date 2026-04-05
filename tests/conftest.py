"""共通テスト fixture。

ルートレベルの conftest.py は全テスト（unit / integration）から参照できる共有 fixture を定義する。
"""

from __future__ import annotations

import pytest
import random


def make_mock_embedding_provider(dim: int = 16):
    """固定ベクトルを返すモック EmbeddingProvider を作成する。"""

    class MockEmbeddingProvider:
        dimension = dim

        async def embed(self, text: str) -> list[float]:
            # テキストのハッシュに基づいた決定論的なベクトルを返す
            rng = random.Random(hash(text) % (2**31))
            return [rng.uniform(-1, 1) for _ in range(dim)]

        async def embed_batch(self, texts: list[str]) -> list[list[float]]:
            return [await self.embed(t) for t in texts]

    return MockEmbeddingProvider()


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"
