from __future__ import annotations

import os
import re
from pathlib import Path


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

    expanded = os.path.expanduser(cleaned)
    try:
        path = Path(expanded).resolve()
        if is_path or path.exists():
            if path.exists():
                current = path if path.is_dir() else path.parent
                while True:
                    if (current / ".git").exists():
                        name = current.name.strip()
                        return name.lower() if name else None
                    parent = current.parent
                    if parent == current:
                        break
                    current = parent
    except (OSError, ValueError):
        pass

    segments = [segment for segment in cleaned.replace("\\", "/").split("/") if segment]
    name = segments[-1] if segments else ""
    name = name.strip()
    if not name:
        return None
    return name.lower()
