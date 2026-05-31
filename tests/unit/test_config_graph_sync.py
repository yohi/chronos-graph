"""Config: graph_sync_mode + outbox_* バリデーションテスト。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from context_store.config import Settings


def _make_settings(**overrides: object) -> Settings:
    """_env_file=None で Settings を生成するヘルパー。"""
    defaults: dict[str, object] = {
        "storage_backend": "sqlite",
        "graph_enabled": True,
        "neo4j_password": "secret",
        "embedding_provider": "local-model",
        "local_model_name": "cl-nagoya/ruri-v3-310m",
    }
    defaults.update(overrides)
    return Settings(_env_file=None, **defaults)  # type: ignore[call-arg]


def test_default_graph_sync_mode_is_sync() -> None:
    s = _make_settings()
    assert s.graph_sync_mode == "sync"


def test_async_outbox_requires_graph_enabled() -> None:
    with pytest.raises(ValidationError, match="graph_sync_mode='async_outbox' requires"):
        _make_settings(graph_enabled=False, graph_sync_mode="async_outbox")


def test_supabase_with_graph_requires_async_outbox() -> None:
    with pytest.raises(ValidationError, match="Supabase \\+ graph"):
        _make_settings(
            storage_backend="supabase",
            supabase_url="https://example.supabase.co",
            supabase_key="key",
            graph_enabled=True,
            neo4j_password="secret",
            graph_sync_mode="sync",
            embedding_dimension=768,
        )


def test_supabase_with_async_outbox_passes() -> None:
    s = _make_settings(
        storage_backend="supabase",
        supabase_url="https://example.supabase.co",
        supabase_key="key",
        graph_enabled=True,
        neo4j_password="secret",
        graph_sync_mode="async_outbox",
        embedding_dimension=768,
    )
    assert s.graph_sync_mode == "async_outbox"
    assert s.storage_backend == "supabase"


def test_outbox_defaults() -> None:
    s = _make_settings()
    assert s.outbox_poll_interval_seconds == 5.0
    assert s.outbox_batch_size == 100
    assert s.outbox_max_retries == 10
    assert s.outbox_backoff_base_seconds == 1.0
    assert s.outbox_backoff_max_seconds == 60.0
