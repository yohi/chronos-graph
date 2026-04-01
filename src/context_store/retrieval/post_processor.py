"""Post Processor - フィルタ・トークン制限・アクセス記録"""

import logging
from datetime import datetime, timezone
from context_store.storage.protocols import StorageAdapter
from context_store.models.search import ScoredMemory

logger = logging.getLogger(__name__)


class PostProcessor:
    """検索結果の後処理（フィルタ、トークン制限、アクセス記録更新）"""

    def __init__(
        self,
        storage_adapter: StorageAdapter,
        max_tokens: int | None = None,
    ):
        """
        初期化

        Args:
            storage_adapter: ストレージアダプター（アクセス記録更新用）
            max_tokens: 最大トークン数
        """
        self.storage_adapter = storage_adapter
        self.max_tokens = max_tokens

    async def process(
        self,
        results: list[ScoredMemory],
        project: str | None = None,
        max_tokens: int | None = None,
    ) -> list[ScoredMemory]:
        """
        検索結果を後処理

        Args:
            results: 検索結果
            project: プロジェクトフィルタ
            max_tokens: 最大トークン数（Noneの場合は初期化時の値を使用）

        Returns:
            フィルタリングされた検索結果
        """
        if max_tokens is None:
            max_tokens = self.max_tokens

        # ステップ 1: プロジェクトフィルタ
        filtered = self._filter_by_project(results, project)

        # ステップ 2: トークン制限
        if max_tokens is not None:
            filtered = self._apply_token_limit(filtered, max_tokens)

        # ステップ 3: アクセス記録を更新（非同期）
        for result in filtered:
            await self._update_access_record(result)

        return filtered

    def _filter_by_project(
        self,
        results: list[ScoredMemory],
        project: str | None,
    ) -> list[ScoredMemory]:
        """
        プロジェクト別にフィルタリング

        Args:
            results: 検索結果
            project: プロジェクトフィルタ

        Returns:
            フィルタリングされた結果
        """
        if project is None:
            return results

        return [r for r in results if r.memory.project == project]

    def _apply_token_limit(
        self,
        results: list[ScoredMemory],
        max_tokens: int,
    ) -> list[ScoredMemory]:
        """
        トークン制限を適用

        Args:
            results: 検索結果
            max_tokens: 最大トークン数

        Returns:
            トークン制限内の結果
        """
        if max_tokens <= 0 or not results:
            return results

        # 簡単な推定: 1トークン ≈ 4文字（英語主体）または 3文字（日本語主体）
        # テキストのASCII比率で判定
        limited_results = []
        total_tokens = 0

        for result in results:
            content = result.memory.content
            # ASCII文字比率を計算
            ascii_count = sum(1 for c in content if ord(c) < 128)
            ascii_ratio = ascii_count / len(content) if content else 0

            # トークン推定
            if ascii_ratio >= 0.9:
                # 英語主体
                estimated_tokens = len(content) // 4
                safety_margin = 1.5
            else:
                # 日本語等マルチバイト
                estimated_tokens = len(content) // 3
                safety_margin = 3.0

            # 安全側（過大推定）
            estimated_tokens = int(len(content) / 3.0 * safety_margin)

            if total_tokens + estimated_tokens <= max_tokens:
                limited_results.append(result)
                total_tokens += estimated_tokens
            else:
                # トークン制限に達した
                logger.info(
                    f"Token limit ({max_tokens}) reached. Returning {len(limited_results)} results."
                )
                break

        return limited_results

    async def _update_access_record(self, result: ScoredMemory) -> None:
        """
        アクセス記録を更新

        Args:
            result: 検索結果
        """
        try:
            # アクセス情報を更新
            await self.storage_adapter.update_memory(
                memory_id=str(result.memory.id),
                updates={
                    "access_count": result.memory.access_count + 1,
                    "last_accessed_at": datetime.now(timezone.utc),
                },
            )
        except Exception as e:
            # アクセス記録更新失敗は警告で処理（検索結果は返す）
            logger.warning(
                f"Failed to update access record for memory {result.memory.id}: {str(e)}"
            )
