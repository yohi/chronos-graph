from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from urllib.parse import parse_qs, urlparse
from urllib.request import Request

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

    def read(self) -> bytes:
        return self.body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object | None,
    ) -> None:
        return None


def test_migrate_updates_only_noncanonical_projects(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = load_migration_script()
    monkeypatch.setattr(module, "_PAGE_SIZE", 2)
    requests: list[Request] = []
    pages = {
        0: [
            {"id": "memory-1", "project": " /tmp/Chronos-Graph/ "},
            {"id": "memory-2", "project": "chronos-graph"},
        ],
        2: [{"id": "memory-3", "project": " /tmp/Other-Project/ "}],
    }

    def fake_urlopen(request: Request, timeout: float) -> FakeResponse:
        requests.append(request)
        if request.get_method() == "GET":
            query = parse_qs(urlparse(request.full_url).query)
            offset = int(query["offset"][0])
            assert query == {
                "select": ["id,project"],
                "order": ["id.asc"],
                "limit": ["2"],
                "offset": [str(offset)],
            }
            return FakeResponse(json.dumps(pages[offset]).encode())
        if "memory-3" in request.full_url:
            return FakeResponse(b"[]")
        return FakeResponse(b'[{"id":"memory-1","project":"chronos-graph"}]')

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "test-key")

    result = module.main()

    assert result == 0
    assert capsys.readouterr().out == "changed=1 unchanged=1\n"
    assert [request.get_method() for request in requests] == [
        "GET",
        "GET",
        "PATCH",
        "PATCH",
    ]
    assert requests[0].full_url == (
        "https://example.supabase.co/rest/v1/memories?"
        "select=id%2Cproject&order=id.asc&limit=2&offset=0"
    )
    assert requests[1].full_url == (
        "https://example.supabase.co/rest/v1/memories?"
        "select=id%2Cproject&order=id.asc&limit=2&offset=2"
    )
    assert requests[2].full_url == (
        "https://example.supabase.co/rest/v1/memories?"
        "id=eq.memory-1&project=eq.%20%2Ftmp%2FChronos-Graph%2F%20"
    )
    assert requests[3].full_url == (
        "https://example.supabase.co/rest/v1/memories?"
        "id=eq.memory-3&project=eq.%20%2Ftmp%2FOther-Project%2F%20"
    )
    assert json.loads(requests[2].data.decode()) == {"project": "chronos-graph"}
    assert json.loads(requests[3].data.decode()) == {"project": "other-project"}
    assert requests[2].get_header("Content-type") == "application/json"
    assert requests[2].get_header("Prefer") == "return=representation"


def test_update_project_uses_null_project_cas_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_migration_script()
    requests: list[Request] = []

    def fake_urlopen(request: Request, timeout: float) -> FakeResponse:
        requests.append(request)
        return FakeResponse(b"[]")

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)

    changed = module._update_project(
        "https://example.supabase.co", "test-key", "memory-null", None, "new-project"
    )

    assert changed == 0
    assert requests[0].full_url == (
        "https://example.supabase.co/rest/v1/memories?id=eq.memory-null&project=is.null"
    )
