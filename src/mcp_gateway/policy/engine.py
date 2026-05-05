"""IBAC engine: pure functions over a GatewayPolicy.

evaluate_grant() is invoked at SSE handshake time and computes the effective
capability set. check_call() is invoked at every tools/call before delegating
to the upstream subprocess.
"""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal

from mcp_gateway.errors import PolicyError
from mcp_gateway.policy.models import GatewayPolicy, ToolGuardrail


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    status: Literal["ALLOW", "DENY", "REQUIRES_APPROVAL"]
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class Grant:
    intent: str
    caps: frozenset[str]
    output_filter_profile: str
    guardrails: MappingProxyType[str, ToolGuardrail]


class PolicyEngine:
    def __init__(self, policy: GatewayPolicy) -> None:
        self._policy = policy

    def evaluate_grant(
        self,
        *,
        agent_id: str,
        intent: str,
        requested_tools: frozenset[str] | None,
    ) -> Grant:
        if requested_tools is not None and len(requested_tools) == 0:
            raise PolicyError("requested_tools must be None (all) or a non-empty set")

        agent = self._policy.agents.get(agent_id)
        if agent is None:
            raise PolicyError(f"agent {agent_id!r} is not registered")
        intent_pol = self._policy.intents.get(intent)
        if intent_pol is None:
            raise PolicyError(f"unknown intent {intent!r}")
        if intent not in agent.allowed_intents:
            raise PolicyError(f"agent {agent_id!r} cannot use intent {intent!r}")
        allowed = frozenset(intent_pol.allowed_tools)
        if requested_tools is None:
            caps = allowed
        else:
            # Narrow requested_tools to the intersection with allowed_tools (IBAC hybrid narrowing)
            caps = frozenset(requested_tools & allowed)
            if not caps:
                raise PolicyError(
                    f"none of the requested tools are allowed for intent {intent!r}. "
                    f"requested: {sorted(requested_tools)}, allowed: {sorted(allowed)}"
                )
        return Grant(
            intent=intent,
            caps=caps,
            output_filter_profile=intent_pol.output_filter,
            guardrails=MappingProxyType(deepcopy(intent_pol.guardrails)),
        )

    def evaluate_call(
        self,
        *,
        grant: Grant,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> EvaluationResult:
        try:
            PolicyEngine.check_call(caps=grant.caps, tool_name=tool_name)
            guardrail = grant.guardrails.get(tool_name)
            PolicyEngine.validate_call(
                tool_name=tool_name,
                arguments=arguments,
                guardrail=guardrail,
            )
        except PolicyError as exc:
            if exc.reason == "requires_approval":
                return EvaluationResult(status="REQUIRES_APPROVAL", reason=exc.reason)
            return EvaluationResult(status="DENY", reason=exc.reason)

        return EvaluationResult(status="ALLOW")

    @staticmethod
    def check_call(*, caps: frozenset[str], tool_name: str) -> None:
        if tool_name not in caps:
            raise PolicyError(
                f"tool {tool_name!r} is not in session capabilities",
                reason="tool_not_in_caps",
            )

    @staticmethod
    def validate_call(
        *,
        tool_name: str,
        arguments: dict[str, Any],
        guardrail: ToolGuardrail | None,
    ) -> None:
        if guardrail is None:
            return

        for param_name, constraint in guardrail.params.items():
            if constraint.forbidden and param_name in arguments:
                raise PolicyError(
                    f"parameter {param_name!r} is forbidden for tool {tool_name!r}",
                    reason=f"forbidden_param:{param_name}",
                )

            if param_name not in arguments:
                continue

            val = arguments[param_name]

            # 1. Type check
            expected_type_str = constraint.type
            has_string_constraint = (
                constraint.max_length is not None or constraint.pattern is not None
            )

            if expected_type_str is None and has_string_constraint:
                expected_type_str = "string"

            if expected_type_str is not None:
                if expected_type_str in ("integer", "number") and isinstance(val, bool):
                    raise PolicyError(
                        f"parameter {param_name!r} must be {expected_type_str}, got boolean",
                        reason=f"param_type_mismatch:{param_name}",
                    )

                types_map: dict[str, type | tuple[type, ...]] = {
                    "string": str,
                    "integer": int,
                    "number": (int, float),
                    "boolean": bool,
                }
                expected_type_cls = types_map[expected_type_str]
                if not isinstance(val, expected_type_cls):
                    actual_type = "boolean" if isinstance(val, bool) else type(val).__name__
                    raise PolicyError(
                        f"parameter {param_name!r} must be {expected_type_str}, got {actual_type}",
                        reason=f"param_type_mismatch:{param_name}",
                    )

            # 2. Allowed values
            if constraint.allowed_values is not None:
                if not any(v == val and type(v) is type(val) for v in constraint.allowed_values):
                    raise PolicyError(
                        f"parameter {param_name!r} has invalid value {val!r}. "
                        f"allowed: {constraint.allowed_values}",
                        reason=f"param_not_in_allowed_values:{param_name}",
                    )

            # 3. String-specific constraints
            if isinstance(val, str):
                if constraint.max_length is not None and len(val) > constraint.max_length:
                    raise PolicyError(
                        f"parameter {param_name!r} exceeds max_length ({constraint.max_length})",
                        reason=f"param_too_long:{param_name}",
                    )
                if constraint.pattern is not None:
                    if not re.fullmatch(constraint.pattern, val):
                        raise PolicyError(
                            f"parameter {param_name!r} does not match required pattern",
                            reason=f"param_pattern_mismatch:{param_name}",
                        )

        if guardrail.requires_approval:
            raise PolicyError(
                f"tool {tool_name!r} requires manual approval which is not yet implemented",
                reason="requires_approval",
            )
