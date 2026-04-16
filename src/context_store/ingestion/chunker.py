"""Chunker: SourceType に応じてコンテンツを適切なサイズに分割する。

- CONVERSATION: Q&Aペア(最大3ターン)
- MANUAL: 短文はそのまま、長文はセクション分割(〜1000トークン相当)
- URL: Markdown見出し (H1/H2) ベースのセクション分割

コードブロック(```)の途中でチャンクを分断しないスマートチャンキングを実装する。
遅延評価のためジェネレータ(yield)を使用する。
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Generator
from typing import TYPE_CHECKING

from context_store.ingestion.adapters import RawContent
from context_store.models.memory import SourceType

if TYPE_CHECKING:
    from context_store.config import Settings

# Default constants (fallback if Settings is not provided)
DEFAULT_CHARS_PER_TOKEN = 3
DEFAULT_MAX_TOKENS_PER_CHUNK = 1000
DEFAULT_MAX_TURNS_PER_CHUNK = 3

# ターン区切りパターン
TURN_PATTERN = re.compile(r"^(User|Assistant|Human|AI|System):\s*", re.IGNORECASE | re.MULTILINE)

# Markdown 見出しパターン(H1/H2のみでセクション分割)
HEADING_PATTERN = re.compile(r"^(#{1,2})\s+.+$", re.MULTILINE)


class Chunker:
    """SourceType に応じてコンテンツを適切なサイズに分割するクラス。

    遅延評価のためジェネレータ(yield)を使用する。
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings
        self.chars_per_token = (
            max(1, settings.chars_per_token) if settings else DEFAULT_CHARS_PER_TOKEN
        )
        self.max_tokens_per_chunk = (
            max(1, settings.max_tokens_per_chunk) if settings else DEFAULT_MAX_TOKENS_PER_CHUNK
        )
        self.max_turns_per_chunk = (
            max(1, settings.max_turns_per_chunk) if settings else DEFAULT_MAX_TURNS_PER_CHUNK
        )

        self.max_chars_per_chunk = self.max_tokens_per_chunk * self.chars_per_token
        self._fence_positions: list[int] = []

    def _precompute_fences(self, text: str) -> None:
        """テキスト中のコードフェンス(```)の位置を事前計算する。"""
        self._fence_positions = [m.start() for m in re.finditer("```", text)]

    def _is_inside_code_block(self, pos: int) -> bool:
        """位置 pos がコードブロック内かどうかを判定する。"""
        if not self._fence_positions:
            return False
        # pos より前にあるフェンスの数を二分探索でカウント
        import bisect

        count = bisect.bisect_left(self._fence_positions, pos)
        return count % 2 == 1

    def _split_preserving_code_blocks(self, text: str, max_chars: int) -> list[str]:
        """コードブロックを分断しないように text を max_chars ごとに分割する。"""
        if len(text) <= max_chars:
            return [text]

        self._precompute_fences(text)
        chunks: list[str] = []
        offset = 0
        remaining = text

        while len(remaining) > max_chars:
            # max_chars の位置がコードブロック内かチェック
            split_pos = max_chars

            # コードブロック内なら、終了する ``` を探す
            if self._is_inside_code_block(offset + split_pos):
                end_pos = remaining.find("```", split_pos)
                if end_pos != -1:
                    split_pos = end_pos + 3  # ``` の後ろ
                else:
                    # 終了 ``` が見つからなければ全体を1チャンクにする
                    break

            # 段落境界(\n\n)で調整(コードブロック内でなければ)
            if not self._is_inside_code_block(offset + split_pos):
                boundary = remaining.rfind("\n\n", 0, split_pos)
                if boundary > max_chars // 2:
                    split_pos = boundary + 2

            chunks.append(remaining[:split_pos])
            offset += split_pos
            remaining = remaining[split_pos:]

        if remaining:
            chunks.append(remaining)

        return chunks

    def _split_conversation(self, content: str) -> list[str]:
        """会話トランスクリプトをターン単位に分割し、最大ターン数ずつグループ化する。"""
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

        # 最大 max_turns_per_chunk ターンずつグループ化
        groups: list[str] = []
        for i in range(0, len(turns), self.max_turns_per_chunk):
            group = turns[i : i + self.max_turns_per_chunk]
            groups.append("\n".join(group))

        return groups

    def _split_by_headings(self, content: str) -> list[str]:
        """Markdown 見出し (H1/H2) でセクション分割する。

        コードブロックを分断しない。
        """
        self._precompute_fences(content)
        # 見出し位置を収集(コードブロック内を除く)
        heading_positions: list[int] = []
        for match in HEADING_PATTERN.finditer(content):
            pos = match.start()
            if not self._is_inside_code_block(pos):
                heading_positions.append(pos)

        if not heading_positions:
            # 見出しがなければ max_chars ベースで分割
            return self._split_preserving_code_blocks(content, self.max_chars_per_chunk)

        # 見出し位置でセクションを分割
        sections: list[str] = []
        starts = [*heading_positions, len(content)]

        # 先頭に見出しより前のコンテンツがあれば追加
        if heading_positions[0] > 0:
            preamble = content[: heading_positions[0]].strip()
            if preamble:
                sections.append(preamble)

        for i in range(len(heading_positions)):
            section = content[starts[i] : starts[i + 1]].strip()
            if section:
                # セクションが長すぎる場合は再分割
                if len(section) > self.max_chars_per_chunk:
                    sub_chunks = self._split_preserving_code_blocks(
                        section, self.max_chars_per_chunk
                    )
                    sections.extend(sub_chunks)
                else:
                    sections.append(section)

        return sections if sections else [content]

    def _split_manual(self, content: str) -> list[str]:
        """手動入力テキストを分割する。

        短い場合はそのまま、長い場合はセクション分割する。
        """
        if len(content) <= self.max_chars_per_chunk:
            return [content]

        # Markdown 見出しがあれば見出しベースで分割
        if HEADING_PATTERN.search(content):
            return self._split_by_headings(content)

        # 段落(\n\n)で分割を試みる
        return self._split_preserving_code_blocks(content, self.max_chars_per_chunk)

    def chunk(self, raw: RawContent) -> Generator[RawContent, None, None]:
        """RawContent をチャンクに分割してジェネレータとして返す。

        各チャンクのメタデータには document_id, chunk_index, chunk_count が含まれる。
        """
        document_id = str(uuid.uuid4())
        base_meta = dict(raw.metadata)

        if raw.source_type == SourceType.CONVERSATION:
            raw_chunks = self._split_conversation(raw.content)
        elif raw.source_type == SourceType.URL:
            raw_chunks = self._split_by_headings(raw.content)
        else:
            # MANUAL およびその他
            raw_chunks = self._split_manual(raw.content)

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
