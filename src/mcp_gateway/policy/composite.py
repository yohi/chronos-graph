"""CompositeEvaluator: Tier 1 (deterministic PolicyEngine) + Tier 2 (LLM)."""

from __future__ import annotations

import logging
from typing import Literal

from ..errors import PolicyError
from .engine import Grant, PolicyEngine
from .llm_evaluator import (
    LlmEvaluator,
    LlmUnavailableError,
    ResponseParseError,
)
from .memory_client import MemoryClient, MemoryFetchError
from .models_evaluator import (
    Decision,
    MemoryItem,
    ToolCallInput,
    summarize_tool_input,
)

logger = logging.getLogger("chronos_evaluator")

_FALLBACK_ASK_MESSAGE = "System evaluation failed. Human confirmation required."


class CompositeEvaluator:
    def __init__(
        self,
        *,
        engine: PolicyEngine,
        memory_client: MemoryClient | None,
        llm_evaluator: LlmEvaluator | None,
        default_intent: str = "default",
        default_agent_id: str = "claude-code",
        fallback_when_llm_not_configured: Literal["allow", "ask"] = "allow",
    ) -> None:
        self._engine: PolicyEngine = engine
        self._memory: MemoryClient | None = memory_client
        self._llm: LlmEvaluator | None = llm_evaluator
        self._default_intent: str = default_intent
        self._default_agent_id: str = default_agent_id
        if fallback_when_llm_not_configured not in {"allow", "ask"}:
            raise ValueError(
                "fallback_when_llm_not_configured must be 'allow' or 'ask',"
                f" got {fallback_when_llm_not_configured!r}"
            )
        self._fallback: Literal["allow", "ask"] = fallback_when_llm_not_configured

        logger.warning(
            "evaluator config: llm=%s memory=%s fallback_when_llm_not_configured=%s",
            "enabled" if llm_evaluator is not None else "DISABLED",
            "enabled" if memory_client is not None else "disabled",
            self._fallback,
        )
        if llm_evaluator is None and self._fallback == "allow":
            msg = (
                "evaluator config: llm=DISABLED fallback=allow - "
                "tools will be auto-approved without LLM review"
            )
            logger.warning(msg)

    async def evaluate(self, input_: ToolCallInput) -> Decision:
        intent = str(input_.context.get("intent") or self._default_intent)
        agent_id = str(input_.context.get("agent_id") or self._default_agent_id)

        try:
            grant = self._engine.evaluate_grant(
                agent_id=agent_id,
                intent=intent,
                requested_tools=None,
            )
        except PolicyError as exc:
            return Decision(decision="deny", reason=(exc.reason or "policy_violation"))

        try:
            tier1 = self._engine.evaluate_call(
                grant=grant,
                tool_name=input_.tool_name,
                arguments=input_.tool_input,
            )
        except PolicyError as exc:
            return Decision(decision="deny", reason=(exc.reason or "policy_violation"))

        if tier1.status == "DENY":
            return Decision(decision="deny", reason=(tier1.reason or "guardrail_violation"))
        if tier1.status == "REQUIRES_APPROVAL":
            return Decision(
                decision="ask",
                ask_message=f"Tool {input_.tool_name!r} requires manual approval.",
            )
        if tier1.status != "ALLOW":
            logger.warning(
                "Unexpected tier1 status %r for tool %r; treating as deny",
                tier1.status,
                input_.tool_name,
            )
            return Decision(decision="deny", reason="unexpected_evaluation_status")

        if self._llm is None:
            if self._fallback == "ask":
                return Decision(
                    decision="ask",
                    ask_message="LLM evaluator is not configured; human confirmation required.",
                )
            return Decision(decision="allow")

        memories = await self._fetch_memories_safely(input_)
        rules = self._render_rules_for_prompt(grant, input_.tool_name)
        try:
            return await self._llm.judge(
                input_=input_,
                rules=rules,
                memories=memories,
                intent_name=intent,
            )
        except (LlmUnavailableError, ResponseParseError) as exc:
            logger.warning("Tier-2 fallback to ask: %s", exc)
            return Decision(decision="ask", ask_message=_FALLBACK_ASK_MESSAGE)

    async def _fetch_memories_safely(self, input_: ToolCallInput) -> list[MemoryItem]:
        if self._memory is None:
            return []

        query = f"tool:{input_.tool_name} " + summarize_tool_input(input_.tool_input)
        project = str(input_.context.get("project") or "")
        try:
            return await self._memory.retrieve(query=query, project=project or None)
        except MemoryFetchError as exc:
            logger.warning("memory fetch failed (continuing without memory): %s", exc)
            return []

    @staticmethod
    def _render_rules_for_prompt(grant: Grant, tool_name: str) -> str:
        guardrail = grant.guardrails.get(tool_name)
        if guardrail is None:
            return f"- intent={grant.intent}: no specific guardrails for tool {tool_name}."

        lines: list[str] = [f"- intent={grant.intent}, tool={tool_name}"]
        for param, constraint in guardrail.params.items():
            bits: list[str] = []
            if constraint.forbidden:
                bits.append("FORBIDDEN")
            if constraint.type:
                bits.append(f"type={constraint.type}")
            if constraint.max_length is not None:
                bits.append(f"max_length={constraint.max_length}")
            if constraint.pattern:
                bits.append(f"pattern={constraint.pattern!r}")
            if constraint.allowed_values:
                bits.append(f"allowed_values={constraint.allowed_values}")
            lines.append(f"  - {param}: {', '.join(bits) or '(no constraints)'}")

        if guardrail.requires_approval:
            lines.append("  - requires_approval=true")
        return "\n".join(lines)
