"""Post Processor - フィルタ・トークン制限・アクセス記録"""

import asyncio
import logging
import math

from context_store.models.memory import ScoredMemory
from context_store.storage.protocols import StorageAdapter

logger = logging.getLogger(__name__)


class PostProcessor:
    """検索結果の後処理（フィルタ、トークン制限、アクセス記録更新）"""

    def __init__(
        self,
        storage_adapter: StorageAdapter,
        max_tokens: int | None = None,
    ) -> None:
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
        await asyncio.gather(
            *(self._update_access_record(result) for result in filtered),
            return_exceptions=True,
        )

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
        if not results:
            return results
        if max_tokens <= 0:
            return []

        # 推定: ASCII文字比率で言語を判定し、安全側（過大推定）でトークン数を推定
        limited_results: list[ScoredMemory] = []
        total_tokens = 0
        safety_margin = 1.5

        for result in results:
            content = result.memory.content
            if not content:
                estimated_tokens = 0
            else:
                ascii_count = sum(1 for c in content if ord(c) < 128)
                ascii_ratio = ascii_count / len(content)

                if ascii_ratio >= 0.9:
                    estimated_tokens = math.ceil((len(content) / 4.0) * safety_margin)
                else:
                    estimated_tokens = math.ceil((len(content) / 3.0) * safety_margin)
                estimated_tokens = max(1, estimated_tokens)

            # total_tokens + estimated_tokens が max_tokens を超えないことを保証
            if total_tokens + estimated_tokens <= max_tokens:
                limited_results.append(result)
                total_tokens += estimated_tokens
            else:
                logger.info(
                    f"Token limit ({max_tokens}) reached. Returning {len(limited_results)} results."
                )
                break

        return limited_results

    async def _update_access_record(self, result: ScoredMemory) -> None:
        """
        アクセス記録をアトミックに更新

        Args:
            result: 検索結果
        """
        try:
            # アトミックなインクリメント API を使用して、競合による更新消失を防ぐ
            memory_id = str(result.memory.id)
            await self.storage_adapter.increment_memory_access_count(memory_id)
        except Exception as e:
            # 更新失敗は警告に留める（検索機能自体は継続）
            logger.warning(
                f"Failed to update access record for memory {result.memory.id}: {str(e)}"
            )
