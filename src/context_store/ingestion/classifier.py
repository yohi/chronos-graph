"""Classifier: ルールベースによる記憶種別の自動分類。

LLMを使用せず、キーワードマッチと構文パターンで分類する。
- EPISODIC: 「〜した」「〜を決めた」、タイムスタンプ付き、会話ログ由来
- SEMANTIC: 「〜とは」「〜の仕様は」、ドキュメント/URL由来
- PROCEDURAL: 「〜する方法」「手順: 」、コマンド列、ステップ構造
- フォールバック: EPISODIC + importance_score に 0.5倍ペナルティ
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from context_store.ingestion.adapters import RawContent
from context_store.models.memory import MemoryType, SourceType

logger = logging.getLogger(__name__)

# デフォルト importance_score
DEFAULT_IMPORTANCE_SCORE = 0.5
# フォールバック時のペナルティ係数
FALLBACK_PENALTY = 0.5

# ===========================================================================
# 分類ルール: EPISODIC パターン
# ===========================================================================
# 過去形・完了形の動詞 (日本語)
_EPISODIC_VERB_PATTERNS = [
    r"した[。、。\s」\)]",  # 〜した
    r"しました",
    r"決めた",
    r"決定した",
    r"完了した",
    r"終わった",
    r"やった",
    r"行った",
    r"実行した",
    r"作成した",
    r"修正した",
    r"対応した",
    r"リリースした",
    r"デプロイした",
    r"確認した",
    r"実施した",
    r"達成した",
    r"開始した",
    r"終了した",
    r"失敗した",
    r"成功した",
    r"was done",
    r"was completed",
    r"decided",
]

# タイムスタンプパターン
_TIMESTAMP_PATTERN = re.compile(
    r"\d{4}[-/]\d{1,2}[-/]\d{1,2}"  # YYYY-MM-DD または YYYY/M/D
    r"|昨日|今日|先週|先月|今週",
    re.IGNORECASE,
)

_EPISODIC_VERB_RE = re.compile("|".join(_EPISODIC_VERB_PATTERNS), re.IGNORECASE)

# ===========================================================================
# 分類ルール: SEMANTIC パターン
# ===========================================================================
_SEMANTIC_PATTERNS = [
    r"とは",  # 〜とは
    r"という",  # 〜という概念
    r"の仕様",  # 〜の仕様は
    r"の概要",
    r"の定義",
    r"について",
    r"を指す",
    r"を意味する",
    r"とは何",
    r"is defined as",
    r"refers to",
    r"is a type of",
    r"is an abbreviation",
    r"stands for",
    r"# ",  # Markdown 見出し（ドキュメント）
    r"## ",
]

_SEMANTIC_RE = re.compile("|".join(_SEMANTIC_PATTERNS))

# ===========================================================================
# 分類ルール: PROCEDURAL パターン
# ===========================================================================
_PROCEDURAL_PATTERNS = [
    r"する方法",  # 〜する方法
    r"のやり方",
    r"手順",  # 手順：
    r"ステップ",  # ステップ構造
    r"step \d+",  # Step 1, Step 2
    r"^\d+\. ",  # 番号付きリスト (1. 〜)
    r"^\$ ",  # シェルコマンド
    r"^> ",  # コマンドプロンプト
    r"```",  # コードブロック（コマンド例）
    r"how to",
    r"instructions",
    r"procedure",
]

_PROCEDURAL_RE = re.compile("|".join(_PROCEDURAL_PATTERNS), re.IGNORECASE | re.MULTILINE)

# コマンド列の検出（複数のコマンドが連続する）
_COMMAND_LINE_RE = re.compile(
    r"(^\$\s+\S+|^>\s+\S+|^\d+\.\s+\S+)",
    re.MULTILINE,
)


@dataclass
class ClassificationResult:
    """分類結果を保持するデータクラス。"""

    memory_type: MemoryType
    importance_score: float
    is_fallback: bool = False
    confidence: float = 1.0


def _score_episodic(content: str, source_type: SourceType) -> float:
    """EPISODIC スコアを計算する。"""
    score = 0.0

    # 会話ログ由来
    if source_type == SourceType.CONVERSATION:
        score += 3.0

    # 過去形動詞パターン
    matches = _EPISODIC_VERB_RE.findall(content)
    score += len(matches) * 2.0

    # タイムスタンプ
    if _TIMESTAMP_PATTERN.search(content):
        score += 2.0

    return score


def _score_semantic(content: str, source_type: SourceType) -> float:
    """SEMANTIC スコアを計算する。"""
    score = 0.0

    # URL/ドキュメント由来
    if source_type == SourceType.URL:
        score += 2.0

    # 定義・説明パターン
    matches = _SEMANTIC_RE.findall(content)
    score += len(matches) * 1.5

    return score


def _score_procedural(content: str, source_type: SourceType) -> float:
    """PROCEDURAL スコアを計算する。"""
    score = 0.0

    # 手順・ステップパターン
    matches = _PROCEDURAL_RE.findall(content)
    score += len(matches) * 1.5

    # 複数のコマンド行が連続している場合
    cmd_matches = _COMMAND_LINE_RE.findall(content)
    if len(cmd_matches) >= 2:
        score += len(cmd_matches) * 2.0

    return score


class Classifier:
    """ルールベースによる記憶種別の自動分類器。"""

    def classify(self, raw: RawContent) -> ClassificationResult:
        """RawContent を分析して MemoryType に分類する。

        Returns:
            ClassificationResult: 分類結果（memory_type, importance_score, is_fallback）
        """
        content = raw.content
        source_type = raw.source_type

        # 各タイプのスコアを計算
        episodic_score = _score_episodic(content, source_type)
        semantic_score = _score_semantic(content, source_type)
        procedural_score = _score_procedural(content, source_type)

        max_score = max(episodic_score, semantic_score, procedural_score)

        # スコアがすべて 0 またはほぼ同点 → フォールバック
        if max_score < 1.0:
            logger.warning(
                "分類フォールバック: コンテンツが既定のパターンに合致しません。"
                " EPISODIC にフォールバックします（importance_score にペナルティ適用）。"
                " content_preview=%r",
                content[:50],
            )
            return ClassificationResult(
                memory_type=MemoryType.EPISODIC,
                importance_score=DEFAULT_IMPORTANCE_SCORE * FALLBACK_PENALTY,
                is_fallback=True,
                confidence=0.0,
            )

        # 最高スコアのタイプを選択
        if procedural_score == max_score and procedural_score >= 1.0:
            return ClassificationResult(
                memory_type=MemoryType.PROCEDURAL,
                importance_score=DEFAULT_IMPORTANCE_SCORE,
                is_fallback=False,
                confidence=procedural_score / (max_score + 1e-9),
            )
        elif semantic_score == max_score and semantic_score >= 1.0:
            return ClassificationResult(
                memory_type=MemoryType.SEMANTIC,
                importance_score=DEFAULT_IMPORTANCE_SCORE,
                is_fallback=False,
                confidence=semantic_score / (max_score + 1e-9),
            )
        else:
            return ClassificationResult(
                memory_type=MemoryType.EPISODIC,
                importance_score=DEFAULT_IMPORTANCE_SCORE,
                is_fallback=False,
                confidence=episodic_score / (max_score + 1e-9),
            )
