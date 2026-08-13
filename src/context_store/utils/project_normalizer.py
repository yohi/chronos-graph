from __future__ import annotations

import os


def normalize_project_name(project: str | None) -> str | None:
    """Convert a raw project identifier into a canonical repository name."""
    if project is None:
        return None

    cleaned = project.strip().rstrip("/\\")
    if not cleaned:
        return None

    parts = cleaned.replace("\\", "/").split("/")
    if "src" in parts:
        name = parts[parts.index("src") - 1]
    else:
        name = os.path.basename(cleaned) or cleaned
    name = name.strip()
    return name.lower() if name else None
