"""CompositeEvaluator: Tier 1 (deterministic PolicyEngine) + Tier 2 (LLM)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from typing import Literal

from ..errors import PolicyError
from .engine import Grant, PolicyEngine
from .llm_evaluator import (
    READ_ONLY_TOOLS,
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
        evaluation_cache_ttl_seconds: float = 300.0,
        memory_timeout_seconds: float = 3.0,
    ) -> None:
        self._engine: PolicyEngine = engine
        self._memory: MemoryClient | None = memory_client
        self._llm: LlmEvaluator | None = llm_evaluator
        self._default_intent: str = default_intent
        self._default_agent_id: str = default_agent_id
        if fallback_when_llm_not_configured not in {"allow", "ask"}:
            invalid_fallback = fallback_when_llm_not_configured
            raise ValueError(
                f"fallback_when_llm_not_configured must be allow/ask, got {invalid_fallback!r}"
            )
        self._fallback: Literal["allow", "ask"] = fallback_when_llm_not_configured
        if memory_timeout_seconds <= 0:
            raise ValueError(f"memory_timeout_seconds must be > 0, got {memory_timeout_seconds}")
        self._evaluation_cache_ttl_seconds: float = evaluation_cache_ttl_seconds
        self._memory_timeout_seconds: float = memory_timeout_seconds
        self._decision_cache: dict[str, tuple[float, Decision]] = {}
        self._last_cleanup_time: float = time.monotonic()
        self._cache_cleanup_interval: float = 60.0  # seconds
        self._in_flight_judgments: dict[str, asyncio.Future[Decision]] = {}

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

        # Skip LLM evaluation if guardrail explicitly configures skip_llm=true
        guardrail = grant.guardrails.get(input_.tool_name)
        if guardrail is not None and getattr(guardrail, "skip_llm", False):
            return Decision(decision="allow")

        if input_.tool_name in READ_ONLY_TOOLS:
            return Decision(decision="allow")

        if self._llm is None:
            if self._fallback == "ask":
                return Decision(
                    decision="ask",
                    ask_message="LLM evaluator is not configured; human confirmation required.",
                )
            return Decision(decision="allow")

        self._maybe_cleanup_cache()
        cache_key = self._make_decision_cache_key(input_, intent, agent_id)
        cached = self._get_cached_decision(cache_key)
        if cached is not None:
            return cached

        # Coalesce duplicate concurrent evaluations
        if cache_key in self._in_flight_judgments:
            logger.info("Found in-flight judgment for key %s, waiting for result", cache_key)
            return await asyncio.shield(self._in_flight_judgments[cache_key])

        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._in_flight_judgments[cache_key] = fut

        try:
            memories = await self._fetch_memories_safely(input_)
            rules = self._render_rules_for_prompt(grant, input_.tool_name)
            decision = await self._llm.judge(
                input_=input_,
                rules=rules,
                memories=memories,
                intent_name=intent,
            )
            self._store_cached_decision(cache_key, decision)
            if not fut.done():
                fut.set_result(decision)
            return decision
        except (LlmUnavailableError, ResponseParseError) as exc:
            logger.warning("Tier-2 fallback to ask: %s", exc)
            fallback_decision = Decision(decision="ask", ask_message=_FALLBACK_ASK_MESSAGE)
            if not fut.done():
                fut.set_result(fallback_decision)
            return fallback_decision
        except Exception as exc:
            if not fut.done():
                fut.set_exception(exc)
            raise exc
        finally:
            self._in_flight_judgments.pop(cache_key, None)

    async def _fetch_memories_safely(self, input_: ToolCallInput) -> list[MemoryItem]:
        if self._memory is None:
            return []

        query = f"tool:{input_.tool_name} " + summarize_tool_input(input_.tool_input)
        project = str(input_.context.get("project") or "")
        try:
            return await asyncio.wait_for(
                self._memory.retrieve(query=query, project=project or None),
                timeout=self._memory_timeout_seconds,
            )
        except (asyncio.TimeoutError, MemoryFetchError) as exc:
            logger.warning("memory fetch failed (continuing without memory): %s", exc)
            return []

    def _get_cached_decision(self, cache_key: str) -> Decision | None:
        cached = self._decision_cache.get(cache_key)
        if cached is None:
            return None
        expires_at, decision = cached
        if expires_at <= time.monotonic():
            _ = self._decision_cache.pop(cache_key, None)
            return None
        return decision

    def _store_cached_decision(self, cache_key: str, decision: Decision) -> None:
        if self._evaluation_cache_ttl_seconds <= 0:
            return
        expires_at = time.monotonic() + self._evaluation_cache_ttl_seconds
        self._decision_cache[cache_key] = (expires_at, decision)

    def _maybe_cleanup_cache(self) -> None:
        """一定時間経過していたら期限切れキャッシュを掃除する。"""
        now = time.monotonic()
        if now - self._last_cleanup_time < self._cache_cleanup_interval:
            return
        self._last_cleanup_time = now
        self._cleanup_expired_decisions()

    def _cleanup_expired_decisions(self) -> None:
        """期限切れのエントリをすべて削除する。"""
        now = time.monotonic()
        expired_keys = [
            k for k, (expires_at, _) in self._decision_cache.items() if expires_at <= now
        ]
        for k in expired_keys:
            self._decision_cache.pop(k, None)
        if expired_keys:
            logger.debug("Cleaned up %d expired cache entries", len(expired_keys))

    def _make_decision_cache_key(
        self,
        input_: ToolCallInput,
        intent: str,
        agent_id: str,
    ) -> str:
        payload = {
            "agent_id": agent_id,
            "intent": intent,
            "llm_model": getattr(self._llm, "_model", None),
            "project": str(input_.context.get("project") or ""),
            "tool_input": input_.tool_input,
            "tool_name": input_.tool_name,
        }
        raw = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

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
