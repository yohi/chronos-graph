from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from urllib.parse import parse_qs, urlparse

import pytest


def load_migration_script() -> ModuleType:
    """Load the migration script without requiring scripts to be a package."""
    script_path = Path(__file__).resolve().parents[3] / "scripts" / "migrate_normalize_projects.py"
    spec = importlib.util.spec_from_file_location("migrate_normalize_projects", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    @property
    def content(self) -> bytes:
        return self.body

    def raise_for_status(self) -> None:
        return None


def test_migrate_updates_only_noncanonical_projects(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = load_migration_script()
    monkeypatch.setattr(module, "_PAGE_SIZE", 2)
    requests: list[dict[str, object]] = []
    pages = {
        "": [
            {"id": "memory-1", "project": " /tmp/Chronos-Graph/ "},
            {"id": "memory-2", "project": "chronos-graph"},
        ],
        "memory-2": [{"id": "memory-3", "project": " /tmp/Other-Project/ "}],
    }

    def fake_request(method: str, url: str, **kwargs: object) -> FakeResponse:
        requests.append({"method": method, "url": url, **kwargs})
        if method == "GET":
            query = parse_qs(urlparse(url).query)
            last_id = query.get("id", ["gt."])[0].removeprefix("gt.")
            assert query == {
                "select": ["id,project"],
                "order": ["id.asc"],
                "limit": ["2"],
                **({"id": [f"gt.{last_id}"]} if last_id else {}),
            }
            return FakeResponse(json.dumps(pages[last_id]).encode())
        if "memory-3" in url:
            return FakeResponse(b"[]")
        return FakeResponse(b'[{"id":"memory-1","project":"chronos-graph"}]')

    monkeypatch.setattr(module.httpx, "request", fake_request)
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "test-key")

    result = module.main()

    assert result == 0
    assert capsys.readouterr().out == "changed=1 unchanged=1\n"
    assert [request["method"] for request in requests] == [
        "GET",
        "GET",
        "PATCH",
        "PATCH",
    ]
    assert requests[0]["url"] == (
        "https://example.supabase.co/rest/v1/memories?select=id%2Cproject&order=id.asc&limit=2"
    )
    assert requests[1]["url"] == (
        "https://example.supabase.co/rest/v1/memories?"
        "select=id%2Cproject&order=id.asc&limit=2&id=gt.memory-2"
    )
    assert requests[2]["url"] == (
        "https://example.supabase.co/rest/v1/memories?"
        "id=eq.memory-1&project=eq.%20%2Ftmp%2FChronos-Graph%2F%20"
    )
    assert requests[3]["url"] == (
        "https://example.supabase.co/rest/v1/memories?"
        "id=eq.memory-3&project=eq.%20%2Ftmp%2FOther-Project%2F%20"
    )
    assert json.loads(requests[2]["content"].decode()) == {"project": "chronos-graph"}
    assert json.loads(requests[3]["content"].decode()) == {"project": "other-project"}
    assert requests[2]["headers"]["Content-Type"] == "application/json"
    assert requests[2]["headers"]["Prefer"] == "return=representation"


def test_fetch_rows_processes_remaining_rows_when_earlier_row_is_deleted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_migration_script()
    monkeypatch.setattr(module, "_PAGE_SIZE", 2)
    rows = [
        {"id": "memory-1", "project": "project-1"},
        {"id": "memory-2", "project": "project-2"},
        {"id": "memory-3", "project": "project-3"},
        {"id": "memory-4", "project": "project-4"},
    ]
    requests: list[str] = []

    def fake_request(method: str, url: str, **kwargs: object) -> FakeResponse:
        assert method == "GET"
        query = parse_qs(urlparse(url).query)
        requests.append(url)
        if "id" in query:
            last_id = query["id"][0].removeprefix("gt.")
            page = [row for row in rows if row["id"] > last_id][:2]
        elif "offset" in query:
            offset = int(query["offset"][0])
            page = rows[offset : offset + 2]
        else:
            page = rows[:2]
        if len(requests) == 1:
            rows.pop(0)
        return FakeResponse(json.dumps(page).encode())

    monkeypatch.setattr(module.httpx, "request", fake_request)

    fetched = module._fetch_rows("https://example.supabase.co", "test-key")

    assert [row["id"] for row in fetched] == [
        "memory-1",
        "memory-2",
        "memory-3",
        "memory-4",
    ]
    assert all("offset" not in url for url in requests)


def test_update_project_uses_null_project_cas_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_migration_script()
    requests: list[dict[str, object]] = []

    def fake_request(method: str, url: str, **kwargs: object) -> FakeResponse:
        requests.append({"method": method, "url": url, **kwargs})
        return FakeResponse(b"[]")

    monkeypatch.setattr(module.httpx, "request", fake_request)

    changed = module._update_project(
        "https://example.supabase.co", "test-key", "memory-null", None, "new-project"
    )

    assert changed == 0
    assert requests[0]["url"] == (
        "https://example.supabase.co/rest/v1/memories?id=eq.memory-null&project=is.null"
    )
