"""IBAC engine: pure functions over a GatewayPolicy.

evaluate_grant() is invoked at SSE handshake time and computes the effective
capability set. check_call() is invoked at every tools/call before delegating
to the upstream subprocess.
"""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from mcp_gateway.errors import PolicyError
from mcp_gateway.policy.models import GatewayPolicy, ToolGuardrail


@dataclass(frozen=True, slots=True)
class Grant:
    intent: str
    caps: frozenset[str]
    output_filter_profile: str
    guardrails: dict[str, ToolGuardrail]


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
            guardrails=deepcopy(intent_pol.guardrails),
        )

    @staticmethod
    def check_call(*, caps: frozenset[str], tool_name: str) -> None:
        if tool_name not in caps:
            raise PolicyError(f"tool {tool_name!r} is not in session capabilities")

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
                raise PolicyError(f"parameter {param_name!r} is forbidden for tool {tool_name!r}")

            if param_name not in arguments:
                continue

            val = arguments[param_name]

            # 1. Type check
            if constraint.type is not None:
                types_map: dict[str, type | tuple[type, ...]] = {
                    "string": str,
                    "integer": int,
                    "number": (int, float),
                    "boolean": bool,
                }
                expected_type = types_map[constraint.type]
                if not isinstance(val, expected_type):
                    raise PolicyError(
                        f"parameter {param_name!r} must be {constraint.type}, "
                        f"got {type(val).__name__}"
                    )

            # 2. Allowed values
            if constraint.allowed_values is not None:
                if val not in constraint.allowed_values:
                    raise PolicyError(
                        f"parameter {param_name!r} has invalid value {val!r}. "
                        f"allowed: {constraint.allowed_values}"
                    )

            # 3. String-specific constraints
            if isinstance(val, str):
                if constraint.max_length is not None and len(val) > constraint.max_length:
                    raise PolicyError(
                        f"parameter {param_name!r} exceeds max_length ({constraint.max_length})"
                    )
                if constraint.pattern is not None:
                    # Note: We rely on the fact that pattern was validated at load time.
                    # For absolute ReDoS safety, one could use a library with timeouts,
                    # but here we ensure pattern length and max_length are capped.
                    if not re.match(constraint.pattern, val):
                        raise PolicyError(
                            f"parameter {param_name!r} does not match required pattern"
                        )
