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


class TestToolRegistry:
    def test_filter_by_caps_default_deny(self):
        from mcp_gateway.tools.registry import ToolRegistry

        reg = ToolRegistry(
            all_tools=[
                {"name": "memory_search", "description": "...", "inputSchema": {}},
                {"name": "memory_save", "description": "...", "inputSchema": {}},
                {"name": "memory_delete", "description": "...", "inputSchema": {}},
            ]
        )
        out = reg.filter_by_caps(caps=frozenset({"memory_search"}))
        names = [t["name"] for t in out]
        assert names == ["memory_search"]

    def test_filter_by_caps_empty_when_none_match(self):
        from mcp_gateway.tools.registry import ToolRegistry

        reg = ToolRegistry(all_tools=[{"name": "memory_search"}])
        assert reg.filter_by_caps(caps=frozenset()) == []

    def test_filter_preserves_order(self):
        from mcp_gateway.tools.registry import ToolRegistry

        reg = ToolRegistry(
            all_tools=[
                {"name": "a"},
                {"name": "b"},
                {"name": "c"},
            ]
        )
        out = reg.filter_by_caps(caps=frozenset({"a", "c"}))
        assert [t["name"] for t in out] == ["a", "c"]


class TestStructuralAllowlistFilter:
    def _filter(self):
        from mcp_gateway.filters.structural_allowlist import StructuralAllowlistFilter

        return StructuralAllowlistFilter(
            schemas={
                "memory_search": {
                    "results": ["id", "content"],
                    "total_count": True,
                },
            }
        )

    def test_strips_unlisted_top_level_fields(self):
        f = self._filter()
        out = f.apply(
            tool_name="memory_search",
            payload={"results": [], "total_count": 0, "secret": "x"},
        )
        assert out == {"results": [], "total_count": 0}

    def test_strips_unlisted_nested_fields(self):
        f = self._filter()
        out = f.apply(
            tool_name="memory_search",
            payload={
                "results": [
                    {
                        "id": "m1",
                        "content": "hello",
                        "embedding": [0.1, 0.2],
                        "internal_score": 0.9,
                    }
                ],
                "total_count": 1,
            },
        )
        assert out["results"][0] == {"id": "m1", "content": "hello"}
        assert out["total_count"] == 1

    def test_unknown_tool_returns_empty_payload(self):
        # スキーマがない=露出禁止
        f = self._filter()
        out = f.apply(tool_name="memory_save", payload={"x": 1})
        assert out == {}

    def test_denies_by_default_on_unknown_schema_value(self):
        from mcp_gateway.errors import PolicyError
        from mcp_gateway.filters.structural_allowlist import StructuralAllowlistFilter

        # invalid schema value: False (should be True or list[str])
        # Now raises PolicyError at construction time
        with pytest.raises(PolicyError, match="Invalid schema value"):
            StructuralAllowlistFilter(schemas={"t": {"secret": False}})  # type: ignore[arg-type]

    def test_preserves_none_value_if_allowed(self):
        from mcp_gateway.filters.structural_allowlist import StructuralAllowlistFilter

        f = StructuralAllowlistFilter(schemas={"t": {"nullable": True}})
        out = f.apply(tool_name="t", payload={"nullable": None})
        assert "nullable" in out
        assert out["nullable"] is None

    def test_raises_error_on_invalid_schema_type_at_init(self):
        from mcp_gateway.errors import PolicyError
        from mcp_gateway.filters.structural_allowlist import StructuralAllowlistFilter

        with pytest.raises(PolicyError, match="Invalid schema value for 'field'"):
            StructuralAllowlistFilter(schemas={"t": {"field": 123}})  # type: ignore[arg-type]

    def test_raises_policy_error_on_unsupported_schema_type(self):
        from mcp_gateway.errors import PolicyError
        from mcp_gateway.filters.structural_allowlist import StructuralAllowlistFilter

        # None is unsupported type for schema
        with pytest.raises(PolicyError, match="Invalid schema object type: NoneType"):
            StructuralAllowlistFilter(schemas={"t": None})  # type: ignore[arg-type]

    def test_rejects_non_dict_list_elements(self):
        """リスト内の非 dict 要素がドロップされることを確認 (Issue 1)"""
        from mcp_gateway.filters.structural_allowlist import StructuralAllowlistFilter

        f = StructuralAllowlistFilter(
            schemas={
                "memory_search": {
                    "results": ["id", "content"],
                    "total_count": True,
                },
            }
        )
        payload = {
            "results": ["bad_string", 123, {"id": "m1", "content": "ok", "secret": "x"}],
            "total_count": 1,
        }
        out = f.apply(tool_name="memory_search", payload=payload)

        # 非 dict 要素が削除され、正当な要素のみがフィルタリングされて残る
        assert out["results"] == [{"id": "m1", "content": "ok"}]
        assert out["total_count"] == 1


class TestNoneFilter:
    def test_passthrough(self):
        from mcp_gateway.filters.none_filter import NoneFilter

        f = NoneFilter()
        payload = {"a": 1, "b": [{"c": 2}]}
        assert f.apply(tool_name="any", payload=payload) == payload

    def test_returns_copy(self):
        from mcp_gateway.filters.none_filter import NoneFilter

        f = NoneFilter()
        payload = {"a": 1}
        out = f.apply(tool_name="any", payload=payload)
        assert out is not payload
        out["a"] = 2
        assert payload["a"] == 1

    def test_returns_deep_copy(self):
        from mcp_gateway.filters.none_filter import NoneFilter

        f = NoneFilter()
        payload = {"a": {"b": 1}}
        out = f.apply(tool_name="any", payload=payload)

        out["a"]["b"] = 2
        assert payload["a"]["b"] == 1, "Original payload should not be affected deep down"


class TestFilterFactory:
    def test_factory_builds_none(self):
        from mcp_gateway.filters.factory import build_filter
        from mcp_gateway.policy.models import OutputFilterDef

        f = build_filter(OutputFilterDef(type="none"))
        assert f.apply(tool_name="x", payload={"a": 1}) == {"a": 1}

    def test_factory_builds_structural_allowlist(self):
        from mcp_gateway.filters.factory import build_filter
        from mcp_gateway.policy.models import OutputFilterDef

        f = build_filter(
            OutputFilterDef(
                type="structural_allowlist",
                schemas={"t": {"id": True}},  # type: ignore[arg-type]
            )
        )
        out = f.apply(tool_name="t", payload={"id": 1, "x": 2})
        assert out == {"id": 1}


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
                "curate_memories": IntentPolicy(
                    description="y",
                    allowed_tools=["memory_save"],
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
        with pytest.raises(PolicyError, match="cannot use intent"):
            eng.evaluate_grant(agent_id="agent-a", intent="curate_memories", requested_tools=None)

    def test_unknown_intent_message_priority(self):
        # Even if the intent is not in agent.allowed_intents,
        # "unknown intent" should be raised first if the intent is not in the policy.
        from mcp_gateway.errors import PolicyError
        from mcp_gateway.policy.engine import PolicyEngine

        eng = PolicyEngine(self._policy())
        with pytest.raises(PolicyError, match="unknown intent"):
            eng.evaluate_grant(agent_id="agent-a", intent="ghost_intent", requested_tools=None)

    def test_requested_tools_outside_intent_narrowed(self):
        from mcp_gateway.policy.engine import PolicyEngine

        eng = PolicyEngine(self._policy())
        # intent 'read_only_recall' allows ["memory_search", "memory_stats"]
        # requesting "memory_save" (not allowed) and "memory_search" (allowed)
        grant = eng.evaluate_grant(
            agent_id="agent-a",
            intent="read_only_recall",
            requested_tools=frozenset({"memory_search", "memory_save"}),
        )
        assert grant.caps == frozenset({"memory_search"})
        assert "memory_save" not in grant.caps

    def test_evaluate_grant_empty_requested_tools_denied(self):
        from mcp_gateway.errors import PolicyError
        from mcp_gateway.policy.engine import PolicyEngine

        eng = PolicyEngine(self._policy())
        with pytest.raises(PolicyError, match="requested_tools must be None"):
            eng.evaluate_grant(
                agent_id="agent-a",
                intent="read_only_recall",
                requested_tools=frozenset(),
            )

    def test_evaluate_grant_normalizes_to_frozenset(self):
        from mcp_gateway.policy.engine import PolicyEngine

        eng = PolicyEngine(self._policy())
        # Pass a mutable set despite type hinting
        grant = eng.evaluate_grant(
            agent_id="agent-a",
            intent="read_only_recall",
            requested_tools={"memory_search"},  # type: ignore
        )
        assert isinstance(grant.caps, frozenset)
        assert grant.caps == frozenset({"memory_search"})

    def test_check_call_is_staticmethod(self):
        from mcp_gateway.policy.engine import PolicyEngine

        # インスタンス化せずにクラスから直接呼び出せることを確認
        PolicyEngine.check_call(caps=frozenset({"memory_search"}), tool_name="memory_search")

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


class TestHeaderParsing:
    def test_parse_bearer_token(self):
        from mcp_gateway.auth.headers import parse_bearer

        assert parse_bearer("Bearer ck_abc") == "ck_abc"

    def test_parse_bearer_case_insensitive_scheme(self):
        from mcp_gateway.auth.headers import parse_bearer

        assert parse_bearer("bearer ck_abc") == "ck_abc"

    def test_parse_bearer_missing_returns_none(self):
        from mcp_gateway.auth.headers import parse_bearer

        assert parse_bearer(None) is None
        assert parse_bearer("") is None
        assert parse_bearer("Basic xxx") is None

    def test_parse_intent(self):
        from mcp_gateway.auth.headers import parse_intent

        assert parse_intent("read_only_recall") == "read_only_recall"
        assert parse_intent("  read_only_recall  ") == "read_only_recall"
        assert parse_intent("") is None
        assert parse_intent(None) is None

    def test_parse_bearer_rejects_spaces_in_token(self):
        from mcp_gateway.auth.headers import parse_bearer

        assert parse_bearer("Bearer tok en") is None
        assert parse_bearer("Bearer token extra") is None

    def test_parse_bearer_rejects_malformed(self):
        from mcp_gateway.auth.headers import parse_bearer

        assert parse_bearer("Bearer") is None
        assert parse_bearer("Bearer  ") is None
        assert parse_bearer("Bearer token extra words") is None

    def test_parse_requested_tools(self):
        from mcp_gateway.auth.headers import parse_requested_tools

        assert parse_requested_tools("memory_search,memory_save") == frozenset(
            {"memory_search", "memory_save"}
        )
        assert parse_requested_tools("memory_search , memory_save ") == frozenset(
            {"memory_search", "memory_save"}
        )
        assert parse_requested_tools("memory_search,memory_search") == frozenset({"memory_search"})
        assert parse_requested_tools("") is None
        assert parse_requested_tools(None) is None


class TestApiKeyAuthenticator:
    def test_resolves_known_agent(self):
        from mcp_gateway.auth.api_key import ApiKeyAuthenticator

        a = ApiKeyAuthenticator({"summarizer-bot": "ck_xxx"})
        assert a.authenticate("ck_xxx") == "summarizer-bot"

    def test_unknown_key_raises_auth_error(self):
        from mcp_gateway.auth.api_key import ApiKeyAuthenticator
        from mcp_gateway.errors import AuthError

        a = ApiKeyAuthenticator({"summarizer-bot": "ck_xxx"})
        with pytest.raises(AuthError, match="unknown api key"):
            a.authenticate("ck_wrong")

    def test_empty_key_raises_auth_error(self):
        from mcp_gateway.auth.api_key import ApiKeyAuthenticator
        from mcp_gateway.errors import AuthError

        a = ApiKeyAuthenticator({"summarizer-bot": "ck_xxx"})
        with pytest.raises(AuthError, match="empty credential"):
            a.authenticate("")

    def test_authenticate_returns_identifier_for_matching_key(self):
        # Verify that ApiKeyAuthenticator returns the correct identifier for a matching key.
        from mcp_gateway.auth.api_key import ApiKeyAuthenticator

        a = ApiKeyAuthenticator({"x": "ck_aaa"})
        assert a.authenticate("ck_aaa") == "x"

    def test_duplicate_keys_raise_value_error(self):
        from mcp_gateway.auth.api_key import ApiKeyAuthenticator

        with pytest.raises(ValueError, match="Duplicate API key found"):
            ApiKeyAuthenticator({"agent1": "key1", "agent2": "key1"})


class TestSessionLifecycle:
    def _make_registry(self, ttl: int = 60, idle: int = 30):
        from mcp_gateway.auth.session import InMemorySessionRegistry

        return InMemorySessionRegistry(ttl_seconds=ttl, idle_timeout_seconds=idle)

    def test_create_and_lookup(self):
        from mcp_gateway.auth.session import SessionRecord

        reg = self._make_registry()
        rec = reg.create(
            agent_id="a",
            intent="read_only_recall",
            caps=frozenset({"memory_search"}),
            output_filter_profile="recall_safe",
        )
        assert isinstance(rec, SessionRecord)
        assert reg.lookup(rec.session_id) is rec

    def test_lookup_unknown_raises(self):
        from mcp_gateway.errors import SessionError

        reg = self._make_registry()
        with pytest.raises(SessionError):
            reg.lookup("nonexistent")

    def test_ttl_expiry(self, monkeypatch):
        from datetime import timedelta

        import mcp_gateway.auth.session as sess

        reg = self._make_registry(ttl=10)
        rec = reg.create(agent_id="a", intent="i", caps=frozenset(), output_filter_profile="none_f")
        future = rec.expires_at + timedelta(seconds=1)
        monkeypatch.setattr(sess, "_utcnow", lambda: future)
        from mcp_gateway.errors import SessionError

        with pytest.raises(SessionError):
            reg.lookup(rec.session_id)

    def test_idle_timeout(self, monkeypatch):
        from datetime import timedelta

        import mcp_gateway.auth.session as sess

        reg = self._make_registry(ttl=600, idle=5)
        rec = rec = reg.create(
            agent_id="a", intent="i", caps=frozenset(), output_filter_profile="none_f"
        )
        original = sess._utcnow()
        monkeypatch.setattr(sess, "_utcnow", lambda: original + timedelta(seconds=10))
        from mcp_gateway.errors import SessionError

        with pytest.raises(SessionError):
            reg.lookup(rec.session_id)

    def test_touch_resets_idle(self, monkeypatch):
        from datetime import timedelta

        import mcp_gateway.auth.session as sess

        reg = self._make_registry(ttl=600, idle=5)
        rec = reg.create(agent_id="a", intent="i", caps=frozenset(), output_filter_profile="none_f")
        original = sess._utcnow()
        monkeypatch.setattr(sess, "_utcnow", lambda: original + timedelta(seconds=3))
        reg.touch(rec.session_id)
        monkeypatch.setattr(sess, "_utcnow", lambda: original + timedelta(seconds=7))
        # 3秒時にtouch → 7秒時はtouchから4秒経過 → idle=5秒未満なので有効
        assert reg.lookup(rec.session_id).session_id == rec.session_id

    def test_remove(self):
        from mcp_gateway.errors import SessionError

        reg = self._make_registry()
        rec = reg.create(agent_id="a", intent="i", caps=frozenset(), output_filter_profile="none_f")
        reg.remove(rec.session_id)
        with pytest.raises(SessionError):
            reg.lookup(rec.session_id)

    def test_session_record_is_frozen(self):
        from dataclasses import FrozenInstanceError

        reg = self._make_registry()
        rec = reg.create(agent_id="a", intent="i", caps=frozenset(), output_filter_profile="none_f")
        with pytest.raises(FrozenInstanceError):
            rec.agent_id = "other"  # type: ignore[misc]
