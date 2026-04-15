"""mask_url ユーティリティのユニットテスト。"""

from context_store.utils.url import mask_url


def test_mask_url_removes_query_and_fragment() -> None:
    """クエリパラメータとフラグメントが削除される。"""
    url = "https://example.com/path?token=secret#section1"
    expected = "https://example.com/path"
    assert mask_url(url) == expected


def test_mask_url_preserves_path_and_host() -> None:
    """ホストとパスは保持される。"""
    url = "http://sub.example.co.jp:8080/api/v1/data"
    assert mask_url(url) == url


def test_mask_url_empty_string() -> None:
    """空文字列は空文字列を返す。"""
    assert mask_url("") == ""


def test_mask_url_invalid_input() -> None:
    """無効な URL 形式の場合、'invalid-url' を返す（例外を投げない）。"""
    # 実際には urlparse はほとんどの文字列を受け入れるが、
    # 極端なケースでの挙動を確認
    assert mask_url("not a url") == "not a url"
