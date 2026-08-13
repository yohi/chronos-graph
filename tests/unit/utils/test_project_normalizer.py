from pathlib import Path

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


def test_normalize_project_name_current_repo_root() -> None:
    repo_root = Path(__file__).resolve().parents[3]

    assert normalize_project_name(str(repo_root)) == repo_root.name.lower()


def test_normalize_project_name_nested_repo_directory() -> None:
    nested_directory = Path(__file__).resolve().parents[1]
    repo_root = Path(__file__).resolve().parents[3]

    assert normalize_project_name(str(nested_directory)) == repo_root.name.lower()
