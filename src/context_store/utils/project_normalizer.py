from __future__ import annotations

import os
import re
import subprocess


def normalize_project_name(project: str | None) -> str | None:
    """Convert a raw project identifier into the git repository root name."""
    if project is None:
        return None

    cleaned = project.strip()
    if not cleaned:
        return None

    cleaned = cleaned.rstrip("/\\")
    if not cleaned:
        return None

    is_path = (
        cleaned in {".", ".."}
        or "/" in cleaned
        or "\\" in cleaned
        or bool(re.match(r"^[A-Za-z]:[\\/]", cleaned))
    )
    if not is_path:
        return cleaned.lower()

    # --- path handling: never pass user input directly to Path; use git subprocess ---
    # expanduser is necessary for tilde paths, but we keep the value as a string.
    expanded = os.path.expanduser(cleaned)

    # Resolve the candidate directory without building a Path from user data.
    candidate_dir = expanded
    try:
        if not os.path.isdir(candidate_dir):
            parent = os.path.dirname(candidate_dir) or candidate_dir
            if os.path.isdir(parent):
                candidate_dir = parent
    except (OSError, ValueError):
        candidate_dir = ""

    if candidate_dir:
        try:
            result = subprocess.run(  # noqa: S607
                ["git", "rev-parse", "--show-toplevel"],
                cwd=candidate_dir,
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout:
                repo_root = result.stdout.strip()
                if repo_root:
                    name = os.path.basename(repo_root).strip()
                    if name:
                        return name.lower()
        except (OSError, subprocess.SubprocessError, ValueError):
            pass

    segments = [segment for segment in cleaned.replace("\\", "/").split("/") if segment]
    name = segments[-1] if segments else ""
    name = name.strip()
    if not name:
        return None
    return name.lower()
