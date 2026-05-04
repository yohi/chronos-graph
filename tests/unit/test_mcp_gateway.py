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


class TestAuditLogger:
    def test_writes_jsonl_to_stderr(self, capsys):
        from mcp_gateway.audit.logger import AuditLogger

        log = AuditLogger()
        log.log(ev="handshake", agent="a", intent="i", decision="allow", sid="s1")
        captured = capsys.readouterr()
        # stdout は汚染しない
        assert captured.out == ""
        # stderr は1行 JSON
        line = captured.err.strip()
        import json

        rec = json.loads(line)
        assert rec["ev"] == "handshake"
        assert rec["level"] == "INFO"
        assert rec["agent"] == "a"
        assert rec["intent"] == "i"
        assert rec["decision"] == "allow"
        assert rec["sid"] == "s1"
        assert "ts" in rec
        # タイムスタンプの精度 (マイクロ秒を含む ISO 8601 形式: YYYY-MM-DDTHH:MM:SS.mmmmmmZ)
        assert rec["ts"].endswith("Z")
        assert "." in rec["ts"]

    def test_audit_log_level_filtering(self, capsys):
        from mcp_gateway.audit.logger import AuditLogger

        # INFO レベル設定
        log = AuditLogger(level="INFO")
        log.log(ev="info_event", level="INFO")
        log.log(ev="debug_event", level="DEBUG")
        captured = capsys.readouterr()
        assert "info_event" in captured.err
        assert "debug_event" not in captured.err

        # DEBUG レベル設定
        log.set_level("DEBUG")
        log.log(ev="debug_event_2", level="DEBUG")
        captured = capsys.readouterr()
        assert "debug_event_2" in captured.err

    def test_does_not_emit_secrets(self, capsys):
        from mcp_gateway.audit.logger import AuditLogger

        log = AuditLogger()
        # シークレットがマスクされることを検証
        log.log(
            ev="call",
            agent="a",
            api_key="sk-hidden",
            ck_token="secret",
            normal_field="visible",
        )
        captured = capsys.readouterr()
        assert "sk-hidden" not in captured.err
        assert "secret" not in captured.err
        assert "**********" in captured.err
        assert "visible" in captured.err

    def test_prevents_reserved_key_overwrite(self, capsys):
        from mcp_gateway.audit.logger import AuditLogger

        log = AuditLogger()
        import pytest

        with pytest.raises(ValueError) as excinfo:
            log.log(ev="test", ts="2000-01-01T00:00:00Z")
        assert "reserved audit field(s): ts" in str(excinfo.value)

    def test_expanded_sensitive_field_masking(self, capsys):
        from mcp_gateway.audit.logger import AuditLogger

        log = AuditLogger()
        log.log(
            ev="auth",
            token="secret-token",
            secret="my-secret",
            authorization="Bearer token",
            PASSWORD="should-be-masked",
        )
        captured = capsys.readouterr()
        import json

        rec = json.loads(captured.err)
        assert rec["token"] == "**********"
        assert rec["secret"] == "**********"
        assert rec["authorization"] == "**********"
        assert rec["PASSWORD"] == "**********"

    def test_audit_log_value_redaction(self, capsys):
        from mcp_gateway.audit.logger import AuditLogger

        log = AuditLogger()
        # 値の中に機密パターンが含まれる場合にマスクされることを検証
        log.log(
            ev="error_event",
            error="Failed with Authorization: Bearer secret-token-123",
            message="Internal error: sk-987654321",
            details="long-hex-value: 1234567890abcdef1234567890abcdef",
            normal_field="this is a safe message",
        )
        captured = capsys.readouterr()
        import json

        rec = json.loads(captured.err)
        assert rec["error"] == "**********"
        assert rec["message"] == "**********"
        assert rec["details"] == "**********"
        assert rec["normal_field"] == "this is a safe message"
        # 生のシークレットが露出していないことを念のため確認
        assert "secret-token-123" not in captured.err
        assert "sk-987654321" not in captured.err
        assert "1234567890abcdef1234567890abcdef" not in captured.err

    def test_recursive_sensitive_field_masking(self, capsys):
        from mcp_gateway.audit.logger import AuditLogger

        log = AuditLogger()
        # ネストした構造のサニタイズを検証
        log.log(
            ev="nested_test",
            details={
                "authorization": "Bearer secret-token",
                "meta": ["sk-api-key", "safe-value"],
                "nested": {
                    "password": "hidden-password",
                    "id": "1234567890abcdef1234567890abcdef",  # 値の内容によるマスク
                },
            },
            tags=["normal", "sk-another-key"],
        )
        captured = capsys.readouterr()
        import json

        rec = json.loads(captured.err)
        # 辞書内のキー名によるマスク
        assert rec["details"]["authorization"] == "**********"
        assert rec["details"]["nested"]["password"] == "**********"
        # リスト内の値の内容によるマスク
        assert rec["details"]["meta"][0] == "**********"
        assert rec["details"]["meta"][1] == "safe-value"
        # 辞書内の値の内容によるマスク
        assert rec["details"]["nested"]["id"] == "**********"
        # トップレベルのリスト内の値の内容によるマスク
        assert rec["tags"][0] == "normal"
        assert rec["tags"][1] == "**********"

    def test_level_validation(self):
        from mcp_gateway.audit.logger import AuditLogger

        # Valid levels should pass
        AuditLogger(level="INFO")
        AuditLogger(level="DEBUG")
        AuditLogger(level="ERROR")

        # Invalid level in init should raise ValueError
        with pytest.raises(ValueError) as excinfo:
            AuditLogger(level="INVALID")
        assert "Invalid log level: INVALID" in str(excinfo.value)

        # Invalid level in set_level should raise ValueError
        logger = AuditLogger()
        with pytest.raises(ValueError) as excinfo:
            logger.set_level("FATAL")
        assert "Invalid log level: FATAL" in str(excinfo.value)

        # Invalid level in log should raise ValueError
        with pytest.raises(ValueError) as excinfo:
            logger.log(ev="test", level="WARN")  # type: ignore[arg-type]
        assert "Invalid log level: WARN" in str(excinfo.value)

    def test_token_variants_not_masked(self, capsys):
        from mcp_gateway.audit.logger import AuditLogger

        log = AuditLogger()
        log.log(
            ev="token_stats",
            token_count=100,
            total_tokens=500,
            token="secret-token",
        )
        captured = capsys.readouterr()
        import json

        rec = json.loads(captured.err)
        # 完全一致の token はマスクされるが、token_count などは維持されるべき
        assert rec["token"] == "**********"
        assert rec["token_count"] == 100
        assert rec["total_tokens"] == 500

    def test_error_level_always_emitted(self, capsys):
        from mcp_gateway.audit.logger import AuditLogger

        # ERROR レベル設定のロガー
        log = AuditLogger(level="ERROR")
        log.log(ev="info_ev", level="INFO")
        log.log(ev="error_ev", level="ERROR")
        captured = capsys.readouterr()
        assert "info_ev" not in captured.err
        assert "error_ev" in captured.err

    def test_startup_failure_log_content(self, capsys):
        import traceback

        from mcp_gateway.audit.logger import AuditLogger

        log = AuditLogger()
        try:
            raise RuntimeError("test failure")
        except Exception as e:
            log.log(
                ev="startup_failure",
                level="ERROR",
                error_type=e.__class__.__name__,
                error=str(e),
                stacktrace=traceback.format_exc(),
            )

        captured = capsys.readouterr()
        import json

        rec = json.loads(captured.err)
        assert rec["ev"] == "startup_failure"
        assert rec["level"] == "ERROR"
        assert rec["error_type"] == "RuntimeError"
        assert rec["error"] == "test failure"
        assert "traceback" in rec["stacktrace"].lower()

    def test_handles_non_serializable_types(self, capsys):
        from datetime import datetime

        from mcp_gateway.audit.logger import AuditLogger

        log = AuditLogger()

        class Custom:
            def __str__(self):
                return "custom-data"

        class SensitiveCustom:
            def __str__(self):
                return "sk-sensitive-data"

        now = datetime.now()
        log.log(
            ev="type_test",
            dt=now,
            obj=Custom(),
            secret_obj=SensitiveCustom(),
        )

        captured = capsys.readouterr()
        import json

        rec = json.loads(captured.err)
        assert rec["dt"] == str(now)
        assert rec["obj"] == "custom-data"
        assert rec["secret_obj"] == "**********"


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

    def test_defensive_copying(self):
        from mcp_gateway.tools.registry import ToolRegistry

        tools = [{"name": "tool1", "description": "desc1"}]
        registry = ToolRegistry(tools)

        # Verify __init__ deepcopies
        tools[0]["description"] = "modified"
        assert registry.all_tools[0]["description"] == "desc1"

        # Verify all_tools property deepcopies
        retrieved = registry.all_tools
        retrieved[0]["description"] = "modified again"
        assert registry.all_tools[0]["description"] == "desc1"

        # Verify filter_by_caps deepcopies
        filtered = registry.filter_by_caps(caps=frozenset(["tool1"]))
        filtered[0]["description"] = "modified filtered"
        assert registry.all_tools[0]["description"] == "desc1"


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

    def test_raises_error_on_non_string_list_elements_at_init(self):
        from mcp_gateway.errors import PolicyError
        from mcp_gateway.filters.structural_allowlist import StructuralAllowlistFilter

        # List with non-string elements should raise PolicyError
        with pytest.raises(
            PolicyError,
            match="Invalid schema: all elements in list for 'field1' in 'tool1' must be strings",
        ):
            StructuralAllowlistFilter({"tool1": {"field1": ["a", 1]}})

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

    def test_empty_intersection_denied(self):
        from mcp_gateway.errors import PolicyError
        from mcp_gateway.policy.engine import PolicyEngine

        eng = PolicyEngine(self._policy())
        # intent 'read_only_recall' allows ['memory_search', 'memory_stats']
        # requesting 'memory_save' results in an empty intersection
        with pytest.raises(PolicyError) as excinfo:
            eng.evaluate_grant(
                agent_id="agent-a",
                intent="read_only_recall",
                requested_tools=frozenset({"memory_save"}),
            )
        assert "none of the requested tools are allowed" in str(excinfo.value)

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

    def test_empty_keys_raise_value_error(self):
        from mcp_gateway.auth.api_key import ApiKeyAuthenticator

        # Should raise ValueError for empty key
        with pytest.raises(ValueError, match="Empty API key for agent: agent-empty"):
            ApiKeyAuthenticator({"agent-empty": ""})

        # Should raise ValueError for whitespace key
        with pytest.raises(ValueError, match="Empty API key for agent: agent-space"):
            ApiKeyAuthenticator({"agent-space": "   "})

    def test_invalid_agent_id_fails(self):
        from mcp_gateway.auth.api_key import ApiKeyAuthenticator

        with pytest.raises(ValueError, match="Invalid agent_id"):
            ApiKeyAuthenticator({"": "key1"})  # type: ignore[dict-item]
        with pytest.raises(ValueError, match="Invalid agent_id"):
            ApiKeyAuthenticator({None: "key1"})  # type: ignore[dict-item]

    def test_invalid_credential_type_fails(self):
        from mcp_gateway.auth.api_key import ApiKeyAuthenticator
        from mcp_gateway.errors import AuthError

        a = ApiKeyAuthenticator({"a": "k"})
        with pytest.raises(AuthError, match="invalid credential type"):
            a.authenticate(None)  # type: ignore[arg-type]


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
        rec = reg.create(agent_id="a", intent="i", caps=frozenset(), output_filter_profile="none_f")
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


class TestHandshake:
    def _stack(self):
        from mcp_gateway.auth.api_key import ApiKeyAuthenticator
        from mcp_gateway.auth.handshake import HandshakeService
        from mcp_gateway.auth.session import InMemorySessionRegistry
        from mcp_gateway.policy.engine import PolicyEngine
        from mcp_gateway.policy.models import (
            AgentPolicy,
            GatewayPolicy,
            IntentPolicy,
            OutputFilterDef,
        )

        policy = GatewayPolicy(
            version=1,
            output_filters={"rs": OutputFilterDef(type="none")},
            intents={
                "ro": IntentPolicy(
                    description="x", allowed_tools=["memory_search"], output_filter="rs"
                )
            },
            agents={"agent-a": AgentPolicy(allowed_intents=["ro"])},
        )
        return HandshakeService(
            authenticator=ApiKeyAuthenticator({"agent-a": "ck_x"}),
            policy_engine=PolicyEngine(policy),
            session_registry=InMemorySessionRegistry(ttl_seconds=60, idle_timeout_seconds=30),
        )

    def test_happy_path(self):
        svc = self._stack()
        rec = svc.handshake(
            authorization_header="Bearer ck_x",
            intent_header="ro",
            requested_tools_header=None,
        )
        assert rec.agent_id == "agent-a"
        assert rec.intent == "ro"
        assert rec.caps == frozenset({"memory_search"})
        assert rec.output_filter_profile == "rs"

    def test_missing_intent_denied(self):
        from mcp_gateway.errors import PolicyError

        svc = self._stack()
        with pytest.raises(PolicyError):
            svc.handshake(
                authorization_header="Bearer ck_x",
                intent_header=None,
                requested_tools_header=None,
            )

    def test_bad_token_denied(self):
        from mcp_gateway.errors import AuthError

        svc = self._stack()
        with pytest.raises(AuthError):
            svc.handshake(
                authorization_header="Bearer wrong",
                intent_header="ro",
                requested_tools_header=None,
            )

    def test_requested_tools_intersection(self):
        svc = self._stack()
        rec = svc.handshake(
            authorization_header="Bearer ck_x",
            intent_header="ro",
            requested_tools_header="memory_search",
        )
        assert rec.caps == frozenset({"memory_search"})


class TestUpstreamClient:
    def test_build_env_passthrough_allowlist_only(self):
        from mcp_gateway.upstream.context_store_client import build_upstream_env

        env = build_upstream_env(
            passthrough=["OPENAI_API_KEY", "CONTEXT_STORE_DB_PATH"],
            base_env={
                "OPENAI_API_KEY": "sk-allowed",
                "AWS_SECRET_ACCESS_KEY": "should-not-leak",
                "CONTEXT_STORE_DB_PATH": "/tmp/x",  # noqa: S108
                "PATH": "/usr/bin",
            },
        )
        assert env.get("OPENAI_API_KEY") == "sk-allowed"
        assert env.get("CONTEXT_STORE_DB_PATH") == "/tmp/x"  # noqa: S108
        assert "AWS_SECRET_ACCESS_KEY" not in env
        # PATH は明示的に含める(allowlist と別軸でユーティリティで継承)
        assert "PATH" in env

    @pytest.mark.asyncio
    async def test_call_tool_delegates_to_session(self):
        from unittest.mock import AsyncMock

        from mcp_gateway.upstream.context_store_client import UpstreamClient

        fake_session = AsyncMock()
        fake_session.list_tools.return_value = type(
            "R", (), {"tools": [type("T", (), {"model_dump": lambda self: {"name": "t"}})()]}
        )()
        fake_session.call_tool.return_value = type(
            "R", (), {"content": [{"type": "text", "text": '{"a":1}'}], "isError": False}
        )()
        client = UpstreamClient.__new__(UpstreamClient)  # type: ignore[call-arg]
        client._session = fake_session  # type: ignore[attr-defined]
        client._tools_cache = None  # type: ignore[attr-defined]

        tools = await client.list_tools()
        assert tools == [{"name": "t"}]

        payload = await client.call_tool("t", {"q": 1})
        assert payload == {"a": 1}
        fake_session.call_tool.assert_awaited_once_with("t", {"q": 1})

    @pytest.mark.asyncio
    async def test_call_tool_wraps_non_dict_json_payload(self):
        from unittest.mock import AsyncMock

        from mcp_gateway.upstream.context_store_client import UpstreamClient

        fake_session = AsyncMock()
        fake_session.call_tool.return_value = type(
            "R", (), {"content": [{"type": "text", "text": '[{"id": 1}]'}], "isError": False}
        )()

        client = UpstreamClient.__new__(UpstreamClient)  # type: ignore[call-arg]
        client._session = fake_session  # type: ignore[attr-defined]

        payload = await client.call_tool("t", {})

        assert payload == {"result": [{"id": 1}]}

    @pytest.mark.asyncio
    async def test_stop_clears_tools_cache(self):
        from unittest.mock import AsyncMock

        from mcp_gateway.upstream.context_store_client import UpstreamClient

        client = UpstreamClient.__new__(UpstreamClient)  # type: ignore[call-arg]
        client._session = AsyncMock()  # type: ignore[attr-defined]
        client._stdio_ctx = AsyncMock()  # type: ignore[attr-defined]
        client._tools_cache = [{"name": "stale"}]  # type: ignore[attr-defined]

        await client.stop()

        assert client._tools_cache is None

    @pytest.mark.asyncio
    async def test_start_rolls_back_stdio_when_initialize_fails(self, monkeypatch):
        from mcp_gateway.upstream import context_store_client as module

        events: list[str] = []

        class FakeStdioCtx:
            async def __aenter__(self):
                events.append("stdio-enter")
                return object(), object()

            async def __aexit__(self, exc_type, exc, tb):
                events.append("stdio-exit")

        class FakeSession:
            def __init__(self, read, write):
                self.read = read
                self.write = write

            async def __aenter__(self):
                events.append("session-enter")
                return self

            async def __aexit__(self, exc_type, exc, tb):
                events.append("session-exit")

            async def initialize(self):
                events.append("initialize")
                raise RuntimeError("boom")

        monkeypatch.setattr(module, "stdio_client", lambda params: FakeStdioCtx())
        monkeypatch.setattr(module, "ClientSession", FakeSession)

        client = module.UpstreamClient(command=["context-store"], env={})

        with pytest.raises(RuntimeError, match="boom"):
            await client.start()

        assert events == [
            "stdio-enter",
            "session-enter",
            "initialize",
            "session-exit",
            "stdio-exit",
        ]
        assert client._session is None
        assert client._stdio_ctx is None


class TestToolProxy:
    @pytest.mark.asyncio
    async def test_call_through_applies_filter(self):
        from unittest.mock import AsyncMock

        from mcp_gateway.filters.structural_allowlist import StructuralAllowlistFilter
        from mcp_gateway.tools.proxy import ToolProxy

        upstream = AsyncMock()
        upstream.call_tool.return_value = {
            "results": [
                {
                    "id": "m1",
                    "content": "hello",
                    "embedding": [0.1],
                    "internal_score": 0.9,
                }
            ],
            "total_count": 1,
        }
        filt = StructuralAllowlistFilter(
            schemas={"memory_search": {"results": ["id", "content"], "total_count": True}}
        )
        proxy = ToolProxy(upstream=upstream, filter_=filt)

        out = await proxy.call_through(tool_name="memory_search", arguments={"query": "hi"})
        assert out["results"][0] == {"id": "m1", "content": "hello"}
        assert "embedding" not in out["results"][0]
        assert out["total_count"] == 1

    @pytest.mark.asyncio
    async def test_call_through_rejects_secret_like_arguments(self):
        from unittest.mock import AsyncMock

        from mcp_gateway.errors import PolicyError
        from mcp_gateway.filters.none_filter import NoneFilter
        from mcp_gateway.tools.proxy import ToolProxy

        upstream = AsyncMock()
        proxy = ToolProxy(upstream=upstream, filter_=NoneFilter())
        with pytest.raises(PolicyError, match="arguments contain secret-like content"):
            await proxy.call_through(
                tool_name="t",
                arguments={"q": "use sk-1234567890abcdef as a key"},
            )
        upstream.call_tool.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_call_through_rejects_secret_in_dict_keys(self):
        from unittest.mock import AsyncMock

        from mcp_gateway.errors import PolicyError
        from mcp_gateway.filters.none_filter import NoneFilter
        from mcp_gateway.tools.proxy import ToolProxy

        upstream = AsyncMock()
        proxy = ToolProxy(upstream=upstream, filter_=NoneFilter())
        with pytest.raises(PolicyError, match="arguments contain secret-like content"):
            await proxy.call_through(
                tool_name="t",
                arguments={"sk-1234567890abcdef": "some_value"},
            )
        upstream.call_tool.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_call_through_rejects_secret_in_upstream_response(self):
        from unittest.mock import AsyncMock

        from mcp_gateway.errors import PolicyError
        from mcp_gateway.filters.none_filter import NoneFilter
        from mcp_gateway.tools.proxy import ToolProxy

        upstream = AsyncMock()
        upstream.call_tool.return_value = {"output": "here is a secret: sk-1234567890abcdef"}
        proxy = ToolProxy(upstream=upstream, filter_=NoneFilter())
        with pytest.raises(PolicyError, match="upstream response contains secret-like content"):
            await proxy.call_through(tool_name="t", arguments={"q": "safe query"})

    @pytest.mark.asyncio
    async def test_call_through_rejects_aws_asia_prefix(self):
        from unittest.mock import AsyncMock

        from mcp_gateway.errors import PolicyError
        from mcp_gateway.filters.none_filter import NoneFilter
        from mcp_gateway.tools.proxy import ToolProxy

        upstream = AsyncMock()
        proxy = ToolProxy(upstream=upstream, filter_=NoneFilter())
        with pytest.raises(PolicyError, match="arguments contain secret-like content"):
            await proxy.call_through(
                tool_name="t",
                arguments={"key": "ASIA1234567890ABCDEF"},
            )
        upstream.call_tool.assert_not_awaited()


@pytest.fixture
def gateway_app(tmp_path, monkeypatch):
    """Boot the FastAPI app with a mocked upstream and a sample policy."""
    policy = tmp_path / "intents.yaml"
    policy.write_text(
        textwrap.dedent(
            """
            version: 1
            output_filters:
              rs:
                type: structural_allowlist
                schemas:
                  memory_search:
                    results: [id, content]
                    total_count: true
            intents:
              ro:
                description: "x"
                allowed_tools: [memory_search]
                output_filter: rs
            agents:
              agent-a:
                allowed_intents: [ro]
            """
        ).lstrip()
    )
    monkeypatch.setenv("MCP_GATEWAY_POLICY_PATH", str(policy))
    monkeypatch.setenv("MCP_GATEWAY_API_KEYS_JSON", '{"agent-a":"ck_x"}')

    from unittest.mock import AsyncMock

    from mcp_gateway.app import build_app

    upstream = AsyncMock()
    upstream.list_tools.return_value = [
        {"name": "memory_search"},
        {"name": "memory_save"},
    ]
    upstream.call_tool.return_value = {
        "results": [{"id": "m1", "content": "hello", "embedding": [0.1], "internal_score": 0.9}],
        "total_count": 1,
    }
    app = build_app(upstream_override=upstream)
    return app, upstream


@pytest.fixture
async def app_client(gateway_app):
    import httpx
    from httpx import ASGITransport

    app, _ = gateway_app
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        yield client


class TestSseHandshakeEndpoint:
    @pytest.mark.asyncio
    async def test_missing_auth_returns_401(self, app_client):
        resp = await app_client.get("/sse")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_missing_intent_returns_403(self, app_client):
        resp = await app_client.get("/sse", headers={"Authorization": "Bearer ck_x"})
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_handshake_emits_endpoint_event(self, app_client):
        async with app_client.stream(
            "GET",
            "/sse",
            headers={"Authorization": "Bearer ck_x", "X-MCP-Intent": "ro"},
        ) as resp:
            assert resp.status_code == 200
            sid = None
            async for line in resp.aiter_lines():
                if line.startswith("data:") and "session_id=" in line:
                    sid = line.split("session_id=", 1)[1].strip()
                    break
            assert sid is not None and len(sid) > 0


class TestMcpMessagesEndpoint:
    @pytest.mark.asyncio
    async def _open_session(self, app_client) -> str:
        async with app_client.stream(
            "GET",
            "/sse",
            headers={"Authorization": "Bearer ck_x", "X-MCP-Intent": "ro"},
        ) as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data:") and "session_id=" in line:
                    return line.split("session_id=", 1)[1].strip()
        raise AssertionError("no session_id received")

    @pytest.mark.asyncio
    async def test_tools_list_filters_by_caps(self, app_client):
        sid = await self._open_session(app_client)
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        resp = await app_client.post(f"/messages?session_id={sid}", json=body)
        assert resp.status_code == 200
        envelope = resp.json()
        names = [tool["name"] for tool in envelope["result"]["tools"]]
        assert names == ["memory_search"]
        assert "memory_save" not in names

    @pytest.mark.asyncio
    async def test_unknown_session_id_returns_404(self, app_client):
        resp = await app_client.post(
            "/messages?session_id=nonexistent",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_tools_call_filters_output(self, app_client):
        sid = await self._open_session(app_client)
        resp = await app_client.post(
            f"/messages?session_id={sid}",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "memory_search", "arguments": {"query": "hi"}},
            },
        )
        assert resp.status_code == 200
        result = resp.json()["result"]
        assert "embedding" not in result["results"][0]
        assert "internal_score" not in result["results"][0]
        assert result["results"][0]["content"] == "hello"

    @pytest.mark.asyncio
    async def test_tools_call_unauthorized_tool_denied(self, app_client):
        sid = await self._open_session(app_client)
        resp = await app_client.post(
            f"/messages?session_id={sid}",
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "memory_save", "arguments": {}},
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "error" in body
        assert "not found" in body["error"]["message"].lower()


class TestEntrypoint:
    def test_main_callable(self):
        from unittest.mock import patch

        import mcp_gateway.__main__ as entry

        with patch("uvicorn.run") as run:
            entry.main()
        run.assert_called_once()


class TestSamplePolicy:
    def test_sample_policy_is_valid(self):
        from importlib.resources import files

        from mcp_gateway.policy.loader import load_policy

        path = files("mcp_gateway").joinpath("policies/intents.example.yaml")
        policy = load_policy(path)  # type: ignore[arg-type]
        assert policy.version == 1
        assert "read_only_recall" in policy.intents


class TestSecretIsolation:
    def test_upstream_env_filters_unlisted_keys(self):
        from mcp_gateway.upstream.context_store_client import build_upstream_env

        env = build_upstream_env(
            passthrough=["OPENAI_API_KEY"],
            base_env={
                "OPENAI_API_KEY": "sk-allowed",
                "AWS_SECRET_ACCESS_KEY": "should-not-leak",
                "GITHUB_TOKEN": "should-not-leak",
                "PATH": "/usr/bin",
            },
        )
        assert "AWS_SECRET_ACCESS_KEY" not in env
        assert "GITHUB_TOKEN" not in env
        assert env["OPENAI_API_KEY"] == "sk-allowed"
        assert "PATH" in env

    def test_settings_repr_does_not_leak_api_keys(self, tmp_path, monkeypatch):
        policy = tmp_path / "intents.yaml"
        policy.write_text("version: 1\noutput_filters: {}\nintents: {}\nagents: {}\n")
        monkeypatch.setenv("MCP_GATEWAY_POLICY_PATH", str(policy))
        monkeypatch.setenv("MCP_GATEWAY_API_KEYS_JSON", '{"a":"ck_super_secret"}')

        from mcp_gateway.config import GatewaySettings

        settings = GatewaySettings()
        assert "ck_super_secret" not in repr(settings)
        assert "ck_super_secret" not in str(settings.model_dump())
        assert "ck_super_secret" not in str(settings.model_dump(mode="json"))


class TestContextStoreUntouched:
    """Phase 3 acceptance: src/context_store/ must be diff-free vs master."""

    def test_no_imports_from_context_store_in_mcp_gateway(self):
        import pkgutil
        from importlib import import_module

        import mcp_gateway

        bad: list[str] = []
        for mod_info in pkgutil.walk_packages(mcp_gateway.__path__, prefix="mcp_gateway."):
            module = import_module(mod_info.name)
            src = getattr(module, "__file__", None)
            if src is None:
                continue
            with open(src, encoding="utf-8") as handle:
                text = handle.read()
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if "from context_store" in stripped or "import context_store" in stripped:
                    bad.append(f"{mod_info.name}: {stripped}")
        assert bad == [], f"mcp_gateway imports context_store directly: {bad}"
