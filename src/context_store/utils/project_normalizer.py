from __future__ import annotations

import os
from pathlib import Path


def normalize_project_name(project: str | None) -> str | None:
    """Convert a raw project identifier into the git repository root name."""
    if project is None:
        return None

    cleaned = project.strip()
    if not cleaned:
        return None

    cleaned = cleaned.rstrip("/\\")

    if os.sep in cleaned or "/" in cleaned or "\\" in cleaned:
        try:
            path = Path(cleaned).expanduser().resolve()
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

    name = os.path.basename(cleaned) or cleaned
    name = name.strip()
    if not name:
        return None
    return name.lower()
