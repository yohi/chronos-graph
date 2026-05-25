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
```

**設計判断 — 数値設定の fail-soft 維持:**
`max_tokens` と `timeout_seconds` は **意図的に `EvaluatorSettings` に含めない**。理由は、現行実装が「不正値・非正値 → 警告ログ + デフォルトへフォールバック」という fail-soft セマンティクスを持っており、Pydantic v2 の標準バリデーション（`Field(gt=0.0)` 等）に置き換えると `ValidationError` で fail-fast に観測可能な挙動変更が生じるため。これは本リファクタの目的（"純粋な LiteLLM 移行"）を超えるスコープ拡大となる。

数値 env はモジュールレベルのヘルパー `_parse_int_env` / `_parse_float_env`（現行実装から踏襲）で `from_env()` 内から `os.getenv` 経由で読み取り、不正値・非正値はそれぞれ警告ログを残してデフォルトを採用する。設定バリデーション厳格化は別 PR で migration note + CLI 契約と一緒に扱う。

**Migration note:** `ANTHROPIC_API_KEY` → `CHRONOS_EVALUATOR_API_KEY`。`CHRONOS_EVALUATOR_THINKING_BUDGET` は置換なしで削除。`CHRONOS_EVALUATOR_MAX_TOKENS` / `CHRONOS_EVALUATOR_TIMEOUT_SECONDS` の解釈（不正値/非正値は警告 + デフォルト）は **現行と同一** を維持する。

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

`EvaluatorSettings()` から `api_key` と `model` を読む。数値設定は `_parse_int_env` / `_parse_float_env` ヘルパー（モジュールレベル）で `os.getenv` 経由から取得し、fail-soft で正規化する。`api_key` が空、または `litellm` が未インストールの場合は `None` を返す。

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
        timeout_seconds=_parse_float_env("CHRONOS_EVALUATOR_TIMEOUT_SECONDS", 10.0),
        max_tokens=_parse_int_env("CHRONOS_EVALUATOR_MAX_TOKENS", 1536),
    )
```

#### Module-level helpers: `_parse_int_env` / `_parse_float_env`

現行実装の同名ヘルパー（`from_env()` 内のネスト関数）をモジュールレベルに昇格させて流用する。シグネチャと挙動は不変:

- 値が未設定 (`None`) → デフォルト返却
- 値が数値変換不可 → `logger.warning("invalid numeric value for %s: %r; using default %s", ...)` + デフォルト返却
- 値が `<= 0` → `logger.warning("non-positive value for %s: %r; using default %s", ...)` + デフォルト返却
- 値が正値 → そのまま返却

モジュールレベルにすることで `from_env()` 経由テストとは別に単体テストを書きやすくする。

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

    # LiteLLM レスポンスは OpenAI 互換構造を想定するが、プロバイダや障害時は
    # choices=[] / message 欠落 / content=None など歪んだ形で返り得る。
    # IndexError / AttributeError / KeyError / TypeError が外に漏れると
    # CompositeEvaluator の (LlmUnavailableError, ResponseParseError) 捕捉を
    # すり抜け、graceful fallback（ask 降格）が崩れる。すべて
    # ResponseParseError に変換して契約を守る。
    try:
        choices = response.choices
        if not choices:
            raise ResponseParseError("LLM returned no choices")
        text = choices[0].message.content
    except (AttributeError, IndexError, KeyError, TypeError) as exc:
        raise ResponseParseError(f"unexpected response shape: {type(exc).__name__}") from exc

    if not text:
        raise ResponseParseError("LLM returned no text content")
    return _parse_decision(text)
```

**呼び出し側との契約:** `composite.py:CompositeEvaluator` は `judge()` から送出される例外として `LlmUnavailableError` / `ResponseParseError` の 2 種類のみを捕捉する。その他の例外型（`IndexError` 等）は graceful fallback の対象外となるため、本実装では境界で必ずどちらかに変換する。

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
| `test_from_env_returns_none_without_api_key` | env var を `CHRONOS_EVALUATOR_API_KEY=""` に上書き (`delenv` ではローカル `.env` ファイルから値を拾うため flaky) |
| `test_from_env_returns_none_when_litellm_missing` (旧: `…when_anthropic_missing`) | patch target: module-level `litellm` を `None` に差し替え |
| `test_from_env_bumps_max_tokens_if_budget_too_high` | **Deleted** (thinking_budget removed) |
| `test_from_env_respects_max_tokens_env` | env var key unchanged (`CHRONOS_EVALUATOR_MAX_TOKENS`) |
| `test_from_env_handles_invalid_timeout_env` | **fail-soft 維持**。`"invalid"` / `"0.0"` のいずれも `_timeout_seconds == 10.0` を期待（`ValidationError` は **送出しない**） |
| `test_from_env_handles_invalid_max_tokens_env` (新規) | `CHRONOS_EVALUATOR_MAX_TOKENS="invalid"` / `"0"` の両方で `_max_tokens == 1536` を期待 |
| `test_judge_*` | Mock `litellm.acompletion`; response format → OpenAI-compatible |
| `test_llm_evaluator_init_raises_on_invalid_thinking_budget` | **Deleted** |
| All `_parse_decision`, `_build_user_prompt`, `SYSTEM_PROMPT` tests | **No change** |

### Error path tests (新規追加)

`judge()` の例外ハンドリングを網羅するため、以下のテストを追加する。
モック対象はすべて `patch("mcp_gateway.policy.llm_evaluator.litellm.acompletion", ...)` で統一。

| テスト名 | モック入力（side_effect / return_value） | 期待する例外 |
|----------|------------------------------------------|-------------|
| `test_judge_raises_llm_unavailable_on_timeout` | `side_effect=asyncio.TimeoutError()` | `LlmUnavailableError` |
| `test_judge_raises_llm_unavailable_on_api_error` | `side_effect=Exception("AuthenticationError")` | `LlmUnavailableError` |
| `test_judge_raises_parse_error_on_empty_content` | `return_value` = `choices[0].message.content = ""` | `ResponseParseError` |
| `test_judge_raises_parse_error_on_none_content` | `return_value` = `choices[0].message.content = None` | `ResponseParseError` |
| `test_judge_raises_parse_error_on_empty_choices` (新規) | `return_value` = `SimpleNamespace(choices=[])` | `ResponseParseError` |
| `test_judge_raises_parse_error_on_missing_message` (新規) | `return_value` = `choices[0]` から `message` 属性欠落 (`SimpleNamespace()`) | `ResponseParseError` |

**レスポンスのモック構造（OpenAI互換）:**
```python
SimpleNamespace(
    choices=[SimpleNamespace(message=SimpleNamespace(content='{"decision":"allow"}'))]
)
```

`LlmUnavailableError` は `judge()` の `await litellm.acompletion(...)` を包む `except Exception` ブロックで捕捉される全例外に対して送出される。`ResponseParseError` は (a) `content` が空文字列・`None` の明示ガード、(b) `choices=[]` の明示ガード、(c) レスポンス構造アクセス時の `AttributeError` / `IndexError` / `KeyError` / `TypeError` の変換、いずれかで送出される。これにより `CompositeEvaluator` の `(LlmUnavailableError, ResponseParseError)` 捕捉契約から漏れる例外を作らない。

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
