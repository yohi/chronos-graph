from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
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
    """GET rows, PATCH changed projects, and report changed/unchanged counts."""
    module = load_migration_script()
    requests: list[Request] = []
    rows = [
        {"id": "memory-1", "project": " /tmp/Chronos-Graph/ "},
        {"id": "memory-2", "project": "chronos-graph"},
        {"id": "memory-3", "project": None},
    ]

    def fake_urlopen(request: Request, timeout: float) -> FakeResponse:
        requests.append(request)
        if request.get_method() == "GET":
            return FakeResponse(json.dumps(rows).encode())
        return FakeResponse(b"")

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "test-key")

    result = module.main()

    assert result == 0
    assert capsys.readouterr().out == "changed=1 unchanged=2\n"
    assert [request.get_method() for request in requests] == ["GET", "PATCH"]
    assert requests[0].full_url == "https://example.supabase.co/rest/v1/memories?select=id,project"
    assert requests[1].full_url == "https://example.supabase.co/rest/v1/memories?id=eq.memory-1"
    assert json.loads(requests[1].data.decode()) == {"project": "chronos-graph"}
    assert requests[1].get_header("Content-type") == "application/json"
