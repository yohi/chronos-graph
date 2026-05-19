# MCP Gateway — Server-defined Prompts (Hook) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ChronosGraph MCP Gateway に MCP プロトコルの `prompts/list` / `prompts/get` を実装し、`intents.yaml` から決定論的に生成したプロンプト（役割と利用可能ツール）をエージェントへサーバー側から自動配布する。

**Architecture:** 起動時 lifespan で `PromptBuilder` が `policy + tools + language` から全 intent 分の `Prompt` を合成し、起動時のみ差し替え可能・以降は事実上不変な `PromptRegistry`（`ToolRegistry.replace_tools()` と同じパターン）に格納する。`/messages` ディスパッチャはセッション `record.intent` をキーに `tools/list` と完全対称なフィルタリングで応答する。

**Tech Stack:** Python 3.12 / FastAPI / Pydantic v2 / pytest（既存 `mcp_gateway` パッケージに準拠）

**設計書:** `docs/superpowers/specs/2026-05-19-mcp-gateway-server-defined-prompts-design.md`

**Git ブランチ運用フロー:** AI-Native Stacked PR Workflow ― <https://different-sunday-448.notion.site/AI-Native-Stacked-PR-Workflow-3611669a4c16802eb032eb4ab05a8adb>

- 各 Phase ごとに「Phase Base ブランチ」(`phase/N-<slug>`) を `master` から切る。
- Phase 内の Task は **単体で完結する場合は Phase Base から**、**直前 Task の差分が前提なら直前 Task のブランチから** 派生する（Stacked PR）。
- 各 Task 完了時に Phase Base 向け Draft PR を作成する。
- Phase の全 Task がレビュー通過後、Phase Base を `master` にマージする。

**Devcontainer 強制:** すべてのテスト・静的解析コマンドは Devcontainer 内（VS Code "Reopen in Container" もしくは `devcontainer exec`）で実行すること。ローカル環境での実行は禁止する。

---

## Phase 0: 初期セットアップ（不要）

`.github/workflows/ci.yml` および `.devcontainer/devcontainer.json` / `Dockerfile` は既に存在し、`master` 向けの PR で `ruff` / `mypy` / `pytest` が走る構成となっている。**本 Phase はスキップする**。

---

## Phase 1: ドメイン層（モデル / テンプレート / ビルダー）

**Phase Base ブランチ:** `phase/1-prompts-domain`（`master` から派生）

ドメイン純粋層を 3 Task で構築する。`models` と `templates` は副作用ゼロのため独立してマージ可能だが、`builder` は両者に依存する。

### Task 1.1: Prompt データモデル

**派生元:** Phase Base (`phase/1-prompts-domain`)

理由: 既存コードに依存しない新規モジュール。単体で完結。

**Files:**
- Create: `src/mcp_gateway/prompts/__init__.py`
- Create: `src/mcp_gateway/prompts/models.py`
- Create: `tests/unit/test_mcp_gateway_prompts_models.py`

- [ ] **Step 1: ブランチ作成**

```bash
git fetch origin master
git checkout -b phase/1-prompts-domain origin/master
git push -u origin phase/1-prompts-domain
git checkout -b feat/prompts-models phase/1-prompts-domain
```

- [ ] **Step 2: 失敗するテストを書く**

`tests/unit/test_mcp_gateway_prompts_models.py`:

```python
"""Unit tests for prompt dataclasses."""

from __future__ import annotations

import dataclasses

import pytest

from mcp_gateway.prompts.models import Prompt, PromptMessage, PromptSummary


def test_prompt_message_is_frozen_dataclass() -> None:
    msg = PromptMessage(role="user", text="hello")
    assert dataclasses.is_dataclass(msg)
    with pytest.raises(dataclasses.FrozenInstanceError):
        msg.text = "mutated"  # type: ignore[misc]


def test_prompt_message_accepts_valid_roles() -> None:
    # role is Literal["user", "assistant"]; runtime enforcement is delegated
    # to the type system (mypy). This test guarantees both literals are
    # accepted by the dataclass without raising.
    assert PromptMessage(role="user", text="x").role == "user"
    assert PromptMessage(role="assistant", text="y").role == "assistant"


def test_prompt_holds_immutable_messages_tuple() -> None:
    messages = (PromptMessage(role="user", text="hi"),)
    prompt = Prompt(name="chronos-graph.foo", description="desc", messages=messages)
    assert prompt.messages == messages
    assert isinstance(prompt.messages, tuple)
    with pytest.raises(dataclasses.FrozenInstanceError):
        prompt.name = "other"  # type: ignore[misc]


def test_prompt_summary_defaults_to_empty_arguments() -> None:
    summary = PromptSummary(name="chronos-graph.bar", description="d")
    assert summary.arguments == ()
    assert isinstance(summary.arguments, tuple)
```

- [ ] **Step 3: テスト失敗を確認**

Devcontainer 内で実行:

```bash
uv run pytest tests/unit/test_mcp_gateway_prompts_models.py -v
```

Expected: `ModuleNotFoundError: No module named 'mcp_gateway.prompts'`

- [ ] **Step 4: 最小実装**

`src/mcp_gateway/prompts/__init__.py`:

```python
"""Server-defined prompts (MCP `prompts/list`, `prompts/get`)."""
```

`src/mcp_gateway/prompts/models.py`:

```python
"""Immutable data classes for MCP server-defined prompts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True, slots=True)
class PromptMessage:
    """One element of `prompts/get` `messages` (MCP content type=text only)."""

    role: Literal["user", "assistant"]
    text: str


@dataclass(frozen=True, slots=True)
class Prompt:
    """Full prompt body returned from `prompts/get`."""

    name: str
    description: str
    messages: tuple[PromptMessage, ...]


@dataclass(frozen=True, slots=True)
class PromptSummary:
    """Entry of `prompts/list` (MCP spec: body excluded)."""

    name: str
    description: str
    arguments: tuple[object, ...] = field(default_factory=tuple)
```

- [ ] **Step 5: テスト成功を確認**

```bash
uv run pytest tests/unit/test_mcp_gateway_prompts_models.py -v
uv run ruff check src/mcp_gateway/prompts/ tests/unit/test_mcp_gateway_prompts_models.py
uv run ruff format --check src/mcp_gateway/prompts/ tests/unit/test_mcp_gateway_prompts_models.py
uv run mypy src/mcp_gateway/prompts/
```

Expected: 全パス

- [ ] **Step 6: コミット**

```bash
git add src/mcp_gateway/prompts/__init__.py \
        src/mcp_gateway/prompts/models.py \
        tests/unit/test_mcp_gateway_prompts_models.py
git commit -m "feat(mcp-gateway/prompts): Prompt/PromptMessage/PromptSummary を追加"
```

- [ ] **Step 7: Phase Base 向け Draft PR を作成**

```bash
git push -u origin feat/prompts-models
gh pr create --draft --base phase/1-prompts-domain \
  --title "feat(mcp-gateway/prompts): Prompt データモデル" \
  --body "Phase 1 Task 1.1: Prompt/PromptMessage/PromptSummary の不変データクラスを追加。MCP \`prompts/get\` の本文と \`prompts/list\` のサマリ表現。"
```

---

### Task 1.2: 言語別テンプレート関数群

**派生元:** Phase Base (`phase/1-prompts-domain`)

理由: テンプレートは models に依存せず、純粋なフォーマット関数の集合のため Task 1.1 と並行して開発可能。Phase Base から直接派生する。

**Files:**
- Create: `src/mcp_gateway/prompts/templates.py`
- Create: `tests/unit/test_mcp_gateway_prompts_templates.py`

- [ ] **Step 1: ブランチ作成**

```bash
git checkout phase/1-prompts-domain
git pull origin phase/1-prompts-domain
git checkout -b feat/prompts-templates phase/1-prompts-domain
```

- [ ] **Step 2: 失敗するテストを書く**

`tests/unit/test_mcp_gateway_prompts_templates.py`:

```python
"""Unit tests for language-specific prompt templates."""

from __future__ import annotations

import pytest

from mcp_gateway.prompts.templates import (
    render_prompt_body,
    render_tool_line,
)


def test_render_tool_line_en_without_approval() -> None:
    line = render_tool_line(
        language="en",
        tool_name="memory_search",
        description="Search memories by text or vector.",
        requires_approval=False,
    )
    assert line == "- memory_search: Search memories by text or vector."


def test_render_tool_line_en_with_approval_marker() -> None:
    line = render_tool_line(
        language="en",
        tool_name="memory_delete",
        description="Delete a memory by id.",
        requires_approval=True,
    )
    assert line.endswith("[REQUIRES APPROVAL]")
    assert "memory_delete" in line


def test_render_tool_line_ja_with_approval_marker() -> None:
    line = render_tool_line(
        language="ja",
        tool_name="memory_delete",
        description="記憶を ID で削除する。",
        requires_approval=True,
    )
    assert "[要承認]" in line
    assert "memory_delete" in line


def test_render_prompt_body_en_contains_role_and_tools_sections() -> None:
    body = render_prompt_body(
        language="en",
        intent_name="curate_memories",
        intent_description="Curate own working memory.",
        tool_lines=("- memory_search: Search memories.",),
    )
    assert "curate_memories" in body
    assert "## Role" in body
    assert "Curate own working memory." in body
    assert "## Available Tools" in body
    assert "- memory_search: Search memories." in body
    # Guardrails footnote about [REQUIRES APPROVAL] must be present in English template.
    assert "REQUIRES APPROVAL" in body


def test_render_prompt_body_ja_uses_japanese_section_headers() -> None:
    body = render_prompt_body(
        language="ja",
        intent_name="curate_memories",
        intent_description="自分の作業記憶をキュレーションする。",
        tool_lines=("- memory_search: 記憶を検索する。",),
    )
    assert "## 役割" in body
    assert "## 利用可能なツール" in body
    assert "要承認" in body


def test_render_prompt_body_when_no_tools_en() -> None:
    body = render_prompt_body(
        language="en",
        intent_name="x",
        intent_description="d",
        tool_lines=(),
    )
    assert "(none)" in body


def test_render_prompt_body_when_no_tools_ja() -> None:
    body = render_prompt_body(
        language="ja",
        intent_name="x",
        intent_description="d",
        tool_lines=(),
    )
    assert "（なし）" in body
    # Ensure English fallback did not leak into the Japanese template.
    assert "(none)" not in body


def test_render_unsupported_language_raises() -> None:
    with pytest.raises(ValueError, match="unsupported language"):
        render_prompt_body(
            language="de",  # type: ignore[arg-type]
            intent_name="x",
            intent_description="d",
            tool_lines=(),
        )
```

- [ ] **Step 3: テスト失敗を確認**

```bash
uv run pytest tests/unit/test_mcp_gateway_prompts_templates.py -v
```

Expected: `ModuleNotFoundError: No module named 'mcp_gateway.prompts.templates'`

- [ ] **Step 4: 最小実装**

`src/mcp_gateway/prompts/templates.py`:

```python
"""Language-specific text templates for server-defined prompts.

Templates are pure functions of inputs (intent name, description, tool lines).
Adding a new language = adding a new branch here only.
"""

from __future__ import annotations

from typing import Literal

PromptLanguage = Literal["en", "ja"]

_APPROVAL_MARKER = {
    "en": "[REQUIRES APPROVAL]",
    "ja": "[要承認]",
}


def render_tool_line(
    *,
    language: PromptLanguage,
    tool_name: str,
    description: str,
    requires_approval: bool,
) -> str:
    """Render a single bullet line for a tool in the Available Tools section."""
    if language not in _APPROVAL_MARKER:
        raise ValueError(f"unsupported language: {language!r}")
    base = f"- {tool_name}: {description}"
    if requires_approval:
        base = f"{base} {_APPROVAL_MARKER[language]}"
    return base


def render_prompt_body(
    *,
    language: PromptLanguage,
    intent_name: str,
    intent_description: str,
    tool_lines: tuple[str, ...],
) -> str:
    """Render the full prompt body (single user-role message text)."""
    if language == "en":
        return _render_en(intent_name, intent_description, tool_lines)
    if language == "ja":
        return _render_ja(intent_name, intent_description, tool_lines)
    raise ValueError(f"unsupported language: {language!r}")


def _render_en(
    intent_name: str, intent_description: str, tool_lines: tuple[str, ...]
) -> str:
    tools_block = "\n".join(tool_lines) if tool_lines else "(none)"
    return (
        f"You are operating under the '{intent_name}' role on ChronosGraph MCP Gateway.\n"
        "\n"
        "## Role\n"
        f"{intent_description}\n"
        "\n"
        "## Available Tools\n"
        f"{tools_block}\n"
        "\n"
        "Tools marked [REQUIRES APPROVAL] will block on a human approval gate\n"
        "before executing. Only call them when the operation is intentional."
    )


def _render_ja(
    intent_name: str, intent_description: str, tool_lines: tuple[str, ...]
) -> str:
    tools_block = "\n".join(tool_lines) if tool_lines else "（なし）"
    return (
        f"あなたは ChronosGraph MCP Gateway の '{intent_name}' ロールで動作しています。\n"
        "\n"
        "## 役割\n"
        f"{intent_description}\n"
        "\n"
        "## 利用可能なツール\n"
        f"{tools_block}\n"
        "\n"
        "[要承認] のマーカーが付いたツールは、実行前に人手による承認待ちで\n"
        "ブロックされます。操作が意図的な場合のみ呼び出してください。"
    )
```

- [ ] **Step 5: テスト成功を確認**

```bash
uv run pytest tests/unit/test_mcp_gateway_prompts_templates.py -v
uv run ruff check src/mcp_gateway/prompts/templates.py tests/unit/test_mcp_gateway_prompts_templates.py
uv run ruff format --check src/mcp_gateway/prompts/templates.py tests/unit/test_mcp_gateway_prompts_templates.py
uv run mypy src/mcp_gateway/prompts/
```

Expected: 全パス

- [ ] **Step 6: コミット**

```bash
git add src/mcp_gateway/prompts/templates.py \
        tests/unit/test_mcp_gateway_prompts_templates.py
git commit -m "feat(mcp-gateway/prompts): 言語別 (en/ja) テンプレート関数を追加"
```

- [ ] **Step 7: Phase Base 向け Draft PR を作成**

```bash
git push -u origin feat/prompts-templates
gh pr create --draft --base phase/1-prompts-domain \
  --title "feat(mcp-gateway/prompts): en/ja テンプレート関数" \
  --body "Phase 1 Task 1.2: \`render_prompt_body\` / \`render_tool_line\` を実装。言語別固定文言を一箇所に隔離。"
```

---

### Task 1.3: PromptBuilder（純粋関数）

**派生元:** Task 1.2 (`feat/prompts-templates`)

理由: `PromptBuilder` は Task 1.1 の `Prompt` と Task 1.2 の `render_prompt_body` の両方に依存するため、直前 Task の差分（Stacked）を必要とする。

**Files:**
- Create: `src/mcp_gateway/prompts/builder.py`
- Create: `tests/unit/test_mcp_gateway_prompts_builder.py`

- [ ] **Step 1: ブランチ作成（Task 1.1 と 1.2 の両方をマージ済みのベースを作る）**

```bash
git checkout phase/1-prompts-domain
git pull origin phase/1-prompts-domain
# Phase Base にはまだ Task 1.1/1.2 がマージされていない想定のため、両ブランチをマージしたローカル統合ベースを作る
git merge --no-ff feat/prompts-models -m "merge: Task 1.1 (models) into phase/1-prompts-domain"
git merge --no-ff feat/prompts-templates -m "merge: Task 1.2 (templates) into phase/1-prompts-domain"
git push origin phase/1-prompts-domain
git checkout -b feat/prompts-builder phase/1-prompts-domain
```

> **Note:** レビューサイクルで Task 1.1 / 1.2 の PR が先にマージされていれば `git merge` は自動的に no-op になる。コンフリクト発生時は `git status` を確認し、設計書の最終形と一致させること。

- [ ] **Step 2: 失敗するテストを書く**

`tests/unit/test_mcp_gateway_prompts_builder.py`:

```python
"""Unit tests for PromptBuilder."""

from __future__ import annotations

import pytest

from mcp_gateway.policy.models import (
    GatewayPolicy,
    IntentPolicy,
    OutputFilterDef,
    ToolGuardrail,
)
from mcp_gateway.prompts.builder import PromptBuilder


def _policy_for(intent: IntentPolicy) -> GatewayPolicy:
    return GatewayPolicy(
        version=1,
        output_filters={"curator_full": OutputFilterDef(type="none")},
        intents={"curate_memories": intent},
        agents={},
    )


_UPSTREAM_TOOLS = [
    {"name": "memory_search", "description": "Search memories by text or vector."},
    {"name": "memory_save", "description": "Persist a memory item."},
    {"name": "memory_delete", "description": "Delete a memory by id."},
    {"name": "memory_prune", "description": "Prune memories by criteria."},
]


def _curate_intent() -> IntentPolicy:
    return IntentPolicy(
        description="Curate own working memory. Search/save/delete; no external URL.",
        allowed_tools=["memory_search", "memory_save", "memory_delete", "memory_prune"],
        output_filter="curator_full",
        guardrails={
            "memory_delete": ToolGuardrail(requires_approval=True),
            "memory_prune": ToolGuardrail(requires_approval=True),
        },
    )


def test_build_all_returns_one_prompt_per_intent() -> None:
    policy = _policy_for(_curate_intent())
    result = PromptBuilder.build_all(
        policy=policy, tools=_UPSTREAM_TOOLS, language="en"
    )
    assert set(result.keys()) == {"curate_memories"}


def test_build_all_prompt_name_uses_chronos_graph_prefix() -> None:
    policy = _policy_for(_curate_intent())
    prompt = PromptBuilder.build_all(
        policy=policy, tools=_UPSTREAM_TOOLS, language="en"
    )["curate_memories"]
    assert prompt.name == "chronos-graph.curate_memories"


def test_build_all_description_matches_intent_description() -> None:
    intent = _curate_intent()
    policy = _policy_for(intent)
    prompt = PromptBuilder.build_all(
        policy=policy, tools=_UPSTREAM_TOOLS, language="en"
    )["curate_memories"]
    assert prompt.description == intent.description


def test_build_all_body_lists_every_allowed_tool_with_descriptions() -> None:
    policy = _policy_for(_curate_intent())
    prompt = PromptBuilder.build_all(
        policy=policy, tools=_UPSTREAM_TOOLS, language="en"
    )["curate_memories"]
    text = prompt.messages[0].text
    for tool in _UPSTREAM_TOOLS:
        assert tool["name"] in text
        assert tool["description"] in text


def test_build_all_marks_requires_approval_tools() -> None:
    policy = _policy_for(_curate_intent())
    prompt = PromptBuilder.build_all(
        policy=policy, tools=_UPSTREAM_TOOLS, language="en"
    )["curate_memories"]
    text = prompt.messages[0].text
    # delete/prune require approval, search/save do not
    assert "memory_delete: Delete a memory by id. [REQUIRES APPROVAL]" in text
    assert "memory_prune: Prune memories by criteria. [REQUIRES APPROVAL]" in text
    assert "memory_search: Search memories by text or vector." in text
    assert "memory_save: Persist a memory item." in text
    # And no false positive on memory_search
    assert "memory_search: Search memories by text or vector. [REQUIRES APPROVAL]" not in text


def test_build_all_skips_unknown_upstream_tool(caplog: pytest.LogCaptureFixture) -> None:
    intent = IntentPolicy(
        description="x",
        allowed_tools=["memory_search", "ghost_tool"],
        output_filter="curator_full",
    )
    policy = _policy_for(intent)
    with caplog.at_level("WARNING", logger="mcp_gateway.prompts.builder"):
        prompt = PromptBuilder.build_all(
            policy=policy, tools=_UPSTREAM_TOOLS, language="en"
        )["curate_memories"]
    text = prompt.messages[0].text
    assert "memory_search" in text
    assert "ghost_tool" not in text
    assert any("ghost_tool" in r.message for r in caplog.records)


def test_build_all_ja_uses_japanese_template() -> None:
    policy = _policy_for(_curate_intent())
    prompt = PromptBuilder.build_all(
        policy=policy, tools=_UPSTREAM_TOOLS, language="ja"
    )["curate_memories"]
    assert "## 役割" in prompt.messages[0].text
    assert "## 利用可能なツール" in prompt.messages[0].text


def test_build_all_empty_description_raises() -> None:
    bad = IntentPolicy(
        description="",
        allowed_tools=["memory_search"],
        output_filter="curator_full",
    )
    policy = _policy_for(bad)
    with pytest.raises(ValueError, match="empty description"):
        PromptBuilder.build_all(policy=policy, tools=_UPSTREAM_TOOLS, language="en")


def test_build_all_is_deterministic() -> None:
    policy = _policy_for(_curate_intent())
    a = PromptBuilder.build_all(policy=policy, tools=_UPSTREAM_TOOLS, language="en")
    b = PromptBuilder.build_all(policy=policy, tools=_UPSTREAM_TOOLS, language="en")
    assert a == b
```

- [ ] **Step 3: テスト失敗を確認**

```bash
uv run pytest tests/unit/test_mcp_gateway_prompts_builder.py -v
```

Expected: `ImportError: cannot import name 'PromptBuilder'`

- [ ] **Step 4: 最小実装**

`src/mcp_gateway/prompts/builder.py`:

```python
"""Build immutable Prompt objects from policy + upstream tool catalog."""

from __future__ import annotations

import logging
from typing import Any

from mcp_gateway.policy.models import GatewayPolicy, IntentPolicy
from mcp_gateway.prompts.models import Prompt, PromptMessage
from mcp_gateway.prompts.templates import (
    PromptLanguage,
    render_prompt_body,
    render_tool_line,
)

_logger = logging.getLogger(__name__)


class PromptBuilder:
    """Pure-function helpers; no I/O, no state."""

    @staticmethod
    def build_all(
        *,
        policy: GatewayPolicy,
        tools: list[dict[str, Any]],
        language: PromptLanguage,
    ) -> dict[str, Prompt]:
        tools_by_name = {t["name"]: t for t in tools if isinstance(t.get("name"), str)}
        result: dict[str, Prompt] = {}
        for intent_name, intent in policy.intents.items():
            result[intent_name] = PromptBuilder._render(
                intent_name=intent_name,
                intent=intent,
                tools_by_name=tools_by_name,
                language=language,
            )
        return result

    @staticmethod
    def _render(
        *,
        intent_name: str,
        intent: IntentPolicy,
        tools_by_name: dict[str, dict[str, Any]],
        language: PromptLanguage,
    ) -> Prompt:
        if not intent.description:
            raise ValueError(f"intent {intent_name!r} has empty description")

        tool_lines: list[str] = []
        for tool_name in intent.allowed_tools:
            upstream = tools_by_name.get(tool_name)
            if upstream is None:
                _logger.warning(
                    "intent %r references tool %r that is not in upstream tools/list; "
                    "skipping in prompt body",
                    intent_name,
                    tool_name,
                )
                continue
            description = str(upstream.get("description") or "")
            guardrail = intent.guardrails.get(tool_name)
            requires_approval = bool(guardrail and guardrail.requires_approval)
            tool_lines.append(
                render_tool_line(
                    language=language,
                    tool_name=tool_name,
                    description=description,
                    requires_approval=requires_approval,
                )
            )

        body = render_prompt_body(
            language=language,
            intent_name=intent_name,
            intent_description=intent.description,
            tool_lines=tuple(tool_lines),
        )
        return Prompt(
            name=f"chronos-graph.{intent_name}",
            description=intent.description,
            messages=(PromptMessage(role="user", text=body),),
        )
```

- [ ] **Step 5: テスト成功を確認**

```bash
uv run pytest tests/unit/test_mcp_gateway_prompts_builder.py -v
uv run ruff check src/mcp_gateway/prompts/ tests/unit/test_mcp_gateway_prompts_builder.py
uv run ruff format --check src/mcp_gateway/prompts/ tests/unit/test_mcp_gateway_prompts_builder.py
uv run mypy src/mcp_gateway/prompts/
```

Expected: 全パス

- [ ] **Step 6: コミット**

```bash
git add src/mcp_gateway/prompts/builder.py \
        tests/unit/test_mcp_gateway_prompts_builder.py
git commit -m "feat(mcp-gateway/prompts): PromptBuilder で policy+tools から Prompt 合成"
```

- [ ] **Step 7: Phase Base 向け Draft PR を作成**

```bash
git push -u origin feat/prompts-builder
gh pr create --draft --base phase/1-prompts-domain \
  --title "feat(mcp-gateway/prompts): PromptBuilder（純粋関数）" \
  --body "Phase 1 Task 1.3: \`PromptBuilder.build_all\` で policy + upstream tools + language から決定論的に Prompt を生成。フェイルファスト・空 description で ValueError、不明 tool は warning ログ＋スキップ。Stack base: Task 1.1, 1.2"
```

---

## Phase 2: PromptRegistry（不変キャッシュ）

**Phase Base ブランチ:** `phase/2-prompts-registry`（`master` から派生、Phase 1 マージ後）

### Task 2.1: PromptRegistry

**派生元:** Phase Base (`phase/2-prompts-registry`)

理由: Phase 1 の models のみに依存。Phase 1 が `master` にマージ済みであれば、Phase 2 Base から直接派生して単体で完結する。

**Files:**
- Create: `src/mcp_gateway/prompts/registry.py`
- Create: `tests/unit/test_mcp_gateway_prompts_registry.py`

- [ ] **Step 1: ブランチ作成**

```bash
git fetch origin master
git checkout -b phase/2-prompts-registry origin/master
git push -u origin phase/2-prompts-registry
git checkout -b feat/prompts-registry phase/2-prompts-registry
```

- [ ] **Step 2: 失敗するテストを書く**

`tests/unit/test_mcp_gateway_prompts_registry.py`:

```python
"""Unit tests for PromptRegistry (authorization boundary)."""

from __future__ import annotations

from mcp_gateway.prompts.models import Prompt, PromptMessage
from mcp_gateway.prompts.registry import PromptRegistry


def _make_prompt(intent: str) -> Prompt:
    return Prompt(
        name=f"chronos-graph.{intent}",
        description=f"desc-{intent}",
        messages=(PromptMessage(role="user", text=f"body-{intent}"),),
    )


def test_list_for_registered_intent_returns_one_summary() -> None:
    reg = PromptRegistry({"curate_memories": _make_prompt("curate_memories")})
    summaries = reg.list_for("curate_memories")
    assert len(summaries) == 1
    assert summaries[0].name == "chronos-graph.curate_memories"
    assert summaries[0].description == "desc-curate_memories"
    assert summaries[0].arguments == ()


def test_list_for_unknown_intent_returns_empty_list() -> None:
    reg = PromptRegistry({"curate_memories": _make_prompt("curate_memories")})
    assert reg.list_for("unknown_intent") == []


def test_get_for_matching_intent_and_name_returns_prompt() -> None:
    reg = PromptRegistry({"curate_memories": _make_prompt("curate_memories")})
    prompt = reg.get_for("curate_memories", "chronos-graph.curate_memories")
    assert prompt is not None
    assert prompt.messages[0].text == "body-curate_memories"


def test_get_for_unknown_intent_returns_none() -> None:
    reg = PromptRegistry({"curate_memories": _make_prompt("curate_memories")})
    assert reg.get_for("unknown_intent", "chronos-graph.curate_memories") is None


def test_get_for_returns_none_when_name_targets_other_intent() -> None:
    # CRITICAL: prevents cross-intent prompt leakage. See design §4.5.
    reg = PromptRegistry(
        {
            "curate_memories": _make_prompt("curate_memories"),
            "read_only_recall": _make_prompt("read_only_recall"),
        }
    )
    # Session intent = curate_memories but client asks for read_only_recall prompt
    assert reg.get_for("curate_memories", "chronos-graph.read_only_recall") is None


def test_get_for_does_not_strip_prefix_to_relookup() -> None:
    # Even if intent name equals the trailing portion of `name`, the only
    # lookup is by `intent` → must not fall back to suffix matching.
    reg = PromptRegistry({"curate_memories": _make_prompt("curate_memories")})
    # Bare suffix without prefix must not resolve
    assert reg.get_for("curate_memories", "curate_memories") is None


def test_internal_map_is_immutable_view() -> None:
    backing = {"curate_memories": _make_prompt("curate_memories")}
    reg = PromptRegistry(backing)
    # Mutating the backing dict must not affect the registry (defensive copy).
    backing["curate_memories"] = _make_prompt("other")
    prompt = reg.get_for("curate_memories", "chronos-graph.curate_memories")
    assert prompt is not None
    assert prompt.messages[0].text == "body-curate_memories"


def test_default_constructor_yields_empty_registry() -> None:
    # The no-arg form is what app.py uses before lifespan runs.
    reg = PromptRegistry()
    assert reg.list_for("anything") == []


def test_replace_swaps_underlying_mapping() -> None:
    reg = PromptRegistry()
    assert reg.list_for("curate_memories") == []
    reg.replace({"curate_memories": _make_prompt("curate_memories")})
    summaries = reg.list_for("curate_memories")
    assert len(summaries) == 1
    assert summaries[0].name == "chronos-graph.curate_memories"


def test_replace_isolates_caller_dict_mutation() -> None:
    reg = PromptRegistry()
    new_map = {"curate_memories": _make_prompt("curate_memories")}
    reg.replace(new_map)
    # Mutating the caller's dict afterward must not bleed into the registry.
    new_map["curate_memories"] = _make_prompt("other")
    prompt = reg.get_for("curate_memories", "chronos-graph.curate_memories")
    assert prompt is not None
    assert prompt.messages[0].text == "body-curate_memories"
```

- [ ] **Step 3: テスト失敗を確認**

```bash
uv run pytest tests/unit/test_mcp_gateway_prompts_registry.py -v
```

Expected: `ImportError: cannot import name 'PromptRegistry'`

- [ ] **Step 4: 最小実装**

`src/mcp_gateway/prompts/registry.py`:

```python
"""Startup-only mutable, post-lifespan effectively immutable prompt cache."""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

from mcp_gateway.prompts.models import Prompt, PromptSummary


class PromptRegistry:
    """Intent-keyed prompt store wired into `app.state` and `build_router`.

    Lifecycle:
        * `__init__` creates an empty instance at app-construction time
          (before `lifespan` runs, so the same instance can be injected
          into both `app.state.prompt_registry` and `build_router(...)`).
        * `replace()` is the ONLY mutation entry point. It is intended to
          be invoked exactly once during lifespan startup with the result
          of `PromptBuilder.build_all(...)`. After that single call, the
          internal `MappingProxyType` view is treated as immutable by all
          readers (`list_for`, `get_for`).
        * No other code path mutates the registry. This mirrors the
          `ToolRegistry.replace_tools()` pattern used elsewhere in the
          gateway.

    Authorization boundary: every lookup is keyed by the caller's session
    intent. `get_for` returns the prompt **only** when both intent and the
    fully-qualified `name` match. Suffix/prefix relookup is forbidden by
    design (see specs §4.5).
    """

    def __init__(self, prompts_by_intent: Mapping[str, Prompt] | None = None) -> None:
        # Defensive copy so external mutation cannot reach the proxy view.
        self._prompts: Mapping[str, Prompt] = MappingProxyType(
            dict(prompts_by_intent or {})
        )

    def replace(self, prompts_by_intent: Mapping[str, Prompt]) -> None:
        """Swap the underlying mapping. Call exactly once from lifespan startup."""
        self._prompts = MappingProxyType(dict(prompts_by_intent))

    def list_for(self, intent: str) -> list[PromptSummary]:
        prompt = self._prompts.get(intent)
        if prompt is None:
            return []
        return [PromptSummary(name=prompt.name, description=prompt.description)]

    def get_for(self, intent: str, name: str) -> Prompt | None:
        prompt = self._prompts.get(intent)
        if prompt is None:
            return None
        if prompt.name != name:
            return None
        return prompt
```

- [ ] **Step 5: テスト成功を確認**

```bash
uv run pytest tests/unit/test_mcp_gateway_prompts_registry.py -v
uv run ruff check src/mcp_gateway/prompts/registry.py tests/unit/test_mcp_gateway_prompts_registry.py
uv run ruff format --check src/mcp_gateway/prompts/registry.py tests/unit/test_mcp_gateway_prompts_registry.py
uv run mypy src/mcp_gateway/prompts/
```

Expected: 全パス

- [ ] **Step 6: コミット**

```bash
git add src/mcp_gateway/prompts/registry.py \
        tests/unit/test_mcp_gateway_prompts_registry.py
git commit -m "feat(mcp-gateway/prompts): PromptRegistry を追加（intent キー認可境界）"
```

- [ ] **Step 7: Phase Base 向け Draft PR を作成**

```bash
git push -u origin feat/prompts-registry
gh pr create --draft --base phase/2-prompts-registry \
  --title "feat(mcp-gateway/prompts): PromptRegistry（不変キャッシュ）" \
  --body "Phase 2 Task 2.1: \`PromptRegistry\` を実装。\`MappingProxyType\` による不変ビュー、intent をキーとする一次照合のみ（クロス intent 漏洩を構造的に防止）。設計書 §3.3, §4.5 を参照。"
```

---

## Phase 3: 配線（config / app / server）

**Phase Base ブランチ:** `phase/3-prompts-wiring`（`master` から派生、Phase 1, 2 マージ後）

### Task 3.1: `GatewaySettings.prompt_language` 追加

**派生元:** Phase Base (`phase/3-prompts-wiring`)

理由: 設定追加のみで、新フィールドは未使用のまま `master` にマージしても既存機能に影響しない。単体完結。

**Files:**
- Modify: `src/mcp_gateway/config.py`
- Create: `tests/unit/test_mcp_gateway_prompts_config.py`

- [ ] **Step 1: ブランチ作成**

```bash
git fetch origin master
git checkout -b phase/3-prompts-wiring origin/master
git push -u origin phase/3-prompts-wiring
git checkout -b feat/prompts-config phase/3-prompts-wiring
```

- [ ] **Step 2: 失敗するテストを書く**

`tests/unit/test_mcp_gateway_prompts_config.py`:

```python
"""Unit tests for the prompt_language setting."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from mcp_gateway.config import GatewaySettings


def _existing_policy(tmp_path: Path) -> Path:
    p = tmp_path / "intents.yaml"
    p.write_text("version: 1\noutput_filters: {}\nintents: {}\nagents: {}\n")
    return p


def test_prompt_language_defaults_to_en(tmp_path: Path) -> None:
    settings = GatewaySettings(policy_path=_existing_policy(tmp_path))
    assert settings.prompt_language == "en"


def test_prompt_language_accepts_ja(tmp_path: Path) -> None:
    settings = GatewaySettings(
        policy_path=_existing_policy(tmp_path), prompt_language="ja"
    )
    assert settings.prompt_language == "ja"


def test_prompt_language_rejects_unsupported_value(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        GatewaySettings(
            policy_path=_existing_policy(tmp_path),
            prompt_language="de",  # type: ignore[arg-type]
        )
```

- [ ] **Step 3: テスト失敗を確認**

```bash
uv run pytest tests/unit/test_mcp_gateway_prompts_config.py -v
```

Expected: `AttributeError` または `ValidationError`（`prompt_language` 未定義）

- [ ] **Step 4: 最小実装**

`src/mcp_gateway/config.py` の `audit_log_level` フィールド直後（line 60 付近）に追加:

```python
    # ── prompts (server-defined) ─────────────────────────────────
    prompt_language: Literal["en", "ja"] = "en"
```

- [ ] **Step 5: テスト成功を確認**

```bash
uv run pytest tests/unit/test_mcp_gateway_prompts_config.py -v
uv run ruff check src/mcp_gateway/config.py tests/unit/test_mcp_gateway_prompts_config.py
uv run ruff format --check src/mcp_gateway/config.py tests/unit/test_mcp_gateway_prompts_config.py
uv run mypy src/mcp_gateway/config.py
```

Expected: 全パス

- [ ] **Step 6: コミット**

```bash
git add src/mcp_gateway/config.py tests/unit/test_mcp_gateway_prompts_config.py
git commit -m "feat(mcp-gateway/config): prompt_language 設定（en/ja）を追加"
```

- [ ] **Step 7: Phase Base 向け Draft PR を作成**

```bash
git push -u origin feat/prompts-config
gh pr create --draft --base phase/3-prompts-wiring \
  --title "feat(mcp-gateway/config): prompt_language 設定追加" \
  --body "Phase 3 Task 3.1: \`GatewaySettings.prompt_language: Literal[\\\"en\\\", \\\"ja\\\"]\` を追加。デフォルト \"en\"。"
```

---

### Task 3.2: `app.py` lifespan へ PromptRegistry を組み込む

**派生元:** Task 3.1 (`feat/prompts-config`)

理由: `prompt_language` 設定と `PromptBuilder` / `PromptRegistry` を同時に使うため、直前 Task の差分（config）を前提とする Stacked PR。

**Files:**
- Modify: `src/mcp_gateway/app.py`
- Create: `tests/unit/test_mcp_gateway_prompts_app.py`

- [ ] **Step 1: ブランチ作成**

```bash
git checkout feat/prompts-config
git pull origin feat/prompts-config
git checkout -b feat/prompts-app feat/prompts-config
```

- [ ] **Step 2: 失敗するテストを書く**

`tests/unit/test_mcp_gateway_prompts_app.py`:

```python
"""Lifespan-level wiring tests for prompts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from mcp_gateway.app import build_app


class _FakeUpstream:
    def __init__(self, tools: list[dict[str, Any]]) -> None:
        self._tools = tools

    async def list_tools(self) -> list[dict[str, Any]]:
        return list(self._tools)


@pytest.fixture()
def policy_yaml(tmp_path: Path) -> Path:
    p = tmp_path / "intents.yaml"
    p.write_text(
        """
version: 1
output_filters:
  curator_full:
    type: none
intents:
  curate_memories:
    description: "Curate own working memory."
    allowed_tools: [memory_search]
    output_filter: curator_full
agents:
  curator-bot:
    allowed_intents: [curate_memories]
""".strip()
    )
    return p


def test_lifespan_populates_prompt_registry(
    monkeypatch: pytest.MonkeyPatch, policy_yaml: Path
) -> None:
    monkeypatch.setenv("MCP_GATEWAY_POLICY_PATH", str(policy_yaml))
    upstream = _FakeUpstream(
        [{"name": "memory_search", "description": "Search memories."}]
    )
    app = build_app(upstream_override=upstream)
    with TestClient(app):
        registry = app.state.prompt_registry
        summaries = registry.list_for("curate_memories")
        assert len(summaries) == 1
        assert summaries[0].name == "chronos-graph.curate_memories"


def test_lifespan_respects_prompt_language_setting(
    monkeypatch: pytest.MonkeyPatch, policy_yaml: Path
) -> None:
    monkeypatch.setenv("MCP_GATEWAY_POLICY_PATH", str(policy_yaml))
    monkeypatch.setenv("MCP_GATEWAY_PROMPT_LANGUAGE", "ja")
    upstream = _FakeUpstream(
        [{"name": "memory_search", "description": "記憶を検索する。"}]
    )
    app = build_app(upstream_override=upstream)
    with TestClient(app):
        registry = app.state.prompt_registry
        prompt = registry.get_for("curate_memories", "chronos-graph.curate_memories")
        assert prompt is not None
        assert "## 役割" in prompt.messages[0].text
```

- [ ] **Step 3: テスト失敗を確認**

```bash
uv run pytest tests/unit/test_mcp_gateway_prompts_app.py -v
```

Expected: `AttributeError: 'State' object has no attribute 'prompt_registry'`

- [ ] **Step 4: 最小実装**

`build_router` は `lifespan` 開始**前**に呼ばれるため、`PromptRegistry` インスタンスを `build_router` 呼び出し前に生成し、`app.state.prompt_registry` と `build_router` の両方に**同じインスタンス**を渡す。lifespan 内では `replace()` で内部 mapping を差し替える（`ToolRegistry.replace_tools()` と同型）。`build_router` 引数追加そのものは Task 3.3 で行うため、本 Task では `app.state` への配置と lifespan 内の `replace()` 呼び出しまでを実装する。

a. import 追加（既存 `from mcp_gateway.tools.registry import ToolRegistry` の直後）:

```python
from mcp_gateway.prompts.builder import PromptBuilder
from mcp_gateway.prompts.registry import PromptRegistry
```

b. `build_app` 関数内、`registry = ToolRegistry(initial_tools or [])` の直後に空 `PromptRegistry` を生成:

```python
    registry = ToolRegistry(initial_tools or [])
    prompt_registry = PromptRegistry()
```

c. `lifespan` 関数内、`registry.replace_tools(all_tools)` の直後で `replace()` を呼ぶ:

```python
            # Initialize or update tool / prompt registry on startup
            if hasattr(upstream, "list_tools"):
                all_tools = await upstream.list_tools()
                registry.replace_tools(all_tools)
                prompt_registry.replace(
                    PromptBuilder.build_all(
                        policy=policy,
                        tools=all_tools,
                        language=settings.prompt_language,
                    )
                )
```

d. `app.state.tool_registry = registry` の直後に `app.state` への配置を追加:

```python
    app.state.tool_registry = registry
    app.state.prompt_registry = prompt_registry
```

> **Note:** `PromptRegistry` インスタンスを 1 回だけ生成し、`app.state` と (Task 3.3 で) `build_router` の双方に共有するため、`lifespan` 内では新規インスタンス化せず `replace()` のみを使う。これが本機能における唯一正規のミューテーション経路。

- [ ] **Step 5: テスト成功を確認**

```bash
uv run pytest tests/unit/test_mcp_gateway_prompts_app.py -v
uv run pytest tests/unit/ -v  # 既存単体テストの非リグレッション
uv run ruff check src/mcp_gateway/app.py tests/unit/test_mcp_gateway_prompts_app.py
uv run ruff format --check src/mcp_gateway/app.py tests/unit/test_mcp_gateway_prompts_app.py
uv run mypy src/mcp_gateway/
```

Expected: 全パス

- [ ] **Step 6: コミット**

```bash
git add src/mcp_gateway/app.py tests/unit/test_mcp_gateway_prompts_app.py
git commit -m "feat(mcp-gateway/app): lifespan で PromptRegistry を構築・app.state へ配置"
```

- [ ] **Step 7: Phase Base 向け Draft PR を作成**

```bash
git push -u origin feat/prompts-app
gh pr create --draft --base phase/3-prompts-wiring \
  --title "feat(mcp-gateway/app): PromptRegistry を lifespan で構築" \
  --body "Phase 3 Task 3.2: \`build_router\` 前に空の \`PromptRegistry\` を生成して \`app.state.prompt_registry\` に配置し、lifespan 内で \`PromptBuilder.build_all\` の結果を \`replace()\` で差し替える。以降は事実上不変。\`ToolRegistry.replace_tools\` と対称な配線。Stack base: Task 3.1 (config)"
```

---

### Task 3.3: `server.py` ディスパッチャ拡張（`prompts/list` & `prompts/get`）

**派生元:** Task 3.2 (`feat/prompts-app`)

理由: `record.intent` をキーにした `app.state.prompt_registry` の参照と、`build_router` の引数追加が必要。前 Task の差分（registry が app.state に存在する事実）を前提とする Stacked PR。

**Files:**
- Modify: `src/mcp_gateway/server.py`（`build_router` シグネチャ拡張 + dispatcher 分岐 2 つ）
- Modify: `src/mcp_gateway/app.py`（`build_router` 呼び出しに `prompt_registry` を追加）
- Create: `tests/unit/test_mcp_gateway_prompts_dispatch.py`

- [ ] **Step 1: ブランチ作成**

```bash
git checkout feat/prompts-app
git pull origin feat/prompts-app
git checkout -b feat/prompts-dispatch feat/prompts-app
```

- [ ] **Step 2: 失敗するテストを書く**

`tests/unit/test_mcp_gateway_prompts_dispatch.py`:

```python
"""Dispatcher-level tests for prompts/list and prompts/get."""

from __future__ import annotations

import json as _json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from mcp_gateway.app import build_app


class _FakeUpstream:
    def __init__(self, tools: list[dict[str, Any]]) -> None:
        self._tools = tools

    async def list_tools(self) -> list[dict[str, Any]]:
        return list(self._tools)


@pytest.fixture()
def policy_yaml(tmp_path: Path) -> Path:
    p = tmp_path / "intents.yaml"
    p.write_text(
        """
version: 1
output_filters:
  curator_full:
    type: none
  recall_safe:
    type: structural_allowlist
    schemas:
      memory_search:
        results: [id]
intents:
  curate_memories:
    description: "Curate own working memory."
    allowed_tools: [memory_search, memory_delete]
    output_filter: curator_full
    guardrails:
      memory_delete:
        requires_approval: true
  read_only_recall:
    description: "Read-only recall."
    allowed_tools: [memory_search]
    output_filter: recall_safe
agents:
  curator-bot:
    allowed_intents: [curate_memories, read_only_recall]
""".strip()
    )
    return p


@pytest.fixture()
def client(
    monkeypatch: pytest.MonkeyPatch, policy_yaml: Path
) -> Iterator[TestClient]:
    monkeypatch.setenv("MCP_GATEWAY_POLICY_PATH", str(policy_yaml))
    monkeypatch.setenv(
        "MCP_GATEWAY_API_KEYS_JSON",
        _json.dumps({"curator-bot": "k-curator"}),
    )
    upstream = _FakeUpstream(
        [
            {"name": "memory_search", "description": "Search memories."},
            {"name": "memory_delete", "description": "Delete a memory."},
        ]
    )
    app = build_app(upstream_override=upstream)
    with TestClient(app) as c:
        yield c


def _handshake(client: TestClient, *, intent: str) -> str:
    resp = client.get(
        "/sse",
        headers={
            "Authorization": "Bearer k-curator",
            "x-mcp-intent": intent,
        },
        stream=True,
    )
    try:
        assert resp.status_code == 200
        # First SSE event carries the endpoint with session_id query param.
        for raw in resp.iter_lines():
            if not raw:
                continue
            text = raw.decode() if isinstance(raw, bytes) else raw
            if "session_id=" in text:
                return text.split("session_id=")[-1].strip()
        raise AssertionError("session_id not received from SSE handshake")
    finally:
        resp.close()


def test_prompts_list_returns_one_entry_for_session_intent(client: TestClient) -> None:
    sid = _handshake(client, intent="curate_memories")
    r = client.post(
        f"/messages?session_id={sid}",
        json={"jsonrpc": "2.0", "id": 1, "method": "prompts/list"},
    )
    assert r.status_code == 200
    body = r.json()
    prompts = body["result"]["prompts"]
    assert len(prompts) == 1
    assert prompts[0]["name"] == "chronos-graph.curate_memories"
    assert prompts[0]["arguments"] == []


def test_prompts_get_returns_body_for_own_intent(client: TestClient) -> None:
    sid = _handshake(client, intent="curate_memories")
    r = client.post(
        f"/messages?session_id={sid}",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "prompts/get",
            "params": {"name": "chronos-graph.curate_memories"},
        },
    )
    assert r.status_code == 200
    body = r.json()
    result = body["result"]
    assert "Curate own working memory." in result["description"]
    messages = result["messages"]
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    text = messages[0]["content"]["text"]
    assert messages[0]["content"]["type"] == "text"
    assert "memory_search" in text
    assert "memory_delete" in text
    assert "[REQUIRES APPROVAL]" in text


def test_prompts_get_rejects_other_intent_prompt(client: TestClient) -> None:
    sid = _handshake(client, intent="curate_memories")
    r = client.post(
        f"/messages?session_id={sid}",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "prompts/get",
            "params": {"name": "chronos-graph.read_only_recall"},
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["error"]["code"] == -32602
    assert "unknown prompt" in body["error"]["message"]


def test_prompts_get_missing_params_returns_invalid_params(client: TestClient) -> None:
    sid = _handshake(client, intent="curate_memories")
    r = client.post(
        f"/messages?session_id={sid}",
        json={"jsonrpc": "2.0", "id": 4, "method": "prompts/get"},
    )
    assert r.status_code == 200
    assert r.json()["error"]["code"] == -32602


def test_prompts_get_missing_name_returns_invalid_params(client: TestClient) -> None:
    sid = _handshake(client, intent="curate_memories")
    r = client.post(
        f"/messages?session_id={sid}",
        json={"jsonrpc": "2.0", "id": 5, "method": "prompts/get", "params": {}},
    )
    assert r.status_code == 200
    assert r.json()["error"]["code"] == -32602
```

- [ ] **Step 3: テスト失敗を確認**

```bash
uv run pytest tests/unit/test_mcp_gateway_prompts_dispatch.py -v
```

Expected: `unknown method 'prompts/list'` 等のエラー（-32601）

- [ ] **Step 4: `server.py` の `build_router` シグネチャに `prompt_registry` を追加**

`src/mcp_gateway/server.py`:

a. import 追加（既存 import 群の末尾、`from mcp_gateway.tools.registry import ToolRegistry` の直後）:

```python
from mcp_gateway.prompts.registry import PromptRegistry
```

b. `build_router` の引数に追加（既存 `tool_registry: ToolRegistry,` の直後）:

```python
    prompt_registry: PromptRegistry,
```

c. dispatcher の `if method == "tools/call":` ブロックの直後（既存 `if method == "tools/call":` の `return JSONResponse(...)` 群の閉じ後、`return JSONResponse(... unknown method ...)` の直前）に以下を挿入:

```python
        if method == "prompts/list":
            summaries = prompt_registry.list_for(record.intent)
            log_extra: dict[str, Any] = {}
            if not summaries:
                log_extra["reason"] = "intent_not_registered"
            audit.log(
                ev="prompts_list",
                decision="allow",
                agent=record.agent_id,
                intent=record.intent,
                sid=sid,
                count=len(summaries),
                **log_extra,
            )
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "result": {
                        "prompts": [
                            {
                                "name": s.name,
                                "description": s.description,
                                "arguments": list(s.arguments),
                            }
                            for s in summaries
                        ]
                    },
                }
            )

        if method == "prompts/get":
            params = body.get("params")
            if not isinstance(params, dict):
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": rpc_id,
                        "error": {
                            "code": -32602,
                            "message": "Invalid params: 'params' must be an object",
                        },
                    }
                )
            prompt_name = params.get("name")
            if not isinstance(prompt_name, str) or not prompt_name:
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": rpc_id,
                        "error": {
                            "code": -32602,
                            "message": "Invalid params: missing required parameter: name",
                        },
                    }
                )
            prompt = prompt_registry.get_for(record.intent, prompt_name)
            if prompt is None:
                audit.log(
                    ev="prompts_get",
                    decision="deny",
                    reason="unknown_prompt",
                    agent=record.agent_id,
                    intent=record.intent,
                    sid=sid,
                    prompt=prompt_name,
                )
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": rpc_id,
                        "error": {
                            "code": -32602,
                            "message": f"unknown prompt {prompt_name!r}",
                        },
                    }
                )
            audit.log(
                ev="prompts_get",
                decision="allow",
                agent=record.agent_id,
                intent=record.intent,
                sid=sid,
                prompt=prompt_name,
            )
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "result": {
                        "description": prompt.description,
                        "messages": [
                            {
                                "role": m.role,
                                "content": {"type": "text", "text": m.text},
                            }
                            for m in prompt.messages
                        ],
                    },
                }
            )
```

- [ ] **Step 5: `app.py` で `build_router` へ `prompt_registry` を渡す**

Task 3.2 で既に `prompt_registry = PromptRegistry()` を `build_router` 呼び出し前に生成し、`app.state.prompt_registry` に配置し、lifespan で `prompt_registry.replace(...)` を呼ぶ構成にしてある。本 Step では `build_router` のキーワード引数を増やすのみ。

`src/mcp_gateway/app.py` の `app.include_router(build_router(...))` 呼び出しに `prompt_registry=prompt_registry` を追加:

```python
    app.include_router(
        build_router(
            handshake=handshake,
            sessions=sessions,
            tool_registry=registry,
            prompt_registry=prompt_registry,  # NEW: same instance as app.state.prompt_registry
            upstream=upstream,
            policy=policy,
            audit=audit,
            engine=engine,
            approval_notifier=LogOnlyApprovalNotifier(),
            approval_registry=approval_registry if settings.approval_blocking_mode else None,
            approval_blocking_mode=settings.approval_blocking_mode,
            approval_timeout_seconds=settings.approval_timeout_seconds,
            api_authenticator=auth,
        )
    )
```

> **Note:** `build_router` が lifespan より先に評価される時点では `prompt_registry` の内部 mapping は空。実際の呼び出し（`/messages` 受信時）は lifespan 完了後となるため、`replace()` 済みの状態でハンドラが起動する。これにより `tool_registry` の `replace_tools()` パターンと完全に対称な配線が実現する。

- [ ] **Step 6: テスト成功を確認**

```bash
uv run pytest tests/unit/test_mcp_gateway_prompts_dispatch.py -v
uv run pytest tests/unit/test_mcp_gateway_prompts_registry.py -v
uv run pytest tests/unit/test_mcp_gateway_prompts_app.py -v
uv run pytest tests/unit/ -v  # 既存単体テストの非リグレッション
uv run ruff check src/mcp_gateway/ tests/unit/
uv run ruff format --check src/mcp_gateway/ tests/unit/
uv run mypy src/mcp_gateway/
```

Expected: 全パス

- [ ] **Step 7: コミット**

```bash
git add src/mcp_gateway/server.py \
        src/mcp_gateway/app.py \
        tests/unit/test_mcp_gateway_prompts_dispatch.py
git commit -m "feat(mcp-gateway/server): prompts/list, prompts/get ディスパッチャを追加"
```

- [ ] **Step 8: Phase Base 向け Draft PR を作成**

```bash
git push -u origin feat/prompts-dispatch
gh pr create --draft --base phase/3-prompts-wiring \
  --title "feat(mcp-gateway/server): prompts/list & prompts/get ディスパッチャ" \
  --body "Phase 3 Task 3.3: JSON-RPC \`prompts/list\` / \`prompts/get\` を実装。\`record.intent\` をキーに認可境界を維持。-32602 \"unknown prompt\" で他 intent 漏洩を構造的に防止。\`build_router\` には Task 3.2 で生成済みの \`PromptRegistry\` 同一インスタンスを渡す。Stack base: Task 3.2 (app)"
```

---

## Phase 4: E2E テスト + SPEC 更新

**Phase Base ブランチ:** `phase/4-prompts-e2e-docs`（`master` から派生、Phase 1, 2, 3 マージ後）

### Task 4.1: E2E 統合テスト

**派生元:** Phase Base (`phase/4-prompts-e2e-docs`)

理由: Phase 3 マージ後の `master` に対する純粋なテスト追加。コードに依存なし。

**Files:**
- Create: `tests/integration/test_mcp_gateway_prompts_e2e.py`

- [ ] **Step 1: ブランチ作成**

```bash
git fetch origin master
git checkout -b phase/4-prompts-e2e-docs origin/master
git push -u origin phase/4-prompts-e2e-docs
git checkout -b feat/prompts-e2e phase/4-prompts-e2e-docs
```

- [ ] **Step 2: E2E テストを書く**

`tests/integration/test_mcp_gateway_prompts_e2e.py`:

```python
"""End-to-end tests for server-defined prompts over the HTTP/JSON-RPC dispatcher."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from mcp_gateway.app import build_app


class _FakeUpstream:
    def __init__(self, tools: list[dict[str, Any]]) -> None:
        self._tools = tools

    async def list_tools(self) -> list[dict[str, Any]]:
        return list(self._tools)


@pytest.fixture()
def policy_yaml(tmp_path: Path) -> Path:
    p = tmp_path / "intents.yaml"
    p.write_text(
        """
version: 1
output_filters:
  curator_full:
    type: none
  recall_safe:
    type: structural_allowlist
    schemas:
      memory_search:
        results: [id]
intents:
  curate_memories:
    description: "Curate own working memory. Search/save/delete; no external URL."
    allowed_tools: [memory_search, memory_save, memory_delete, memory_prune]
    output_filter: curator_full
    guardrails:
      memory_delete:
        requires_approval: true
      memory_prune:
        requires_approval: true
  read_only_recall:
    description: "Search and summarize past memories."
    allowed_tools: [memory_search]
    output_filter: recall_safe
agents:
  curator-bot:
    allowed_intents: [curate_memories, read_only_recall]
""".strip()
    )
    return p


@pytest.fixture()
def upstream() -> _FakeUpstream:
    return _FakeUpstream(
        [
            {"name": "memory_search", "description": "Search memories by text or vector."},
            {"name": "memory_save", "description": "Persist a memory item."},
            {"name": "memory_delete", "description": "Delete a memory by id."},
            {"name": "memory_prune", "description": "Prune memories by criteria."},
        ]
    )


def _client(
    monkeypatch: pytest.MonkeyPatch,
    policy_yaml: Path,
    upstream: _FakeUpstream,
    *,
    language: str | None = None,
) -> TestClient:
    monkeypatch.setenv("MCP_GATEWAY_POLICY_PATH", str(policy_yaml))
    monkeypatch.setenv(
        "MCP_GATEWAY_API_KEYS_JSON", json.dumps({"curator-bot": "k-curator"})
    )
    if language is not None:
        monkeypatch.setenv("MCP_GATEWAY_PROMPT_LANGUAGE", language)
    else:
        monkeypatch.delenv("MCP_GATEWAY_PROMPT_LANGUAGE", raising=False)
    return TestClient(build_app(upstream_override=upstream))


def _handshake(client: TestClient, intent: str) -> str:
    resp = client.get(
        "/sse",
        headers={"Authorization": "Bearer k-curator", "x-mcp-intent": intent},
        stream=True,
    )
    try:
        for raw in resp.iter_lines():
            if not raw:
                continue
            text = raw.decode() if isinstance(raw, bytes) else raw
            if "session_id=" in text:
                return text.split("session_id=")[-1].strip()
    finally:
        resp.close()
    raise AssertionError("session_id missing")


def test_e2e_prompts_list_and_get_for_curate_memories(
    monkeypatch: pytest.MonkeyPatch, policy_yaml: Path, upstream: _FakeUpstream
) -> None:
    with _client(monkeypatch, policy_yaml, upstream) as client:
        sid = _handshake(client, "curate_memories")

        listed = client.post(
            f"/messages?session_id={sid}",
            json={"jsonrpc": "2.0", "id": 1, "method": "prompts/list"},
        ).json()
        assert listed["result"]["prompts"] == [
            {
                "name": "chronos-graph.curate_memories",
                "description": "Curate own working memory. "
                "Search/save/delete; no external URL.",
                "arguments": [],
            }
        ]

        got = client.post(
            f"/messages?session_id={sid}",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "prompts/get",
                "params": {"name": "chronos-graph.curate_memories"},
            },
        ).json()
        text = got["result"]["messages"][0]["content"]["text"]
        for tool_name in ("memory_search", "memory_save", "memory_delete", "memory_prune"):
            assert tool_name in text
        assert "memory_delete: Delete a memory by id. [REQUIRES APPROVAL]" in text
        assert "memory_prune: Prune memories by criteria. [REQUIRES APPROVAL]" in text


def test_e2e_cross_intent_prompt_request_is_rejected(
    monkeypatch: pytest.MonkeyPatch, policy_yaml: Path, upstream: _FakeUpstream
) -> None:
    with _client(monkeypatch, policy_yaml, upstream) as client:
        sid = _handshake(client, "read_only_recall")
        body = client.post(
            f"/messages?session_id={sid}",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "prompts/get",
                "params": {"name": "chronos-graph.curate_memories"},
            },
        ).json()
        assert body["error"]["code"] == -32602
        assert "unknown prompt" in body["error"]["message"]


def test_e2e_ja_language_switches_section_headers(
    monkeypatch: pytest.MonkeyPatch, policy_yaml: Path, upstream: _FakeUpstream
) -> None:
    with _client(monkeypatch, policy_yaml, upstream, language="ja") as client:
        sid = _handshake(client, "curate_memories")
        got = client.post(
            f"/messages?session_id={sid}",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "prompts/get",
                "params": {"name": "chronos-graph.curate_memories"},
            },
        ).json()
        text = got["result"]["messages"][0]["content"]["text"]
        assert "## 役割" in text
        assert "## 利用可能なツール" in text
        assert "[要承認]" in text


def test_e2e_invalid_params_returns_jsonrpc_error(
    monkeypatch: pytest.MonkeyPatch, policy_yaml: Path, upstream: _FakeUpstream
) -> None:
    with _client(monkeypatch, policy_yaml, upstream) as client:
        sid = _handshake(client, "curate_memories")
        body = client.post(
            f"/messages?session_id={sid}",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "prompts/get",
                "params": "not-an-object",
            },
        ).json()
        assert body["error"]["code"] == -32602
        assert "must be an object" in body["error"]["message"]
```

- [ ] **Step 3: テスト実行**

```bash
uv run pytest tests/integration/test_mcp_gateway_prompts_e2e.py -v
```

Expected: 全パス（Phase 3 までで実装済みのため新規実装は不要）

- [ ] **Step 4: 既存全テストの非リグレッション確認**

```bash
uv run pytest tests/unit tests/integration -v
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/
```

Expected: 全パス

- [ ] **Step 5: コミット**

```bash
git add tests/integration/test_mcp_gateway_prompts_e2e.py
git commit -m "test(mcp-gateway/prompts): E2E 統合テスト（認可境界・言語切替）"
```

- [ ] **Step 6: Phase Base 向け Draft PR を作成**

```bash
git push -u origin feat/prompts-e2e
gh pr create --draft --base phase/4-prompts-e2e-docs \
  --title "test(mcp-gateway/prompts): E2E 統合テスト" \
  --body "Phase 4 Task 4.1: \`TestClient\` 経由でハンドシェイク→\`prompts/list\`→\`prompts/get\` を回し、認可境界（クロス intent 拒否）と言語切替（en/ja）を E2E で検証。"
```

---

### Task 4.2: SPEC.md の更新

**派生元:** Phase Base (`phase/4-prompts-e2e-docs`)

理由: ドキュメント変更のみで実装非依存。

**Files:**
- Modify: `SPEC.md` (§16.1 と §16.2)

- [ ] **Step 1: ブランチ作成**

```bash
git checkout phase/4-prompts-e2e-docs
git pull origin phase/4-prompts-e2e-docs
git checkout -b docs/prompts-spec phase/4-prompts-e2e-docs
```

- [ ] **Step 2: SPEC.md を編集**

a. `SPEC.md` §16.1 の「実装済み」表（既存末尾、「MCP Gateway: Permission Hook (Suspend/Resume)」行の直下）に追記:

```markdown
| MCP Gateway: Server-defined Prompts (Hook) | `prompts/list` / `prompts/get` 実装済み。intent 単位でサーバー側からプロンプトを動的注入。 |
```

b. `SPEC.md` §16.2 の「近期予定」表から以下行を**削除**:

```markdown
| MCP Gateway: Server-defined Prompts (Hook) | High | サーバー側からエージェントのコンテキストにプロンプト（役割と利用可能ツール）を動的注入する `prompts/list`, `prompts/get` の実装。エージェント側の手動プロンプト設定の手間をゼロにし、権限設定の「最大効率」を実現する。 |
```

c. §16.1 の見出しの日付「（2026-05-10 時点）」を「（2026-05-19 時点）」に更新する。

- [ ] **Step 3: Markdown lint 確認**

```bash
npx --yes markdownlint-cli2 SPEC.md
```

Expected: 既存ルール違反なし

- [ ] **Step 4: コミット**

```bash
git add SPEC.md
git commit -m "docs(spec): Server-defined Prompts を §16.1 へ移動・§16.2 から削除"
```

- [ ] **Step 5: Phase Base 向け Draft PR を作成**

```bash
git push -u origin docs/prompts-spec
gh pr create --draft --base phase/4-prompts-e2e-docs \
  --title "docs(spec): Server-defined Prompts を実装済みに移動" \
  --body "Phase 4 Task 4.2: SPEC.md §16.1 (実装済み) へ Server-defined Prompts を移動、§16.2 (近期予定) から削除。実装済み日付を 2026-05-19 に更新。"
```

---

## Phase 5: 最終マージ（Phase Base → master）

各 Phase の全 Task のレビューが完了し、Phase Base ブランチに統合されたら、以下の順序で `master` へマージする:

- [ ] Phase 1 (`phase/1-prompts-domain`) の Draft PR を Ready for Review に変更し、`master` 向けの PR を作成、マージ
- [ ] Phase 2 (`phase/2-prompts-registry`) を `master` ベースへ rebase してマージ
- [ ] Phase 3 (`phase/3-prompts-wiring`) を `master` ベースへ rebase してマージ
- [ ] Phase 4 (`phase/4-prompts-e2e-docs`) を `master` ベースへ rebase してマージ
- [ ] `master` 上で `uv run pytest tests/ -v` および CI（GitHub Actions）の全グリーンを Devcontainer 内で最終確認する
- [ ] マージ済みの作業ブランチ（`feat/prompts-*`, `docs/prompts-spec`, `phase/*-prompts-*`）をリモートから削除する

---

## 補足: Devcontainer 実行コマンド早見表

VS Code "Reopen in Container" 後、または `devcontainer exec --workspace-folder . -- bash -c "..."` から:

| 目的 | コマンド |
|------|----------|
| 単体テスト | `uv run pytest tests/unit -v` |
| 統合テスト | `uv run pytest tests/integration -v` |
| 単一ファイル | `uv run pytest tests/unit/test_mcp_gateway_prompts_builder.py -v` |
| Ruff lint | `uv run ruff check src/ tests/` |
| Ruff format check | `uv run ruff format --check src/ tests/` |
| Mypy | `uv run mypy src/` |
| 全 CI 同等チェック | `uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && uv run mypy src/ && uv run pytest tests/ -v` |

---

## 自己レビュー結果

**1. 設計書カバレッジ**: 設計書 §1〜§10 の全要素が Phase 1〜4 のいずれかの Task に対応している（モデル §3.1→Task 1.1、ビルダー §3.2→Task 1.3、レジストリ §3.3→Task 2.1、ディスパッチャ §3.4→Task 3.3、配線 §3.5→Task 3.2、設定 §3.6→Task 3.1、E2E §6.2→Task 4.1、SPEC §7→Task 4.2、認可境界 §4.5→Task 2.1 のテスト＋Task 3.3 の E2E でカバー）。設計外（§9 YAGNI）はスコープ外として明示。

**2. プレースホルダ走査**: 「TBD」「TODO」「適切な〜」「実装する」等の抽象的指示なし。全コードブロックに具体的な実装を記載。

**3. 型整合性**: `PromptRegistry` は Task 2.1 の時点で `__init__(prompts_by_intent=None)` と `replace(prompts_by_intent)` の両 API を持ち、Task 3.2 の `app.py` が `PromptRegistry()` を `build_router` 呼び出し前に生成して `app.state` と `build_router` の同一インスタンスへ渡し、lifespan 内で `replace()` で差し替えるという単一の初期化順序に統一されている（`ToolRegistry.replace_tools` パターンと対称）。`PromptMessage.role` は Literal、`Prompt.messages` は tuple のまま一貫。`prompt_language: Literal["en", "ja"]` は config / templates / builder で同一型を流用。Task 3.3 の `client` フィクスチャは `Iterator[TestClient]`、テスト関数は `client: TestClient` として Task 4.1 と整合。

---

**Plan complete and saved to `docs/superpowers/plans/2026-05-19-mcp-gateway-server-defined-prompts.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
