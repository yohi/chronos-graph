from __future__ import annotations

import os


def normalize_project_name(project: str | None) -> str | None:
    """Convert a raw project identifier into a canonical repository name."""
    if project is None:
        return None

    cleaned = project.strip()
    if not cleaned:
        return None

    cleaned = cleaned.rstrip("/\\")
    name = os.path.basename(cleaned) or cleaned
    name = name.strip()
    if not name:
        return None
    return name.lower()
