"""Keyword Search - キーワード検索"""

from context_store.models.search import ScoredMemory
from context_store.storage.protocols import StorageAdapter


class KeywordSearch:
    """キーワード検索エンジン"""

    def __init__(
        self,
        storage_adapter: StorageAdapter,
        default_top_k: int = 10,
    ):
        """
        初期化

        Args:
            storage_adapter: ストレージアダプター
            default_top_k: デフォルトの結果数
        """
        self.storage_adapter = storage_adapter
        self.default_top_k = default_top_k

    async def search(self, query: str, top_k: int | None = None) -> list[ScoredMemory]:
        """
        キーワード検索を実行

        Args:
            query: 検索クエリ
            top_k: 返す結果の数（Noneの場合はデフォルト値）

        Returns:
            ScoredMemory のリスト
        """
        if top_k is None:
            top_k = self.default_top_k

        # Storage Adapter でキーワード検索
        results = await self.storage_adapter.keyword_search(
            query=query,
            top_k=top_k,
        )

        return results
