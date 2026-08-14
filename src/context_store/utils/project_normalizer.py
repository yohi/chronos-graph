from __future__ import annotations

import re
import subprocess
from pathlib import Path


def _sanitize_project_input(project: str) -> str | None:
    """Strip whitespace, trailing separators, and dangerous control characters."""
    cleaned = project.strip()
    cleaned = cleaned.rstrip("/\\")
    if not cleaned:
        return None
    # Remove embedded null bytes and other control characters that could cause
    # path-processing APIs to behave unexpectedly or bypass validation.
    cleaned = cleaned.replace("\x00", "")
    cleaned = "".join(char for char in cleaned if ord(char) >= 32 or char in {"\t"})
    cleaned = cleaned.strip()
    cleaned = cleaned.rstrip("/\\")
    if not cleaned:
        return None
    return cleaned


def _safe_basename(cleaned: str) -> str | None:
    """Extract a safe project name from a string without touching the filesystem."""
    # Strip a Windows drive letter prefix (e.g. C: or C:) so the remainder is
    # treated as a normal path segment list.
    without_drive = re.sub(r"^[A-Za-z]:", "", cleaned)
    segments = [segment for segment in without_drive.replace("\\", "/").split("/") if segment]
    name = segments[-1] if segments else ""
    name = name.strip()
    if not name:
        return None
    return name.lower()


def normalize_project_name(project: str | None) -> str | None:
    """Convert a raw project identifier into a stable project name.

    User-provided paths are treated lexically and are never opened or passed to
    a subprocess. The current working directory is trusted, so ``.`` may still
    be resolved to its repository name for local callers.
    """
    if project is None:
        return None

    cleaned = _sanitize_project_input(project)
    if cleaned is None:
        return None

    if cleaned == ".":
        try:
            result = subprocess.run(  # noqa: S607
                ["git", "rev-parse", "--show-toplevel"],
                cwd=Path.cwd(),
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout:
                repo_root = Path(result.stdout.strip())
                if repo_root.name:
                    return repo_root.name.lower()
        except (OSError, subprocess.SubprocessError, ValueError):
            pass

    return _safe_basename(cleaned)
