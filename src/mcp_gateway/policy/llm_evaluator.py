from __future__ import annotations

import asyncio
import importlib
import json
import logging
import os
from collections.abc import Mapping
from typing import Protocol, cast

from mcp_gateway.policy.models_evaluator import (
    REDACTED_MARKER,
    Decision,
    MemoryItem,
    ToolCallInput,
)

logger = logging.getLogger("chronos_evaluator.llm")

__all__ = [
    "LlmEvaluator",
    "LlmUnavailableError",
    "ResponseParseError",
    "SYSTEM_PROMPT",
    "_build_user_prompt",
    "_parse_decision",
]

_REASON_MAX = 200
_ASK_MESSAGE_MAX = 300
_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "authorization",
        "bearer",
        "credential",
    }
)


class LlmUnavailableError(Exception):
    pass


class ResponseParseError(Exception):
    pass


class _MessagesProtocol(Protocol):
    def create(self, **kwargs: object) -> object: ...


class _AnthropicClientProtocol(Protocol):
    messages: _MessagesProtocol


class _AnthropicFactoryProtocol(Protocol):
    def __call__(self, *, api_key: str, timeout: object) -> _AnthropicClientProtocol: ...


class _TextBlockProtocol(Protocol):
    type: str
    text: str


SYSTEM_PROMPT = """<role>
You are the ChronosGraph Universal Evaluator — a security-and-intent gate
that judges whether a proposed local tool call is safe and aligned with the
project's policy and the user's accumulated preferences.
</role>

<task>
Given a tool invocation (already passing deterministic guardrails), inspect:
  1. The tool intent (<tool_intent>): what the agent wants to do
  2. The project's hard rules (<rules>): immutable constraints
  3. Long-term memory (<memory>): user preferences and past decisions

Decide one of:
  - "allow": clearly safe and aligned. Proceed without bothering the user.
  - "deny":  clearly unsafe, destructive, or violates a hard rule.
  - "ask":   ambiguous, unusual, or contradicts recalled preference.
             Default to "ask" when in doubt — false-allow is the worst outcome.
</task>

<output_format>
Respond with EXACTLY one JSON object. No prose, no markdown fences, no
preamble. Schema:
  {"decision": "allow"}
  {"decision": "deny",  "reason":       "<=200 chars, why blocked"}
  {"decision": "ask",   "ask_message":  "<=300 chars, what to confirm"}
Any other output will be treated as a parse failure and downgraded to "ask".
</output_format>

<priorities>
1. Hard rules in <rules> are absolute. Violation -> "deny".
2. Explicit user preferences in <memory> override defaults.
3. When <memory> is empty or irrelevant, judge on tool semantics alone.
4. Never invent facts not present in the provided context.
</priorities>"""


def _parse_decision(text: str) -> Decision:
    stripped = text.strip()
    if not stripped.startswith("{") or not stripped.endswith("}"):
        raise ResponseParseError(f"non-JSON response: {stripped[:80]!r}")

    try:
        parsed = cast(object, json.loads(stripped))
    except json.JSONDecodeError as exc:
        raise ResponseParseError(f"invalid JSON: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ResponseParseError(f"top-level must be object, got {type(parsed).__name__}")

    obj = cast(Mapping[str, object], parsed)
    decision = obj.get("decision")
    if decision == "allow":
        return Decision(decision="allow")
    if decision == "deny":
        reason = obj.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ResponseParseError("deny requires non-empty 'reason'")
        return Decision(decision="deny", reason=reason[:_REASON_MAX])
    if decision == "ask":
        ask_message = obj.get("ask_message")
        if not isinstance(ask_message, str) or not ask_message.strip():
            raise ResponseParseError("ask requires non-empty 'ask_message'")
        return Decision(decision="ask", ask_message=ask_message[:_ASK_MESSAGE_MAX])

    raise ResponseParseError(f"unknown decision: {decision!r}")


def _build_user_prompt(
    *,
    input_: ToolCallInput,
    rules: str,
    memories: list[MemoryItem],
    intent_name: str,
) -> str:
    redacted = _redact_prompt_value(input_.tool_input)
    tool_input_json = json.dumps(redacted, ensure_ascii=False)
    cwd = str(input_.context.get("cwd") or "unknown")
    agent_id = str(input_.context.get("agent_id") or "unknown")
    memory_blocks = "\n".join(
        (
            f'  <item type="{memory.memory_type}" importance="{memory.importance:.2f}">'
            f"\n    {memory.content}\n  </item>"
        )
        for memory in memories
    )

    return f"""<tool_intent>
  <tool_name>{input_.tool_name}</tool_name>
  <tool_input>{tool_input_json}</tool_input>
  <cwd>{cwd}</cwd>
  <agent_id>{agent_id}</agent_id>
</tool_intent>

<rules source="intents.yaml" intent="{intent_name}">
{rules}
</rules>

<memory source="chronos-graph" top_k="{len(memories)}">
{memory_blocks}
</memory>

Decide now. Output JSON only."""


def _redact_prompt_value(value: object) -> object:
    if isinstance(value, dict):
        mapping = cast(dict[object, object], value)
        return {
            str(key): (
                REDACTED_MARKER
                if _is_prompt_sensitive_key(str(key))
                else _redact_prompt_value(child)
            )
            for key, child in mapping.items()
        }
    if isinstance(value, list):
        values = cast(list[object], value)
        return [_redact_prompt_value(child) for child in values]
    return value


def _is_prompt_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(sensitive in normalized for sensitive in _SENSITIVE_KEYS)


class LlmEvaluator:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = "claude-haiku-4-5-20251001",
        timeout_seconds: float = 10.0,
        thinking_budget: int = 1024,
        max_tokens: int = 1536,
    ) -> None:
        self._api_key: str = api_key
        self._model: str = model
        self._timeout_seconds: float = timeout_seconds
        self._thinking_budget: int = thinking_budget
        self._max_tokens: int = max_tokens
        self._client: _AnthropicClientProtocol | None = None

    @classmethod
    def from_env(cls) -> LlmEvaluator | None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            return None
        try:
            _ = importlib.import_module("anthropic")
        except ImportError:
            logger.warning("anthropic SDK not installed; LLM evaluator disabled")
            return None
        return cls(
            api_key=api_key,
            model=os.getenv("CHRONOS_EVALUATOR_MODEL", "claude-haiku-4-5-20251001"),
            timeout_seconds=float(os.getenv("CHRONOS_EVALUATOR_TIMEOUT_SECONDS", "10.0")),
            thinking_budget=int(os.getenv("CHRONOS_EVALUATOR_THINKING_BUDGET", "1024")),
        )

    def _get_client(self) -> _AnthropicClientProtocol:
        if self._client is None:
            import httpx

            anthropic_module = importlib.import_module("anthropic")
            anthropic_factory = cast(
                _AnthropicFactoryProtocol,
                anthropic_module.__dict__["Anthropic"],
            )
            self._client = anthropic_factory(
                api_key=self._api_key,
                timeout=httpx.Timeout(self._timeout_seconds, connect=2.0),
            )
        return self._client

    async def judge(
        self,
        *,
        input_: ToolCallInput,
        rules: str,
        memories: list[MemoryItem],
        intent_name: str = "default",
    ) -> Decision:
        user_prompt = _build_user_prompt(
            input_=input_, rules=rules, memories=memories, intent_name=intent_name
        )
        try:
            response = await asyncio.to_thread(
                self._invoke_sdk,
                system_prompt=SYSTEM_PROMPT,
                user_prompt=user_prompt,
            )
        except Exception as exc:
            raise LlmUnavailableError(f"LLM call failed: {exc}") from exc

        content = cast(list[object], getattr(response, "content", []))
        text_blocks = [block for block in content if getattr(block, "type", None) == "text"]
        if not text_blocks:
            raise ResponseParseError("LLM returned no text block")
        text = cast(_TextBlockProtocol, text_blocks[0]).text
        return _parse_decision(text)

    def _invoke_sdk(self, *, system_prompt: str, user_prompt: str) -> object:
        client = self._get_client()
        return client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_prompt}],
            thinking={"type": "enabled", "budget_tokens": self._thinking_budget},
        )
