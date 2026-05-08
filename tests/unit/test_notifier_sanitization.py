from mcp_gateway.approval.notifier import _sanitize_for_log


def test_sanitize_value_patterns():
    # Bearer token
    assert _sanitize_for_log("Bearer sk-12345") == "**********"
    assert _sanitize_for_log("bearer abcdef") == "**********"

    # JWT
    jwt = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ."
        "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    )
    assert _sanitize_for_log(jwt) == "**********"

    # Long hex/base64
    assert _sanitize_for_log("a" * 32) == "**********"  # hex
    assert _sanitize_for_log("0123456789abcdef0123456789abcdef") == "**********"
    assert _sanitize_for_log("A" * 32) == "**********"  # base64-like

    # Credit Card
    assert _sanitize_for_log("1234-5678-9012-3456") == "**********"
    assert _sanitize_for_log("1234 5678 9012 3456") == "**********"

    # Normal strings
    assert _sanitize_for_log("normal string") == "normal string"
    assert _sanitize_for_log("short") == "short"
    assert _sanitize_for_log("a" * 31) == "a" * 31  # too short for conservative hex match


def test_sanitize_collections():
    # List
    assert _sanitize_for_log(["Bearer token", "normal"]) == ["**********", "normal"]

    # Set / Frozenset
    s = {"Bearer token", "normal"}
    sanitized_s = _sanitize_for_log(s)
    assert isinstance(sanitized_s, set)
    assert sanitized_s == {"**********", "normal"}

    fs = frozenset({"Bearer token", "normal"})
    sanitized_fs = _sanitize_for_log(fs)
    assert isinstance(sanitized_fs, frozenset)
    assert sanitized_fs == frozenset({"**********", "normal"})


def test_sanitize_nested():
    data = {
        "params": [{"key": "Bearer token"}, frozenset({"0123456789abcdef0123456789abcdef"})],
        "safe": "hello",
    }
    sanitized = _sanitize_for_log(data)
    assert sanitized["params"][0]["key"] == "**********"
    assert sanitized["params"][1] == frozenset({"**********"})
    assert sanitized["safe"] == "hello"
