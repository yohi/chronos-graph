"""Source Adapter: 各種ソースからのコンテンツ取り込みアダプター。

SSRF対策として、URLAdapterはDNS解決後にプライベートIP/ループバック/
リンクローカル/マルチキャスト等をブロックする。
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import socket
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, ClassVar, Protocol, cast, runtime_checkable

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
    """会話トランスクリプトを RawContent に変換するアダプター。"""

    async def adapt(
        self, source: str, *, metadata: dict[str, Any] | None = None
    ) -> list[RawContent]:
        """会話トランスクリプトを RawContent のリストに変換する。"""
        meta = metadata or {}
        turns = self._parse_turns(source)

        if not turns:
            return [RawContent(content=source, source_type=SourceType.CONVERSATION, metadata=meta)]

        # 会話を一定数（例: 5ターン）ごとに分割して返す
        chunk_size = 5
        results: list[RawContent] = []

        for i in range(0, len(turns), chunk_size):
            chunk = turns[i : i + chunk_size]
            results.append(
                RawContent(
                    content="\n".join(chunk),
                    source_type=SourceType.CONVERSATION,
                    metadata={**meta, "turn_start": i, "turn_end": i + len(chunk) - 1},
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
    SKIP_TAGS: ClassVar[set[str]] = {"script", "style", "noscript", "head"}
    # ブロック要素（前後に改行を挿入）
    BLOCK_TAGS: ClassVar[set[str]] = {
        "p",
        "div",
        "br",
        "li",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "blockquote",
    }
    # 見出しタグのプレフィックスマッピング
    HEADING_PREFIX: ClassVar[dict[str, str]] = {
        "h1": "# ",
        "h2": "## ",
        "h3": "### ",
        "h4": "#### ",
    }

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
        inner: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._verified_ip = verified_ip
        self._transport = inner or httpx.AsyncHTTPTransport(retries=0)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """検証済みIPへ接続するため、URLだけを差し替えて内部 transport に転送する。"""
        # 元のURLからホスト名（およびポート番号を含む authority）を取得
        host = request.url.host
        if host is None:
            raise ValueError("request.url.host must not be None")

        try:
            ipaddress.ip_address(self._verified_ip)
        except ValueError as exc:
            raise ValueError(
                f"self._verified_ip must be a valid IP address: {self._verified_ip}"
            ) from exc

        # ヘッダーの Host は元のリクエストから引き継ぐ（ポート番号等も維持される）
        headers = httpx.Headers(request.headers)
        # もし Host ヘッダーがなければ URL の authority を使う
        if "Host" not in headers:
            headers["Host"] = request.url.netloc.decode("ascii")

        new_extensions = dict(request.extensions or {})
        # SNI はポートを含まない純粋なホスト名を使用
        new_extensions["sni_hostname"] = host
        forwarded_request = httpx.Request(
            request.method,
            request.url.copy_with(host=self._verified_ip),
            headers=headers,
            stream=request.stream,
            extensions=new_extensions,
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

        グローバルIP以外（プライベート、ループバック、リンクローカル、マルチキャスト等）をブロック。
        """
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            return True  # 解析できない場合は拒否

        # SSRF対策: グローバルユニキャスト以外を制限
        if addr.is_loopback or addr.is_private or addr.is_link_local or addr.is_multicast or addr.is_reserved or addr.is_unspecified:
            return True

        return not addr.is_global

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
            addr_infos = await asyncio.to_thread(socket.getaddrinfo, hostname, None)
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

    async def _fetch_with_verified_ip(
        self, url: str, resolved_ips: list[str]
    ) -> tuple[int, httpx.Headers, bytes]:
        """検証済みIPを使ってURLにHTTPリクエストを発行する。

        TLS SNI・Hostヘッダーは元のホスト名を維持する。
        """
        parsed = httpx.URL(url)
        hostname = parsed.host
        host_header = parsed.netloc.decode("ascii")
        last_exception: Exception | None = None

        # 検証済みIPリストを順に試行する
        for ip in resolved_ips:
            # カスタムトランスポートで検証済みIPへルーティング
            transport = _SSRFBlockingTransport(verified_ip=ip)

            try:
                async with httpx.AsyncClient(
                    transport=transport,
                    follow_redirects=False,
                    timeout=float(self.settings.url_timeout_seconds),
                    verify=True,  # TLS証明書検証を強制
                ) as client:
                    async with client.stream("GET", url, headers={"Host": host_header}) as response:
                        # リダイレクトまたは 2xx 以外はボディを読まずにステータスのみ返す
                        if response.status_code in (301, 302, 303, 307, 308) or not (
                            200 <= response.status_code < 300
                        ):
                            return response.status_code, response.headers, b""

                        # Content-Type チェック（ボディ読み込み前に実施）
                        content_type = response.headers.get("content-type", "")
                        if not self._is_allowed_content_type(content_type):
                            raise ValueError(
                                f"Content-Type '{content_type}' is not allowed. "
                                f"Allowed types: {self.settings.url_allowed_content_types}"
                            )

                        body_chunks: list[bytes] = []
                        total_bytes = 0
                        async for chunk in response.aiter_bytes():
                            total_bytes += len(chunk)
                            if total_bytes > self.settings.url_max_response_bytes:
                                raise ValueError(
                                    f"Response size exceeds max limit of "
                                    f"{self.settings.url_max_response_bytes} bytes"
                                )
                            body_chunks.append(chunk)

                        return response.status_code, response.headers, b"".join(body_chunks)

            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                # ネットワーク接続エラーの場合は次のIPを試す
                last_exception = exc
                continue
            except ValueError:
                # バリデーションエラー（サイズ超過等）は即座に再送
                raise
            except (
                httpx.ReadError,
                httpx.WriteError,
                httpx.ProtocolError,
                httpx.ReadTimeout,
                httpx.WriteTimeout,
                httpx.PoolTimeout,
                httpx.NetworkError,
                httpx.TimeoutException,
            ) as exc:
                # HTTP(S)リクエスト/レスポンスのI/Oエラー等も記録して次を試す
                last_exception = exc
                continue

        # 全てのIPで失敗した場合
        if last_exception:
            raise ValueError(
                f"Failed to connect to '{hostname}' via any resolved IPs: {last_exception}"
            ) from last_exception
        raise ValueError(f"Failed to connect to '{hostname}' (no valid IPs)")

    def _is_allowed_content_type(self, content_type: str) -> bool:
        """Content-Typeがホワイトリストに含まれるかを確認する。"""
        ct_main = content_type.split(";")[0].strip().lower()
        for allowed in self.settings.url_allowed_content_types:
            if allowed.endswith("/*"):
                prefix = allowed[:-1]
                if ct_main.startswith(prefix):
                    return True
            elif ct_main == allowed.lower():
                return True
        return False

    async def aclose(self) -> None:
        """リソースを解放する（現在は特になし）。"""
        pass

    async def adapt(
        self, source: str, *, metadata: dict[str, Any] | None = None
    ) -> list[RawContent]:
        """URLからコンテンツを取得して RawContent リストを返す。"""
        meta = metadata or {}
        url = source

        # リダイレクト処理ループ
        for redirect_count in range(self.settings.url_max_redirects + 1):
            parsed_url = httpx.URL(url)

            # バリデーション: 絶対URL、http/https、ホスト名の存在
            if not parsed_url.is_absolute_url:
                raise ValueError(f"URL must be absolute: {url}")
            if parsed_url.scheme not in ("http", "https"):
                raise ValueError(f"Unsupported URL scheme: {parsed_url.scheme}")
            hostname = parsed_url.host
            if not hostname:
                raise ValueError(f"URL must have a host: {url}")

            # DNS解決と検証
            resolved_ips = await self._resolve_and_validate_ips(hostname)

            # HTTPリクエスト発行
            status_code, headers, raw_body = await self._fetch_with_verified_ip(url, resolved_ips)

            # リダイレクト処理
            if status_code in (301, 302, 303, 307, 308):
                if redirect_count >= self.settings.url_max_redirects:
                    raise ValueError(
                        f"Too many redirects: exceeded url_max_redirects={self.settings.url_max_redirects}"
                    )
                location = headers.get("location", "")
                if not location:
                    raise ValueError("Redirect response missing Location header")
                url = str(httpx.URL(url).join(location))
                continue

            # 非 2xx の場合はエラー
            if not (200 <= status_code < 300):
                raise ValueError(f"HTTP request failed with status code {status_code}")

            # HTMLを Markdown/テキストに変換
            content_type = headers.get("content-type", "")
            content_type_main = content_type.split(";")[0].strip().lower()

            charset = "utf-8"
            match = re.search(r"charset=([\w-]+)", content_type, re.IGNORECASE)
            if match:
                charset = match.group(1)

            try:
                decoded_body = raw_body.decode(charset)
            except (LookupError, UnicodeDecodeError):
                decoded_body = raw_body.decode("utf-8", errors="replace")

            if "html" in content_type_main:
                text_content = _html_to_text(decoded_body)
            else:
                text_content = decoded_body

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
