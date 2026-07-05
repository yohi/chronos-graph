from typing import cast
from unittest.mock import AsyncMock, MagicMock

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


@pytest.mark.anyio
async def test_server_startup_initializes_url_semaphore_and_logs_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import context_store.server as server_module

    server = server_module.ChronosServer()

    async def fake_do_initialize() -> None:
        orchestrator = MagicMock()
        orchestrator.start_lifecycle = AsyncMock(return_value=None)
        orchestrator.url_fetch_concurrency = 5
        object.__setattr__(server, "_orchestrator", orchestrator)

    monkeypatch.setattr(server, "_do_initialize", fake_do_initialize)

    with caplog.at_level("WARNING"):
        await server.startup()

    orchestrator = server._orchestrator
    assert orchestrator is not None
    assert server._initialized is True
    assert server._url_semaphore is not None
    cast(AsyncMock, orchestrator.start_lifecycle).assert_awaited_once()
    assert "現在のURLフェッチ制限はプロセススコープです。" in caplog.text
