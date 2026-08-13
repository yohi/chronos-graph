#!/usr/bin/env -S uv run --script
# How to run:
# export SUPABASE_URL=... SUPABASE_KEY=...
# uv run python scripts/migrate_normalize_projects.py

"""Backfill canonical project names in a Supabase memories table."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypedDict
from urllib.parse import quote, urlencode

import httpx

_SRC_PATH: Final = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_PATH) not in sys.path:
    sys.path.insert(0, str(_SRC_PATH))

from context_store.utils.project_normalizer import normalize_project_name  # noqa: E402

_REQUEST_TIMEOUT_SECONDS: Final = 60.0
_PAGE_SIZE: Final = 1000


class MemoryRow(TypedDict):
    """The memory columns required by this migration."""

    id: str
    project: str | None


@dataclass(frozen=True, slots=True)
class MigrationCounts:
    """Counts of changed and unchanged memory rows."""

    changed: int
    unchanged: int


def _request(
    endpoint: str,
    key: str,
    *,
    method: str = "GET",
    payload: bytes | None = None,
    prefer: str | None = None,
) -> bytes:
    """Execute one authenticated PostgREST request and return its body."""
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {key}",
        "apikey": key,
    }
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if prefer is not None:
        headers["Prefer"] = prefer

    response = httpx.request(
        method,
        endpoint,
        content=payload,
        headers=headers,
        timeout=_REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.content


def _parse_rows(payload: bytes) -> list[MemoryRow]:
    """Parse and validate the memory rows returned by PostgREST."""
    decoded = json.loads(payload)
    if not isinstance(decoded, list):
        raise ValueError("PostgREST response must be a list")

    rows: list[MemoryRow] = []
    for item in decoded:
        if not isinstance(item, dict):
            raise ValueError("PostgREST row must be an object")
        memory_id = item.get("id")
        project = item.get("project")
        if not isinstance(memory_id, str):
            raise ValueError("PostgREST row id must be a string")
        if project is not None and not isinstance(project, str):
            raise ValueError("PostgREST project must be a string or null")
        rows.append({"id": memory_id, "project": project})
    return rows


def _fetch_rows(base_url: str, key: str) -> list[MemoryRow]:
    """Fetch all memory identifiers and project values from Supabase."""
    rows: list[MemoryRow] = []
    offset = 0
    while True:
        query = urlencode(
            {
                "select": "id,project",
                "order": "id.asc",
                "limit": _PAGE_SIZE,
                "offset": offset,
            }
        )
        endpoint = f"{base_url}/rest/v1/memories?{query}"
        page = _parse_rows(_request(endpoint, key))
        rows.extend(page)
        if len(page) < _PAGE_SIZE:
            return rows
        offset += _PAGE_SIZE


def _update_project(
    base_url: str, key: str, memory_id: str, old_project: str | None, project: str | None
) -> int:
    """Replace one memory's project value through PostgREST."""
    encoded_id = quote(memory_id, safe="")
    project_filter = "is.null" if old_project is None else f"eq.{quote(old_project, safe='')}"
    endpoint = f"{base_url}/rest/v1/memories?id=eq.{encoded_id}&project={project_filter}"
    payload = json.dumps({"project": project}).encode()
    response = _request(
        endpoint,
        key,
        method="PATCH",
        payload=payload,
        prefer="return=representation",
    )
    updated_rows = json.loads(response)
    if not isinstance(updated_rows, list):
        raise ValueError("PostgREST update response must be a list")
    return len(updated_rows)


def migrate(base_url: str, key: str) -> MigrationCounts:
    """Normalize every fetched memory and update only changed rows."""
    changed = 0
    unchanged = 0
    for row in _fetch_rows(base_url.rstrip("/"), key):
        normalized = normalize_project_name(row["project"])
        if normalized == row["project"]:
            unchanged += 1
            continue
        changed += _update_project(base_url.rstrip("/"), key, row["id"], row["project"], normalized)
    return MigrationCounts(changed=changed, unchanged=unchanged)


def main() -> int:
    """Run the backfill using Supabase credentials from the environment."""
    base_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_KEY", "")
    if not base_url or not key:
        print("SUPABASE_URL and SUPABASE_KEY are required", file=sys.stderr)
        return 1

    counts = migrate(base_url, key)
    print(f"changed={counts.changed} unchanged={counts.unchanged}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
