"""Source Adapter: 各種ソースからのコンテンツ取り込みアダプター。

SSRF対策として、URLAdapterはDNS解決後にプライベートIP/ループバック/
リンクローカル/マルチキャスト等をブロックする。
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Protocol, cast, runtime_checkable

import httpcore
import httpx

from context_store.config import Settings
from context_store.models.memory import SourceType

logger = logging.getLogger(__name__)


@dataclass
class RawContent:
    """ソースアダプターが返す生コンテンツ。"""

    content: str
    source_type: SourceType
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class SourceAdapter(Protocol):
    """ソースアダプターの抽象プロトコル。"""

    async def adapt(
        self, source: str, *, metadata: dict[str, Any] | None = None
    ) -> list[RawContent]:
        """ソースを RawContent リストに変換する。"""
        ...


class ConversationAdapter:
    """会話トランスクリプトを RawContent リストに変換するアダプター。

    1〜3ターンずつグループ化して RawContent を生成する。
    """

    MAX_TURNS_PER_CHUNK = 3

    async def adapt(
        self, source: str, *, metadata: dict[str, Any] | None = None
    ) -> list[RawContent]:
        """会話トランスクリプトを分割して RawContent リストを返す。"""
        meta = metadata or {}
        turns = self._parse_turns(source)

        if not turns:
            return [RawContent(content=source, source_type=SourceType.CONVERSATION, metadata=meta)]

        results: list[RawContent] = []
        for i in range(0, len(turns), self.MAX_TURNS_PER_CHUNK):
            chunk_turns = turns[i : i + self.MAX_TURNS_PER_CHUNK]
            chunk_text = "\n".join(chunk_turns)
            results.append(
                RawContent(
                    content=chunk_text,
                    source_type=SourceType.CONVERSATION,
                    metadata={**meta, "turn_start": i, "turn_end": i + len(chunk_turns) - 1},
                )
            )
        return results

    def _parse_turns(self, transcript: str) -> list[str]:
        """トランスクリプトを個々のターンに分割する。

        "Speaker: text" 形式の行を認識する。
        """
        lines = transcript.strip().split("\n")
        turns: list[str] = []
        current_turn: list[str] = []

        # "Speaker: text" パターン
        turn_pattern = re.compile(r"^(User|Assistant|Human|AI|System):\s*(.+)$", re.IGNORECASE)

        for line in lines:
            if turn_pattern.match(line):
                if current_turn:
                    turns.append("\n".join(current_turn))
                current_turn = [line]
            else:
                current_turn.append(line)

        if current_turn:
            turns.append("\n".join(current_turn))

        return turns


class ManualAdapter:
    """テキストを RawContent に変換するシンプルなアダプター。"""

    async def adapt(
        self, source: str, *, metadata: dict[str, Any] | None = None
    ) -> list[RawContent]:
        """テキストをそのまま RawContent に変換する。"""
        return [
            RawContent(
                content=source,
                source_type=SourceType.MANUAL,
                metadata=metadata or {},
            )
        ]


class _SimpleHTMLToTextParser(HTMLParser):
    """HTMLを簡易的にプレーンテキスト/Markdownへ変換するパーサー。"""

    # テキストを無視するタグ
    SKIP_TAGS = {"script", "style", "noscript", "head"}
    # ブロック要素（前後に改行を挿入）
    BLOCK_TAGS = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote"}
    # 見出しタグのプレフィックスマッピング
    HEADING_PREFIX = {"h1": "# ", "h2": "## ", "h3": "### ", "h4": "#### "}

    def __init__(self) -> None:
        super().__init__()
        self._result: list[str] = []
        self._skip_depth = 0
        self._current_tag = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
        if self._skip_depth > 0:
            return
        if tag in self.HEADING_PREFIX:
            self._result.append("\n" + self.HEADING_PREFIX[tag])
        elif tag == "br":
            self._result.append("\n")
        elif tag in self.BLOCK_TAGS:
            self._result.append("\n")
        self._current_tag = tag

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        if self._skip_depth > 0:
            return
        if tag in self.BLOCK_TAGS:
            self._result.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        self._result.append(data)

    def get_text(self) -> str:
        text = "".join(self._result)
        # 連続した空行を2行に圧縮
        return re.sub(r"\n{3,}", "\n\n", text).strip()


def _html_to_text(html: str) -> str:
    """HTMLをプレーンテキスト/Markdownに変換する。"""
    parser = _SimpleHTMLToTextParser()
    parser.feed(html)
    return parser.get_text()


class _SSRFBlockingTransport(httpx.AsyncBaseTransport):
    """SSRF対策のカスタムトランスポート。

    DNS解決後に検証済みIPへルーティングしつつ、
    TLS SNI と Host ヘッダーは元のホスト名を維持する。
    """

    def __init__(
        self,
        verified_ip: str,
        inner: httpcore.AsyncNetworkBackend | None = None,
    ) -> None:
        self._verified_ip = verified_ip
        if inner is None:
            backend_cls = getattr(httpcore, "AsyncNetworkBackend", None)
            if backend_cls is not None:
                self._inner = backend_cls()
            else:
                self._inner = httpcore.AsyncConnectionPool()._network_backend  # type: ignore[attr-defined]
        else:
            self._inner = inner
        self._transport = httpx.AsyncHTTPTransport(retries=0)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """検証済みIPへ接続するため、URLだけを差し替えて内部 transport に転送する。"""
        host = request.url.host
        if host is None:
            raise ValueError("request.url.host must not be None")

        try:
            ipaddress.ip_address(self._verified_ip)
        except ValueError as exc:
            raise ValueError(
                f"self._verified_ip must be a valid IP address: {self._verified_ip}"
            ) from exc

        headers = httpx.Headers(request.headers)
        headers["Host"] = host
        forwarded_request = httpx.Request(
            request.method,
            request.url.copy_with(host=self._verified_ip),
            headers=headers,
            stream=request.stream,
            extensions=request.extensions,
        )
        return await self._transport.handle_async_request(forwarded_request)

    async def aclose(self) -> None:
        await self._transport.aclose()


class URLAdapter:
    """URLからコンテンツを取得し RawContent に変換するアダプター。

    SSRF対策:
    - DNS解決後にプライベートIP/ループバック/リンクローカル/マルチキャスト等をブロック
    - 検証済みIPへ直接接続（TLS SNI・Hostヘッダーは元のホスト名を維持）
    - Content-Typeホワイトリスト検証（ヘッダー受信直後、ボディ読み込み前）
    - 10MB上限のストリーミング読み取り（超過時は即中断・aclose()保証）
    - リダイレクト最大 url_max_redirects 回
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()

    def _is_restricted_ip(self, ip_str: str) -> bool:
        """IPアドレスが制限されたアドレスかどうかを判定する。

        プライベート/ループバック/リンクローカル/マルチキャスト/未指定アドレスをブロック。
        """
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            return True  # 解析できない場合は拒否

        return (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_multicast
            or addr.is_unspecified
            or addr.is_reserved
        )

    async def _resolve_and_validate_ips(self, hostname: str) -> list[str]:
        """ホスト名をDNS解決し、すべてのIPが安全かを検証する。

        1件でもプライベートIPが含まれれば ValueError を送出する。
        allow_private_urls=True の場合はスキップ。
        """
        # IPリテラルの場合は直接検証
        try:
            addr = ipaddress.ip_address(hostname)
            if not self.settings.allow_private_urls and self._is_restricted_ip(str(addr)):
                raise ValueError(
                    f"Blocked: IP literal address '{hostname}' is private/loopback/restricted (SSRF prevention)"
                )
            return [str(addr)]
        except ValueError as e:
            if "Blocked" in str(e) or "SSRF" in str(e):
                raise
            # IPリテラルではない（通常のホスト名）

        # DNS解決
        try:
            addr_infos = socket.getaddrinfo(hostname, None)
        except socket.gaierror as exc:
            raise ValueError(f"DNS resolution failed for '{hostname}': {exc}") from exc

        resolved_ips: list[str] = []
        for addr_info in addr_infos:
            # addr_info: (family, type, proto, canonname, sockaddr)
            sockaddr = cast(tuple[str, object], addr_info[4])
            ip_str = sockaddr[0]  # IPv4: ("ip", port), IPv6: ("ip", port, flow, scope)

            if not self.settings.allow_private_urls and self._is_restricted_ip(ip_str):
                raise ValueError(
                    f"Blocked: DNS resolved '{hostname}' to restricted IP '{ip_str}' (SSRF prevention)"
                )
            resolved_ips.append(ip_str)

        if not resolved_ips:
            raise ValueError(f"No IP addresses resolved for '{hostname}'")

        return resolved_ips

    async def _fetch_with_verified_ip(self, url: str, resolved_ips: list[str]) -> httpx.Response:
        """検証済みIPを使ってURLにHTTPリクエストを発行する。

        TLS SNI・Hostヘッダーは元のホスト名を維持する。
        """
        parsed = httpx.URL(url)
        hostname = parsed.host
        first_ip = resolved_ips[0]

        # カスタムトランスポートで検証済みIPへルーティング
        transport = _SSRFBlockingTransport(verified_ip=first_ip)

        async with httpx.AsyncClient(
            transport=transport,
            follow_redirects=False,
            timeout=float(self.settings.url_timeout_seconds),
            verify=True,  # TLS証明書検証を強制
        ) as client:
            response = await client.get(url, headers={"Host": hostname})
            return response

    def _is_allowed_content_type(self, content_type: str) -> bool:
        """Content-Typeがホワイトリストに含まれるかを確認する。"""
        ct_main = content_type.split(";")[0].strip().lower()
        for allowed in self.settings.url_allowed_content_types:
            if allowed.endswith("/*"):
                prefix = allowed[:-2]
                if ct_main.startswith(prefix):
                    return True
            elif ct_main == allowed.lower():
                return True
        return False

    async def adapt(
        self, source: str, *, metadata: dict[str, Any] | None = None
    ) -> list[RawContent]:
        """URLからコンテンツを取得して RawContent リストを返す。"""
        meta = metadata or {}
        url = source

        # リダイレクト処理ループ
        for redirect_count in range(self.settings.url_max_redirects + 1):
            parsed_url = httpx.URL(url)
            hostname = parsed_url.host

            # DNS解決と検証
            resolved_ips = await self._resolve_and_validate_ips(hostname)

            # HTTPリクエスト発行
            response = await self._fetch_with_verified_ip(url, resolved_ips)

            # リダイレクト処理
            if response.status_code in (301, 302, 303, 307, 308):
                if redirect_count >= self.settings.url_max_redirects:
                    await response.aclose()
                    raise ValueError(
                        f"Too many redirects: exceeded url_max_redirects={self.settings.url_max_redirects}"
                    )
                location = response.headers.get("location", "")
                if not location:
                    await response.aclose()
                    raise ValueError("Redirect response missing Location header")
                await response.aclose()
                url = location
                continue

            # Content-Type 検証（ボディ読み込み前に実施）
            content_type = response.headers.get("content-type", "")
            if not self._is_allowed_content_type(content_type):
                await response.aclose()
                raise ValueError(
                    f"Content-Type '{content_type}' is not allowed. "
                    f"Allowed types: {self.settings.url_allowed_content_types}"
                )

            # ストリーミング読み取り（サイズ上限チェック）
            body_chunks: list[bytes] = []
            total_bytes = 0
            try:
                async for chunk in response.aiter_bytes():
                    total_bytes += len(chunk)
                    if total_bytes > self.settings.url_max_response_bytes:
                        await response.aclose()
                        raise ValueError(
                            f"Response size exceeds max limit of "
                            f"{self.settings.url_max_response_bytes} bytes"
                        )
                    body_chunks.append(chunk)
            except ValueError:
                raise
            except Exception as exc:
                await response.aclose()
                raise ValueError(f"Failed to read response body: {exc}") from exc

            raw_body = b"".join(body_chunks)

            # HTMLを Markdown/テキストに変換
            content_type_main = content_type.split(";")[0].strip().lower()
            if "html" in content_type_main:
                text_content = _html_to_text(raw_body.decode("utf-8", errors="replace"))
            else:
                text_content = raw_body.decode("utf-8", errors="replace")

            return [
                RawContent(
                    content=text_content,
                    source_type=SourceType.URL,
                    metadata={
                        **meta,
                        "url": source,
                        "final_url": url,
                        "content_type": content_type,
                    },
                )
            ]

        # ループを抜けた場合（通常はリダイレクト上限エラーで終了しているはず）
        raise ValueError(
            f"Too many redirects: exceeded url_max_redirects={self.settings.url_max_redirects}"
        )
