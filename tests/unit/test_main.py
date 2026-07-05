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


def test_main_runs_mcp_without_preinitialization(monkeypatch: pytest.MonkeyPatch) -> None:
    import context_store.__main__ as entrypoint

    calls: list[str] = []
    monkeypatch.setattr(entrypoint, "mcp", FakeMcp(calls))

    entrypoint.main()

    assert calls == ["run"]


@pytest.mark.anyio
async def test_mcp_lifespan_initializes_server(monkeypatch: pytest.MonkeyPatch) -> None:
    import context_store.server as server_module

    calls: list[str] = []

    async def fake_startup() -> None:
        calls.append("startup")

    monkeypatch.setattr("context_store.server._server.startup", fake_startup)

    lifespan = server_module.mcp.settings.lifespan
    assert lifespan is not None

    async with lifespan(server_module.mcp):
        pass

    assert calls == ["startup"]


@pytest.mark.anyio
async def test_mcp_lifespan_propagates_startup_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    import context_store.server as server_module

    async def fake_startup() -> None:
        raise RuntimeError("storage unavailable")

    monkeypatch.setattr("context_store.server._server.startup", fake_startup)

    lifespan = server_module.mcp.settings.lifespan
    assert lifespan is not None

    with pytest.raises(RuntimeError, match="storage unavailable"):
        async with lifespan(server_module.mcp):
            pass
