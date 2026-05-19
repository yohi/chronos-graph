import pytest
from pydantic import ValidationError

from context_store.config import Settings


def _make_supabase_settings(**overrides):
    base = {
        "storage_backend": "supabase",
        "supabase_url": "https://example.supabase.co",
        "supabase_key": "test-service-role-key",
        "graph_enabled": False,
        "embedding_dimension": 768,
    }
    base.update(overrides)
    return Settings(**base)


def test_supabase_settings_valid_minimum():
    s = _make_supabase_settings()
    assert s.storage_backend == "supabase"
    assert s.supabase_url == "https://example.supabase.co"
    assert s.supabase_key.get_secret_value() == "test-service-role-key"


def test_supabase_requires_url():
    with pytest.raises(ValueError, match="SUPABASE_URL"):
        _make_supabase_settings(supabase_url="")


def test_supabase_requires_key():
    with pytest.raises(ValueError, match="SUPABASE_KEY"):
        _make_supabase_settings(supabase_key="")


def test_supabase_url_must_be_https():
    with pytest.raises(ValueError, match="https://"):
        _make_supabase_settings(supabase_url="http://example.supabase.co")


def test_supabase_rejects_graph_enabled():
    with pytest.raises(ValueError, match="graph_enabled=true"):
        _make_supabase_settings(graph_enabled=True)


def test_supabase_rejects_dimension_mismatch():
    with pytest.raises(ValueError, match="vector\\(768\\)"):
        _make_supabase_settings(embedding_dimension=1024)


def test_default_embedding_dimension_is_768():
    s = Settings(storage_backend="sqlite")
    assert s.embedding_dimension == 768


def test_graph_backend_for_supabase_is_disabled():
    s = _make_supabase_settings()
    assert s.graph_backend == "disabled"
