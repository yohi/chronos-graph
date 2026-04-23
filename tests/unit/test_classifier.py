"""Task 4.3: Classifier のユニットテスト。"""

from __future__ import annotations

import logging

import pytest

from context_store.ingestion.adapters import RawContent
from context_store.ingestion.classifier import Classifier
from context_store.models.memory import MEMORY_TYPE_TAGS, MemoryType, SourceType


def _make_raw(content: str, source_type: SourceType = SourceType.MANUAL) -> RawContent:
    return RawContent(content=content, source_type=source_type, metadata={})


# ===========================================================================
# EPISODIC 分類テスト
# ===========================================================================


def test_classifier_episodic_past_action() -> None:
    """「DBのマイグレーションを実行した」→ EPISODIC。"""
    raw = _make_raw("DBのマイグレーションを実行した")
    classifier = Classifier()
    result = classifier.classify(raw)

    assert result.memory_type == MemoryType.EPISODIC
    assert result.is_fallback is False


def test_classifier_episodic_decision() -> None:
    """「新しいアーキテクチャを採用することを決めた」→ EPISODIC。"""
    raw = _make_raw("新しいアーキテクチャを採用することを決めた")
    classifier = Classifier()
    result = classifier.classify(raw)

    assert result.memory_type == MemoryType.EPISODIC
    assert result.is_fallback is False


def test_classifier_episodic_conversation_source() -> None:
    """会話ログ (CONVERSATION) 由来は EPISODIC になりやすい。"""
    raw = _make_raw(
        "User: 今日何してた?\nAssistant: コードレビューをしました。", SourceType.CONVERSATION
    )
    classifier = Classifier()
    result = classifier.classify(raw)

    assert result.memory_type == MemoryType.EPISODIC


def test_classifier_episodic_timestamp() -> None:
    """タイムスタンプ付きの内容は EPISODIC。"""
    raw = _make_raw("2024-01-15: プロジェクトのキックオフミーティングが行われた")
    classifier = Classifier()
    result = classifier.classify(raw)

    assert result.memory_type == MemoryType.EPISODIC


# ===========================================================================
# SEMANTIC 分類テスト
# ===========================================================================


def test_classifier_semantic_definition() -> None:
    """「JWTとはJSON Web Tokenの略で...」→ SEMANTIC。"""
    raw = _make_raw(
        "JWTとはJSON Web Tokenの略で、認証情報をJSONオブジェクトとして"
        "安全に送受信するための仕様です。"
    )
    classifier = Classifier()
    result = classifier.classify(raw)

    assert result.memory_type == MemoryType.SEMANTIC
    assert result.is_fallback is False


def test_classifier_semantic_specification() -> None:
    """「〜の仕様は」を含む → SEMANTIC。"""
    raw = _make_raw("このAPIの仕様はREST準拠で、JSONを返します。")
    classifier = Classifier()
    result = classifier.classify(raw)

    assert result.memory_type == MemoryType.SEMANTIC


def test_classifier_semantic_url_source() -> None:
    """URL由来のドキュメントは SEMANTIC になりやすい。"""
    raw = _make_raw(
        "# 概要\n\nこのライブラリはPythonの非同期処理を簡略化します。",
        SourceType.URL,
    )
    classifier = Classifier()
    result = classifier.classify(raw)

    assert result.memory_type == MemoryType.SEMANTIC


def test_classifier_semantic_what_is() -> None:
    """「〜とは」パターン → SEMANTIC。"""
    raw = _make_raw("非同期プログラミングとは、複数の処理を並行して実行する手法です。")
    classifier = Classifier()
    result = classifier.classify(raw)

    assert result.memory_type == MemoryType.SEMANTIC


# ===========================================================================
# PROCEDURAL 分類テスト
# ===========================================================================


def test_classifier_procedural_deployment() -> None:
    """「デプロイ手順: 1. docker compose up 2. ...」→ PROCEDURAL。"""
    raw = _make_raw("デプロイ手順:\n1. docker compose up\n2. マイグレーション実行\n3. 動作確認")
    classifier = Classifier()
    result = classifier.classify(raw)

    assert result.memory_type == MemoryType.PROCEDURAL
    assert result.is_fallback is False


def test_classifier_procedural_how_to() -> None:
    """「〜する方法」パターン → PROCEDURAL。"""
    raw = _make_raw("環境をセットアップする方法:\n1. uvをインストール\n2. uv sync を実行")
    classifier = Classifier()
    result = classifier.classify(raw)

    assert result.memory_type == MemoryType.PROCEDURAL


def test_classifier_procedural_command_sequence() -> None:
    """コマンド列 ($ prefix) → PROCEDURAL。"""
    raw = _make_raw("$ git clone repo\n$ cd repo\n$ make install")
    classifier = Classifier()
    result = classifier.classify(raw)

    assert result.memory_type == MemoryType.PROCEDURAL


def test_classifier_procedural_steps() -> None:
    """「ステップ構造（Step 1, Step 2）」→ PROCEDURAL。"""
    raw = _make_raw(
        "Step 1: リポジトリをクローン\nStep 2: 依存関係をインストール\nStep 3: テストを実行"
    )
    classifier = Classifier()
    result = classifier.classify(raw)

    assert result.memory_type == MemoryType.PROCEDURAL


# ===========================================================================
# フォールバック (EPISODIC) テスト
# ===========================================================================


def test_classifier_fallback_ambiguous() -> None:
    """「なるほど」→ EPISODIC にフォールバック。"""
    raw = _make_raw("なるほど")
    classifier = Classifier()
    result = classifier.classify(raw)

    assert result.memory_type == MemoryType.EPISODIC
    assert result.is_fallback is True


def test_classifier_fallback_penalty() -> None:
    """フォールバック時に importance_score にペナルティが適用される。"""
    raw = _make_raw("そうなんだ")
    classifier = Classifier()
    result = classifier.classify(raw)

    assert result.is_fallback is True
    # ペナルティ係数 0.5 が適用されているはず
    assert result.importance_score < 0.5 + 1e-9  # デフォルト 0.5 の 0.5倍 = 0.25


def test_classifier_fallback_warning_log(caplog: pytest.LogCaptureFixture) -> None:
    """フォールバック時に警告ログが出力される。"""
    raw = _make_raw("あー")
    classifier = Classifier()

    with caplog.at_level(logging.WARNING, logger="context_store.ingestion.classifier"):
        result = classifier.classify(raw)

    assert result.is_fallback is True
    assert any(
        "fallback" in r.message.lower() or "未分類" in r.message or "フォールバック" in r.message
        for r in caplog.records
    )


# ===========================================================================
# ClassificationResult テスト
# ===========================================================================


def test_classification_result_has_memory_type() -> None:
    """ClassificationResult に memory_type が含まれる。"""
    raw = _make_raw("テスト")
    classifier = Classifier()
    result = classifier.classify(raw)

    assert hasattr(result, "memory_type")
    assert isinstance(result.memory_type, MemoryType)


def test_classification_result_has_importance_score() -> None:
    """ClassificationResult に importance_score が含まれる。"""
    raw = _make_raw("デプロイ手順: 1. ビルド 2. デプロイ")
    classifier = Classifier()
    result = classifier.classify(raw)

    assert hasattr(result, "importance_score")
    assert 0.0 <= result.importance_score <= 1.0


def test_classification_result_non_fallback_normal_score() -> None:
    """非フォールバック時は importance_score がペナルティなし。"""
    raw = _make_raw("デプロイ手順: 1. ビルド 2. デプロイ")
    classifier = Classifier()
    result = classifier.classify(raw)

    assert result.is_fallback is False
    assert result.importance_score >= 0.5  # ペナルティなし


# ===========================================================================
# 明示的タグ (Emoji) テスト
# ===========================================================================


@pytest.mark.parametrize(
    "mem_type, sample_text",
    [
        (MemoryType.EPISODIC, "昨日の会議で決定しました。"),
        (MemoryType.SEMANTIC, "これはシステムの仕様です。"),
        (MemoryType.PROCEDURAL, "セットアップ方法を説明します。"),
    ],
)
def test_classifier_explicit_tags(mem_type: MemoryType, sample_text: str) -> None:
    """明示的なタグによる分類（各メモリタイプ）。"""
    raw = _make_raw(f"{MEMORY_TYPE_TAGS[mem_type]}\n{sample_text}")
    classifier = Classifier()
    result = classifier.classify(raw)

    assert result.memory_type == mem_type
    assert result.confidence == pytest.approx(1.0)


def test_classifier_explicit_tag_overrides_other_patterns() -> None:
    """明示的なタグは、中身の内容(例: 過去形)よりも優先される。"""
    # 中身は「した(Episodic)」だが、タグは [🧠 Semantic]
    raw = _make_raw(
        f"{MEMORY_TYPE_TAGS[MemoryType.SEMANTIC]}\n過去の設計を分析した結果をまとめました。"
    )
    classifier = Classifier()
    result = classifier.classify(raw)

    assert result.memory_type == MemoryType.SEMANTIC
    assert result.is_fallback is False
