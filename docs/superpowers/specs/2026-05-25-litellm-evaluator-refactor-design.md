# Design: LiteLLM Migration for Universal Evaluator

**Date:** 2026-05-25
**Scope:** `src/mcp_gateway/` — LLM evaluator decoupling from Anthropic SDK

## Problem

`LlmEvaluator` directly imports the Anthropic SDK and reads `ANTHROPIC_API_KEY`, making the evaluation pipeline provider-locked. The goal is to replace this with LiteLLM so any model supported by LiteLLM can serve as the evaluator backend.

## Out of Scope

- New evaluation metrics or scoring logic
- Changes to `_build_user_prompt`, `_parse_decision`, or `SYSTEM_PROMPT`
- Changes to `Decision`, `ToolCallInput`, `MemoryItem` types

---

## Architecture

### New: `EvaluatorSettings` in `config.py`

A dedicated Pydantic `BaseSettings` class separate from `GatewaySettings` (which cannot be instantiated standalone due to mandatory `policy_path`).

```python
class EvaluatorSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CHRONOS_EVALUATOR_",
        env_file=".env",
        extra="ignore",
    )
    api_key: SecretStr | None = None                          # CHRONOS_EVALUATOR_API_KEY
    model: str = "claude-haiku-4-5-20251001"                  # CHRONOS_EVALUATOR_MODEL
    max_tokens: int = 1536                                    # CHRONOS_EVALUATOR_MAX_TOKENS
    timeout_seconds: float = Field(default=10.0, gt=0.0)      # CHRONOS_EVALUATOR_TIMEOUT_SECONDS
```

**Migration note:** `ANTHROPIC_API_KEY` → `CHRONOS_EVALUATOR_API_KEY`. `CHRONOS_EVALUATOR_THINKING_BUDGET` is removed with no replacement.

### Updated: `LlmEvaluator` in `llm_evaluator.py`

#### Module-level optional import (new)

`litellm` はオプショナル依存のため、モジュールトップレベルで `try-except ImportError` により安全にインポートする。これにより `judge()` 内で `NameError` が発生しない。

```python
try:
    import litellm
except ImportError:
    litellm = None  # type: ignore[assignment]
```

`from_env()` は `litellm is None` を検査して返却を制御する。`LlmEvaluator` のインスタンスが生成できた時点で `litellm` は必ず有効であるため、`judge()` での呼び出しは安全。

#### Removed entirely
- `import threading`
- `import importlib`（モジュールレベルの try-except に置き換え）
- `_CLIENT_INIT_LOCK` (threading lock)
- All Protocol classes (`_AnthropicClientProtocol`, `_AnthropicFactoryProtocol`, `_MessagesProtocol`, `_TextBlockProtocol`)
- `thinking_budget` parameter and `_thinking_budget` attribute
- `_client` attribute
- `_get_client()` method
- `_invoke_sdk()` method
- `thinking_budget >= max_tokens` validation in `__init__`

#### New `__init__` signature

```python
def __init__(
    self,
    *,
    api_key: str,
    model: str = "claude-haiku-4-5-20251001",
    timeout_seconds: float = 10.0,
    max_tokens: int = 1536,
) -> None:
```

#### Updated `from_env()`

Reads from `EvaluatorSettings()`. Returns `None` if `api_key` is absent or `litellm` is not installed (モジュールレベル import が失敗していれば `litellm is None`)。

```python
@classmethod
def from_env(cls) -> LlmEvaluator | None:
    if litellm is None:
        logger.warning("litellm not installed; LLM evaluator disabled")
        return None
    settings = EvaluatorSettings()
    if not settings.api_key:
        return None
    return cls(
        api_key=settings.api_key.get_secret_value(),
        model=settings.model,
        timeout_seconds=settings.timeout_seconds,
        max_tokens=settings.max_tokens,
    )
```

#### Updated `judge()`

```python
async def judge(self, *, input_, rules, memories, intent_name="default") -> Decision:
    user_prompt = _build_user_prompt(...)
    try:
        response = await litellm.acompletion(
            model=self._model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=self._max_tokens,
            timeout=self._timeout_seconds,
            api_key=self._api_key,
        )
    except Exception as exc:
        raise LlmUnavailableError(f"LLM call failed: {type(exc).__name__}") from exc

    text = response.choices[0].message.content
    if not text:
        raise ResponseParseError("LLM returned no text content")
    return _parse_decision(text)
```

#### `cache_control: ephemeral` の削除について

現行の `_invoke_sdk()` は Anthropic のプロンプトキャッシュ（`"cache_control": {"type": "ephemeral"}`）を system フィールドに付与している。LiteLLM の標準 messages 形式にはこの拡張フィールドが存在しないため、**意図的に削除する**。

- `SYSTEM_PROMPT` は 600 トークン超であるため、Anthropic モデルを引き続き使用する場合は毎リクエストで入力トークンがフルカウントされる（コスト増）。
- これはプロバイダ非依存化のトレードオフとして受け入れる。Anthropic キャッシュの再有効化が必要になった場合は、LiteLLM の `extra_body` パラメータ経由で対応可能だが、本リファクタのスコープ外とする。

### Updated: `pyproject.toml`

```toml
[project.optional-dependencies]
evaluator = [
    "litellm>=1.0.0",
]
```

`anthropic>=0.40.0` is removed. `embedding-litellm` extra is unchanged.

---

## Test Changes

| Test | Change |
|------|--------|
| `test_from_env_returns_none_without_api_key` | `ANTHROPIC_API_KEY` → `CHRONOS_EVALUATOR_API_KEY` |
| `test_from_env_returns_none_when_litellm_missing` (旧: `…when_anthropic_missing`) | patch target: module-level `litellm` を `None` に差し替え |
| `test_from_env_bumps_max_tokens_if_budget_too_high` | **Deleted** (thinking_budget removed) |
| `test_from_env_respects_max_tokens_env` | env var key unchanged (`CHRONOS_EVALUATOR_MAX_TOKENS`) |
| `test_from_env_handles_invalid_timeout_env` | env var key unchanged |
| `test_judge_*` | Mock `litellm.acompletion`; response format → OpenAI-compatible |
| `test_llm_evaluator_init_raises_on_invalid_thinking_budget` | **Deleted** |
| All `_parse_decision`, `_build_user_prompt`, `SYSTEM_PROMPT` tests | **No change** |

### Error path tests (新規追加)

`judge()` の例外ハンドリングを網羅するため、以下のテストを追加する。
モック対象はすべて `patch("mcp_gateway.policy.llm_evaluator.litellm.acompletion", ...)` で統一。

| テスト名 | モック入力（side_effect） | 期待する例外 |
|----------|--------------------------|-------------|
| `test_judge_raises_llm_unavailable_on_timeout` | `asyncio.TimeoutError()` | `LlmUnavailableError` |
| `test_judge_raises_llm_unavailable_on_api_error` | `Exception("AuthenticationError")` | `LlmUnavailableError` |
| `test_judge_raises_parse_error_on_empty_content` | `return_value` = `choices[0].message.content = ""` | `ResponseParseError` |
| `test_judge_raises_parse_error_on_none_content` | `return_value` = `choices[0].message.content = None` | `ResponseParseError` |

**レスポンスのモック構造（OpenAI互換）:**
```python
SimpleNamespace(
    choices=[SimpleNamespace(message=SimpleNamespace(content='{"decision":"allow"}'))]
)
```

`LlmUnavailableError` は `judge()` の `except Exception` ブロックで捕捉される全例外に対して送出される。`ResponseParseError` は `content` が空文字列・`None` の場合の明示ガードで送出される。

---

## Environment Variable Reference

| Variable | Before | After |
|----------|--------|-------|
| `ANTHROPIC_API_KEY` | LLM evaluator API key | Removed |
| `CHRONOS_EVALUATOR_API_KEY` | — | LLM evaluator API key (new) |
| `CHRONOS_EVALUATOR_MODEL` | Evaluator model name | Unchanged (default updated if needed) |
| `CHRONOS_EVALUATOR_MAX_TOKENS` | Max output tokens | Unchanged, maps to LiteLLM `max_tokens` |
| `CHRONOS_EVALUATOR_TIMEOUT_SECONDS` | Request timeout | Unchanged |
| `CHRONOS_EVALUATOR_THINKING_BUDGET` | Anthropic thinking budget | **Removed** |
