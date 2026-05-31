"""Pydantic models for intents.yaml.

References are validated post-parse (`_verify_references`) so the gateway refuses
to start with a malformed policy (Fail-fast / Default Deny).
"""

from __future__ import annotations

import re
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StructuralAllowlistSchema(BaseModel):
    # フィールド名 = True | list[str] (ネストの allowlist)
    # 動的キーを許すため extra="allow"。タイポ検出は GatewayPolicy._verify_references で実施。
    model_config = ConfigDict(extra="allow")


class OutputFilterDef(BaseModel):
    type: Literal["none", "structural_allowlist"]
    schemas: dict[str, StructuralAllowlistSchema] | None = None


MAX_PARAM_LENGTH = 1048576  # 1MB
MAX_PATTERN_LENGTH = 200
RE_DOS_MAX_LENGTH = 4096


class ParamConstraint(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal["string", "integer", "number", "boolean"] | None = None
    max_length: int | None = None
    pattern: str | None = None
    allowed_values: list[str | int | float | bool] | None = None
    forbidden: bool = False

    @model_validator(mode="after")
    def validate_consistency(self) -> Self:
        # 1. pattern/max_length are only allowed for "string" or when type is None
        if self.type not in (None, "string"):
            if self.pattern is not None:
                raise ValueError(
                    f"pattern is only allowed for type='string', got type={self.type!r}"
                )
            if self.max_length is not None:
                raise ValueError(
                    f"max_length is only allowed for type='string', got type={self.type!r}"
                )

        # 2. Type-specific validation for allowed_values
        if self.allowed_values is not None:
            if not self.allowed_values:
                raise ValueError("allowed_values cannot be empty if specified")

            if self.type is not None:
                types_map: dict[str, type | tuple[type, ...]] = {
                    "string": str,
                    "integer": int,
                    "number": (int, float),
                    "boolean": bool,
                }
                expected_type = types_map[self.type]
                for val in self.allowed_values:
                    # Booleans are subclasses of int in Python, but for policy enforcement
                    # we treat them as distinct types.
                    if self.type in ("integer", "number") and isinstance(val, bool):
                        raise ValueError(f"allowed_values must be {self.type}, got boolean")

                    if not isinstance(val, expected_type):
                        raise ValueError(
                            f"allowed_values must be {self.type}, got {type(val).__name__}"
                        )
            else:
                # If type is None, ensure all elements in allowed_values are the same type
                first_type = type(self.allowed_values[0])
                for val in self.allowed_values:
                    if type(val) is not first_type:
                        raise ValueError(
                            f"allowed_values must be homogeneous when type is None, "
                            f"got mixture of {first_type.__name__} and {type(val).__name__}"
                        )

        # 3. String-specific validation: pattern and max_length
        if self.pattern is not None:
            if self.max_length is None:
                raise ValueError("pattern requires max_length to be set (ReDoS mitigation)")
            if len(self.pattern) > MAX_PATTERN_LENGTH:
                raise ValueError(f"pattern exceeds {MAX_PATTERN_LENGTH} chars (ReDoS mitigation)")
            try:
                re.compile(self.pattern)
            except re.error as exc:
                raise ValueError(f"invalid regex pattern: {exc}") from exc

        # 4. Limit max_length to MAX_PARAM_LENGTH and enforce ReDoS mitigation cap.
        # We check RE_DOS_MAX_LENGTH first because it is the stricter constraint.
        if self.max_length is not None:
            if self.max_length > RE_DOS_MAX_LENGTH:
                raise ValueError(f"max_length exceeds ReDoS mitigation limit ({RE_DOS_MAX_LENGTH})")
            if self.max_length > MAX_PARAM_LENGTH:
                raise ValueError(f"max_length exceeds system limit ({MAX_PARAM_LENGTH})")

        return self


class ToolGuardrail(BaseModel):
    model_config = ConfigDict(frozen=True)
    params: dict[str, ParamConstraint] = Field(default_factory=dict)
    requires_approval: bool = False
    skip_llm: bool = False


class IntentPolicy(BaseModel):
    description: str
    allowed_tools: list[str] = Field(..., min_length=1)
    output_filter: str
    guardrails: dict[str, ToolGuardrail] = Field(default_factory=dict)


class AgentPolicy(BaseModel):
    allowed_intents: list[str]


class GatewayPolicy(BaseModel):
    version: Literal[1]
    output_filters: dict[str, OutputFilterDef]
    intents: dict[str, IntentPolicy]
    agents: dict[str, AgentPolicy]
    approvers: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _verify_references(self) -> Self:
        # 1. intent.output_filter は output_filters に存在
        # 5. guardrail keys exist in allowed_tools
        for iname, intent in self.intents.items():
            if intent.output_filter not in self.output_filters:
                raise ValueError(
                    f"intent {iname!r} references unknown output_filter {intent.output_filter!r}"
                )

            allowed_set = set(intent.allowed_tools)
            for tname in intent.guardrails:
                if tname not in allowed_set:
                    raise ValueError(f"intent {iname!r} guardrail {tname!r} not in allowed_tools")

        # 2. agent.allowed_intents は intents に存在
        for aname, agent in self.agents.items():
            for iname in agent.allowed_intents:
                if iname not in self.intents:
                    raise ValueError(f"agent {aname!r} references unknown intent {iname!r}")
        # 3. structural_allowlist は schemas 必須
        for fname, fdef in self.output_filters.items():
            if fdef.type == "structural_allowlist" and not fdef.schemas:
                raise ValueError(
                    f"output_filter {fname!r} type=structural_allowlist requires schemas"
                )
        # 4. structural_allowlist の schema キーは、
        # そのフィルターを使用している intent.allowed_tools に含まれる
        for fname, fdef in self.output_filters.items():
            if fdef.type != "structural_allowlist" or fdef.schemas is None:
                continue
            # そのフィルターを参照しているインテントが許可しているツールの集合
            referencing_tools: set[str] = {
                t
                for intent in self.intents.values()
                if intent.output_filter == fname
                for t in intent.allowed_tools
            }
            for tool_name in fdef.schemas:
                if tool_name not in referencing_tools:
                    raise ValueError(
                        f"output_filter {fname!r} schema key {tool_name!r} is not "
                        "referenced by any intent that uses this filter (typo?)"
                    )
        return self
