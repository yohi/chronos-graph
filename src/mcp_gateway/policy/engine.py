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
from mcp_gateway.policy.models import GatewayPolicy, ParamConstraint, ToolGuardrail


@dataclass(frozen=True, slots=True)
class Grant:
    intent: str
    caps: frozenset[str]
    output_filter_profile: str
    guardrails: MappingProxyType[str, ToolGuardrail]


@dataclass(frozen=True, slots=True)
class CallDecision:
    status: Literal["ALLOW", "DENY", "REQUIRES_APPROVAL"]
    reason: str | None = None


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

    @staticmethod
    def check_call(*, caps: frozenset[str], tool_name: str) -> None:
        if tool_name not in caps:
            raise PolicyError(f"tool {tool_name!r} is not in session capabilities")

    def evaluate_call(
        self,
        *,
        caps: frozenset[str],
        tool_name: str,
        arguments: dict[str, Any],
        intent: str,
    ) -> CallDecision:
        if tool_name not in caps:
            return CallDecision(status="DENY", reason="tool_not_in_caps")

        intent_pol = self._policy.intents.get(intent)
        if intent_pol is None:
            return CallDecision(status="DENY", reason="unknown_intent")

        if tool_name not in intent_pol.allowed_tools:
            return CallDecision(status="DENY", reason="tool_not_allowed_for_intent")

        guardrail = intent_pol.guardrails.get(tool_name)
        if guardrail is None:
            return CallDecision(status="ALLOW")

        for param_name, constraint in guardrail.params.items():
            if constraint.forbidden and param_name in arguments:
                return CallDecision(status="DENY", reason=f"forbidden_param:{param_name}")

            if param_name not in arguments:
                continue

            value = arguments[param_name]

            if self._type_mismatch(value, constraint):
                return CallDecision(status="DENY", reason=f"param_type_mismatch:{param_name}")

            if constraint.max_length is not None and isinstance(value, str):
                if len(value) > constraint.max_length:
                    return CallDecision(status="DENY", reason=f"param_too_long:{param_name}")

            if constraint.pattern is not None and isinstance(value, str):
                if not re.fullmatch(constraint.pattern, value):
                    return CallDecision(
                        status="DENY",
                        reason=f"param_pattern_mismatch:{param_name}",
                    )

            if constraint.allowed_values is not None:
                if not self._matches_allowed_value(value, constraint.allowed_values):
                    return CallDecision(
                        status="DENY",
                        reason=f"param_not_in_allowed_values:{param_name}",
                    )

        if guardrail.requires_approval:
            return CallDecision(status="REQUIRES_APPROVAL")

        return CallDecision(status="ALLOW")

    @staticmethod
    def validate_call(
        *,
        tool_name: str,
        arguments: dict[str, Any],
        guardrail: ToolGuardrail | None,
    ) -> None:
        if guardrail is None:
            return

        if guardrail.requires_approval:
            raise PolicyError(
                f"tool {tool_name!r} requires manual approval which is not yet implemented"
            )

        for param_name, constraint in guardrail.params.items():
            if constraint.forbidden and param_name in arguments:
                raise PolicyError(f"parameter {param_name!r} is forbidden for tool {tool_name!r}")

            if param_name not in arguments:
                continue

            value = arguments[param_name]

            if PolicyEngine._type_mismatch(value, constraint):
                expected_type = constraint.type or "string"
                actual_type = "boolean" if isinstance(value, bool) else type(value).__name__
                raise PolicyError(
                    f"parameter {param_name!r} must be {expected_type}, got {actual_type}"
                )

            if constraint.allowed_values is not None and not PolicyEngine._matches_allowed_value(
                value, constraint.allowed_values
            ):
                raise PolicyError(
                    f"parameter {param_name!r} has invalid value {value!r}. "
                    f"allowed: {constraint.allowed_values}"
                )

            if isinstance(value, str):
                if constraint.max_length is not None and len(value) > constraint.max_length:
                    raise PolicyError(
                        f"parameter {param_name!r} exceeds max_length ({constraint.max_length})"
                    )
                if constraint.pattern is not None and not re.fullmatch(constraint.pattern, value):
                    raise PolicyError(f"parameter {param_name!r} does not match required pattern")

    @staticmethod
    def _type_mismatch(value: Any, constraint: ParamConstraint) -> bool:
        constraint_type = constraint.type
        has_string_constraint = constraint.max_length is not None or constraint.pattern is not None

        if constraint_type is None and not has_string_constraint:
            return False

        if constraint_type == "string" or (constraint_type is None and has_string_constraint):
            return not isinstance(value, str)

        if constraint_type == "integer":
            return isinstance(value, bool) or not isinstance(value, int)

        if constraint_type == "number":
            return isinstance(value, bool) or not isinstance(value, (int, float))

        if constraint_type == "boolean":
            return not isinstance(value, bool)

        return False

    @staticmethod
    def _matches_allowed_value(
        value: Any,
        allowed_values: list[str | int | float | bool],
    ) -> bool:
        return any(
            candidate == value and type(candidate) is type(value) for candidate in allowed_values
        )
