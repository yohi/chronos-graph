"""URL 関連のユーティリティ。"""

from urllib.parse import urlparse, urlunparse


def mask_url(url: str) -> str:
    """URL の認証情報、クエリ、フラグメントを削除して機密情報を保護する。

    認証情報 (user:pass@)、クエリパラメータ、およびフラグメントを削除し、
    ログ等に機密情報が漏洩するのを防ぐ。

    Args:
        url: マスク対象の URL。

    Returns:
        機密情報が削除された URL。
    """
    if not url:
        return ""

    try:
        parsed = urlparse(url)
        # ユーザー情報 (user:pass@) が含まれている場合は削除
        netloc = parsed.netloc
        if "@" in netloc:
            netloc = netloc.split("@")[-1]

        # クエリパラメータ、フラグメント、ユーザー情報を空にして再構築
        return urlunparse(parsed._replace(netloc=netloc, query="", fragment=""))

    except Exception:
        # urlparse は堅牢なため通常例外を投げないが、
        # 万が一解析に失敗した場合は、安全のため "invalid-url" を返す
        return "invalid-url"
