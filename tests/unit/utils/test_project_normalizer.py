from pathlib import Path
from unittest.mock import MagicMock

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
    # On Linux these paths don't exist, so we expect a safe basename fallback.
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
    if relative_path in {"."}:
        # Mock git so we don't need an actual git repository in the temp dir.
        monkeypatch.setattr(
            "context_store.utils.project_normalizer.subprocess.run",
            lambda *args, **kwargs: MagicMock(returncode=0, stdout=str(repo_root)),
        )
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


def test_normalize_project_name_nested_repo_directory(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "my-repo"
    nested_directory = repo_root / "src" / "package"
    (repo_root / ".git").mkdir(parents=True)
    nested_directory.mkdir(parents=True)

    assert normalize_project_name(str(nested_directory)) == "package"


def test_normalize_project_name_does_not_use_user_path_as_git_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_directory = tmp_path / "project"
    project_directory.mkdir()

    def fail_if_git_is_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("user-controlled paths must not become git cwd")

    monkeypatch.setattr(
        "context_store.utils.project_normalizer.subprocess.run",
        fail_if_git_is_called,
    )

    assert normalize_project_name(str(project_directory)) == "project"


def test_normalize_project_name_rejects_path_traversal() -> None:
    # CodeQL: user input must not be passed directly to path expressions.
    assert normalize_project_name("../../../etc/passwd") == "passwd"
    assert normalize_project_name("/foo/../bar/../baz") == "baz"
    assert normalize_project_name("foo/../../bar") == "bar"


def test_normalize_project_name_strips_null_bytes_and_nontext() -> None:
    # CodeQL: input containing embedded nulls or control chars is unsafe.
    # Null bytes are removed (not treated as separators), so the remainder is concatenated.
    assert normalize_project_name("repo\x00secret") == "reposecret"
    assert normalize_project_name("repo\x1bescape") == "repoescape"


def test_normalize_project_name_rejects_unsafe_drive_path() -> None:
    # Drive-relative paths should fall back to a safe basename.
    assert normalize_project_name("C:secret") == "secret"
    assert normalize_project_name("C:\\..\\..\\windows") == "windows"
