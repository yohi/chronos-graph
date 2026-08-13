import pytest

from context_store.utils.project_normalizer import normalize_project_name


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("/home/y_ohi/program/private/justice", "justice"),
        ("/home/y_ohi/dotfiles", "dotfiles"),
        (" dotfiles-ai ", "dotfiles-ai"),
        ("DotFiles-AI", "dotfiles-ai"),
        ("chronos-graph/", "chronos-graph"),
        ("  /home/y_ohi/program/private/bitbucket-mcp  ", "bitbucket-mcp"),
        ("sibyl", "sibyl"),
        ("none", "none"),
        (None, None),
        ("", None),
        ("   ", None),
    ],
)
def test_normalize_project_name(raw: str | None, expected: str | None) -> None:
    assert normalize_project_name(raw) == expected
