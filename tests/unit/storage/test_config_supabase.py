import pytest

from context_store.config import Settings


def _make_supabase_settings(**overrides):
    base = {
        "storage_backend": "supabase",
        "supabase_url": "https://example.supabase.co",
        "supabase_key": "test-service-role-key",
        "graph_enabled": False,
        "embedding_dimension": 768,
        "_env_file": None,
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
    s = Settings(storage_backend="sqlite", _env_file=None)
    assert s.embedding_dimension == 768


def test_graph_backend_for_supabase_is_disabled():
    s = _make_supabase_settings()
    assert s.graph_backend == "disabled"


def test_supabase_request_timeout_default(monkeypatch):
    """Default request timeout should be 10.0 seconds."""
    monkeypatch.setenv("STORAGE_BACKEND", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "service-role-key")
    monkeypatch.setenv("EMBEDDING_DIMENSION", "768")
    monkeypatch.delenv("SUPABASE_REQUEST_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setenv("ENV_FILE", "/dev/null")

    from context_store.config import get_settings

    settings = get_settings()
    assert settings.supabase_request_timeout_seconds == 10.0


def test_supabase_request_timeout_env_override(monkeypatch):
    """SUPABASE_REQUEST_TIMEOUT_SECONDS should override the default."""
    monkeypatch.setenv("STORAGE_BACKEND", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "service-role-key")
    monkeypatch.setenv("EMBEDDING_DIMENSION", "768")
    monkeypatch.setenv("SUPABASE_REQUEST_TIMEOUT_SECONDS", "30")
    monkeypatch.setenv("ENV_FILE", "/dev/null")

    from context_store.config import get_settings

    settings = get_settings()
    assert settings.supabase_request_timeout_seconds == 30.0
