"""共通テスト fixture。

ルートレベルの conftest.py は全テスト（unit / integration）から参照できる共有 fixture を定義する。
"""
from __future__ import annotations

import pytest


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"
