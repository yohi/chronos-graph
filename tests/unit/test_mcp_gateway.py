"""Unit tests for src/mcp_gateway/."""

from __future__ import annotations

import textwrap

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

    def test_policy_path_must_be_file_not_dir(self, tmp_path, monkeypatch):
        a_dir = tmp_path / "subdir"
        a_dir.mkdir()
        monkeypatch.setenv("MCP_GATEWAY_POLICY_PATH", str(a_dir))
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


class TestPolicyLoader:
    def _write(self, tmp_path, body: str):
        p = tmp_path / "intents.yaml"
        p.write_text(textwrap.dedent(body).lstrip())
        return p

    def test_loads_minimal_policy(self, tmp_path):
        p = self._write(
            tmp_path,
            """
            version: 1
            output_filters:
              recall_safe:
                type: structural_allowlist
                schemas:
                  memory_search:
                    results: [id, content]
                    total_count: true
            intents:
              read_only_recall:
                description: "test"
                allowed_tools: [memory_search]
                output_filter: recall_safe
            agents:
              test-agent:
                allowed_intents: [read_only_recall]
            """,
        )

        from mcp_gateway.policy.loader import load_policy

        pol = load_policy(p)
        assert pol.version == 1
        assert "read_only_recall" in pol.intents
        assert pol.intents["read_only_recall"].allowed_tools == ["memory_search"]
        assert pol.agents["test-agent"].allowed_intents == ["read_only_recall"]

    def test_unknown_output_filter_reference_fails_fast(self, tmp_path):
        p = self._write(
            tmp_path,
            """
            version: 1
            output_filters: {}
            intents:
              read_only_recall:
                description: "test"
                allowed_tools: [memory_search]
                output_filter: nonexistent
            agents: {}
            """,
        )

        from mcp_gateway.errors import PolicyError
        from mcp_gateway.policy.loader import load_policy

        with pytest.raises(PolicyError):
            load_policy(p)

    def test_unknown_intent_reference_fails_fast(self, tmp_path):
        p = self._write(
            tmp_path,
            """
            version: 1
            output_filters:
              none_f:
                type: none
            intents:
              ok_intent:
                description: "x"
                allowed_tools: [memory_search]
                output_filter: none_f
            agents:
              bad-agent:
                allowed_intents: [ghost_intent]
            """,
        )

        from mcp_gateway.errors import PolicyError
        from mcp_gateway.policy.loader import load_policy

        with pytest.raises(PolicyError):
            load_policy(p)

    def test_invalid_encoding_fails_with_policy_error(self, tmp_path):
        # UTF-8 として不正なバイト列を書き込む
        p = tmp_path / "binary.yaml"
        p.write_bytes(b"\xff\xfe\xfd")

        from mcp_gateway.errors import PolicyError
        from mcp_gateway.policy.loader import load_policy

        with pytest.raises(PolicyError) as excinfo:
            load_policy(p)
        assert "failed to read policy file" in str(excinfo.value)

    def test_policy_file_size_limit(self, tmp_path, monkeypatch):
        # Issue 2: サイズ制限のチェック
        from mcp_gateway.policy import loader

        monkeypatch.setattr(loader, "_MAX_POLICY_FILE_SIZE", 10)
        p = tmp_path / "large.yaml"
        p.write_text("a" * 11)

        from mcp_gateway.errors import PolicyError
        from mcp_gateway.policy.loader import load_policy

        with pytest.raises(PolicyError) as excinfo:
            load_policy(p)
        assert "exceeds size limit" in str(excinfo.value)

    def test_schema_key_must_be_referenced_by_some_intent(self, tmp_path):
        # Issue 1: そのフィルターを使っているインテントがそのツールを許可している必要がある
        p = self._write(
            tmp_path,
            """
            version: 1
            output_filters:
              rs:
                type: structural_allowlist
                schemas:
                  other_tool:   # intent_a は memory_search しか持っていないのでエラーになるべき
                    results: [id]
              none_f:
                type: none
            intents:
              intent_a:
                description: "x"
                allowed_tools: [memory_search]
                output_filter: rs
              intent_b:
                description: "y"
                allowed_tools: [other_tool]
                output_filter: none_f
            agents: {}
            """,
        )

        from mcp_gateway.errors import PolicyError
        from mcp_gateway.policy.loader import load_policy

        with pytest.raises(PolicyError) as excinfo:
            load_policy(p)
        assert "is not referenced by any intent that uses this filter" in str(excinfo.value)

    def test_empty_allowed_tools_fails(self, tmp_path):
        # Issue 3: allowed_tools は空リストを許可しない
        p = self._write(
            tmp_path,
            """
            version: 1
            output_filters:
              default:
                type: none
            intents:
              empty_intent:
                description: "empty"
                allowed_tools: []
                output_filter: default
            agents: {}
            """,
        )

        from mcp_gateway.errors import PolicyError
        from mcp_gateway.policy.loader import load_policy

        with pytest.raises(PolicyError) as excinfo:
            load_policy(p)
        assert "List should have at least 1 item" in str(excinfo.value)


class TestPolicyEngine:
    def _policy(self):
        from mcp_gateway.policy.models import (
            AgentPolicy,
            GatewayPolicy,
            IntentPolicy,
            OutputFilterDef,
        )

        return GatewayPolicy(
            version=1,
            output_filters={
                "rs": OutputFilterDef(type="none"),
            },
            intents={
                "read_only_recall": IntentPolicy(
                    description="x",
                    allowed_tools=["memory_search", "memory_stats"],
                    output_filter="rs",
                ),
            },
            agents={
                "agent-a": AgentPolicy(allowed_intents=["read_only_recall"]),
            },
        )

    def test_evaluate_grant_allows_subset(self):
        from mcp_gateway.policy.engine import PolicyEngine

        eng = PolicyEngine(self._policy())
        grant = eng.evaluate_grant(
            agent_id="agent-a",
            intent="read_only_recall",
            requested_tools=frozenset({"memory_search"}),
        )
        assert grant.caps == frozenset({"memory_search"})
        assert grant.output_filter_profile == "rs"

    def test_evaluate_grant_full_when_no_request(self):
        from mcp_gateway.policy.engine import PolicyEngine

        eng = PolicyEngine(self._policy())
        grant = eng.evaluate_grant(
            agent_id="agent-a", intent="read_only_recall", requested_tools=None
        )
        assert grant.caps == frozenset({"memory_search", "memory_stats"})

    def test_unknown_agent_denied(self):
        from mcp_gateway.errors import PolicyError
        from mcp_gateway.policy.engine import PolicyEngine

        eng = PolicyEngine(self._policy())
        with pytest.raises(PolicyError):
            eng.evaluate_grant(agent_id="ghost", intent="read_only_recall", requested_tools=None)

    def test_intent_not_allowed_for_agent_denied(self):
        from mcp_gateway.errors import PolicyError
        from mcp_gateway.policy.engine import PolicyEngine

        eng = PolicyEngine(self._policy())
        with pytest.raises(PolicyError):
            eng.evaluate_grant(agent_id="agent-a", intent="curate_memories", requested_tools=None)

    def test_requested_tools_outside_intent_denied(self):
        from mcp_gateway.errors import PolicyError
        from mcp_gateway.policy.engine import PolicyEngine

        eng = PolicyEngine(self._policy())
        with pytest.raises(PolicyError):
            eng.evaluate_grant(
                agent_id="agent-a",
                intent="read_only_recall",
                requested_tools=frozenset({"memory_save"}),
            )

    def test_check_call_allows_in_caps(self):
        from mcp_gateway.policy.engine import PolicyEngine

        eng = PolicyEngine(self._policy())
        eng.check_call(caps=frozenset({"memory_search"}), tool_name="memory_search")

    def test_check_call_denies_outside_caps(self):
        from mcp_gateway.errors import PolicyError
        from mcp_gateway.policy.engine import PolicyEngine

        eng = PolicyEngine(self._policy())
        with pytest.raises(PolicyError):
            eng.check_call(caps=frozenset({"memory_search"}), tool_name="memory_save")
