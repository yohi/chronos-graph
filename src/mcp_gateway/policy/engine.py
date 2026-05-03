"""IBAC engine: pure functions over a GatewayPolicy.

evaluate_grant() is invoked at SSE handshake time and computes the effective
capability set. check_call() is invoked at every tools/call before delegating
to the upstream subprocess.
"""

from __future__ import annotations

from dataclasses import dataclass

from mcp_gateway.errors import PolicyError
from mcp_gateway.policy.models import GatewayPolicy


@dataclass(frozen=True, slots=True)
class Grant:
    intent: str
    caps: frozenset[str]
    output_filter_profile: str


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
        if intent not in agent.allowed_intents:
            raise PolicyError(f"agent {agent_id!r} cannot use intent {intent!r}")
        intent_pol = self._policy.intents.get(intent)
        if intent_pol is None:
            raise PolicyError(f"unknown intent {intent!r}")
        allowed = frozenset(intent_pol.allowed_tools)
        if requested_tools is None:
            caps = allowed
        else:
            extra = requested_tools - allowed
            if extra:
                raise PolicyError(
                    f"requested tools {sorted(extra)!r} are outside intent {intent!r}"
                )
            # Ensure caps is always an immutable frozenset even if a mutable set was passed
            caps = frozenset(requested_tools)
        return Grant(intent=intent, caps=caps, output_filter_profile=intent_pol.output_filter)

    @staticmethod
    def check_call(*, caps: frozenset[str], tool_name: str) -> None:
        if tool_name not in caps:
            raise PolicyError(f"tool {tool_name!r} is not in session capabilities")
