"""Task 4.2: Chunker のユニットテスト。"""

from __future__ import annotations

from context_store.ingestion.adapters import RawContent
from context_store.ingestion.chunker import Chunker
from context_store.models.memory import SourceType


def _make_raw(content: str, source_type: SourceType, **meta: object) -> RawContent:
    return RawContent(content=content, source_type=source_type, metadata=dict(meta))


# ===========================================================================
# 会話ログの Q&A ペア分割テスト
# ===========================================================================


def test_chunker_conversation_basic() -> None:
    """会話ログが Q&A ペアに分割される。"""
    transcript = (
        "User: 質問1\n"
        "Assistant: 回答1\n"
        "User: 質問2\n"
        "Assistant: 回答2\n"
        "User: 質問3\n"
        "Assistant: 回答3\n"
        "User: 質問4\n"
        "Assistant: 回答4\n"
    )
    raw = _make_raw(transcript, SourceType.CONVERSATION)
    chunker = Chunker()
    chunks = list(chunker.chunk(raw))

    # 8ターン → 最大3ターンずつ → 少なくとも2チャンク
    assert len(chunks) >= 2
    for chunk in chunks:
        assert chunk.source_type == SourceType.CONVERSATION
        assert chunk.content.strip()


def test_chunker_conversation_metadata_required() -> None:
    """CONVERSATION チャンクに必須メタデータが含まれる。"""
    raw = _make_raw("User: Q\nAssistant: A", SourceType.CONVERSATION)
    chunker = Chunker()
    chunks = list(chunker.chunk(raw))

    for i, chunk in enumerate(chunks):
        assert "document_id" in chunk.metadata
        assert "chunk_index" in chunk.metadata
        assert "chunk_count" in chunk.metadata
        assert chunk.metadata["chunk_index"] == i
        assert chunk.metadata["chunk_count"] == len(chunks)


# ===========================================================================
# 手動入力の分割テスト
# ===========================================================================


def test_chunker_manual_short_passthrough() -> None:
    """短い手動入力はそのまま1チャンクになる。"""
    short_text = "これは短いテキストです。"
    raw = _make_raw(short_text, SourceType.MANUAL)
    chunker = Chunker()
    chunks = list(chunker.chunk(raw))

    assert len(chunks) == 1
    assert chunks[0].content == short_text


def test_chunker_manual_long_splits() -> None:
    """長い手動入力がセクション分割される（〜1000トークン）。"""
    # 十分に長いテキストを生成（MAX_CHARS_PER_CHUNK = 3000 を超えるように）
    long_text = "これはテスト文章です。" * 400  # ~4400文字（3000文字を超える）
    raw = _make_raw(long_text, SourceType.MANUAL)
    chunker = Chunker()
    chunks = list(chunker.chunk(raw))

    # 長いテキストは複数チャンクに分割される
    assert len(chunks) >= 2
    for chunk in chunks:
        assert chunk.content.strip()


def test_chunker_manual_metadata_required() -> None:
    """MANUAL チャンクに必須メタデータが含まれる。"""
    raw = _make_raw("テスト", SourceType.MANUAL)
    chunker = Chunker()
    chunks = list(chunker.chunk(raw))

    for i, chunk in enumerate(chunks):
        assert "document_id" in chunk.metadata
        assert "chunk_index" in chunk.metadata
        assert "chunk_count" in chunk.metadata
        assert isinstance(chunk.metadata["chunk_index"], int)
        assert chunk.metadata["chunk_index"] == i


# ===========================================================================
# URLドキュメントのセクション分割テスト
# ===========================================================================


def test_chunker_url_heading_split() -> None:
    """URLドキュメントがMarkdown見出しでセクション分割される。"""
    url_doc = (
        "# セクション1\n\n"
        "セクション1の内容です。詳細な説明が続きます。\n\n"
        "## サブセクション1.1\n\n"
        "サブセクションの内容です。\n\n"
        "# セクション2\n\n"
        "セクション2の内容です。\n\n"
    )
    raw = _make_raw(url_doc, SourceType.URL)
    chunker = Chunker()
    chunks = list(chunker.chunk(raw))

    assert len(chunks) >= 2
    # 各セクションが独立したチャンクになっている
    all_content = "\n".join(c.content for c in chunks)
    assert "セクション1" in all_content
    assert "セクション2" in all_content


def test_chunker_url_metadata_required() -> None:
    """URL チャンクに必須メタデータが含まれる。"""
    url_doc = "# Section1\n\nContent1\n\n# Section2\n\nContent2\n"
    raw = _make_raw(url_doc, SourceType.URL)
    chunker = Chunker()
    chunks = list(chunker.chunk(raw))

    for i, chunk in enumerate(chunks):
        assert "document_id" in chunk.metadata
        assert "chunk_index" in chunk.metadata
        assert "chunk_count" in chunk.metadata
        assert chunk.metadata["chunk_index"] == i
        assert chunk.metadata["chunk_count"] == len(chunks)


# ===========================================================================
# コードブロック保護テスト
# ===========================================================================


def test_chunker_does_not_split_inside_code_block() -> None:
    """コードブロック (```) の内部でチャンクが分断されない。"""
    # 長いテキストにコードブロックを挿入
    preamble = "これは導入テキストです。" * 50
    code_inner = "def example():\n    # 非常に長いコード\n" + "    x = 1\n" * 30 + "    return x\n"
    code_block = "```python\n" + code_inner + "```\n"
    epilogue = "これは末尾のテキストです。" * 10

    doc = preamble + "\n\n" + code_block + "\n\n" + epilogue
    raw = _make_raw(doc, SourceType.URL)
    chunker = Chunker()
    chunks = list(chunker.chunk(raw))

    # コードブロックが分断されていないことを確認
    # コードブロック全体が1つのチャンク内に含まれているはず
    code_block_chunks = [c for c in chunks if "```" in c.content]
    for chunk in code_block_chunks:
        # ``` の出現回数が偶数（開始と終了が揃っている）
        backtick_count = chunk.content.count("```")
        assert backtick_count % 2 == 0, (
            f"コードブロックが分断されています。チャンク内の``` の数: {backtick_count}\n"
            f"チャンク内容: {chunk.content[:200]}"
        )


def test_chunker_code_block_protection_manual() -> None:
    """MANUAL ソースのコードブロックも分断されない。"""
    preamble = "テキスト " * 100  # 十分に長い前文
    code_block = "```bash\necho hello\nfor i in range(100):\n    echo $i\ndone\n```"
    doc = preamble + "\n\n" + code_block

    raw = _make_raw(doc, SourceType.MANUAL)
    chunker = Chunker()
    chunks = list(chunker.chunk(raw))

    # コードブロックを含むチャンクのバッククォートが偶数
    code_block_chunks = [c for c in chunks if "```" in c.content]
    for chunk in code_block_chunks:
        backtick_count = chunk.content.count("```")
        assert backtick_count % 2 == 0


# ===========================================================================
# ジェネレータ（遅延評価）テスト
# ===========================================================================


def test_chunker_returns_generator() -> None:
    """Chunker.chunk() がジェネレータを返す（遅延評価）。"""
    import types

    raw = _make_raw("テスト", SourceType.MANUAL)
    chunker = Chunker()
    result = chunker.chunk(raw)
    assert isinstance(result, types.GeneratorType)


def test_chunker_chunk_index_sequential() -> None:
    """chunk_index が 0 から連続した整数になっている。"""
    doc = "# S1\n\nContent1\n\n# S2\n\nContent2\n\n# S3\n\nContent3\n"
    raw = _make_raw(doc, SourceType.URL)
    chunker = Chunker()
    chunks = list(chunker.chunk(raw))

    indices = [c.metadata["chunk_index"] for c in chunks]
    assert indices == list(range(len(chunks)))


def test_chunker_chunk_count_consistent() -> None:
    """全チャンクの chunk_count が同一の値になっている。"""
    doc = "# S1\n\nContent1\n\n# S2\n\nContent2\n"
    raw = _make_raw(doc, SourceType.URL)
    chunker = Chunker()
    chunks = list(chunker.chunk(raw))

    counts = [c.metadata["chunk_count"] for c in chunks]
    assert len(set(counts)) == 1  # 全て同じ値
    assert counts[0] == len(chunks)


def test_chunker_document_id_consistent() -> None:
    """全チャンクの document_id が同一の値になっている。"""
    doc = "# S1\n\nContent1\n\n# S2\n\nContent2\n"
    raw = _make_raw(doc, SourceType.URL)
    chunker = Chunker()
    chunks = list(chunker.chunk(raw))

    doc_ids = [c.metadata["document_id"] for c in chunks]
    assert len(set(doc_ids)) == 1  # 全て同じ document_id
