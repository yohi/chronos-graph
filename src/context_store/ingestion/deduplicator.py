"""Deduplicator: ベクトル類似度に基づく重複排除。

- 類似度 >= 0.90: Append-only 置換（既存を Archived に、新規を INSERT）
- 0.85 <= 類似度 < 0.90: 統合候補としてマーク
- 類似度 < 0.85: 新規挿入
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from context_store.models.memory import Memory
from context_store.storage.protocols import StorageAdapter

logger = logging.getLogger(__name__)

# 類似度閾値
REPLACE_THRESHOLD = 0.90  # >= この値で Append-only 置換
MERGE_THRESHOLD = 0.85  # >= この値で統合候補

# vector_search の top_k
DEDUP_TOP_K = 5


class DeduplicationAction(str, Enum):
    """重複排除の結果アクション。"""

    INSERT = "insert"  # 新規挿入
    REPLACE = "replace"  # Append-only 置換（既存を Archive）
    MERGE_CANDIDATE = "merge_candidate"  # 統合候補としてマーク


@dataclass
class DeduplicationResult:
    """重複排除の結果を保持するデータクラス。"""

    action: DeduplicationAction
    existing_memory: Memory | None
    similarity: float = 0.0


class Deduplicator:
    """StorageAdapter の vector_search を使って重複排除を行う。"""

    def __init__(self, storage: StorageAdapter) -> None:
        self._storage = storage

    async def deduplicate(self, new_memory: Memory) -> DeduplicationResult:
        """新規記憶の重複チェックを行い、アクションを決定する。

        Args:
            new_memory: 新しく追加しようとしている記憶

        Returns:
            DeduplicationResult: 推奨アクションと既存記憶（存在する場合）
        """
        if not new_memory.embedding:
            # 埋め込みベクトルがない場合は新規挿入
            return DeduplicationResult(action=DeduplicationAction.INSERT, existing_memory=None)

        # 既存記憶を類似度検索
        similar_memories = await self._storage.vector_search(
            embedding=new_memory.embedding,
            top_k=DEDUP_TOP_K,
            project=new_memory.project,
        )

        if not similar_memories:
            return DeduplicationResult(action=DeduplicationAction.INSERT, existing_memory=None)

        # 最高類似度の記憶を取得
        top_match = max(similar_memories, key=lambda sm: sm.score)
        top_similarity = top_match.score
        top_memory = top_match.memory

        logger.debug(
            "重複チェック: top_similarity=%.4f, existing_id=%s",
            top_similarity,
            top_memory.id,
        )

        if top_similarity >= REPLACE_THRESHOLD:
            # Append-only 置換: 既存記憶を Archive に遷移
            await self._archive_memory(top_memory)
            logger.info(
                "Append-only 置換: existing_id=%s を Archived に遷移 (similarity=%.4f)",
                top_memory.id,
                top_similarity,
            )
            return DeduplicationResult(
                action=DeduplicationAction.REPLACE,
                existing_memory=top_memory,
                similarity=top_similarity,
            )
        elif top_similarity >= MERGE_THRESHOLD:
            # 統合候補としてマーク
            logger.info(
                "統合候補: existing_id=%s (similarity=%.4f)",
                top_memory.id,
                top_similarity,
            )
            return DeduplicationResult(
                action=DeduplicationAction.MERGE_CANDIDATE,
                existing_memory=top_memory,
                similarity=top_similarity,
            )
        else:
            # 新規挿入
            return DeduplicationResult(
                action=DeduplicationAction.INSERT,
                existing_memory=None,
                similarity=top_similarity,
            )

    async def _archive_memory(self, memory: Memory) -> None:
        """記憶を Archived 状態に遷移させる。

        archived_at を設定して update_memory を呼ぶ。
        """
        updates: dict[str, Any] = {
            "archived_at": datetime.now(timezone.utc).isoformat(),
        }
        await self._storage.update_memory(str(memory.id), updates)
