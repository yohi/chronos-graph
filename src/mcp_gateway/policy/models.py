"""Pydantic models for intents.yaml.

References are validated post-parse (`_verify_references`) so the gateway refuses
to start with a malformed policy (Fail-fast / Default Deny).
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StructuralAllowlistSchema(BaseModel):
    # フィールド名 = True | list[str] (ネストの allowlist)
    # 動的キーを許すため extra="allow"。タイポ検出は GatewayPolicy._verify_references で実施。
    model_config = ConfigDict(extra="allow")


class OutputFilterDef(BaseModel):
    type: Literal["none", "structural_allowlist"]
    schemas: dict[str, StructuralAllowlistSchema] | None = None


class IntentPolicy(BaseModel):
    description: str
    allowed_tools: list[str] = Field(..., min_length=1)
    output_filter: str


class AgentPolicy(BaseModel):
    allowed_intents: list[str]


class GatewayPolicy(BaseModel):
    version: Literal[1]
    output_filters: dict[str, OutputFilterDef]
    intents: dict[str, IntentPolicy]
    agents: dict[str, AgentPolicy]

    @model_validator(mode="after")
    def _verify_references(self) -> Self:
        # 1. intent.output_filter は output_filters に存在
        for iname, intent in self.intents.items():
            if intent.output_filter not in self.output_filters:
                raise ValueError(
                    f"intent {iname!r} references unknown output_filter {intent.output_filter!r}"
                )
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
