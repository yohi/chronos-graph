"""Local Model (sentence-transformers) Embedding Provider。"""

from __future__ import annotations

import asyncio
import logging
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
    - embed_batch は asyncio.to_thread で同期処理をノンブロッキングで実行
    """

    def __init__(self, model_name: str = _DEFAULT_MODEL_NAME) -> None:
        self._model_name = model_name
        self._model: Any = None
        self._dimension: int | None = None

    def _get_model(self) -> Any:
        """モデルを遅延ロードして返す。"""
        if self._model is None:
            logger.info(f"ローカルモデルをロード中: {self._model_name}")
            self._model = SentenceTransformer(self._model_name)
            self._dimension = int(self._model.get_sentence_embedding_dimension())
            logger.info(f"モデルのロード完了: dimension={self._dimension}")
        return self._model

    @property
    def dimension(self) -> int:
        """埋め込みベクトルの次元数を返す。モデル未ロード時はロードを行う。"""
        self._get_model()
        return self._dimension or 768

    async def embed(self, text: str) -> list[float]:
        """単一テキストを埋め込みベクトルに変換する。"""
        results = await self.embed_batch([text])
        return results[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """複数テキストを埋め込みベクトルに変換する。

        同期処理を asyncio.to_thread でバックグラウンドスレッドで実行する。
        """
        if not texts:
            return []

        def _encode() -> list[list[float]]:
            model = self._get_model()
            embeddings = model.encode(texts, show_progress_bar=False)
            return [emb.tolist() for emb in embeddings]

        return await asyncio.to_thread(_encode)
