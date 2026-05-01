"""Unit tests for src/mcp_gateway/."""

from __future__ import annotations

import pytest
from pydantic import ValidationError


class TestErrors:
    def test_gateway_error_is_exception(self) -> None:
        from mcp_gateway.errors import GatewayError

        assert issubclass(GatewayError, Exception)

    def test_auth_error_inherits_gateway_error(self) -> None:
        from mcp_gateway.errors import AuthError, GatewayError

        assert issubclass(AuthError, GatewayError)

    def test_policy_error_inherits_gateway_error(self) -> None:
        from mcp_gateway.errors import GatewayError, PolicyError

        assert issubclass(PolicyError, GatewayError)

    def test_session_error_inherits_gateway_error(self) -> None:
        from mcp_gateway.errors import GatewayError, SessionError

        assert issubclass(SessionError, GatewayError)

    def test_upstream_error_inherits_gateway_error(self) -> None:
        from mcp_gateway.errors import GatewayError, UpstreamError

        assert issubclass(UpstreamError, GatewayError)


class TestSettings:
    def test_required_policy_path(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MCP_GATEWAY_POLICY_PATH", raising=False)
        from mcp_gateway.config import GatewaySettings

        with pytest.raises(ValidationError):
            GatewaySettings()

    def test_policy_path_must_exist(self, tmp_path, monkeypatch):
        non_existent = tmp_path / "missing.yaml"
        monkeypatch.setenv("MCP_GATEWAY_POLICY_PATH", str(non_existent))
        from mcp_gateway.config import GatewaySettings

        with pytest.raises(ValidationError) as excinfo:
            GatewaySettings()
        assert "policy_path が存在しません" in str(excinfo.value)

    def test_loads_from_env(self, tmp_path, monkeypatch):
        policy = tmp_path / "intents.yaml"
        policy.write_text("version: 1\noutput_filters: {}\nintents: {}\nagents: {}\n")
        monkeypatch.setenv("MCP_GATEWAY_POLICY_PATH", str(policy))
        monkeypatch.setenv("MCP_GATEWAY_HOST", "0.0.0.0")  # noqa: S104
        monkeypatch.setenv("MCP_GATEWAY_PORT", "9999")
        monkeypatch.setenv("MCP_GATEWAY_API_KEYS_JSON", '{"agent-a":"ck_xxx"}')

        from mcp_gateway.config import GatewaySettings

        s = GatewaySettings()
        assert s.host == "0.0.0.0"  # noqa: S104
        assert s.port == 9999
        assert s.policy_path == policy
        assert s.session_ttl_seconds == 900
        assert s.session_idle_timeout_seconds == 300
        assert s.upstream_command == ["python", "-m", "context_store"]

    def test_api_keys_secret_not_in_repr(self, tmp_path, monkeypatch):
        policy = tmp_path / "intents.yaml"
        policy.write_text("version: 1\noutput_filters: {}\nintents: {}\nagents: {}\n")
        monkeypatch.setenv("MCP_GATEWAY_POLICY_PATH", str(policy))
        monkeypatch.setenv("MCP_GATEWAY_API_KEYS_JSON", '{"agent-a":"ck_secret"}')

        from mcp_gateway.config import GatewaySettings

        s = GatewaySettings()
        assert "ck_secret" not in repr(s)

    def test_api_keys_masked_in_json_but_preserved_in_python(self, tmp_path, monkeypatch):
        policy = tmp_path / "intents.yaml"
        policy.write_text("version: 1\noutput_filters: {}\nintents: {}\nagents: {}\n")
        monkeypatch.setenv("MCP_GATEWAY_POLICY_PATH", str(policy))
        raw_key = '{"agent-a":"ck_secret"}'
        monkeypatch.setenv("MCP_GATEWAY_API_KEYS_JSON", raw_key)

        from mcp_gateway.config import GatewaySettings

        s = GatewaySettings()

        # JSON シリアライズ時はマスクされること (Issue 1)
        json_data = s.model_dump(mode="json")
        assert json_data["api_keys_json"] == "**********"
        assert "ck_secret" not in s.model_dump_json()

        # Python モード (default) では生値が保持されること (インライン指摘対応)
        # ※ SecretStr オブジェクト自体が返るため、get_secret_value() で確認
        python_data = s.model_dump()
        assert python_data["api_keys_json"].get_secret_value() == raw_key
