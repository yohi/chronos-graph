"""evaluate_call() signature + Grant reliance enforcement tests."""

from __future__ import annotations


class TestParamConstraint:
    """evaluate_call() を通じたパラメータ制約の動作テスト。"""

    def _make_engine_and_grant(
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
            ParamConstraint,
            ToolGuardrail,
        )

        # 生の dict を ParamConstraint に変換して型安全性を確保
        typed_params = {k: ParamConstraint(**v) for k, v in params.items()}

        policy = GatewayPolicy(
            version=1,
            output_filters={"f": OutputFilterDef(type="none")},
            intents={
                intent: IntentPolicy(
                    description="test",
                    allowed_tools=[tool_name],
                    output_filter="f",
                    guardrails={
                        tool_name: ToolGuardrail(
                            params=typed_params,
                            requires_approval=requires_approval,
                        )
                    },
                )
            },
            agents={"agent-a": AgentPolicy(allowed_intents=[intent])},
        )
        engine = PolicyEngine(policy)
        grant = engine.evaluate_grant(agent_id="agent-a", intent=intent, requested_tools=None)
        return engine, grant

    def _call(self, engine, grant, tool_name, arguments):
        return engine.evaluate_call(
            grant=grant,
            tool_name=tool_name,
            arguments=arguments,
        )

    def test_max_length_boundary_allow(self):
        engine, grant = self._make_engine_and_grant(
            "memory_search", {"query": {"type": "string", "max_length": 512}}
        )
        result = self._call(engine, grant, "memory_search", {"query": "a" * 512})
        assert result.status == "ALLOW"

    def test_max_length_exceeded_deny(self):
        engine, grant = self._make_engine_and_grant(
            "memory_search", {"query": {"type": "string", "max_length": 512}}
        )
        result = self._call(engine, grant, "memory_search", {"query": "a" * 513})
        assert result.status == "DENY"
        assert result.reason == "param_too_long:query"

    def test_max_length_empty_string_allow(self):
        engine, grant = self._make_engine_and_grant(
            "memory_search", {"query": {"type": "string", "max_length": 512}}
        )
        result = self._call(engine, grant, "memory_search", {"query": ""})
        assert result.status == "ALLOW"

    def test_pattern_full_match_allow(self):
        engine, grant = self._make_engine_and_grant(
            "memory_search",
            {"query": {"type": "string", "max_length": 100, "pattern": "^[a-z_]+$"}},
        )
        result = self._call(engine, grant, "memory_search", {"query": "hello_world"})
        assert result.status == "ALLOW"

    def test_pattern_partial_match_deny(self):
        engine, grant = self._make_engine_and_grant(
            "memory_search",
            {"query": {"type": "string", "max_length": 100, "pattern": "^[a-z_]+$"}},
        )
        result = self._call(engine, grant, "memory_search", {"query": "hello world!"})
        assert result.status == "DENY"
        assert result.reason == "param_pattern_mismatch:query"

    def test_pattern_script_injection_deny(self):
        engine, grant = self._make_engine_and_grant(
            "memory_search",
            {"query": {"type": "string", "max_length": 100, "pattern": "^[^<>{};]*$"}},
        )
        result = self._call(engine, grant, "memory_search", {"query": "<script>alert(1)</script>"})
        assert result.status == "DENY"
        assert result.reason == "param_pattern_mismatch:query"

    def test_pattern_unicode_deny(self):
        engine, grant = self._make_engine_and_grant(
            "memory_search",
            {"query": {"type": "string", "max_length": 100, "pattern": "^[a-z_]+$"}},
        )
        result = self._call(engine, grant, "memory_search", {"query": "こんにちは"})
        assert result.status == "DENY"
        assert result.reason == "param_pattern_mismatch:query"

    def test_allowed_values_in_list_allow(self):
        engine, grant = self._make_engine_and_grant(
            "memory_search", {"mode": {"type": "string", "allowed_values": ["read", "write"]}}
        )
        result = self._call(engine, grant, "memory_search", {"mode": "read"})
        assert result.status == "ALLOW"

    def test_allowed_values_not_in_list_deny(self):
        engine, grant = self._make_engine_and_grant(
            "memory_search", {"mode": {"type": "string", "allowed_values": ["read", "write"]}}
        )
        result = self._call(engine, grant, "memory_search", {"mode": "admin"})
        assert result.status == "DENY"
        assert result.reason == "param_not_in_allowed_values:mode"

    def test_forbidden_param_present_deny(self):
        engine, grant = self._make_engine_and_grant(
            "memory_search", {"secret": {"forbidden": True}}
        )
        result = self._call(engine, grant, "memory_search", {"secret": "x"})
        assert result.status == "DENY"
        assert result.reason == "forbidden_param:secret"

    def test_forbidden_param_absent_allow(self):
        engine, grant = self._make_engine_and_grant(
            "memory_search", {"secret": {"forbidden": True}}
        )
        result = self._call(engine, grant, "memory_search", {"query": "hi"})
        assert result.status == "ALLOW"

    def test_missing_constrained_param_allow(self):
        engine, grant = self._make_engine_and_grant(
            "memory_search", {"query": {"type": "string", "max_length": 512}}
        )
        result = self._call(engine, grant, "memory_search", {})
        assert result.status == "ALLOW"

    def test_type_mismatch_int_for_string_constraint_deny(self):
        engine, grant = self._make_engine_and_grant(
            "memory_search", {"query": {"type": "string", "max_length": 512, "pattern": "^[a-z]+$"}}
        )
        result = self._call(engine, grant, "memory_search", {"query": 12345})
        assert result.status == "DENY"
        assert result.reason == "param_type_mismatch:query"

    def test_type_string_explicit_int_deny(self):
        engine, grant = self._make_engine_and_grant("memory_search", {"query": {"type": "string"}})
        result = self._call(engine, grant, "memory_search", {"query": 12345})
        assert result.status == "DENY"
        assert result.reason == "param_type_mismatch:query"

    def test_type_integer_bool_excluded_deny(self):
        engine, grant = self._make_engine_and_grant("memory_search", {"count": {"type": "integer"}})
        result = self._call(engine, grant, "memory_search", {"count": True})
        assert result.status == "DENY"
        assert result.reason == "param_type_mismatch:count"

    def test_type_string_correct_allow(self):
        engine, grant = self._make_engine_and_grant("memory_search", {"query": {"type": "string"}})
        result = self._call(engine, grant, "memory_search", {"query": "safe"})
        assert result.status == "ALLOW"


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
        # Use valid tools for the intent, but restricted by requested_tools
        grant = eng.evaluate_grant(
            agent_id="agent-a",
            intent="read_only_recall",
            requested_tools=frozenset(["memory_stats"]),
        )
        # Call a tool that is allowed by intent but NOT in grant caps
        result = eng.evaluate_call(
            grant=grant,
            tool_name="memory_search",
            arguments={},
        )
        assert result.status == "DENY"
        assert result.reason == "tool_not_in_caps"

    def test_no_guardrail_allow(self):
        eng = self._engine()
        grant = eng.evaluate_grant(
            agent_id="agent-a", intent="read_only_recall", requested_tools=None
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
            agent_id="agent-a", intent="read_only_recall", requested_tools=None
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
            agent_id="agent-a", intent="curate_memories", requested_tools=None
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
        grant = eng.evaluate_grant(agent_id="agent-a", intent="intent_x", requested_tools=None)
        result = eng.evaluate_call(
            grant=grant,
            tool_name="tool_a",
            arguments={"query": "a" * 600},
        )
        assert result.status == "DENY"
        assert result.reason == "param_too_long:query"
