from pathlib import Path

import pytest

from context_store.utils.project_normalizer import normalize_project_name


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" dotfiles-ai ", "dotfiles-ai"),
        ("DotFiles-AI", "dotfiles-ai"),
        ("chronos-graph/", "chronos-graph"),
        ("sibyl", "sibyl"),
        ("none", "none"),
        (None, None),
        ("", None),
        ("   ", None),
    ],
)
def test_normalize_project_name(raw: str | None, expected: str | None) -> None:
    assert normalize_project_name(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        r"C:\Users\Alice\MyRepo\\",
        r"C:\Users\Alice\MyRepo",
    ],
)
def test_normalize_project_name_windows_path(raw: str) -> None:
    assert normalize_project_name(raw) == "myrepo"


@pytest.mark.parametrize("separator", ["/", "\\", "///", "\\\\"])
def test_normalize_project_name_trailing_separator(separator: str) -> None:
    assert normalize_project_name(f"my-repo{separator}") == "my-repo"


@pytest.mark.parametrize(
    ("relative_path", "expected"),
    [(".", "my-repo"), ("src", "src"), ("frontend", "frontend")],
)
def test_normalize_project_name_relative_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative_path: str,
    expected: str,
) -> None:
    repo_root = tmp_path / "my-repo"
    (repo_root / ".git").mkdir(parents=True)
    (repo_root / "src").mkdir()
    monkeypatch.chdir(repo_root)

    assert normalize_project_name(relative_path) == expected


@pytest.mark.parametrize(
    "value",
    [
        "src",
        "frontend",
        "./repo",
        "../repo",
        "~/repo",
        "/path/to/repo",
        r"C:\\Users\\Alice\\MyRepo",
        "  Mixed-Case  ",
        "repo/",
    ],
)
def test_normalize_project_name_is_idempotent(value: str) -> None:
    normalized = normalize_project_name(value)
    assert normalize_project_name(normalized) == normalized


def test_normalize_project_name_expands_user_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    repo_root = home / "my-repo"
    (repo_root / ".git").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))

    assert normalize_project_name("~/my-repo") == "my-repo"


def test_normalize_project_name_nested_repo_directory(tmp_path: Path) -> None:
    repo_root = tmp_path / "my-repo"
    nested_directory = repo_root / "src" / "package"
    (repo_root / ".git").mkdir(parents=True)
    nested_directory.mkdir(parents=True)

    assert normalize_project_name(str(nested_directory)) == "my-repo"
