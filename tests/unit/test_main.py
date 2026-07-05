import anyio
import pytest


class FakeMcp:
    def __init__(self, calls: list[str]) -> None:
        self._calls: list[str] = calls

    def run(self, transport: str = "stdio", mount_path: str | None = None) -> None:
        _ = transport
        _ = mount_path
        self._calls.append("run")


class FakeServer:
    def __init__(self, calls: list[str]) -> None:
        self._calls: list[str] = calls

    async def startup(self) -> None:
        self._calls.append("startup")


def test_initialize_server_calls_global_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    import context_store.server as server_module

    calls: list[str] = []

    monkeypatch.setattr(server_module, "_server", FakeServer(calls))

    anyio.run(server_module.initialize_server)

    assert calls == ["startup"]


def test_main_initializes_before_running_mcp(monkeypatch: pytest.MonkeyPatch) -> None:
    import context_store.__main__ as entrypoint

    calls: list[str] = []

    async def fake_initialize_server() -> None:
        calls.append("initialize")

    monkeypatch.setattr(entrypoint, "initialize_server", fake_initialize_server)
    monkeypatch.setattr(entrypoint, "mcp", FakeMcp(calls))

    entrypoint.main()

    assert calls == ["initialize", "run"]


def test_main_does_not_run_mcp_after_startup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import context_store.__main__ as entrypoint

    async def fake_initialize_server() -> None:
        raise RuntimeError("storage unavailable")

    run_calls: list[str] = []

    monkeypatch.setattr(entrypoint, "initialize_server", fake_initialize_server)
    monkeypatch.setattr(entrypoint, "mcp", FakeMcp(run_calls))

    with pytest.raises(RuntimeError, match="storage unavailable"):
        entrypoint.main()

    assert run_calls == []
