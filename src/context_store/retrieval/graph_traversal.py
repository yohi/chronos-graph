"""Graph Traversal - グラフトラバーサル検索"""

import logging
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


class GraphTraversal:
    """グラフトラバーサルエンジン"""

    def __init__(
        self,
        graph_adapter: Any,
        default_depth: int = 2,
        fanout_limit: int = 100,
        max_physical_hops: int = 50,
    ):
        """
        初期化

        Args:
            graph_adapter: グラフアダプター
            default_depth: デフォルトのグラフ深さ
            fanout_limit: 各ノードからのエッジ展開上限
            max_physical_hops: 物理的な最大ホップ数
        """
        self.graph_adapter = graph_adapter
        self.default_depth = default_depth
        self.fanout_limit = fanout_limit
        self.max_physical_hops = max_physical_hops

    async def traverse(
        self,
        seed_ids: list[UUID],
        edge_types: list[str] | None = None,
        depth: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        グラフをトラバース

        Args:
            seed_ids: 起点ノードID
            edge_types: フィルタするエッジタイプ
            depth: トラバーサルの深さ

        Returns:
            トラバーサル結果（ノードID、スコアなど）
        """
        if depth is None:
            depth = self.default_depth

        try:
            # Graph Adapter でトラバーサル
            results = await self.graph_adapter.traverse(
                seed_ids=seed_ids,
                edge_types=edge_types or [],
                depth=depth,
                fanout_limit=self.fanout_limit,
                max_physical_hops=self.max_physical_hops,
            )

            return results

        except Exception as e:
            # Graceful Degradation: グラフ検索失敗時は空結果を返す
            logger.warning(
                f"Graph traversal failed: {type(e).__name__}: {str(e)}. Returning empty results."
            )
            return []
