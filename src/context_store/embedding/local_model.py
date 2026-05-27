"""Local Model (sentence-transformers) Embedding Provider。"""

from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_MODEL_NAME = "cl-nagoya/ruri-v3-310m"


def SentenceTransformer(model_name: str) -> Any:  # noqa: N802
    """sentence_transformers.SentenceTransformer を遅延ロードして初期化する。

    テストでパッチ可能にするためモジュールレベルの関数として定義。
    """
    try:
        from sentence_transformers import SentenceTransformer as ST  # type: ignore[import]

        return ST(model_name)
    except ImportError as e:
        raise ImportError(
            "sentence-transformers が未インストールです。"
            "pip install 'context-store-mcp[embedding-local]' でインストールしてください。"
        ) from e


class LocalModelEmbeddingProvider:
    """sentence-transformers を使ったローカル Embedding Provider。

    - モデルは初回利用時に遅延ロード
    - embed_batch は長寿命の ThreadPoolExecutor で同期処理をノンブロッキングで実行
    - start() で明示的にモデルを事前ロード可能
    """

    def __init__(
        self,
        model_name: str = _DEFAULT_MODEL_NAME,
        dimension: int | None = None,
        max_workers: int = 1,
    ) -> None:
        if dimension is not None:
            if not isinstance(dimension, int) or dimension <= 0:
                raise ValueError(f"dimension must be a positive integer, got {dimension}")
        if max_workers < 1:
            raise ValueError(f"max_workers must be >= 1, got {max_workers}")

        self._model_name = model_name
        self._model: Any = None
        self._dimension: int | None = dimension
        self._model_lock = threading.Lock()
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="local-embedding",
        )
        self._closed = False

    def _get_model(self) -> Any:
        """モデルを遅延ロードして返す。"""
        if self._model is None:
            with self._model_lock:
                if self._model is None:
                    logger.info("ローカルモデルをロード中: %s", self._model_name)
                    model = SentenceTransformer(self._model_name)
                    if self._dimension is None:
                        dim = model.get_sentence_embedding_dimension()
                        if dim is not None:
                            self._dimension = int(dim)
                        else:
                            logger.info(
                                "次元数を自動取得するためにサンプルテキストをエンコードします"
                            )
                            sample_emb = model.encode(["dim check"])[0]
                            self._dimension = len(sample_emb)
                    self._model = model
                    logger.info("モデルのロード完了: dimension=%d", self._dimension)
        return self._model

    @property
    def dimension(self) -> int:
        """埋め込みベクトルの次元数を返す。"""
        if self._dimension is not None:
            return self._dimension

        self._get_model()
        if self._dimension is None:
            raise RuntimeError("Dimension must be set after loading model")
        return self._dimension

    async def start(self) -> None:
        """ワーカースレッド上でモデルを明示的に事前ロードする。"""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self._executor, self._get_model)

    async def embed(self, text: str) -> list[float]:
        """単一テキストを埋め込みベクトルに変換する。"""
        results = await self.embed_batch([text])
        return results[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """複数テキストを埋め込みベクトルに変換する。"""
        if not texts:
            return []

        def _encode() -> list[list[float]]:
            model = self._get_model()
            embeddings = model.encode(texts, show_progress_bar=False)
            return [emb.tolist() for emb in embeddings]

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, _encode)

    async def close(self) -> None:
        """ワーカースレッドプールを解放する (idempotent)。"""
        if self._closed:
            return
        self._closed = True
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._executor.shutdown, True)
