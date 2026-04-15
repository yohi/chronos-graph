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


def test_mask_url_non_url_input() -> None:
    """URL 形式でない文字列の場合、そのままの文字列を返す。"""
    # urlparse は多くの文字列をパスとして受け入れるため、
    # URL として成立しない文字列もそのまま返される。
    assert mask_url("not a url") == "not a url"
