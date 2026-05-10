"""Unit tests for src/mcp_gateway/."""

from __future__ import annotations

import asyncio
import textwrap
from typing import Any

import pytest
import pytest_asyncio
from pydantic import ValidationError


async def _get_sse_session_id(client, *, intent: str) -> str:
    async with client.stream(
        "GET",
        "/sse",
        headers={"Authorization": "Bearer ck_x", "X-MCP-Intent": intent},
    ) as resp:
        assert resp.status_code == 200
        async for line in resp.aiter_lines():
            if line.startswith("data:") and "session_id=" in line:
                return line.split("session_id=", 1)[1].strip()
    raise AssertionError("SSE endpoint event did not return session_id")


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


class TestGatewaySettingsApprovalFields:
    _MINIMAL_POLICY = "version: 1\noutput_filters: {f: {type: none}}\nintents: {}\nagents: {}\n"

    def test_defaults(self, monkeypatch, tmp_path):
        policy = tmp_path / "p.yaml"
        policy.write_text(self._MINIMAL_POLICY)
        monkeypatch.setenv("MCP_GATEWAY_POLICY_PATH", str(policy))
        from mcp_gateway.config import GatewaySettings

        settings = GatewaySettings()
        assert settings.approval_blocking_mode is False
        assert settings.approval_timeout_seconds == 30.0
        assert settings.approval_max_pending == 1000

    def test_env_overrides(self, monkeypatch, tmp_path):
        policy = tmp_path / "p.yaml"
        policy.write_text(self._MINIMAL_POLICY)
        monkeypatch.setenv("MCP_GATEWAY_POLICY_PATH", str(policy))
        monkeypatch.setenv("MCP_GATEWAY_APPROVAL_BLOCKING_MODE", "true")
        monkeypatch.setenv("MCP_GATEWAY_APPROVAL_TIMEOUT_SECONDS", "5")
        monkeypatch.setenv("MCP_GATEWAY_APPROVAL_MAX_PENDING", "10")
        from mcp_gateway.config import GatewaySettings

        settings = GatewaySettings()
        assert settings.approval_blocking_mode is True
        assert settings.approval_timeout_seconds == 5.0
        assert settings.approval_max_pending == 10

    def test_validation_bounds(self, monkeypatch, tmp_path):
        policy = tmp_path / "p.yaml"
        policy.write_text(self._MINIMAL_POLICY)
        monkeypatch.setenv("MCP_GATEWAY_POLICY_PATH", str(policy))

        from mcp_gateway.config import GatewaySettings

        # timeout <= 0
        monkeypatch.setenv("MCP_GATEWAY_APPROVAL_TIMEOUT_SECONDS", "0")
        with pytest.raises(ValidationError):
            GatewaySettings()

        # timeout > 600
        monkeypatch.setenv("MCP_GATEWAY_APPROVAL_TIMEOUT_SECONDS", "601")
        with pytest.raises(ValidationError):
            GatewaySettings()

        # max_pending <= 0
        monkeypatch.setenv("MCP_GATEWAY_APPROVAL_TIMEOUT_SECONDS", "30")
        monkeypatch.setenv("MCP_GATEWAY_APPROVAL_MAX_PENDING", "0")
        with pytest.raises(ValidationError):
            GatewaySettings()

        # max_pending > 100,000
        monkeypatch.setenv("MCP_GATEWAY_APPROVAL_MAX_PENDING", "100001")
        with pytest.raises(ValidationError):
            GatewaySettings()


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

    def test_evaluate_grant_propagates_and_copies_guardrails(self):
        from mcp_gateway.policy.engine import PolicyEngine
        from mcp_gateway.policy.models import (
            AgentPolicy,
            GatewayPolicy,
            IntentPolicy,
            ParamConstraint,
            ToolGuardrail,
        )

        guardrails = {
            "tool_a": ToolGuardrail(
                params={"p": ParamConstraint(type="string", max_length=10)}, requires_approval=True
            )
        }
        policy = GatewayPolicy(
            version=1,
            output_filters={"f": {"type": "none"}},
            intents={
                "intent_a": IntentPolicy(
                    description="d",
                    allowed_tools=["tool_a"],
                    output_filter="f",
                    guardrails=guardrails,
                )
            },
            agents={"agent_a": AgentPolicy(allowed_intents=["intent_a"])},
        )

        eng = PolicyEngine(policy)
        grant = eng.evaluate_grant(agent_id="agent_a", intent="intent_a", requested_tools=None)

        # Verifying propagation
        assert "tool_a" in grant.guardrails
        assert grant.guardrails["tool_a"].requires_approval is True
        assert grant.guardrails["tool_a"].params["p"].max_length == 10

        # Verifying reference independence (no shared mutable state)
        assert grant.guardrails is not policy.intents["intent_a"].guardrails
        assert grant.guardrails["tool_a"] is not policy.intents["intent_a"].guardrails["tool_a"]

        # Verifying deep-copy immutability (Issue 3 Nitpick)
        # Note: Pydantic models are frozen, so we check if they are distinct objects
        # that were independent at creation. The 'is not' check above already covers this,
        # but we can also verify that modifying a nested mutable (if any existed) would be safe.
        # Since ParamConstraint is frozen, we can't mutate it. But we can verify
        # that the guardrails dict in policy can be modified without affecting grant.

        # Original guardrails dict in policy is mutable (Pydantic field is dict)
        policy.intents["intent_a"].guardrails["tool_b"] = ToolGuardrail()
        assert "tool_b" not in grant.guardrails

        # Verifying dict-level immutability of the Grant (Issue 1)
        # MappingProxyType should prevent direct modifications
        from types import MappingProxyType

        assert isinstance(grant.guardrails, MappingProxyType)
        with pytest.raises(TypeError):
            grant.guardrails["tool_c"] = ToolGuardrail()  # type: ignore[index]

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
            guardrails={},
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
        rec = reg.create(
            agent_id="a",
            intent="i",
            caps=frozenset(),
            guardrails={},
            output_filter_profile="none_f",
        )
        future = rec.expires_at + timedelta(seconds=1)
        monkeypatch.setattr(sess, "_utcnow", lambda: future)
        from mcp_gateway.errors import SessionError

        with pytest.raises(SessionError):
            reg.lookup(rec.session_id)

    def test_idle_timeout(self, monkeypatch):
        from datetime import timedelta

        import mcp_gateway.auth.session as sess

        reg = self._make_registry(ttl=600, idle=5)
        rec = reg.create(
            agent_id="a",
            intent="i",
            caps=frozenset(),
            guardrails={},
            output_filter_profile="none_f",
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
        rec = reg.create(
            agent_id="a",
            intent="i",
            caps=frozenset(),
            guardrails={},
            output_filter_profile="none_f",
        )
        original = sess._utcnow()
        monkeypatch.setattr(sess, "_utcnow", lambda: original + timedelta(seconds=3))
        reg.touch(rec.session_id)
        monkeypatch.setattr(sess, "_utcnow", lambda: original + timedelta(seconds=7))
        # 3秒時にtouch → 7秒時はtouchから4秒経過 → idle=5秒未満なので有効
        assert reg.lookup(rec.session_id).session_id == rec.session_id

    def test_remove(self):
        from mcp_gateway.errors import SessionError

        reg = self._make_registry()
        rec = reg.create(
            agent_id="a",
            intent="i",
            caps=frozenset(),
            guardrails={},
            output_filter_profile="none_f",
        )
        reg.remove(rec.session_id)
        with pytest.raises(SessionError):
            reg.lookup(rec.session_id)

    def test_session_record_is_frozen(self):
        from dataclasses import FrozenInstanceError

        reg = self._make_registry()
        rec = reg.create(
            agent_id="a",
            intent="i",
            caps=frozenset(),
            guardrails={},
            output_filter_profile="none_f",
        )
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
                    description="x",
                    allowed_tools=["memory_search", "memory_save"],
                    output_filter="rs",
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
        assert rec.caps == frozenset({"memory_search", "memory_save"})
        assert rec.output_filter_profile == "rs"

    def test_missing_intent_header_denied(self):
        from mcp_gateway.errors import PolicyError

        svc = self._stack()
        with pytest.raises(PolicyError, match="missing X-MCP-Intent header"):
            svc.handshake(
                authorization_header="Bearer ck_x",
                intent_header=None,
                requested_tools_header=None,
            )

    def test_invalid_intent_header_denied(self):
        from mcp_gateway.errors import PolicyError

        svc = self._stack()
        with pytest.raises(PolicyError, match="invalid X-MCP-Intent header"):
            svc.handshake(
                authorization_header="Bearer ck_x",
                intent_header="   ",
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

    @pytest.mark.parametrize("bad_header", ["Basic xyz", "Malformed"])
    def test_malformed_auth_header_denied(self, bad_header):
        from mcp_gateway.errors import AuthError

        svc = self._stack()
        with pytest.raises(AuthError, match="missing or malformed Authorization header"):
            svc.handshake(
                authorization_header=bad_header,
                intent_header="ro",
                requested_tools_header=None,
            )

    def test_requested_tools_intersection_narrowed(self):
        svc = self._stack()
        # Policy allows [memory_search, memory_save]
        # Requesting [memory_search, admin_tool] -> should result in [memory_search] only
        rec = svc.handshake(
            authorization_header="Bearer ck_x",
            intent_header="ro",
            requested_tools_header="memory_search,admin_tool",
        )
        assert rec.caps == frozenset({"memory_search"})

    def test_no_overlap_tools_denied(self):
        from mcp_gateway.errors import PolicyError

        svc = self._stack()
        with pytest.raises(PolicyError, match="none of the requested tools are allowed"):
            svc.handshake(
                authorization_header="Bearer ck_x",
                intent_header="ro",
                requested_tools_header="admin_tool",
            )

    def test_intent_not_allowed_for_agent_denied(self):
        # We need a stack with another intent that is NOT allowed for agent-a
        from mcp_gateway.auth.api_key import ApiKeyAuthenticator
        from mcp_gateway.auth.handshake import HandshakeService
        from mcp_gateway.auth.session import InMemorySessionRegistry
        from mcp_gateway.errors import PolicyError
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
                ),
                "admin": IntentPolicy(
                    description="y", allowed_tools=["admin_tool"], output_filter="rs"
                ),
            },
            agents={"agent-a": AgentPolicy(allowed_intents=["ro"])},
        )
        svc = HandshakeService(
            authenticator=ApiKeyAuthenticator({"agent-a": "ck_x"}),
            policy_engine=PolicyEngine(policy),
            session_registry=InMemorySessionRegistry(ttl_seconds=60, idle_timeout_seconds=30),
        )

        with pytest.raises(PolicyError, match="cannot use intent"):
            svc.handshake(
                authorization_header="Bearer ck_x",
                intent_header="admin",
                requested_tools_header=None,
            )


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
    async def test_list_tools_wraps_exception(self):
        from unittest.mock import AsyncMock

        from mcp_gateway.errors import UpstreamError
        from mcp_gateway.upstream.context_store_client import UpstreamClient

        fake_session = AsyncMock()
        fake_session.list_tools.side_effect = Exception("network error")
        client = UpstreamClient.__new__(UpstreamClient)  # type: ignore[call-arg]
        client._session = fake_session  # type: ignore[attr-defined]
        client._tools_cache = None  # type: ignore[attr-defined]

        with pytest.raises(UpstreamError) as excinfo:
            await client.list_tools()
        assert "upstream list tools failed" in str(excinfo.value)
        assert "network error" in str(excinfo.value.__cause__)

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
    async def test_call_tool_wraps_upstream_exception_in_upstream_error(self):
        from unittest.mock import AsyncMock

        from mcp_gateway.errors import UpstreamError
        from mcp_gateway.upstream.context_store_client import UpstreamClient

        fake_session = AsyncMock()
        fake_session.call_tool.side_effect = RuntimeError("connection lost")

        client = UpstreamClient.__new__(UpstreamClient)  # type: ignore[call-arg]
        client._session = fake_session  # type: ignore[attr-defined]

        with pytest.raises(UpstreamError, match="upstream tool call 't' failed") as excinfo:
            await client.call_tool("t", {})

        assert isinstance(excinfo.value.__cause__, RuntimeError)
        assert str(excinfo.value.__cause__) == "connection lost"

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

    @pytest.mark.asyncio
    async def test_call_through_rejects_param_violation_before_approval(self):
        from unittest.mock import AsyncMock

        from mcp_gateway.errors import PolicyError
        from mcp_gateway.filters.none_filter import NoneFilter
        from mcp_gateway.policy.models import ParamConstraint, ToolGuardrail
        from mcp_gateway.tools.proxy import ToolProxy

        upstream = AsyncMock()
        proxy = ToolProxy(upstream=upstream, filter_=NoneFilter())

        guardrail = ToolGuardrail(
            params={"p": ParamConstraint(type="integer")}, requires_approval=True
        )

        with pytest.raises(PolicyError) as exc_info:
            await proxy.call_through(
                tool_name="t",
                arguments={"p": "not_an_int"},
                guardrail=guardrail,
            )

        assert exc_info.value.reason == "param_type_mismatch:p"
        upstream.call_tool.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_call_server_trusted_skips_redundant_validation(self, monkeypatch):
        from unittest.mock import AsyncMock

        from mcp_gateway.filters.none_filter import NoneFilter
        from mcp_gateway.policy.engine import PolicyEngine
        from mcp_gateway.tools.proxy import ToolProxy

        upstream = AsyncMock()
        upstream.call_tool.return_value = {"ok": True}
        proxy = ToolProxy(upstream=upstream, filter_=NoneFilter())

        def fail_if_called(*, tool_name, arguments, guardrail=None):
            raise AssertionError("validate_call should be skipped")

        monkeypatch.setattr(PolicyEngine, "validate_call", fail_if_called)

        out = await proxy._call_server_trusted(
            tool_name="t",
            arguments={"q": "safe query"},
        )

        assert out == {"ok": True}
        upstream.call_tool.assert_awaited_once_with("t", {"q": "safe query"})


@pytest.fixture(autouse=True)
def mock_sse_keep_alive(monkeypatch):
    """Mock the SSE keep-alive loop to prevent hanging in unit tests."""
    from unittest.mock import AsyncMock

    import mcp_gateway.server as server_module

    # By raising CancelledError, we terminate the loop in event_stream immediately
    # after the first yield (the 'endpoint' event).
    monkeypatch.setattr(server_module, "_keep_alive", AsyncMock(side_effect=asyncio.CancelledError))


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
    app = build_app(upstream_override=upstream, initial_tools=upstream.list_tools.return_value)
    return app, upstream


@pytest_asyncio.fixture
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
        return await _get_sse_session_id(app_client, intent="ro")

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

    @pytest.mark.asyncio
    async def test_call_tool_with_invalid_falsy_arguments(self, app_client):
        # [] is falsy but not a dict
        sid = await self._open_session(app_client)
        resp = await app_client.post(
            f"/messages?session_id={sid}",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "memory_search", "arguments": []},
            },
        )
        assert resp.status_code == 200
        assert resp.json()["error"]["code"] == -32602
        assert "arguments' must be an object" in resp.json()["error"]["message"]

    @pytest.mark.asyncio
    async def test_call_tool_missing_name(self, app_client):
        sid = await self._open_session(app_client)
        resp = await app_client.post(
            f"/messages?session_id={sid}",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"arguments": {}},
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["error"]["code"] == -32602
        assert "missing required parameter: name" in body["error"]["message"]


class TestServerRequiresApproval:
    """REQUIRES_APPROVAL パスの /messages エンドポイントテスト。"""

    @pytest.fixture
    def approval_app(self, tmp_path, monkeypatch):
        policy = tmp_path / "intents.yaml"
        policy.write_text(
            textwrap.dedent(
                """
                version: 1
                output_filters:
                  f:
                    type: none
                intents:
                  curate_memories:
                    description: "x"
                    allowed_tools: [memory_delete]
                    output_filter: f
                    guardrails:
                      memory_delete:
                        requires_approval: true
                agents:
                  agent-a:
                    allowed_intents: [curate_memories]
                """
            ).lstrip()
        )
        monkeypatch.setenv("MCP_GATEWAY_POLICY_PATH", str(policy))
        monkeypatch.setenv("MCP_GATEWAY_API_KEYS_JSON", '{"agent-a":"ck_x"}')

        from unittest.mock import AsyncMock

        from mcp_gateway.app import build_app

        upstream = AsyncMock()
        upstream.list_tools.return_value = [{"name": "memory_delete"}]
        return build_app(
            upstream_override=upstream,
            initial_tools=upstream.list_tools.return_value,
        )

    @pytest_asyncio.fixture
    async def approval_client(self, approval_app):
        import httpx
        from httpx import ASGITransport

        transport = ASGITransport(app=approval_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            yield client

    @pytest.mark.asyncio
    async def test_requires_approval_returns_32001(self, approval_client):
        sid = await _get_sse_session_id(approval_client, intent="curate_memories")
        resp = await approval_client.post(
            f"/messages?session_id={sid}",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "memory_delete", "arguments": {"id": "m-001"}},
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["error"]["code"] == -32001
        assert body["error"]["message"] == "approval_required"
        assert "session_id" in body["error"]["data"]

    @pytest.mark.asyncio
    async def test_requires_approval_audit_log(self, approval_client, caplog):
        import logging

        sid = await _get_sse_session_id(approval_client, intent="curate_memories")
        with caplog.at_level(logging.INFO, logger="mcp_gateway.approval.notifier"):
            resp = await approval_client.post(
                f"/messages?session_id={sid}",
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "memory_delete", "arguments": {}},
                },
            )
            await asyncio.sleep(0)
        assert resp.status_code == 200
        assert any("approval_required" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_requires_approval_notifier_failure_is_isolated(
        self, approval_client, monkeypatch, capfd
    ):
        from mcp_gateway.approval.notifier import LogOnlyApprovalNotifier

        started = asyncio.Event()

        async def raise_error(self, request):
            started.set()
            raise RuntimeError("boom")

        monkeypatch.setattr(LogOnlyApprovalNotifier, "request_approval", raise_error)

        sid = await _get_sse_session_id(approval_client, intent="curate_memories")
        resp = await approval_client.post(
            f"/messages?session_id={sid}",
            json={
                "jsonrpc": "2.0",
                "id": 99,
                "method": "tools/call",
                "params": {"name": "memory_delete", "arguments": {}},
            },
        )
        await asyncio.wait_for(started.wait(), timeout=1.0)
        await asyncio.sleep(0)

        assert resp.status_code == 200
        body = resp.json()
        assert body["error"]["code"] == -32001
        assert body["error"]["message"] == "approval_required"

        _, err = capfd.readouterr()
        assert '"ev":"notification_failed"' in err
        assert '"detail":"Approval notification failed"' in err
        assert '"error_type":"RuntimeError"' in err
        assert "boom" not in err

    @pytest.mark.asyncio
    async def test_requires_approval_notification_is_fire_and_forget(
        self, approval_client, monkeypatch
    ):
        import mcp_gateway.server as server_module
        from mcp_gateway.approval.notifier import LogOnlyApprovalNotifier

        started = asyncio.Event()
        release = asyncio.Event()
        created_tasks: list[asyncio.Task] = []
        original_schedule = server_module._schedule_approval_request

        async def block_until_released(self, request):
            started.set()
            await release.wait()

        def capture_task(*, approval_notifier, request, audit, sid, timeout=5.0):
            task = original_schedule(
                approval_notifier=approval_notifier,
                request=request,
                audit=audit,
                sid=sid,
                timeout=timeout,
            )
            created_tasks.append(task)
            return task

        monkeypatch.setattr(LogOnlyApprovalNotifier, "request_approval", block_until_released)
        monkeypatch.setattr(server_module, "_schedule_approval_request", capture_task)

        sid = await _get_sse_session_id(approval_client, intent="curate_memories")
        resp = await approval_client.post(
            f"/messages?session_id={sid}",
            json={
                "jsonrpc": "2.0",
                "id": 100,
                "method": "tools/call",
                "params": {"name": "memory_delete", "arguments": {}},
            },
        )

        assert resp.status_code == 200
        assert resp.json()["error"]["message"] == "approval_required"
        await asyncio.wait_for(started.wait(), timeout=1.0)
        assert created_tasks

        release.set()
        await asyncio.gather(*created_tasks, return_exceptions=True)

    @pytest.mark.asyncio
    async def test_requires_approval_secret_args_denied_without_notifier_calls(
        self, approval_client, monkeypatch
    ):
        import mcp_gateway.server as server_module
        from mcp_gateway.approval.notifier import LogOnlyApprovalNotifier

        notifier_called = False
        schedule_called = False

        async def fail_if_called(self, request):
            nonlocal notifier_called
            notifier_called = True
            raise AssertionError("request_approval should not be called")

        def fail_if_scheduled(*, approval_notifier, request, audit, sid, timeout=5.0):
            nonlocal schedule_called
            schedule_called = True
            raise AssertionError("_schedule_approval_request should not be called")

        monkeypatch.setattr(LogOnlyApprovalNotifier, "request_approval", fail_if_called)
        monkeypatch.setattr(server_module, "_schedule_approval_request", fail_if_scheduled)

        sid = await _get_sse_session_id(approval_client, intent="curate_memories")
        resp = await approval_client.post(
            f"/messages?session_id={sid}",
            json={
                "jsonrpc": "2.0",
                "id": 101,
                "method": "tools/call",
                "params": {
                    "name": "memory_delete",
                    "arguments": {"token": "sk-1234567890abcdef"},
                },
            },
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["error"]["code"] == -32601
        assert body["error"]["message"] == "tool not found"
        assert notifier_called is False
        assert schedule_called is False

    @pytest.mark.asyncio
    async def test_requires_approval_sanitizes_notifier_request_arguments(
        self, approval_client, monkeypatch
    ):
        import mcp_gateway.server as server_module

        captured_request = None
        created_tasks: list[asyncio.Task] = []

        def capture_request(*, approval_notifier, request, audit, sid, timeout=5.0):
            nonlocal captured_request
            captured_request = request
            task = asyncio.create_task(asyncio.sleep(0))
            created_tasks.append(task)
            return task

        monkeypatch.setattr(server_module, "_schedule_approval_request", capture_request)

        sid = await _get_sse_session_id(approval_client, intent="curate_memories")
        resp = await approval_client.post(
            f"/messages?session_id={sid}",
            json={
                "jsonrpc": "2.0",
                "id": 102,
                "method": "tools/call",
                "params": {
                    "name": "memory_delete",
                    "arguments": {
                        "password": "s3cr3t",
                        "api_key": "hunter2",
                        "safe_param": "visible",
                    },
                },
            },
        )

        assert resp.status_code == 200
        assert resp.json()["error"]["message"] == "approval_required"
        assert captured_request is not None
        assert captured_request.arguments["password"] == "**********"
        assert captured_request.arguments["api_key"] == "**********"
        assert captured_request.arguments["safe_param"] == "visible"

        await asyncio.gather(*created_tasks, return_exceptions=True)

    @pytest.mark.asyncio
    async def test_caps_denied_returns_32601(self, approval_client):
        sid = await _get_sse_session_id(approval_client, intent="curate_memories")
        resp = await approval_client.post(
            f"/messages?session_id={sid}",
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "admin_tool", "arguments": {}},
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["error"]["code"] == -32601
        assert body["error"]["message"] == "tool not found"


class TestBuildRouterApprovalPrecondition:
    def test_build_router_raises_when_blocking_without_registry(self) -> None:
        from mcp_gateway.server import build_router

        with pytest.raises(ValueError, match="approval_registry"):
            build_router(
                handshake=object(),  # type: ignore[arg-type]
                sessions=object(),  # type: ignore[arg-type]
                tool_registry=object(),  # type: ignore[arg-type]
                upstream=object(),
                policy=object(),  # type: ignore[arg-type]
                audit=object(),  # type: ignore[arg-type]
                engine=object(),  # type: ignore[arg-type]
                approval_blocking_mode=True,
                approval_registry=None,
            )

    def test_build_router_raises_when_timeout_is_non_positive(self) -> None:
        from mcp_gateway.server import build_router

        with pytest.raises(ValueError, match="approval_timeout_seconds must be positive"):
            build_router(
                handshake=object(),  # type: ignore[arg-type]
                sessions=object(),  # type: ignore[arg-type]
                tool_registry=object(),  # type: ignore[arg-type]
                upstream=object(),
                policy=object(),  # type: ignore[arg-type]
                audit=object(),  # type: ignore[arg-type]
                engine=object(),  # type: ignore[arg-type]
                approval_blocking_mode=True,
                approval_registry=object(),  # type: ignore[arg-type]
                approval_timeout_seconds=0,
                api_authenticator=object(),  # type: ignore[arg-type]
            )
        with pytest.raises(ValueError, match="approval_timeout_seconds must be positive"):
            build_router(
                handshake=object(),  # type: ignore[arg-type]
                sessions=object(),  # type: ignore[arg-type]
                tool_registry=object(),  # type: ignore[arg-type]
                upstream=object(),
                policy=object(),  # type: ignore[arg-type]
                audit=object(),  # type: ignore[arg-type]
                engine=object(),  # type: ignore[arg-type]
                approval_blocking_mode=True,
                approval_registry=object(),  # type: ignore[arg-type]
                approval_timeout_seconds=-1.0,
                api_authenticator=object(),  # type: ignore[arg-type]
            )


class TestBlockingModeHandlerDirect:
    """Direct router-level tests for the blocking-mode REQUIRES_APPROVAL handler."""

    @pytest.fixture
    def router_with_registry(self, tmp_path):
        from unittest.mock import AsyncMock

        from fastapi import FastAPI

        from mcp_gateway.approval.registry import PendingApprovalRegistry
        from mcp_gateway.audit.logger import AuditLogger
        from mcp_gateway.auth.api_key import ApiKeyAuthenticator
        from mcp_gateway.auth.handshake import HandshakeService
        from mcp_gateway.auth.session import InMemorySessionRegistry
        from mcp_gateway.policy.engine import PolicyEngine
        from mcp_gateway.policy.loader import load_policy
        from mcp_gateway.server import build_router
        from mcp_gateway.tools.registry import ToolRegistry

        policy_file = tmp_path / "intents.yaml"
        policy_file.write_text(
            textwrap.dedent(
                """
                version: 1
                output_filters:
                  f:
                    type: none
                intents:
                  curate_memories:
                    description: "x"
                    allowed_tools: [memory_delete]
                    output_filter: f
                    guardrails:
                      memory_delete:
                        requires_approval: true
                agents:
                  agent-a:
                    allowed_intents: [curate_memories]
                  operator:
                    allowed_intents: [curate_memories]
                """
            ).lstrip()
        )
        policy = load_policy(policy_file)
        engine = PolicyEngine(policy)
        sessions = InMemorySessionRegistry(ttl_seconds=900, idle_timeout_seconds=300)
        auth = ApiKeyAuthenticator({"agent-a": "ck_a", "operator": "ck_o"})
        handshake = HandshakeService(
            authenticator=auth,
            policy_engine=engine,
            session_registry=sessions,
        )
        registry = PendingApprovalRegistry(max_pending=4)
        upstream = AsyncMock()
        upstream.call_tool.return_value = {"ok": True}
        tools = ToolRegistry([{"name": "memory_delete"}])
        audit = AuditLogger()

        app = FastAPI()
        app.include_router(
            build_router(
                handshake=handshake,
                sessions=sessions,
                tool_registry=tools,
                upstream=upstream,
                policy=policy,
                audit=audit,
                engine=engine,
                approval_registry=registry,
                approval_blocking_mode=True,
                approval_timeout_seconds=0.5,
                api_authenticator=auth,
            )
        )
        return app, registry, sessions, handshake, upstream

    async def _wait_for_approval_id(self, registry: Any, timeout: float = 2.0) -> str:
        """Helper to poll for a pending approval ID with timeout."""
        for _ in range(int(timeout / 0.05)):
            if registry._pending:  # type: ignore[attr-defined]
                return next(iter(registry._pending.keys()))  # type: ignore[attr-defined]
            await asyncio.sleep(0.05)
        pytest.fail("timed out waiting for pending approval id")

    @pytest.mark.asyncio
    async def test_blocking_mode_returns_32003_on_timeout(self, router_with_registry):
        app, _registry, _sessions, handshake, _upstream = router_with_registry
        rec = handshake.handshake(
            authorization_header="Bearer ck_a",
            intent_header="curate_memories",
            requested_tools_header="memory_delete",
        )

        import httpx
        from httpx import ASGITransport

        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            resp = await c.post(
                f"/messages?session_id={rec.session_id}",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "memory_delete", "arguments": {}},
                },
            )
        body = resp.json()
        assert body["error"]["code"] == -32003
        assert body["error"]["message"] == "approval_timeout"

    @pytest.mark.asyncio
    async def test_blocking_mode_suspends_until_approve(self, router_with_registry):
        app, registry, _sessions, handshake, _upstream = router_with_registry
        rec = handshake.handshake(
            authorization_header="Bearer ck_a",
            intent_header="curate_memories",
            requested_tools_header="memory_delete",
        )

        import httpx
        from httpx import ASGITransport

        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            call_task = asyncio.create_task(
                c.post(
                    f"/messages?session_id={rec.session_id}",
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {"name": "memory_delete", "arguments": {}},
                    },
                )
            )
            approval_id = await self._wait_for_approval_id(registry)
            from mcp_gateway.approval.models import DecisionStatus

            await registry.resolve(
                approval_id,
                resolver_agent_id="operator",
                status=DecisionStatus.APPROVED,
            )
            resp = await call_task
        body = resp.json()
        assert body["result"] == {"ok": True}

    @pytest.mark.asyncio
    async def test_blocking_mode_returns_32002_on_reject(self, router_with_registry):
        app, registry, _sessions, handshake, _upstream = router_with_registry
        rec = handshake.handshake(
            authorization_header="Bearer ck_a",
            intent_header="curate_memories",
            requested_tools_header="memory_delete",
        )
        import httpx
        from httpx import ASGITransport

        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            call_task = asyncio.create_task(
                c.post(
                    f"/messages?session_id={rec.session_id}",
                    json={
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {"name": "memory_delete", "arguments": {}},
                    },
                )
            )
            approval_id = await self._wait_for_approval_id(registry)
            from mcp_gateway.approval.models import DecisionStatus

            await registry.resolve(
                approval_id,
                resolver_agent_id="operator",
                status=DecisionStatus.REJECTED,
                reason="not authorized",
            )
            resp = await call_task
        body = resp.json()
        assert body["error"]["code"] == -32002
        assert body["error"]["message"] == "approval_rejected"

    @pytest.mark.asyncio
    async def test_blocking_mode_returns_32603_when_registry_full(self, tmp_path):
        from unittest.mock import AsyncMock

        from fastapi import FastAPI

        from mcp_gateway.approval.registry import PendingApprovalRegistry
        from mcp_gateway.audit.logger import AuditLogger
        from mcp_gateway.auth.api_key import ApiKeyAuthenticator
        from mcp_gateway.auth.handshake import HandshakeService
        from mcp_gateway.auth.session import InMemorySessionRegistry
        from mcp_gateway.policy.engine import PolicyEngine
        from mcp_gateway.policy.loader import load_policy
        from mcp_gateway.server import build_router
        from mcp_gateway.tools.registry import ToolRegistry

        policy_file = tmp_path / "intents.yaml"
        policy_file.write_text(
            textwrap.dedent(
                """
                version: 1
                output_filters: {f: {type: none}}
                intents:
                  curate_memories:
                    description: x
                    allowed_tools: [memory_delete]
                    output_filter: f
                    guardrails: {memory_delete: {requires_approval: true}}
                agents:
                  agent-a: {allowed_intents: [curate_memories]}
                  agent-b: {allowed_intents: [curate_memories]}
                """
            ).lstrip()
        )
        policy = load_policy(policy_file)
        engine = PolicyEngine(policy)
        sessions = InMemorySessionRegistry(ttl_seconds=900, idle_timeout_seconds=300)
        auth = ApiKeyAuthenticator({"agent-a": "ck_a", "agent-b": "ck_b"})
        handshake = HandshakeService(
            authenticator=auth,
            policy_engine=engine,
            session_registry=sessions,
        )
        registry = PendingApprovalRegistry(max_pending=1)
        upstream = AsyncMock()
        tools = ToolRegistry([{"name": "memory_delete"}])
        audit = AuditLogger()
        app = FastAPI()
        app.include_router(
            build_router(
                handshake=handshake,
                sessions=sessions,
                tool_registry=tools,
                upstream=upstream,
                policy=policy,
                audit=audit,
                engine=engine,
                approval_registry=registry,
                approval_blocking_mode=True,
                approval_timeout_seconds=2.0,
                api_authenticator=auth,
            )
        )

        rec_a = handshake.handshake(
            authorization_header="Bearer ck_a",
            intent_header="curate_memories",
            requested_tools_header="memory_delete",
        )
        rec_b = handshake.handshake(
            authorization_header="Bearer ck_b",
            intent_header="curate_memories",
            requested_tools_header="memory_delete",
        )

        import httpx
        from httpx import ASGITransport

        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            t_a = asyncio.create_task(
                c.post(
                    f"/messages?session_id={rec_a.session_id}",
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {"name": "memory_delete", "arguments": {}},
                    },
                )
            )
            await self._wait_for_approval_id(registry)
            resp_b = await c.post(
                f"/messages?session_id={rec_b.session_id}",
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "memory_delete", "arguments": {}},
                },
            )
            assert resp_b.json()["error"]["code"] == -32603
            resp_a = await t_a
            assert resp_a.json()["error"]["code"] == -32003

    @pytest.mark.asyncio
    async def test_audit_logs_truncate_approval_id(self, router_with_registry, capfd):
        app, registry, _sessions, handshake, _upstream = router_with_registry
        rec = handshake.handshake(
            authorization_header="Bearer ck_a",
            intent_header="curate_memories",
            requested_tools_header="memory_delete",
        )
        import httpx
        from httpx import ASGITransport

        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            task = asyncio.create_task(
                c.post(
                    f"/messages?session_id={rec.session_id}",
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {"name": "memory_delete", "arguments": {}},
                    },
                )
            )
            approval_id = await self._wait_for_approval_id(registry)
            from mcp_gateway.approval.models import DecisionStatus

            await registry.resolve(
                approval_id,
                resolver_agent_id="operator",
                status=DecisionStatus.APPROVED,
            )
            await task

        _, err = capfd.readouterr()
        assert '"decision":"approval_pending"' in err
        assert '"decision":"allow_after_approval"' in err
        assert '"approval_ref":"' in err
        # Verify approval_ref is in allow_after_approval log too
        allow_log = [
            line for line in err.splitlines() if '"decision":"allow_after_approval"' in line
        ]
        assert len(allow_log) == 1
        assert '"approval_ref":"' in allow_log[0]

        import re

        full_hex = re.findall(r"[0-9a-f]{32}", err)
        assert not full_hex

    @pytest.mark.asyncio
    async def test_does_not_call_upstream_on_reject(self, router_with_registry):
        app, registry, _sessions, handshake, upstream = router_with_registry
        rec = handshake.handshake(
            authorization_header="Bearer ck_a",
            intent_header="curate_memories",
            requested_tools_header="memory_delete",
        )
        import httpx
        from httpx import ASGITransport

        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            task = asyncio.create_task(
                c.post(
                    f"/messages?session_id={rec.session_id}",
                    json={
                        "jsonrpc": "2.0",
                        "id": 9,
                        "method": "tools/call",
                        "params": {"name": "memory_delete", "arguments": {}},
                    },
                )
            )
            approval_id = await self._wait_for_approval_id(registry)
            from mcp_gateway.approval.models import DecisionStatus

            await registry.resolve(
                approval_id,
                resolver_agent_id="operator",
                status=DecisionStatus.REJECTED,
            )
            resp = await task
        assert resp.json()["error"]["code"] == -32002
        upstream.call_tool.assert_not_called()


class TestApprovalsEndpoint:
    @pytest.fixture
    def router_with_registry(self, tmp_path):
        from unittest.mock import AsyncMock

        from fastapi import FastAPI

        from mcp_gateway.approval.registry import PendingApprovalRegistry
        from mcp_gateway.audit.logger import AuditLogger
        from mcp_gateway.auth.api_key import ApiKeyAuthenticator
        from mcp_gateway.auth.handshake import HandshakeService
        from mcp_gateway.auth.session import InMemorySessionRegistry
        from mcp_gateway.policy.engine import PolicyEngine
        from mcp_gateway.policy.loader import load_policy
        from mcp_gateway.server import build_router
        from mcp_gateway.tools.registry import ToolRegistry

        policy_file = tmp_path / "intents.yaml"
        policy_file.write_text(
            textwrap.dedent(
                """
                version: 1
                output_filters: {f: {type: none}}
                intents:
                  curate_memories:
                    description: x
                    allowed_tools: [memory_delete]
                    output_filter: f
                    guardrails: {memory_delete: {requires_approval: true}}
                agents:
                  agent-a: {allowed_intents: [curate_memories]}
                  operator: {allowed_intents: [curate_memories]}
                """
            ).lstrip()
        )
        policy = load_policy(policy_file)
        engine = PolicyEngine(policy)
        sessions = InMemorySessionRegistry(ttl_seconds=900, idle_timeout_seconds=300)
        auth = ApiKeyAuthenticator({"agent-a": "ck_a", "operator": "ck_o"})
        handshake = HandshakeService(
            authenticator=auth,
            policy_engine=engine,
            session_registry=sessions,
        )
        registry = PendingApprovalRegistry(max_pending=4)
        upstream = AsyncMock()
        upstream.call_tool.return_value = {"ok": True}
        tools = ToolRegistry([{"name": "memory_delete"}])
        audit = AuditLogger()
        app = FastAPI()
        app.include_router(
            build_router(
                handshake=handshake,
                sessions=sessions,
                tool_registry=tools,
                upstream=upstream,
                policy=policy,
                audit=audit,
                engine=engine,
                approval_registry=registry,
                approval_blocking_mode=True,
                approval_timeout_seconds=10.0,
                api_authenticator=auth,
            )
        )
        return app, registry, auth, handshake

    @pytest.mark.asyncio
    async def test_401_without_auth(self, router_with_registry):
        app, _registry, _auth, _handshake = router_with_registry
        import httpx
        from httpx import ASGITransport

        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            resp = await c.post(
                "/approvals",
                json={"approval_id": "x" * 32, "decision": "approve"},
            )
        assert resp.status_code == 401
        assert resp.json() == {"error": "auth_failed"}

    @pytest.mark.asyncio
    async def test_404_for_unknown_id(self, router_with_registry):
        app, _registry, _auth, _handshake = router_with_registry
        import httpx
        from httpx import ASGITransport

        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            resp = await c.post(
                "/approvals",
                headers={"Authorization": "Bearer ck_o"},
                json={"approval_id": "0" * 32, "decision": "approve"},
            )
        assert resp.status_code == 404
        assert resp.json() == {"error": "approval_not_found"}

    @pytest.mark.asyncio
    async def test_404_for_already_resolved(self, router_with_registry):
        app, registry, _auth, _handshake = router_with_registry
        from datetime import UTC, datetime

        from mcp_gateway.approval.models import DecisionStatus
        from mcp_gateway.approval.notifier import ApprovalRequest

        approval_id = await registry.register(
            session_id="s1",
            requester_agent_id="agent-a",
            request=ApprovalRequest(
                session_id="s1",
                approval_id="0" * 32,
                agent_id="agent-a",
                intent="curate_memories",
                tool_name="memory_delete",
                arguments={},
                requested_at=datetime.now(UTC),
            ),
        )
        await registry.resolve(
            approval_id,
            resolver_agent_id="operator",
            status=DecisionStatus.APPROVED,
        )
        await registry.wait_for_decision(approval_id, timeout=0.1)

        import httpx
        from httpx import ASGITransport

        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            resp = await c.post(
                "/approvals",
                headers={"Authorization": "Bearer ck_o"},
                json={"approval_id": approval_id, "decision": "approve"},
            )
        assert resp.status_code == 404
        assert resp.json() == {"error": "approval_not_found"}

    @pytest.mark.asyncio
    async def test_403_for_self_approval(self, router_with_registry):
        app, registry, _auth, _handshake = router_with_registry
        from datetime import UTC, datetime

        from mcp_gateway.approval.notifier import ApprovalRequest

        approval_id = await registry.register(
            session_id="s1",
            requester_agent_id="agent-a",
            request=ApprovalRequest(
                session_id="s1",
                approval_id="0" * 32,
                agent_id="agent-a",
                intent="curate_memories",
                tool_name="memory_delete",
                arguments={},
                requested_at=datetime.now(UTC),
            ),
        )

        import httpx
        from httpx import ASGITransport

        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            resp = await c.post(
                "/approvals",
                headers={"Authorization": "Bearer ck_a"},
                json={"approval_id": approval_id, "decision": "approve"},
            )
        assert resp.status_code == 403
        assert resp.json() == {"error": "self_approval_forbidden"}

    @pytest.mark.asyncio
    async def test_400_for_invalid_decision(self, router_with_registry):
        app, _registry, _auth, _handshake = router_with_registry
        import httpx
        from httpx import ASGITransport

        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            resp = await c.post(
                "/approvals",
                headers={"Authorization": "Bearer ck_o"},
                json={"approval_id": "a" * 32, "decision": "maybe"},
            )
        assert resp.status_code == 400
        assert resp.json() == {"error": "invalid_request"}

    @pytest.mark.asyncio
    async def test_413_for_oversized_body(self, router_with_registry):
        app, _registry, _auth, _handshake = router_with_registry
        import httpx
        from httpx import ASGITransport

        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            resp = await c.post(
                "/approvals",
                headers={"Authorization": "Bearer ck_o"},
                content="x" * 1100,
            )
        assert resp.status_code == 413
        assert resp.json() == {"error": "payload_too_large"}

    @pytest.mark.asyncio
    async def test_200_success_resolution(self, router_with_registry):
        app, registry, _auth, _handshake = router_with_registry
        from datetime import UTC, datetime

        from mcp_gateway.approval.models import DecisionStatus
        from mcp_gateway.approval.notifier import ApprovalRequest

        approval_id = await registry.register(
            session_id="s1",
            requester_agent_id="agent-a",
            request=ApprovalRequest(
                session_id="s1",
                approval_id="0" * 32,
                agent_id="agent-a",
                intent="curate_memories",
                tool_name="memory_delete",
                arguments={},
                requested_at=datetime.now(UTC),
            ),
        )

        import httpx
        from httpx import ASGITransport

        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            resp = await c.post(
                "/approvals",
                headers={"Authorization": "Bearer ck_o"},
                json={"approval_id": approval_id, "decision": "approve", "reason": "verified"},
            )
        assert resp.status_code == 200
        assert resp.json() == {"status": "resolved", "approval_id": approval_id}

        # Verify outcome via registry
        decision = await registry.wait_for_decision(approval_id, timeout=1.0)
        assert decision.status == DecisionStatus.APPROVED

    @pytest.mark.asyncio
    async def test_400_for_invalid_utf8(self, router_with_registry):
        app, _registry, _auth, _handshake = router_with_registry
        import httpx
        from httpx import ASGITransport

        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            resp = await c.post(
                "/approvals",
                headers={"Authorization": "Bearer ck_o"},
                content=b"\xff\xfe\xfd",  # Invalid UTF-8
            )
        assert resp.status_code == 400
        assert resp.json() == {"error": "invalid_request"}

    @pytest.mark.asyncio
    async def test_400_for_non_hex_id(self, router_with_registry):
        app, _registry, _auth, _handshake = router_with_registry
        import httpx
        from httpx import ASGITransport

        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            resp = await c.post(
                "/approvals",
                headers={"Authorization": "Bearer ck_o"},
                json={"approval_id": "Z" * 32, "decision": "approve"},
            )
        assert resp.status_code == 400
        assert resp.json() == {"error": "invalid_request"}

    @pytest.mark.asyncio
    async def test_audit_log_includes_reason_on_rejection(self, router_with_registry, capsys):
        app, registry, _auth, handshake = router_with_registry
        from datetime import UTC, datetime

        from mcp_gateway.approval.notifier import ApprovalRequest

        aid = await registry.register(
            session_id="s1",
            requester_agent_id="agent-a",
            request=ApprovalRequest(
                session_id="s1",
                approval_id="PENDING",
                agent_id="agent-a",
                intent="curate_memories",
                tool_name="memory_delete",
                arguments={},
                requested_at=datetime.now(UTC),
            ),
        )

        import httpx
        from httpx import ASGITransport

        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            resp = await c.post(
                "/approvals",
                headers={"Authorization": "Bearer ck_o"},
                json={
                    "approval_id": aid,
                    "decision": "reject",
                    "reason": "policy violation",
                },
            )
        assert resp.status_code == 200

        captured = capsys.readouterr()
        log_lines = [ln for ln in captured.err.splitlines() if '"ev":"approval_decision"' in ln]
        assert len(log_lines) == 1
        assert '"reason":"policy violation"' in log_lines[0]
        assert '"outcome":"ok"' in log_lines[0]


class TestServerApprovalSuspendE2E:
    @pytest.fixture
    def blocking_app(self, tmp_path, monkeypatch):
        policy = tmp_path / "intents.yaml"
        policy.write_text(
            textwrap.dedent(
                """
                version: 1
                output_filters: {f: {type: none}}
                intents:
                  curate_memories:
                    description: x
                    allowed_tools: [memory_delete]
                    output_filter: f
                    guardrails: {memory_delete: {requires_approval: true}}
                agents:
                  agent-a: {allowed_intents: [curate_memories]}
                  operator: {allowed_intents: [curate_memories]}
                """
            ).lstrip()
        )
        monkeypatch.setenv("MCP_GATEWAY_POLICY_PATH", str(policy))
        monkeypatch.setenv(
            "MCP_GATEWAY_API_KEYS_JSON",
            '{"agent-a":"ck_x","operator":"ck_o"}',
        )
        monkeypatch.setenv("MCP_GATEWAY_APPROVAL_BLOCKING_MODE", "true")
        monkeypatch.setenv("MCP_GATEWAY_APPROVAL_TIMEOUT_SECONDS", "5")

        from unittest.mock import AsyncMock

        from mcp_gateway.app import build_app

        upstream = AsyncMock()
        upstream.list_tools.return_value = [{"name": "memory_delete"}]
        upstream.call_tool.return_value = {"ok": True}
        app = build_app(
            upstream_override=upstream,
            initial_tools=upstream.list_tools.return_value,
        )
        app.state.upstream = upstream
        return app

    async def _start_pending_call(self, client, sid: str, registry):
        call_task = asyncio.create_task(
            client.post(
                f"/messages?session_id={sid}",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "memory_delete", "arguments": {}},
                },
            )
        )
        for _ in range(100):
            await asyncio.sleep(0.01)
            # 特定の sid に対する保留中のリクエストが登録されるのを待つ
            if any(p.session_id == sid for p in registry._pending.values()):
                return call_task
            if call_task.done():
                # すでに終了している場合はエラー（サスペンドしなかった）
                break

        raise AssertionError(f"tools/call did not suspend for approval (sid={sid})")

    @pytest.mark.asyncio
    async def test_approve_invokes_upstream_and_returns_result(self, blocking_app):
        import httpx
        from httpx import ASGITransport

        registry = blocking_app.state.approval_registry
        async with httpx.AsyncClient(
            transport=ASGITransport(app=blocking_app),
            base_url="http://t",
        ) as client:
            sid = await _get_sse_session_id(client, intent="curate_memories")
            call_task = await self._start_pending_call(client, sid, registry)
            approval_ids = await registry.get_pending_ids_for_session(sid)
            approval_id = approval_ids[0]
            resp = await client.post(
                "/approvals",
                headers={"Authorization": "Bearer ck_o"},
                json={"approval_id": approval_id, "decision": "approve"},
            )
            assert resp.status_code == 200
            call_resp = await call_task

        assert call_resp.json()["result"] == {"ok": True}
        blocking_app.state.upstream.call_tool.assert_called_once_with("memory_delete", {})

    @pytest.mark.asyncio
    async def test_reject_returns_32002_without_upstream_call(self, blocking_app):
        import httpx
        from httpx import ASGITransport

        registry = blocking_app.state.approval_registry
        async with httpx.AsyncClient(
            transport=ASGITransport(app=blocking_app),
            base_url="http://t",
        ) as client:
            sid = await _get_sse_session_id(client, intent="curate_memories")
            call_task = await self._start_pending_call(client, sid, registry)
            approval_ids = await registry.get_pending_ids_for_session(sid)
            approval_id = approval_ids[0]
            resp = await client.post(
                "/approvals",
                headers={"Authorization": "Bearer ck_o"},
                json={"approval_id": approval_id, "decision": "reject"},
            )
            assert resp.status_code == 200
            call_resp = await call_task

        body = call_resp.json()
        assert body["error"]["code"] == -32002
        assert body["error"]["message"] == "approval_rejected"
        blocking_app.state.upstream.call_tool.assert_not_called()

    @pytest.mark.asyncio
    async def test_timeout_returns_32003_without_upstream_call(self, tmp_path, monkeypatch):
        policy = tmp_path / "intents.yaml"
        policy.write_text(
            textwrap.dedent(
                """
                version: 1
                output_filters: {f: {type: none}}
                intents:
                  curate_memories:
                    description: x
                    allowed_tools: [memory_delete]
                    output_filter: f
                    guardrails: {memory_delete: {requires_approval: true}}
                agents:
                  agent-a: {allowed_intents: [curate_memories]}
                """
            ).lstrip()
        )
        monkeypatch.setenv("MCP_GATEWAY_POLICY_PATH", str(policy))
        monkeypatch.setenv("MCP_GATEWAY_API_KEYS_JSON", '{"agent-a":"ck_x"}')
        monkeypatch.setenv("MCP_GATEWAY_APPROVAL_BLOCKING_MODE", "true")
        monkeypatch.setenv("MCP_GATEWAY_APPROVAL_TIMEOUT_SECONDS", "0.05")

        from unittest.mock import AsyncMock

        from mcp_gateway.app import build_app

        upstream = AsyncMock()
        upstream.list_tools.return_value = [{"name": "memory_delete"}]
        upstream.call_tool.return_value = {"ok": True}
        app = build_app(
            upstream_override=upstream,
            initial_tools=upstream.list_tools.return_value,
        )

        import httpx
        from httpx import ASGITransport

        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t"
        ) as client:
            sid = await _get_sse_session_id(client, intent="curate_memories")
            resp = await client.post(
                f"/messages?session_id={sid}",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "memory_delete", "arguments": {}},
                },
            )

        body = resp.json()
        assert body["error"]["code"] == -32003
        assert body["error"]["message"] == "approval_timeout"
        upstream.call_tool.assert_not_called()

    @pytest.mark.asyncio
    async def test_session_eviction_cancels_pending(self, blocking_app):
        import httpx
        from httpx import ASGITransport

        registry = blocking_app.state.approval_registry
        sessions = blocking_app.state.sessions
        async with httpx.AsyncClient(
            transport=ASGITransport(app=blocking_app),
            base_url="http://t",
        ) as client:
            sid = await _get_sse_session_id(client, intent="curate_memories")
            call_task = await self._start_pending_call(client, sid, registry)

            sessions.remove(sid)
            # 退避処理（cancel_session）が非同期に完了するのを待機
            for _ in range(50):
                ids = await registry.get_pending_ids_for_session(sid)
                if not ids:
                    break
                await asyncio.sleep(0.01)
            else:
                raise AssertionError(f"Session {sid} was not evicted from registry")

            resp = await call_task

        assert resp.status_code == 200
        body = resp.json()
        assert body["error"]["code"] == -32004
        assert body["error"]["message"] == "session_expired"


class TestServerValidationDeny:
    @pytest.fixture
    def validation_app(self, tmp_path, monkeypatch):
        policy = tmp_path / "intents.yaml"
        policy.write_text(
            textwrap.dedent(
                """
                version: 1
                output_filters:
                  f:
                    type: none
                intents:
                  ro:
                    description: "x"
                    allowed_tools: [memory_search]
                    output_filter: f
                    guardrails:
                      memory_search:
                        params:
                          query:
                            type: string
                            max_length: 3
                          secret:
                            forbidden: true
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
        upstream.list_tools.return_value = [{"name": "memory_search"}]
        return build_app(
            upstream_override=upstream,
            initial_tools=upstream.list_tools.return_value,
        )

    @pytest_asyncio.fixture
    async def validation_client(self, validation_app):
        import httpx
        from httpx import ASGITransport

        transport = ASGITransport(app=validation_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            yield client

    @pytest.fixture
    def allow_app_with_upstream(self, tmp_path, monkeypatch):
        policy = tmp_path / "intents.yaml"
        policy.write_text(
            textwrap.dedent(
                """
                version: 1
                output_filters:
                  f:
                    type: none
                intents:
                  ro:
                    description: "x"
                    allowed_tools: [memory_search]
                    output_filter: f
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
        upstream.list_tools.return_value = [{"name": "memory_search"}]
        upstream.call_tool.return_value = {"ok": True}
        app = build_app(
            upstream_override=upstream,
            initial_tools=upstream.list_tools.return_value,
        )
        return app, upstream

    @pytest_asyncio.fixture
    async def allow_client_with_upstream(self, allow_app_with_upstream):
        import httpx
        from httpx import ASGITransport

        app, upstream = allow_app_with_upstream
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            yield client, upstream

    @pytest.mark.asyncio
    async def test_param_validation_denied_returns_32602(self, validation_client):
        sid = await _get_sse_session_id(validation_client, intent="ro")
        resp = await validation_client.post(
            f"/messages?session_id={sid}",
            json={
                "jsonrpc": "2.0",
                "id": 10,
                "method": "tools/call",
                "params": {"name": "memory_search", "arguments": {"query": "abcd"}},
            },
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["error"]["code"] == -32602
        assert body["error"]["message"] == "param_too_long:query"

    @pytest.mark.asyncio
    async def test_forbidden_param_validation_denied_returns_32602(self, validation_client):
        sid = await _get_sse_session_id(validation_client, intent="ro")
        resp = await validation_client.post(
            f"/messages?session_id={sid}",
            json={
                "jsonrpc": "2.0",
                "id": 11,
                "method": "tools/call",
                "params": {"name": "memory_search", "arguments": {"secret": "query"}},
            },
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["error"]["code"] == -32602
        assert body["error"]["message"] == "forbidden_param:secret"

    @pytest.mark.asyncio
    async def test_allow_secret_args_denied_before_upstream_call(self, allow_client_with_upstream):
        client, upstream = allow_client_with_upstream

        sid = await _get_sse_session_id(client, intent="ro")
        resp = await client.post(
            f"/messages?session_id={sid}",
            json={
                "jsonrpc": "2.0",
                "id": 12,
                "method": "tools/call",
                "params": {
                    "name": "memory_search",
                    "arguments": {"token": "sk-1234567890abcdef"},
                },
            },
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["error"]["code"] == -32601
        assert body["error"]["message"] == "tool not found"
        upstream.call_tool.assert_not_awaited()


class TestEntrypoint:
    def test_main_callable(self, monkeypatch):
        from unittest.mock import patch

        import mcp_gateway.__main__ as entry

        # Ensure environment variables don't interfere with the test
        monkeypatch.delenv("MCP_GATEWAY_HOST", raising=False)
        monkeypatch.delenv("MCP_GATEWAY_PORT", raising=False)

        with patch("uvicorn.run") as run:
            entry.main()
        run.assert_called_once_with(
            "mcp_gateway.app:build_app",
            factory=True,
            host="127.0.0.1",
            port=9100,
            log_level="info",
        )

    def test_build_app_uses_as_file_for_packaged_sample_policy(self, monkeypatch, tmp_path):
        from contextlib import contextmanager
        from unittest.mock import AsyncMock

        import mcp_gateway.app as app_module

        policy = tmp_path / "intents.example.yaml"
        policy.write_text(
            "\n".join(
                [
                    "version: 1",
                    "output_filters: {none: {type: none}}",
                    (
                        "intents: {read_only_recall: {description: x, "
                        "allowed_tools: [memory_search], output_filter: none}}"
                    ),
                    "agents: {summarizer-bot: {allowed_intents: [read_only_recall]}}",
                    "",
                ]
            )
        )

        class FakePackage:
            def __init__(self, resource):
                self._resource = resource

            def joinpath(self, path):
                assert path == "policies/intents.example.yaml"
                return self._resource

        resource = object()
        used_as_file = False

        @contextmanager
        def fake_as_file(traversable):
            nonlocal used_as_file
            assert traversable is resource
            used_as_file = True
            yield policy

        monkeypatch.delenv("MCP_GATEWAY_POLICY_PATH", raising=False)
        monkeypatch.setattr(app_module, "files", lambda package: FakePackage(resource))
        monkeypatch.setattr(app_module, "as_file", fake_as_file, raising=False)

        upstream = AsyncMock()
        upstream.list_tools.return_value = []

        app = app_module.build_app(upstream_override=upstream, initial_tools=[])

        assert app is not None
        assert used_as_file is True

    def test_build_app_prefers_env_file_policy_path_with_upstream_override(
        self, monkeypatch, tmp_path
    ):
        from unittest.mock import AsyncMock

        policy = tmp_path / "env-policy.yaml"
        policy.write_text(
            "\n".join(
                [
                    "version: 1",
                    "output_filters: {none: {type: none}}",
                    (
                        "intents: {read_only_recall: {description: x, "
                        "allowed_tools: [memory_search], output_filter: none}}"
                    ),
                    "agents: {summarizer-bot: {allowed_intents: [read_only_recall]}}",
                    "",
                ]
            )
        )
        (tmp_path / ".env").write_text(f"MCP_GATEWAY_POLICY_PATH={policy}\n")

        # Move chdir before import
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("MCP_GATEWAY_POLICY_PATH", raising=False)

        import mcp_gateway.app as app_module

        monkeypatch.setattr(
            app_module,
            "as_file",
            lambda traversable: (_ for _ in ()).throw(
                AssertionError("sample policy should not be used")
            ),
            raising=False,
        )

        upstream = AsyncMock()
        upstream.list_tools.return_value = []

        app = app_module.build_app(upstream_override=upstream, initial_tools=[])

        assert app is not None


class TestSamplePolicy:
    def test_sample_policy_is_valid(self):
        from importlib.resources import files

        from mcp_gateway.policy.loader import load_policy

        path = files("mcp_gateway").joinpath("policies/intents.example.yaml")
        policy = load_policy(path)  # type: ignore[arg-type]
        assert policy.version == 1
        assert "read_only_recall" in policy.intents
        assert "summarizer-bot" in policy.agents
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
        import importlib.util
        import pkgutil

        import mcp_gateway

        bad: list[str] = []
        for mod_info in pkgutil.walk_packages(mcp_gateway.__path__, prefix="mcp_gateway."):
            spec = importlib.util.find_spec(mod_info.name)
            if spec is None:
                continue

            src = spec.origin
            if src is None and spec.loader is not None and hasattr(spec.loader, "get_filename"):
                try:
                    src = spec.loader.get_filename(mod_info.name)
                except (ImportError, OSError):
                    continue

            if src in {None, "built-in", "frozen"}:
                continue

            import ast

            with open(src, encoding="utf-8") as handle:
                text = handle.read()
            try:
                # Pass filename for better error reporting in AST
                tree = ast.parse(text, filename=src)
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "context_store" or alias.name.startswith("context_store."):
                            bad.append(f"{mod_info.name}: import {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    # Check module name
                    is_bad = node.module == "context_store" or (
                        node.module and node.module.startswith("context_store.")
                    )
                    # Check aliases (e.g., from x import context_store)
                    if not is_bad:
                        for alias in node.names:
                            if alias.name == "context_store" or alias.name.startswith(
                                "context_store."
                            ):
                                is_bad = True
                                break
                    if is_bad:
                        bad.append(f"{mod_info.name}: from {node.module or ''} import ...")
        assert bad == [], f"mcp_gateway imports context_store directly: {bad}"


class TestIBACModels:
    """ParamConstraint / ToolGuardrail / IntentPolicy.guardrails の単体テスト。"""

    def test_param_constraint_defaults(self):
        from mcp_gateway.policy.models import ParamConstraint

        c = ParamConstraint()
        assert c.type is None
        assert c.max_length is None
        assert c.pattern is None
        assert c.allowed_values is None
        assert c.forbidden is False

    def test_param_constraint_accepts_all_fields(self):
        from mcp_gateway.policy.models import ParamConstraint

        c = ParamConstraint(
            type="string", max_length=100, pattern="^[a-z]+$", allowed_values=["foo"]
        )
        assert c.type == "string"
        assert c.max_length == 100
        assert c.pattern == "^[a-z]+$"
        assert c.allowed_values == ["foo"]

    def test_tool_guardrail_defaults(self):
        from mcp_gateway.policy.models import ToolGuardrail

        g = ToolGuardrail()
        assert g.params == {}
        assert g.requires_approval is False

    def test_intent_policy_accepts_guardrails(self):
        from mcp_gateway.policy.models import IntentPolicy, ParamConstraint, ToolGuardrail

        p = IntentPolicy(
            description="test",
            allowed_tools=["tool_a"],
            output_filter="f",
            guardrails={
                "tool_a": ToolGuardrail(
                    params={"q": ParamConstraint(type="string", max_length=512)},
                    requires_approval=False,
                )
            },
        )
        assert "tool_a" in p.guardrails
        assert p.guardrails["tool_a"].params["q"].max_length == 512

    def test_verify_references_guardrail_key_not_in_allowed_tools(self):
        from mcp_gateway.policy.models import GatewayPolicy

        with pytest.raises(ValidationError, match="guardrail"):
            GatewayPolicy.model_validate(
                {
                    "version": 1,
                    "output_filters": {"f": {"type": "none"}},
                    "intents": {
                        "intent_a": {
                            "description": "x",
                            "allowed_tools": ["tool_a"],
                            "output_filter": "f",
                            "guardrails": {"unlisted_tool": {}},
                        }
                    },
                    "agents": {},
                }
            )

    def test_verify_references_pattern_without_max_length_raises(self):
        from mcp_gateway.policy.models import GatewayPolicy

        with pytest.raises(ValidationError, match="pattern requires max_length"):
            GatewayPolicy.model_validate(
                {
                    "version": 1,
                    "output_filters": {"f": {"type": "none"}},
                    "intents": {
                        "intent_a": {
                            "description": "x",
                            "allowed_tools": ["tool_a"],
                            "output_filter": "f",
                            "guardrails": {
                                "tool_a": {
                                    "params": {"query": {"type": "string", "pattern": "^[a-z]+$"}}
                                }
                            },
                        }
                    },
                    "agents": {},
                }
            )

    def test_verify_references_pattern_too_long_raises(self):
        from mcp_gateway.policy.models import GatewayPolicy

        with pytest.raises(ValidationError, match="pattern exceeds 200 chars"):
            GatewayPolicy.model_validate(
                {
                    "version": 1,
                    "output_filters": {"f": {"type": "none"}},
                    "intents": {
                        "intent_a": {
                            "description": "x",
                            "allowed_tools": ["tool_a"],
                            "output_filter": "f",
                            "guardrails": {
                                "tool_a": {
                                    "params": {
                                        "query": {
                                            "type": "string",
                                            "pattern": "a" * 201,
                                            "max_length": 512,
                                        }
                                    }
                                }
                            },
                        }
                    },
                    "agents": {},
                }
            )

    def test_verify_references_pattern_empty_string_requires_max_length(self):
        from mcp_gateway.policy.models import GatewayPolicy

        with pytest.raises(ValidationError, match="pattern requires max_length"):
            GatewayPolicy.model_validate(
                {
                    "version": 1,
                    "output_filters": {"f": {"type": "none"}},
                    "intents": {
                        "intent_a": {
                            "description": "x",
                            "allowed_tools": ["tool_a"],
                            "output_filter": "f",
                            "guardrails": {
                                "tool_a": {"params": {"query": {"type": "string", "pattern": ""}}}
                            },
                        }
                    },
                    "agents": {},
                }
            )

    def test_verify_references_valid_guardrail_passes(self):
        from mcp_gateway.policy.models import GatewayPolicy

        policy = GatewayPolicy.model_validate(
            {
                "version": 1,
                "output_filters": {"f": {"type": "none"}},
                "intents": {
                    "intent_a": {
                        "description": "x",
                        "allowed_tools": ["tool_a"],
                        "output_filter": "f",
                        "guardrails": {
                            "tool_a": {
                                "params": {
                                    "query": {
                                        "type": "string",
                                        "max_length": 512,
                                        "pattern": "^[^<>]+$",
                                    }
                                },
                                "requires_approval": False,
                            }
                        },
                    }
                },
                "agents": {},
            }
        )
        assert "tool_a" in policy.intents["intent_a"].guardrails


class TestRuntimeValidation:
    def test_validate_call_forbidden(self):
        from mcp_gateway.errors import PolicyError
        from mcp_gateway.policy.engine import PolicyEngine
        from mcp_gateway.policy.models import ParamConstraint, ToolGuardrail

        guardrail = ToolGuardrail(params={"secret": ParamConstraint(forbidden=True)})
        with pytest.raises(PolicyError, match="parameter 'secret' is forbidden"):
            PolicyEngine.validate_call(
                tool_name="test", arguments={"secret": "val"}, guardrail=guardrail
            )

    def test_validate_call_type_mismatch(self):
        from mcp_gateway.errors import PolicyError
        from mcp_gateway.policy.engine import PolicyEngine
        from mcp_gateway.policy.models import ParamConstraint, ToolGuardrail

        guardrail = ToolGuardrail(params={"count": ParamConstraint(type="integer")})
        with pytest.raises(PolicyError, match="must be integer"):
            PolicyEngine.validate_call(
                tool_name="test", arguments={"count": "not_int"}, guardrail=guardrail
            )

    def test_validate_call_allowed_values(self):
        from mcp_gateway.errors import PolicyError
        from mcp_gateway.policy.engine import PolicyEngine
        from mcp_gateway.policy.models import ParamConstraint, ToolGuardrail

        guardrail = ToolGuardrail(
            params={"color": ParamConstraint(type="string", allowed_values=["red", "blue"])}
        )
        # Valid
        PolicyEngine.validate_call(
            tool_name="test", arguments={"color": "red"}, guardrail=guardrail
        )
        # Invalid
        with pytest.raises(PolicyError, match="has invalid value 'green'"):
            PolicyEngine.validate_call(
                tool_name="test", arguments={"color": "green"}, guardrail=guardrail
            )

    def test_validate_call_max_length(self):
        from mcp_gateway.errors import PolicyError
        from mcp_gateway.policy.engine import PolicyEngine
        from mcp_gateway.policy.models import ParamConstraint, ToolGuardrail

        guardrail = ToolGuardrail(params={"name": ParamConstraint(type="string", max_length=5)})
        # Valid
        PolicyEngine.validate_call(tool_name="test", arguments={"name": "abc"}, guardrail=guardrail)
        # Invalid
        with pytest.raises(PolicyError, match="exceeds max_length"):
            PolicyEngine.validate_call(
                tool_name="test", arguments={"name": "abcdef"}, guardrail=guardrail
            )

    def test_validate_call_pattern(self):
        from mcp_gateway.errors import PolicyError
        from mcp_gateway.policy.engine import PolicyEngine
        from mcp_gateway.policy.models import ParamConstraint, ToolGuardrail

        guardrail = ToolGuardrail(
            params={"id": ParamConstraint(type="string", pattern="^ID-[0-9]+$", max_length=10)}
        )
        # Valid
        PolicyEngine.validate_call(
            tool_name="test", arguments={"id": "ID-123"}, guardrail=guardrail
        )
        # Invalid
        with pytest.raises(PolicyError, match="does not match required pattern"):
            PolicyEngine.validate_call(
                tool_name="test", arguments={"id": "abc"}, guardrail=guardrail
            )

    def test_validate_call_requires_approval(self):
        from mcp_gateway.errors import PolicyError
        from mcp_gateway.policy.engine import PolicyEngine
        from mcp_gateway.policy.models import ToolGuardrail

        guardrail = ToolGuardrail(requires_approval=True)
        with pytest.raises(PolicyError, match="requires manual approval"):
            PolicyEngine.validate_call(
                tool_name="restricted_tool", arguments={}, guardrail=guardrail
            )

    def test_validate_call_numeric_bool_rejection(self):
        from mcp_gateway.errors import PolicyError
        from mcp_gateway.policy.engine import PolicyEngine
        from mcp_gateway.policy.models import ParamConstraint, ToolGuardrail

        # Integer constraint
        guardrail_int = ToolGuardrail(params={"age": ParamConstraint(type="integer")})
        with pytest.raises(PolicyError, match="must be integer, got boolean"):
            PolicyEngine.validate_call(
                tool_name="test", arguments={"age": True}, guardrail=guardrail_int
            )

        # Number constraint
        guardrail_num = ToolGuardrail(params={"price": ParamConstraint(type="number")})
        with pytest.raises(PolicyError, match="must be number, got boolean"):
            PolicyEngine.validate_call(
                tool_name="test", arguments={"price": False}, guardrail=guardrail_num
            )


class TestApprovalNotifier:
    """LogOnlyApprovalNotifier の単体テスト。"""

    @pytest.mark.asyncio
    async def test_request_approval_does_not_raise(self):
        from datetime import UTC, datetime

        from mcp_gateway.approval.notifier import ApprovalRequest, LogOnlyApprovalNotifier

        notifier = LogOnlyApprovalNotifier()
        req = ApprovalRequest(
            session_id="sid-001",
            approval_id="0" * 32,
            agent_id="agent-a",
            intent="curate_memories",
            tool_name="memory_delete",
            arguments={"id": "m-xyz"},
            requested_at=datetime(2026, 5, 5, 12, 0, 0, tzinfo=UTC),
        )
        await notifier.request_approval(req)

    def test_approval_request_is_immutable(self):
        from datetime import UTC, datetime

        from pydantic import ValidationError

        from mcp_gateway.approval.notifier import ApprovalRequest

        req = ApprovalRequest(
            session_id="s",
            approval_id="0" * 32,
            agent_id="a",
            intent="i",
            tool_name="t",
            arguments={},
            requested_at=datetime.now(UTC),
        )
        with pytest.raises(ValidationError):
            req.session_id = "mutated"  # type: ignore[misc]

    def test_approval_notifier_is_abstract(self):
        from mcp_gateway.approval.notifier import ApprovalNotifier

        with pytest.raises(TypeError):
            ApprovalNotifier()  # type: ignore[abstract]

    @pytest.mark.asyncio
    async def test_request_approval_logs(self, caplog):
        import logging
        from datetime import UTC, datetime

        from mcp_gateway.approval.notifier import ApprovalRequest, LogOnlyApprovalNotifier

        notifier = LogOnlyApprovalNotifier()
        req = ApprovalRequest(
            session_id="sid-log",
            approval_id="0" * 32,
            agent_id="agent-b",
            intent="curate_memories",
            tool_name="memory_delete",
            arguments={"id": "m-abc"},
            requested_at=datetime.now(UTC),
        )
        with caplog.at_level(logging.INFO, logger="mcp_gateway.approval.notifier"):
            await notifier.request_approval(req)
        assert any("approval_required" in record.message for record in caplog.records)

    @pytest.mark.asyncio
    async def test_request_approval_logs_masking(self, caplog):
        """機密情報がログ出力時にマスクされることを検証します。"""
        import logging
        from datetime import UTC, datetime

        from mcp_gateway.approval.notifier import ApprovalRequest, LogOnlyApprovalNotifier

        notifier = LogOnlyApprovalNotifier()
        req = ApprovalRequest(
            session_id="sid-mask",
            approval_id="0" * 32,
            agent_id="agent-c",
            intent="sensitive_op",
            tool_name="auth_tool",
            arguments={
                "api_key": "secret123",
                "user_password": "mypassword",
                "auth_token": "token456",
                "safe_param": "visible",
            },
            requested_at=datetime.now(UTC),
        )
        with caplog.at_level(logging.INFO, logger="mcp_gateway.approval.notifier"):
            await notifier.request_approval(req)

        log_records = [r.message for r in caplog.records if "approval_required" in r.message]
        assert len(log_records) == 1
        log_msg = log_records[0]

        # 完全一致および部分一致でのマスクを確認
        assert "'api_key': '**********'" in log_msg
        assert "'user_password': '**********'" in log_msg
        assert "'auth_token': '**********'" in log_msg
        assert "'safe_param': 'visible'" in log_msg

        # 生の値が残っていないことを確認
        assert "secret123" not in log_msg
        assert "mypassword" not in log_msg
        assert "token456" not in log_msg


class TestParamConstraint:
    """evaluate_call() を通じたパラメータ制約の動作テスト。"""

    def _make_engine(
        self,
        tool_name: str,
        params: dict,
        *,
        requires_approval: bool = False,
        intent: str = "test_intent",
    ):
        from mcp_gateway.policy.engine import PolicyEngine
        from mcp_gateway.policy.models import (
            AgentPolicy,
            GatewayPolicy,
            IntentPolicy,
            OutputFilterDef,
        )

        policy = GatewayPolicy(
            version=1,
            output_filters={"f": OutputFilterDef(type="none")},
            intents={
                intent: IntentPolicy(
                    description="test",
                    allowed_tools=[tool_name],
                    output_filter="f",
                    guardrails={
                        tool_name: {
                            "params": params,
                            "requires_approval": requires_approval,
                        }
                    },
                )
            },
            agents={"agent-a": AgentPolicy(allowed_intents=[intent])},
        )
        return PolicyEngine(policy)

    def _call(self, engine, tool_name, arguments, intent="test_intent", requested_tools=None):
        # For testing, we create a grant assuming intent is allowed for agent-a
        grant = engine.evaluate_grant(
            agent_id="agent-a", intent=intent, requested_tools=requested_tools
        )
        # Note: testing caps filtering here is bypassed, but evaluated specifically
        # in TestEvaluateCall
        return engine.evaluate_call(
            grant=grant,
            tool_name=tool_name,
            arguments=arguments,
        )

    def test_max_length_boundary_allow(self):
        engine = self._make_engine(
            "memory_search", {"query": {"type": "string", "max_length": 512}}
        )
        result = self._call(engine, "memory_search", {"query": "a" * 512})
        assert result.status == "ALLOW"

    def test_max_length_exceeded_deny(self):
        engine = self._make_engine(
            "memory_search", {"query": {"type": "string", "max_length": 512}}
        )
        result = self._call(engine, "memory_search", {"query": "a" * 513})
        assert result.status == "DENY"
        assert result.reason == "param_too_long:query"

    def test_max_length_empty_string_allow(self):
        engine = self._make_engine(
            "memory_search", {"query": {"type": "string", "max_length": 512}}
        )
        result = self._call(engine, "memory_search", {"query": ""})
        assert result.status == "ALLOW"

    def test_pattern_full_match_allow(self):
        engine = self._make_engine(
            "memory_search",
            {"query": {"type": "string", "max_length": 100, "pattern": "^[a-z_]+$"}},
        )
        result = self._call(engine, "memory_search", {"query": "hello_world"})
        assert result.status == "ALLOW"

    def test_pattern_partial_match_deny(self):
        engine = self._make_engine(
            "memory_search",
            {"query": {"type": "string", "max_length": 100, "pattern": "^[a-z_]+$"}},
        )
        result = self._call(engine, "memory_search", {"query": "hello world!"})
        assert result.status == "DENY"
        assert result.reason == "param_pattern_mismatch:query"

    def test_pattern_script_injection_deny(self):
        engine = self._make_engine(
            "memory_search",
            {"query": {"type": "string", "max_length": 100, "pattern": "^[^<>{};]*$"}},
        )
        result = self._call(engine, "memory_search", {"query": "<script>alert(1)</script>"})
        assert result.status == "DENY"
        assert result.reason == "param_pattern_mismatch:query"

    def test_pattern_unicode_deny(self):
        engine = self._make_engine(
            "memory_search",
            {"query": {"type": "string", "max_length": 100, "pattern": "^[a-z_]+$"}},
        )
        result = self._call(engine, "memory_search", {"query": "こんにちは"})
        assert result.status == "DENY"
        assert result.reason == "param_pattern_mismatch:query"

    def test_allowed_values_in_list_allow(self):
        engine = self._make_engine(
            "memory_search", {"mode": {"type": "string", "allowed_values": ["read", "write"]}}
        )
        result = self._call(engine, "memory_search", {"mode": "read"})
        assert result.status == "ALLOW"

    def test_allowed_values_not_in_list_deny(self):
        engine = self._make_engine(
            "memory_search", {"mode": {"type": "string", "allowed_values": ["read", "write"]}}
        )
        result = self._call(engine, "memory_search", {"mode": "admin"})
        assert result.status == "DENY"
        assert result.reason == "param_not_in_allowed_values:mode"

    def test_forbidden_param_present_deny(self):
        engine = self._make_engine("memory_search", {"secret": {"forbidden": True}})
        result = self._call(engine, "memory_search", {"secret": "x"})
        assert result.status == "DENY"
        assert result.reason == "forbidden_param:secret"

    def test_forbidden_param_absent_allow(self):
        engine = self._make_engine("memory_search", {"secret": {"forbidden": True}})
        result = self._call(engine, "memory_search", {"query": "hi"})
        assert result.status == "ALLOW"

    def test_missing_constrained_param_allow(self):
        engine = self._make_engine(
            "memory_search", {"query": {"type": "string", "max_length": 512}}
        )
        result = self._call(engine, "memory_search", {})
        assert result.status == "ALLOW"

    def test_type_mismatch_int_for_string_constraint_deny(self):
        engine = self._make_engine(
            "memory_search", {"query": {"type": "string", "max_length": 512, "pattern": "^[a-z]+$"}}
        )
        result = self._call(engine, "memory_search", {"query": 12345})
        assert result.status == "DENY"
        assert result.reason == "param_type_mismatch:query"

    def test_type_string_explicit_int_deny(self):
        engine = self._make_engine("memory_search", {"query": {"type": "string"}})
        result = self._call(engine, "memory_search", {"query": 12345})
        assert result.status == "DENY"
        assert result.reason == "param_type_mismatch:query"

    def test_type_integer_bool_excluded_deny(self):
        engine = self._make_engine("memory_search", {"count": {"type": "integer"}})
        result = self._call(engine, "memory_search", {"count": True})
        assert result.status == "DENY"
        assert result.reason == "param_type_mismatch:count"

    def test_type_string_correct_allow(self):
        engine = self._make_engine("memory_search", {"query": {"type": "string"}})
        result = self._call(engine, "memory_search", {"query": "safe"})
        assert result.status == "ALLOW"

    def test_type_inference_max_length_allow(self):
        # type is None, but max_length is set -> infer string
        engine = self._make_engine("memory_search", {"query": {"max_length": 512}})
        result = self._call(engine, "memory_search", {"query": "valid string"})
        assert result.status == "ALLOW"

    def test_type_inference_max_length_deny(self):
        # type is None, but max_length is set -> infer string.
        # Should deny if an integer is passed.
        engine = self._make_engine("memory_search", {"query": {"max_length": 512}})
        result = self._call(engine, "memory_search", {"query": 12345})
        assert result.status == "DENY"
        assert result.reason == "param_type_mismatch:query"

    def test_type_inference_pattern_allow(self):
        # type is None, but pattern is set -> infer string
        engine = self._make_engine(
            "memory_search", {"query": {"max_length": 100, "pattern": "^[a-z]+$"}}
        )
        result = self._call(engine, "memory_search", {"query": "match"})
        assert result.status == "ALLOW"

    def test_type_inference_pattern_deny(self):
        # type is None, but pattern is set -> infer string.
        # Should deny if a non-matching string is passed.
        engine = self._make_engine(
            "memory_search", {"query": {"max_length": 100, "pattern": "^[a-z]+$"}}
        )
        result = self._call(engine, "memory_search", {"query": "123"})
        assert result.status == "DENY"
        assert result.reason == "param_pattern_mismatch:query"


class TestEvaluateCall:
    """evaluate_call() 分岐全網羅テスト。"""

    def _policy(self):
        from mcp_gateway.policy.models import (
            AgentPolicy,
            GatewayPolicy,
            IntentPolicy,
            OutputFilterDef,
            ParamConstraint,
            ToolGuardrail,
        )

        return GatewayPolicy(
            version=1,
            output_filters={"f": OutputFilterDef(type="none")},
            intents={
                "read_only_recall": IntentPolicy(
                    description="x",
                    allowed_tools=["memory_search", "memory_stats"],
                    output_filter="f",
                    guardrails={
                        "memory_search": ToolGuardrail(
                            params={
                                "query": ParamConstraint(
                                    type="string",
                                    max_length=512,
                                    pattern="^[^<>]*$",
                                )
                            },
                            requires_approval=False,
                        )
                    },
                ),
                "curate_memories": IntentPolicy(
                    description="y",
                    allowed_tools=["memory_delete"],
                    output_filter="f",
                    guardrails={"memory_delete": ToolGuardrail(requires_approval=True)},
                ),
            },
            agents={
                "agent-a": AgentPolicy(allowed_intents=["read_only_recall", "curate_memories"])
            },
        )

    def _engine(self):
        from mcp_gateway.policy.engine import PolicyEngine

        return PolicyEngine(self._policy())

    def test_tool_not_in_caps_deny(self):
        eng = self._engine()
        # intent 'read_only_recall' allows memory_search and memory_stats
        grant = eng.evaluate_grant(
            agent_id="agent-a",
            intent="read_only_recall",
            requested_tools=frozenset(["memory_search"]),
        )
        result = eng.evaluate_call(
            grant=grant,
            tool_name="memory_stats",  # allowed by intent, but not in grant caps
            arguments={},
        )
        assert result.status == "DENY"
        assert result.reason == "tool_not_in_caps"

    def test_no_guardrail_allow(self):
        eng = self._engine()
        grant = eng.evaluate_grant(
            agent_id="agent-a",
            intent="read_only_recall",
            requested_tools=frozenset(["memory_stats"]),
        )
        result = eng.evaluate_call(
            grant=grant,
            tool_name="memory_stats",
            arguments={},
        )
        assert result.status == "ALLOW"

    def test_all_constraints_pass_allow(self):
        eng = self._engine()
        grant = eng.evaluate_grant(
            agent_id="agent-a",
            intent="read_only_recall",
            requested_tools=frozenset(["memory_search"]),
        )
        result = eng.evaluate_call(
            grant=grant,
            tool_name="memory_search",
            arguments={"query": "safe query"},
        )
        assert result.status == "ALLOW"

    def test_requires_approval_only_params_empty(self):
        eng = self._engine()
        grant = eng.evaluate_grant(
            agent_id="agent-a",
            intent="curate_memories",
            requested_tools=frozenset(["memory_delete"]),
        )
        result = eng.evaluate_call(
            grant=grant,
            tool_name="memory_delete",
            arguments={},
        )
        assert result.status == "REQUIRES_APPROVAL"
        assert result.reason == "requires_approval"

    def test_param_violation_beats_requires_approval(self):
        from mcp_gateway.policy.engine import PolicyEngine
        from mcp_gateway.policy.models import (
            AgentPolicy,
            GatewayPolicy,
            IntentPolicy,
            OutputFilterDef,
            ParamConstraint,
            ToolGuardrail,
        )

        policy = GatewayPolicy(
            version=1,
            output_filters={"f": OutputFilterDef(type="none")},
            intents={
                "intent_x": IntentPolicy(
                    description="x",
                    allowed_tools=["tool_a"],
                    output_filter="f",
                    guardrails={
                        "tool_a": ToolGuardrail(
                            params={"query": ParamConstraint(type="string", max_length=512)},
                            requires_approval=True,
                        )
                    },
                )
            },
            agents={"agent-a": AgentPolicy(allowed_intents=["intent_x"])},
        )
        eng = PolicyEngine(policy)
        grant = eng.evaluate_grant(
            agent_id="agent-a", intent="intent_x", requested_tools=frozenset(["tool_a"])
        )
        result = eng.evaluate_call(
            grant=grant,
            tool_name="tool_a",
            arguments={"query": "a" * 600},
        )
        assert result.status == "DENY"
        assert result.reason == "param_too_long:query"
