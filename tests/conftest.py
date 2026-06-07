"""共通テスト fixture。

ルートレベルの conftest.py は全テスト（unit / integration）から参照できる共有 fixture を定義する。
"""

from __future__ import annotations

import logging
import os
import random
import re
import socket
import urllib.error
import urllib.request
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from context_store.embedding.protocols import EmbeddingProvider


def make_mock_embedding_provider(dim: int = 16) -> EmbeddingProvider:
    """固定ベクトルを返すモック EmbeddingProvider を作成する。"""

    class MockEmbeddingProvider:
        @property
        def dimension(self) -> int:
            return dim

        async def embed(self, text: str) -> list[float]:
            import hashlib

            # テキストのハッシュに基づいた決定論的なベクトルを返す（hash() ではなく hashlib を使用）
            h = hashlib.sha256(text.encode("utf-8")).digest()
            seed = int.from_bytes(h[:4], "little") % (2**31)
            rng = random.Random(seed)  # noqa: S311
            return [rng.uniform(-1, 1) for _ in range(dim)]

        async def embed_batch(self, texts: list[str]) -> list[list[float]]:
            return [await self.embed(t) for t in texts]

        async def close(self) -> None:
            pass

    return MockEmbeddingProvider()  # type: ignore[return-value]


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session")
def sandbox_profile() -> str:
    """OpenSandbox プロファイル名を返す session-scope fixture。"""
    return "lite"


@pytest.fixture(scope="session")
def sandbox_api_base() -> str:
    """OpenSandbox API のベース URL を返す session-scope fixture。"""
    return "http://localhost:8090"


@pytest.fixture(scope="session")
def sandbox_container(sandbox_profile: str, sandbox_api_base: str) -> dict[str, str] | None:
    """OpenSandbox コンテナのライフサイクルを管理する session-scope fixture。

    OpenSandbox サーバーが localhost:8090 で起動している場合、テストセッション開始時に
    コンテナを起動し、テストセッション終了時に停止・削除する。
    """
    # サーバーが起動しているか確認
    try:
        req = urllib.request.Request(  # noqa: S310
            f"{sandbox_api_base}/health", method="GET"
        )
        with urllib.request.urlopen(req, timeout=2) as resp:  # noqa: S310
            if resp.status == 200:
                return {"profile": sandbox_profile, "api_base": sandbox_api_base}
    except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
        logging.debug(
            "OpenSandbox health check failed, assuming server not running: %s",
            e,
        )

    # サーバーが起動していない場合は skip
    pytest.skip("OpenSandbox server is not running; skip sandbox integration tests")


@pytest.fixture
def mock_sandbox_api(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[dict]]:
    """OpenSandbox API 呼び出しを記録するモック fixture。

    Returns:
        呼び出し履歴を保持する dict。キー 'calls' にリクエスト dict のリストが入る。
    """
    calls: list[dict] = []

    def mock_urlopen(req, *args, **kwargs):
        calls.append(
            {
                "url": req.full_url if hasattr(req, "full_url") else str(req),
                "method": req.get_method() if hasattr(req, "get_method") else "GET",
                "headers": dict(req.headers) if hasattr(req, "headers") else {},
            }
        )

        # 空のレスポンスを返す
        class FakeResponse:
            def read(self):
                return b"{}"

            @property
            def status(self):
                return 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)
    return {"calls": calls}


@pytest.fixture(scope="session")
def sandbox_egress_allowlist(sandbox_profile: str) -> list[str]:
    """OpenSandbox プロファイルの egress 許可リストを返す session-scope fixture。"""
    import yaml

    config_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        ".devcontainer",
        "opensandbox",
        "sandbox.yaml",
    )
    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    profiles = config.get("profiles", {})
    profile = profiles.get(sandbox_profile, {})
    allowlist = list(profile.get("egress", {}).get("allow", []))

    parent = profile.get("extends")
    if parent:
        parent_profile = profiles.get(parent, {})
        allowlist = [
            *parent_profile.get("egress", {}).get("allow", []),
            *allowlist,
        ]

    return [_expand_env_default(host) for host in allowlist]


def _expand_env_default(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        name, default = match.groups()
        return os.environ.get(name, default)

    return re.sub(r"\$\{([^:}]+):-([^}]+)\}", replace, value)


@pytest.fixture
def sandbox_aware_sqlite_env() -> None:
    return None


@pytest.fixture(scope="session")
def sandbox_resource_limits(sandbox_profile: str) -> dict[str, str]:
    """OpenSandbox プロファイルのリソース制限を返す session-scope fixture。"""
    if sandbox_profile == "lite":
        return {"cpu": "2", "memory": "2Gi"}
    return {}


@pytest.fixture(autouse=True)
def _sandbox_aware_sqlite(tmp_path, monkeypatch, sandbox_aware_sqlite_env):
    """OpenSandbox 内で実行される場合、SQLite DB パスを一時ディレクトリに切り替える。

    OPENSANDBOX=1 の場合のみ発火し、ホスト環境の既存 DB ファイルを汚染しない。
    """
    if os.environ.get("OPENSANDBOX") == "1":
        monkeypatch.setenv("SQLITE_DB_PATH", str(tmp_path / "test.db"))
        monkeypatch.setenv("SQLITE_GRAPH_PATH", str(tmp_path / "test_graph.db"))
