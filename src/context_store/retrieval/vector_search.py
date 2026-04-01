"""Vector Search - ベクトル検索"""

from typing import Any
from context_store.storage.protocols import StorageAdapter
from context_store.models.search import ScoredMemory


class VectorSearch:
    """ベクトル検索エンジン"""

    def __init__(
        self,
        embedding_provider: Any,  # EmbeddingProvider
        storage_adapter: StorageAdapter,
        default_top_k: int = 10,
    ):
        """
        初期化

        Args:
            embedding_provider: 埋め込みプロバイダー
            storage_adapter: ストレージアダプター
            default_top_k: デフォルトの結果数
        """
        self.embedding_provider = embedding_provider
        self.storage_adapter = storage_adapter
        self.default_top_k = default_top_k

    async def search(self, query: str, top_k: int | None = None) -> list[ScoredMemory]:
        """
        ベクトル検索を実行

        Args:
            query: クエリテキスト
            top_k: 返す結果の数（Noneの場合はデフォルト値）

        Returns:
            ScoredMemory のリスト
        """
        if top_k is None:
            top_k = self.default_top_k

        # クエリをベクトル化
        embedding = await self.embedding_provider.embed(query)

        # Storage Adapter でベクトル検索
        results = await self.storage_adapter.vector_search(
            embedding=embedding,
            top_k=top_k,
        )

        return results
