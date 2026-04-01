"""Chunker: SourceType に応じてコンテンツを適切なサイズに分割する。

- CONVERSATION: Q&Aペア（最大3ターン）
- MANUAL: 短文はそのまま、長文はセクション分割（〜1000トークン相当）
- URL: Markdown見出し (H1/H2) ベースのセクション分割

コードブロック（```）の途中でチャンクを分断しないスマートチャンキングを実装する。
遅延評価のためジェネレータ（yield）を使用する。
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Generator
from typing import Any

from context_store.ingestion.adapters import RawContent
from context_store.models.memory import SourceType

# トークン数の近似値として文字数 ÷ 3 を使用（日本語・英語混在を考慮）
CHARS_PER_TOKEN = 3
# チャンクあたりの最大トークン数（概算）
MAX_TOKENS_PER_CHUNK = 1000
MAX_CHARS_PER_CHUNK = MAX_TOKENS_PER_CHUNK * CHARS_PER_TOKEN

# CONVERSATION の最大ターン数
MAX_TURNS_PER_CHUNK = 3

# ターン区切りパターン
TURN_PATTERN = re.compile(r"^(User|Assistant|Human|AI|System):\s*", re.IGNORECASE | re.MULTILINE)

# Markdown 見出しパターン（H1/H2のみでセクション分割）
HEADING_PATTERN = re.compile(r"^(#{1,2})\s+.+$", re.MULTILINE)


def _assign_metadata(
    chunks: list[str],
    base_metadata: dict[str, Any],
    document_id: str,
) -> list[RawContent]:
    """チャンクリストに必須メタデータを付与して RawContent リストを作成する。"""
    total = len(chunks)
    result = []
    for i, content in enumerate(chunks):
        meta = {
            **base_metadata,
            "document_id": document_id,
            "chunk_index": i,
            "chunk_count": total,
        }
        result.append(RawContent(content=content, source_type=base_metadata.get("_source_type", SourceType.MANUAL), metadata=meta))  # type: ignore[arg-type]
    return result


def _is_inside_code_block(text: str, pos: int) -> bool:
    """テキスト中の位置 pos がコードブロック内かどうかを判定する。"""
    # pos より前の ``` の出現回数が奇数ならコードブロック内
    count = text[:pos].count("```")
    return count % 2 == 1


def _split_preserving_code_blocks(text: str, max_chars: int) -> list[str]:
    """コードブロックを分断しないように text を max_chars ごとに分割する。"""
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    remaining = text

    while len(remaining) > max_chars:
        # max_chars の位置がコードブロック内かチェック
        split_pos = max_chars

        # コードブロック内なら、終了する ``` を探す
        if _is_inside_code_block(remaining, split_pos):
            end_pos = remaining.find("```", split_pos)
            if end_pos != -1:
                split_pos = end_pos + 3  # ``` の後ろ
            else:
                # 終了 ``` が見つからなければ全体を1チャンクにする
                break

        # 段落境界（\n\n）で調整（コードブロック内でなければ）
        if not _is_inside_code_block(remaining, split_pos):
            boundary = remaining.rfind("\n\n", 0, split_pos)
            if boundary > max_chars // 2:
                split_pos = boundary + 2

        chunks.append(remaining[:split_pos])
        remaining = remaining[split_pos:]

    if remaining:
        chunks.append(remaining)

    return chunks


def _split_conversation(content: str) -> list[str]:
    """会話トランスクリプトをターン単位に分割し、最大3ターンずつグループ化する。"""
    lines = content.strip().split("\n")
    turns: list[str] = []
    current_turn: list[str] = []

    for line in lines:
        if TURN_PATTERN.match(line):
            if current_turn:
                turns.append("\n".join(current_turn))
            current_turn = [line]
        else:
            current_turn.append(line)

    if current_turn:
        turns.append("\n".join(current_turn))

    if not turns:
        return [content]

    # 最大 MAX_TURNS_PER_CHUNK ターンずつグループ化
    groups: list[str] = []
    for i in range(0, len(turns), MAX_TURNS_PER_CHUNK):
        group = turns[i : i + MAX_TURNS_PER_CHUNK]
        groups.append("\n".join(group))

    return groups


def _split_by_headings(content: str) -> list[str]:
    """Markdown 見出し (H1/H2) でセクション分割する。

    コードブロックを分断しない。
    """
    # 見出し位置を収集（コードブロック内を除く）
    heading_positions: list[int] = []
    for match in HEADING_PATTERN.finditer(content):
        pos = match.start()
        if not _is_inside_code_block(content, pos):
            heading_positions.append(pos)

    if not heading_positions:
        # 見出しがなければ max_chars ベースで分割
        return _split_preserving_code_blocks(content, MAX_CHARS_PER_CHUNK)

    # 見出し位置でセクションを分割
    sections: list[str] = []
    starts = heading_positions + [len(content)]

    # 先頭に見出しより前のコンテンツがあれば追加
    if heading_positions[0] > 0:
        preamble = content[: heading_positions[0]].strip()
        if preamble:
            sections.append(preamble)

    for i in range(len(heading_positions)):
        section = content[starts[i] : starts[i + 1]].strip()
        if section:
            # セクションが長すぎる場合は再分割
            if len(section) > MAX_CHARS_PER_CHUNK:
                sub_chunks = _split_preserving_code_blocks(section, MAX_CHARS_PER_CHUNK)
                sections.extend(sub_chunks)
            else:
                sections.append(section)

    return sections if sections else [content]


def _split_manual(content: str) -> list[str]:
    """手動入力テキストを分割する。

    短い場合はそのまま、長い場合はセクション分割する。
    """
    if len(content) <= MAX_CHARS_PER_CHUNK:
        return [content]

    # Markdown 見出しがあれば見出しベースで分割
    if HEADING_PATTERN.search(content):
        return _split_by_headings(content)

    # 段落（\n\n）で分割を試みる
    return _split_preserving_code_blocks(content, MAX_CHARS_PER_CHUNK)


class Chunker:
    """SourceType に応じてコンテンツを適切なサイズに分割するクラス。

    遅延評価のためジェネレータ（yield）を使用する。
    """

    def chunk(self, raw: RawContent) -> Generator[RawContent, None, None]:
        """RawContent をチャンクに分割してジェネレータとして返す。

        各チャンクのメタデータには document_id, chunk_index, chunk_count が含まれる。
        """
        document_id = str(uuid.uuid4())
        base_meta = dict(raw.metadata)

        if raw.source_type == SourceType.CONVERSATION:
            raw_chunks = _split_conversation(raw.content)
        elif raw.source_type == SourceType.URL:
            raw_chunks = _split_by_headings(raw.content)
        else:
            # MANUAL およびその他
            raw_chunks = _split_manual(raw.content)

        total = len(raw_chunks)
        for i, chunk_content in enumerate(raw_chunks):
            meta = {
                **base_meta,
                "document_id": document_id,
                "chunk_index": i,
                "chunk_count": total,
            }
            yield RawContent(
                content=chunk_content,
                source_type=raw.source_type,
                metadata=meta,
            )
