# Hybrid Ingestion Mode 統合検証結果

Date: 2026-05-28

## Summary

Task 5.1 の統合検証として、次の項目を確認した。

- `CHRONOS_INGESTION_MODE` の SSOT
- Gateway 設定
- `ToolRegistry.hidden_tools`
- `build_app()` の `memory_save` 隠蔽
- `scripts/agent_turn_hook.py` の fire-and-forget 呼び出し

検証は Devcontainer 内で実行した。

既存の project-local `.venv` と workspace root が Devcontainer ユーザーから
書き込み不可だったため、`uv run` は `.venv` 削除権限で失敗した。
そのため Devcontainer の管理 venv を直接使い、pytest の full run は
writable な一時作業ディレクトリから実行した。

## Verification commands and results

- Prerequisite merge check: PASS
  - Evidence: `chronos_shared`, both Settings,
    `ToolRegistry.hidden_tools`, and `agent_turn_hook.py` are present.
- Static analysis: PASS
  - Evidence: `ruff check` returned `All checks passed!`.
  - Evidence: `mypy` returned `Success: no issues found in 6 source files`.
- Added unit tests: PASS
  - Evidence: 33 tests passed.
- Focused regression: PASS
  - Evidence: 419 passed, 805 deselected.
- Full unit regression: PASS
  - Evidence: 1224 passed.
- `tools/list` E2E: PASS
  - Evidence: `CHRONOS_INGESTION_MODE=all` returned
    `memory_save_url,memory_search`; `memory_save` was absent.
- Hook `tools/call` E2E: PASS
  - Evidence: `agent_turn_hook.py` exited 0.
  - Evidence: Gateway returned HTTP 200 for `POST /messages?...`.
- Classifier / Pipeline diff: PASS
  - Evidence: the diff for `classifier.py` and `pipeline.py` was empty.
- Gateway cross-package import check: PASS
  - Evidence: no `from context_store` imports under `src/mcp_gateway/`.

## Acceptance Criteria

### AC-1: `selective` mode exposes `memory_save` in `tools/list`

- Result: PASS
- Verification:
  - `test_build_app_hidden_tools.py`
  - `test_selective_mode_does_not_hide_memory_save`

### AC-2: `all` mode hides `memory_save`

- Result: PASS
- Verification:
  - Step 6 E2E
  - `test_build_app_hidden_tools.py`
  - `test_all_mode_hides_memory_save`

### AC-3: `tools/call memory_save` remains callable in `all` mode

- Result: PASS
- Verification:
  - Step 7 hook E2E
  - `POST /messages?...` returned HTTP 200

### AC-4: Invalid ingestion mode fails fast

- Result: PASS
- Verification:
  - `test_settings_ingestion_mode.py` invalid-value tests

### AC-5: `agent_turn_hook.py` exits 0 on handled failures

- Result: PASS
- Verification:
  - Unreachable smoke check exited 0.
  - Auth-failure smoke check exited 0.
  - Timeout path exited 0 during the initial hook run.

### AC-6: Ruff and mypy pass for changed files

- Result: PASS
- Verification:
  - Step 3 static checks

### AC-7: Classifier / Pipeline code is unchanged

- Result: PASS
- Verification:
  - Empty git diff for classifier and pipeline paths

### AC-8: Hook truncates oversized logs and handles 413 fail-soft

- Result: PASS
- Verification:
  - `test_agent_turn_hook_truncate.py` truncate cases
  - Hook fail-soft behavior

### AC-9: Ingestion mode SSOT and no Gateway to context-store imports

- Result: PASS
- Verification:
  - Shared module tests
  - Cross-import scan

### AC-10: Gateway passes `CHRONOS_INGESTION_MODE` to context-store

- Result: PASS
- Verification:
  - `test_build_upstream_env_propagates_ingestion_mode`

## Environment notes

- The repository `.env` contained a non-default evaluator model.
  Regression tests were run with the evaluator model explicitly set to the
  documented default to avoid local dotenv contamination.
- The full unit suite needed the Supabase optional dependency in the
  Devcontainer venv. It was installed into the container environment for
  verification only.
- The hook E2E used a temporary policy and a local zero-vector custom
  embedding endpoint. This exercised Gateway `tools/call memory_save`
  without waiting for external model downloads.
