"""URL 関連のユーティリティ。"""

from urllib.parse import urlparse, urlunparse


def mask_url(url: str) -> str:
    """URL のクエリパラメータとフラグメントを削除して機密情報を保護する。

    Args:
        url: マスク対象の URL。

    Returns:
        クエリパラメータとフラグメントが削除された URL。
    """
    if not url:
        return ""

    try:
        parsed = urlparse(url)
        # クエリパラメータとフラグメントを空にして再構築
        return urlunparse(parsed._replace(query="", fragment=""))
    except Exception:
        # 解析に失敗した場合は、安全のため空文字列を返すか、
        # あるいは元の文字列を返さず「invalid-url」などを返す
        return "invalid-url"
