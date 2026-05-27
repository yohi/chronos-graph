# Hybrid Ingestion Mode & Turn-based Full Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Every shell command in this plan MUST be executed inside the project's Devcontainer (`.devcontainer/devcontainer.json`).** Do not run `uv`, `pytest`, `ruff`, `mypy`, or the validation shell scripts on the host system.

**Goal:** `CHRONOS_INGESTION_MODE` ハイブリッド保存モード (`all` / `selective`) を追加し、`all` モードでは `memory_save` を MCP Gateway の `tools/list` から除外する一方、`scripts/agent_turn_hook.py` 経由でターン終了時に fire-and-forget 保存を行う基盤を実装する。

**Architecture:** 共通パッケージ `src/chronos_shared/ingestion_mode.py` を SSOT として新設し、`Settings` (context_store) と `GatewaySettings` (mcp_gateway) の両方が同モジュールから型・デフォルト・env 名を import する。Gateway は `ToolRegistry(hidden_tools=...)` で `memory_save` を tools/list から物理的に隠蔽し、`upstream_env_passthrough` のデフォルト allowlist に `"CHRONOS_INGESTION_MODE"` を追加することで context_store サブプロセスへ env を伝達する。フックは独立スクリプトとして fire-and-forget で動作する。

**Tech Stack:** Python 3.12+ (managed via `uv`), Pydantic 2 / pydantic-settings, FastAPI/FastMCP, httpx, asyncio, pytest, ruff, mypy (strict).

**Design Document:** `docs/superpowers/specs/2026-05-27-hybrid-ingestion-mode-design.md`

---

## Gitブランチ運用フロー

本計画は以下の **AI-Native Stacked PR Workflow** に厳密に従う:

- **参照URL:** <https://different-sunday-448.notion.site/AI-Native-Stacked-PR-Workflow-3611669a4c16802eb032eb4ab05a8adb>

### 共通規約

- **派生元検証 (ポカヨケ):** すべての Task の Step 1 で `git merge-base --is-ancestor` による派生元検証スクリプトを **Devcontainer 内で必ず実行** する。失敗した場合はその Task を中止して原因調査する。
- **Devcontainer 強制:** `uv sync`, `uv run pytest`, `uv run ruff check`, `uv run ruff format --check`, `uv run mypy` を含む **すべての検証コマンドは Devcontainer 内で実行する**。host 側の Python では実行しない。
- **Draft PR の必須化:** すべての Task の最終ステップで「派生元ブランチ向けの Draft PR」を作成し、URL を本計画書のチェックリスト下にメモする。後続 Task の前提条件は「先行 Task の Draft PR URL が存在すること」で判定する。
- **マージ順序:** Draft PR がレビュー通過 → Ready for review → 派生元へマージ → 派生 Task が rebase or merge で取り込む。`master` へのマージは人手が行う (エージェントは行わない)。
- **直接 master push 禁止:** どの Task も `master` への直接コミット/push を行わない。

### ブランチ依存図

```text
master
├── feat/devcontainer-ci-baseline-check   (Task 0.1, 並列, 独立)
├── feat/chronos-shared-ingestion-mode    (Task 1.1, 並列, 独立)
│       └── feat/settings-ingestion-mode  (Task 2.1, 直列: Task 1.1 必須)
├── feat/tool-registry-hidden-tools       (Task 3.1, 並列, 独立)
├── feat/agent-turn-hook-script           (Task 4.1, 並列, 独立)
│
│ (Task 2.1 と Task 3.1 が master へマージされてから)
└── feat/build-app-hide-memory-save       (Task 3.2, 直列: Task 2.1 + Task 3.1 のマージ必須)
        │
        │ (Task 0.1 / 1.1 / 2.1 / 3.1 / 3.2 / 4.1 が全て master へマージされてから)
        └── feat/hybrid-ingestion-integration-verify  (Task 5.1, 直列: 全 Task マージ必須)
```

### Draft PR URL 記録欄 (実装時に追記)

| Task | Draft PR URL |
|---|---|
| Task 0.1 | _未作成_ |
| Task 1.1 | _未作成_ |
| Task 2.1 | _未作成_ |
| Task 3.1 | _未作成_ |
| Task 3.2 | _未作成_ |
| Task 4.1 | _未作成_ |
| Task 5.1 | _未作成_ |

---

## File Structure

| 種別 | パス | 責務 |
|---|---|---|
| 新規 | `src/chronos_shared/__init__.py` | パッケージ初期化 (空) |
| 新規 | `src/chronos_shared/ingestion_mode.py` | `CHRONOS_INGESTION_MODE` の SSOT (型・デフォルト・env 名) |
| 修正 | `pyproject.toml` | `[tool.hatch.build.targets.wheel].packages` に `"src/chronos_shared"` を追加 |
| 修正 | `src/context_store/config.py` | `Settings` に `ingestion_mode` フィールド追加 |
| 修正 | `src/mcp_gateway/config.py` | `GatewaySettings` に `ingestion_mode` 追加、`upstream_env_passthrough` のデフォルトに `"CHRONOS_INGESTION_MODE"` を追加 |
| 修正 | `src/mcp_gateway/tools/registry.py` | `ToolRegistry.__init__` に `hidden_tools` 引数追加、`all_tools` / `filter_by_caps` で除外 |
| 修正 | `src/mcp_gateway/app.py` | `build_app()` で `settings.ingestion_mode == "all"` のとき `hidden_tools={"memory_save"}` を渡す |
| 新規 | `scripts/agent_turn_hook.py` | ターン終了フック (stdin/CLI から会話ログ → 切り詰め → Gateway HTTP fire-and-forget) |
| 新規 | `tests/unit/test_chronos_shared_ingestion_mode.py` | SSOT モジュールのシンボル存在・値検証 |
| 新規 | `tests/unit/test_settings_ingestion_mode.py` | 両 Settings の env 解決 / `upstream_env_passthrough` 検証 / `build_upstream_env` 経由の env 伝達検証 |
| 新規 | `tests/unit/test_tool_registry_hidden.py` | `hidden_tools` 引数の挙動検証 |
| 新規 | `tests/unit/test_agent_turn_hook_truncate.py` | `truncate_log` 純関数の挙動検証 |

---

## Phase 0: 基盤検証

### Task 0.1: Devcontainer + CI ベースライン検証

**派生元ブランチ:** `master`
**実行モード:** 並列可能
**前提条件:** なし
**Files:**
- Verify (no change expected): `.devcontainer/devcontainer.json`, `.devcontainer/Dockerfile`, `.devcontainer/docker-compose.yml`, `.devcontainer/setup.sh`
- Verify (no change expected): `.github/workflows/ci.yml`
- Modify (差分が必要な場合のみ): 上記いずれか

**目的:** 既存の Devcontainer / CI 設定が本実装の検証要件 (master トリガー / `ubuntu-slim` ランナー / Devcontainer 完備) を満たしていることを確認し、不足がある場合のみ最小差分で補強する。事前確認の結果、既存設定で要件を満たしていれば本 Task は **「検証通過のレポート PR」** として空コミット (`--allow-empty`) で Draft PR を作成し、後続 Task が安全に進められる基盤として機能させる。

- [ ] **Step 1: ブランチ作成と派生元検証 (Devcontainer 内で実行)**

```bash
# Devcontainer 内で実行
git fetch origin master
git checkout -b feat/devcontainer-ci-baseline-check origin/master

EXPECTED_BASE="origin/master"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git merge-base --is-ancestor "$EXPECTED_BASE" "$CURRENT_BRANCH" || { echo "ERROR: 派生元ブランチが $EXPECTED_BASE ではありません。スタック構造が壊れています。"; exit 1; }
```

期待出力: コマンド成功 (戻り値 0)、エラー無し。

- [ ] **Step 2: Devcontainer ファイルの存在と内容を検証**

```bash
test -f .devcontainer/devcontainer.json && echo "OK: devcontainer.json exists"
test -f .devcontainer/Dockerfile && echo "OK: Dockerfile exists"
test -f .devcontainer/docker-compose.yml && echo "OK: docker-compose.yml exists"
grep -q '"workspaceFolder"' .devcontainer/devcontainer.json && echo "OK: workspaceFolder set"
```

期待出力: 4 行とも "OK: ..." を表示。何か欠落していれば Step 6 で `.devcontainer/` を補強する。

- [ ] **Step 3: CI ワークフローの master トリガーと ubuntu-slim ランナーを検証**

```bash
test -f .github/workflows/ci.yml && echo "OK: ci.yml exists"
grep -E '^\s*branches:\s*\["master"\]' .github/workflows/ci.yml && echo "OK: master trigger"
grep -E '^\s*runs-on:\s*ubuntu-slim' .github/workflows/ci.yml && echo "OK: ubuntu-slim runner"
```

期待出力: 3 行とも "OK: ..." を表示。

- [ ] **Step 4: Devcontainer 内で uv 依存関係を同期しベースラインテストが緑であることを確認**

```bash
uv sync --all-extras
uv run pytest tests/unit -v -x --ignore=tests/unit/test_settings_ingestion_mode.py --ignore=tests/unit/test_tool_registry_hidden.py --ignore=tests/unit/test_agent_turn_hook_truncate.py --ignore=tests/unit/test_chronos_shared_ingestion_mode.py
```

期待出力: すべての既存 unit test がパス (失敗 0)。本実装で追加予定のテストファイルは現時点では存在しないため `--ignore` で除外されても影響なし (存在しなければ pytest は無視する)。

- [ ] **Step 5: ベースライン記録の commit (検証通過レポート)**

Step 2/3/4 がすべて "OK" / 緑であれば、本 Task はファイル変更不要のため空コミットで PR の足場を作る:

```bash
git commit --allow-empty -m "$(cat <<'EOF'
chore(ci): hybrid ingestion mode 実装前のベースライン検証通過

既存の .devcontainer/ および .github/workflows/ci.yml が以下の要件を満たすことを確認:
- master ブランチ push トリガー設定済み
- runs-on: ubuntu-slim
- devcontainer.json / Dockerfile / docker-compose.yml 一式が完備
- 既存 unit test がすべて緑

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 6: (条件付き) 不足があれば補強コミット**

Step 2 または Step 3 で "OK" が出ない項目があった場合のみ、最小差分で補強する。例:

- `runs-on: ubuntu-slim` でない → `.github/workflows/ci.yml` の `runs-on` 行を `ubuntu-slim` に変更
- `branches: ["master"]` 設定が欠落 → 同ファイルの `push` トリガーに `branches: ["master"]` を追加
- `.devcontainer/Dockerfile` 等が欠落 → 既存リポジトリの `docker/` 配下のイメージから最小構成で復元

補強後、`uv run pytest tests/unit -v` をもう一度走らせて緑を確認し、補強コミットを作成する:

```bash
git add .github/workflows/ci.yml .devcontainer/
git commit -m "$(cat <<'EOF'
fix(ci): baseline 検証で検出した CI/Devcontainer 設定の差分を補正

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 7: Draft PR 作成と URL 記録**

```bash
git push -u origin feat/devcontainer-ci-baseline-check
gh pr create --draft --base master --title "chore(ci): hybrid ingestion mode 実装前のベースライン検証" --body "$(cat <<'EOF'
## Summary
- ハイブリッド保存モード実装の前提として、`.devcontainer/` と `.github/workflows/ci.yml` が要件 (master トリガー / `ubuntu-slim` ランナー / Devcontainer 完備) を満たすことを検証。
- 不足があった場合のみ最小差分で補強済み。

## Test plan
- [ ] CI 上で既存 unit test が緑であること
- [ ] `runs-on: ubuntu-slim` が CI ログに表示されていること

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

作成された Draft PR の URL を本計画書 **「Draft PR URL 記録欄」の Task 0.1 行** に追記する。

---

## Phase 1: SSOT モジュール

### Task 1.1: `chronos_shared` 共通パッケージの新設

**派生元ブランチ:** `master`
**実行モード:** 並列可能 (Task 0.1, 3.1, 4.1 と並列実行可)
**前提条件:** なし
**Files:**
- Create: `src/chronos_shared/__init__.py`
- Create: `src/chronos_shared/ingestion_mode.py`
- Create: `tests/unit/test_chronos_shared_ingestion_mode.py`
- Modify: `pyproject.toml` (行 167-168 周辺、`[tool.hatch.build.targets.wheel].packages`)

- [ ] **Step 1: ブランチ作成と派生元検証 (Devcontainer 内で実行)**

```bash
git fetch origin master
git checkout -b feat/chronos-shared-ingestion-mode origin/master

EXPECTED_BASE="origin/master"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git merge-base --is-ancestor "$EXPECTED_BASE" "$CURRENT_BRANCH" || { echo "ERROR: 派生元ブランチが $EXPECTED_BASE ではありません。スタック構造が壊れています。"; exit 1; }
```

- [ ] **Step 2: 失敗するテストを先に書く** (`tests/unit/test_chronos_shared_ingestion_mode.py` 新規)

```python
"""chronos_shared.ingestion_mode の SSOT 契約検証。"""

from __future__ import annotations

from typing import get_args


def test_default_ingestion_mode_is_selective() -> None:
    from chronos_shared.ingestion_mode import DEFAULT_INGESTION_MODE

    assert DEFAULT_INGESTION_MODE == "selective"


def test_env_var_name_is_chronos_ingestion_mode() -> None:
    from chronos_shared.ingestion_mode import CHRONOS_INGESTION_MODE_ENV

    assert CHRONOS_INGESTION_MODE_ENV == "CHRONOS_INGESTION_MODE"


def test_ingestion_mode_literal_has_exactly_two_values() -> None:
    """`IngestionMode` は Literal["all", "selective"] であること。"""
    from chronos_shared.ingestion_mode import IngestionMode

    assert set(get_args(IngestionMode)) == {"all", "selective"}


def test_module_exposes_only_three_public_symbols() -> None:
    """SSOT モジュールは 3 シンボルのみ公開する (それ以外は意図しない拡張)。"""
    import chronos_shared.ingestion_mode as mod

    public = {name for name in dir(mod) if not name.startswith("_")}
    # typing からの import (Final, Literal) はトップレベルで参照されないよう注意
    expected = {"CHRONOS_INGESTION_MODE_ENV", "DEFAULT_INGESTION_MODE", "IngestionMode"}
    assert expected.issubset(public)
    # ホワイトリスト + typing ヘルパ以外は無いことを確認
    allowed = expected | {"annotations", "Final", "Literal"}
    extras = public - allowed
    assert extras == set(), f"unexpected public symbols: {extras}"
```

- [ ] **Step 3: 失敗を確認 (モジュール未作成のため import エラーになるはず)**

```bash
uv run pytest tests/unit/test_chronos_shared_ingestion_mode.py -v
```

期待出力: `ModuleNotFoundError: No module named 'chronos_shared'` で 4 件すべて FAIL。

- [ ] **Step 4: パッケージ初期化ファイルを作成** (`src/chronos_shared/__init__.py` 新規、空ファイル)

```python
```

(完全に空のファイルにする。`Write` で空文字列の content を渡す。)

- [ ] **Step 5: SSOT モジュールを作成** (`src/chronos_shared/ingestion_mode.py` 新規)

```python
"""SSOT for the ``CHRONOS_INGESTION_MODE`` environment variable.

This module is the single source of truth for the type, default value, and
environment variable name of the hybrid ingestion mode setting. Both
``context_store.config.Settings`` and ``mcp_gateway.config.GatewaySettings``
import from here to guarantee consistency across the two independent
processes.

Placement rationale: ``mcp_gateway/upstream/context_store_client.py`` enforces
"the gateway must NOT import anything from ``context_store``". Placing this
SSOT under either subsystem would force a cross-package import. Hence the
module lives in its own top-level package ``chronos_shared``.
"""

from __future__ import annotations

from typing import Final, Literal

IngestionMode = Literal["all", "selective"]
DEFAULT_INGESTION_MODE: Final[IngestionMode] = "selective"
CHRONOS_INGESTION_MODE_ENV: Final[str] = "CHRONOS_INGESTION_MODE"
```

- [ ] **Step 6: `pyproject.toml` の wheel packages に `src/chronos_shared` を追加**

`Edit` で以下を変更:

`old_string`:
```toml
[tool.hatch.build.targets.wheel]
packages = ["src/context_store", "src/mcp_gateway"]
```

`new_string`:
```toml
[tool.hatch.build.targets.wheel]
packages = ["src/context_store", "src/mcp_gateway", "src/chronos_shared"]
```

- [ ] **Step 7: 依存関係再同期 (新パッケージを editable install に反映)**

```bash
uv sync --all-extras
```

期待出力: `chronos_shared` を含む editable install が成功。

- [ ] **Step 8: テストが緑になることを確認**

```bash
uv run pytest tests/unit/test_chronos_shared_ingestion_mode.py -v
```

期待出力: 4 件すべて PASS。

- [ ] **Step 9: 静的解析 (ruff + mypy strict) をパスすることを確認**

```bash
uv run ruff check src/chronos_shared/ tests/unit/test_chronos_shared_ingestion_mode.py
uv run ruff format --check src/chronos_shared/ tests/unit/test_chronos_shared_ingestion_mode.py
uv run mypy src/chronos_shared/
```

期待出力: いずれもエラー 0。`mypy` は strict 構成で `Literal` / `Final` の使用を含めて pass。

- [ ] **Step 10: 既存 unit test が壊れていないことを再確認**

```bash
uv run pytest tests/unit -v
```

期待出力: 既存テストはすべて緑、追加 4 件も緑。失敗 0。

- [ ] **Step 11: コミット作成**

```bash
git add src/chronos_shared/ tests/unit/test_chronos_shared_ingestion_mode.py pyproject.toml
git commit -m "$(cat <<'EOF'
feat(shared): chronos_shared.ingestion_mode を SSOT として新設

context_store と mcp_gateway の両 Settings から import される
CHRONOS_INGESTION_MODE の型・デフォルト・env 名を一箇所に集約。
mcp_gateway → context_store のクロスパッケージ import 禁止原則を維持するため、
両者の外側に独立した top-level パッケージとして配置。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 12: Draft PR 作成と URL 記録**

```bash
git push -u origin feat/chronos-shared-ingestion-mode
gh pr create --draft --base master --title "feat(shared): chronos_shared.ingestion_mode を SSOT として新設" --body "$(cat <<'EOF'
## Summary
- `CHRONOS_INGESTION_MODE` の型・デフォルト・env 名を `src/chronos_shared/ingestion_mode.py` に集約 (Single Source of Truth)。
- `pyproject.toml` の wheel packages に `src/chronos_shared` を追加。
- 後続 Task 2.1 (両 Settings の拡張) の直接の前提となる。

## Test plan
- [ ] `uv run pytest tests/unit/test_chronos_shared_ingestion_mode.py -v` が緑
- [ ] `uv run mypy src/chronos_shared/` が pass
- [ ] `uv run pytest tests/unit -v` で既存 test に regression 無し

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

PR URL を **「Draft PR URL 記録欄」の Task 1.1 行** に追記する。

---

## Phase 2: Settings 拡張

### Task 2.1: `Settings` と `GatewaySettings` への `ingestion_mode` 追加 (+ env passthrough)

**派生元ブランチ:** `feat/chronos-shared-ingestion-mode` (Task 1.1 のブランチ)
**実行モード:** 直列必須 (Wait for Task 1.1)
**前提条件:** Task 1.1 の Draft PR URL が存在し、Task 1.1 のブランチが push 済みでローカルに `git fetch` できること
**Files:**
- Modify: `src/context_store/config.py` (Ingestion セクション、設計書 §11 では行 139-148)
- Modify: `src/mcp_gateway/config.py` (`GatewaySettings`、行 32-86 / `upstream_env_passthrough` は行 67-72)
- Create: `tests/unit/test_settings_ingestion_mode.py`

- [ ] **Step 1: ブランチ作成と派生元検証 (Devcontainer 内で実行)**

```bash
git fetch origin
git checkout -b feat/settings-ingestion-mode origin/feat/chronos-shared-ingestion-mode

EXPECTED_BASE="origin/feat/chronos-shared-ingestion-mode"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git merge-base --is-ancestor "$EXPECTED_BASE" "$CURRENT_BRANCH" || { echo "ERROR: 派生元ブランチが $EXPECTED_BASE ではありません。スタック構造が壊れています。"; exit 1; }
```

- [ ] **Step 2: 既存の `src/context_store/config.py` の Ingestion セクション位置を確認**

`Read` で `src/context_store/config.py` を読み、「`# --- Ingestion ---`」コメント (設計書 §4.1 参照、行 139-148 付近) の正確な位置を確認する。設計書記載の行番号は時間と共にずれる可能性があるため、必ず最新コードで確認する。

- [ ] **Step 3: 既存の `src/mcp_gateway/config.py` の `GatewaySettings` 位置と `upstream_env_passthrough` の定義を確認**

`Read` で `src/mcp_gateway/config.py` を読み、`upstream_env_passthrough: list[str] = [...]` の現在の値が以下であることを確認する:

```python
upstream_env_passthrough: list[str] = [
    "OPENAI_API_KEY",
    "CONTEXT_STORE_DB_PATH",
    "GRAPH_ENABLED",
    "EMBEDDING_PROVIDER",
]
```

差異があれば計画と整合させてから Step 4 に進む。

- [ ] **Step 4: 失敗するテストを先に書く** (`tests/unit/test_settings_ingestion_mode.py` 新規)

```python
"""Settings / GatewaySettings の ingestion_mode フィールドと env 伝達の検証。"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from chronos_shared.ingestion_mode import (
    CHRONOS_INGESTION_MODE_ENV,
    DEFAULT_INGESTION_MODE,
    IngestionMode,
)
from mcp_gateway.config import GatewaySettings
from mcp_gateway.upstream.context_store_client import build_upstream_env


@pytest.fixture
def policy_file(tmp_path: Path) -> Path:
    """GatewaySettings.policy_path は実在ファイル必須。最小ダミーポリシーを用意。"""
    p = tmp_path / "policy.yaml"
    p.write_text("version: 1\nallow: []\n", encoding="utf-8")
    return p


def test_context_store_settings_defaults_to_selective(monkeypatch: pytest.MonkeyPatch) -> None:
    """env 未設定時は 'selective'。共通 SSOT のデフォルトと一致。"""
    monkeypatch.delenv(CHRONOS_INGESTION_MODE_ENV, raising=False)
    from context_store.config import Settings

    s = Settings()
    assert s.ingestion_mode == "selective"
    assert s.ingestion_mode == DEFAULT_INGESTION_MODE


def test_context_store_settings_reads_all_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CHRONOS_INGESTION_MODE_ENV, "all")
    from context_store.config import Settings

    s = Settings()
    assert s.ingestion_mode == "all"


def test_context_store_settings_rejects_invalid_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CHRONOS_INGESTION_MODE_ENV, "invalid_value")
    from context_store.config import Settings

    with pytest.raises(ValidationError):
        Settings()


def test_gateway_settings_defaults_to_selective(
    monkeypatch: pytest.MonkeyPatch, policy_file: Path
) -> None:
    monkeypatch.delenv(CHRONOS_INGESTION_MODE_ENV, raising=False)
    s = GatewaySettings(policy_path=policy_file)
    assert s.ingestion_mode == "selective"


def test_gateway_settings_reads_all_from_env(
    monkeypatch: pytest.MonkeyPatch, policy_file: Path
) -> None:
    monkeypatch.setenv(CHRONOS_INGESTION_MODE_ENV, "all")
    s = GatewaySettings(policy_path=policy_file)
    assert s.ingestion_mode == "all"


def test_gateway_settings_rejects_invalid_value(
    monkeypatch: pytest.MonkeyPatch, policy_file: Path
) -> None:
    monkeypatch.setenv(CHRONOS_INGESTION_MODE_ENV, "invalid_value")
    with pytest.raises(ValidationError):
        GatewaySettings(policy_path=policy_file)


def test_gateway_upstream_passthrough_includes_ingestion_mode(policy_file: Path) -> None:
    """AC-10: upstream_env_passthrough のデフォルトに CHRONOS_INGESTION_MODE が含まれる。"""
    s = GatewaySettings(policy_path=policy_file)
    assert CHRONOS_INGESTION_MODE_ENV in s.upstream_env_passthrough


def test_build_upstream_env_propagates_ingestion_mode(policy_file: Path) -> None:
    """AC-10: build_upstream_env が CHRONOS_INGESTION_MODE をサブプロセスへ伝達する。"""
    s = GatewaySettings(policy_path=policy_file)
    base = {
        "PATH": "/usr/bin",
        "OPENAI_API_KEY": "dummy",
        CHRONOS_INGESTION_MODE_ENV: "all",
        "UNRELATED": "should-be-filtered",
    }
    env = build_upstream_env(passthrough=s.upstream_env_passthrough, base_env=base)
    assert env[CHRONOS_INGESTION_MODE_ENV] == "all"
    assert "UNRELATED" not in env


def test_both_settings_use_same_ssot_type(
    monkeypatch: pytest.MonkeyPatch, policy_file: Path
) -> None:
    """AC-9: 両 Settings が共通 SSOT の IngestionMode 型を参照する。"""
    monkeypatch.setenv(CHRONOS_INGESTION_MODE_ENV, "all")
    from context_store.config import Settings

    s_ctx = Settings()
    s_gw = GatewaySettings(policy_path=policy_file)
    # 型エイリアスとしての一致を mypy 観点で担保しつつ、ランタイム値も同型であることを確認
    value_ctx: IngestionMode = s_ctx.ingestion_mode
    value_gw: IngestionMode = s_gw.ingestion_mode
    assert value_ctx == value_gw == "all"
```

- [ ] **Step 5: 失敗を確認 (`ingestion_mode` フィールド未追加のため AttributeError 等で FAIL)**

```bash
uv run pytest tests/unit/test_settings_ingestion_mode.py -v
```

期待出力: 全 9 件 FAIL (主に `AttributeError: 'Settings' object has no attribute 'ingestion_mode'` または `ValidationError` のメッセージで)。

- [ ] **Step 6: `src/context_store/config.py` の Ingestion セクションに `ingestion_mode` フィールドを追加**

`Read` で見つけた既存の `# --- Ingestion ---` セクション内に以下を `Edit` で追加する (具体的な前後コンテキストは Step 2 で確認した内容を使う):

```python
from chronos_shared.ingestion_mode import (
    CHRONOS_INGESTION_MODE_ENV,
    DEFAULT_INGESTION_MODE,
    IngestionMode,
)

# ...

class Settings(BaseSettings):
    # ...
    # --- Ingestion ---
    ingestion_mode: IngestionMode = Field(
        default=DEFAULT_INGESTION_MODE,
        validation_alias=CHRONOS_INGESTION_MODE_ENV,
        description=(
            "記憶保存の挙動。'all' は全量保存 (ツール隠蔽併用)、"
            "'selective' は従来判定。"
        ),
    )
```

注意: `pydantic.Field` の import が既に存在することを確認。無ければ追加。

- [ ] **Step 7: `src/mcp_gateway/config.py` の `GatewaySettings` に `ingestion_mode` を追加 + `upstream_env_passthrough` を拡張**

`Edit` で 2 箇所変更する。

(a) ファイル先頭の import に共通モジュールを追加:

`old_string`:
```python
from pydantic import Field, SecretStr, SerializationInfo, field_validator, model_serializer
from pydantic_settings import BaseSettings, SettingsConfigDict
```

`new_string`:
```python
from pydantic import Field, SecretStr, SerializationInfo, field_validator, model_serializer
from pydantic_settings import BaseSettings, SettingsConfigDict

from chronos_shared.ingestion_mode import (
    CHRONOS_INGESTION_MODE_ENV,
    DEFAULT_INGESTION_MODE,
    IngestionMode,
)
```

(b) `upstream_env_passthrough` のデフォルトリストに `"CHRONOS_INGESTION_MODE"` を追加し、その直下に `ingestion_mode` フィールドを定義:

`old_string`:
```python
    upstream_command: list[str] = ["python", "-m", "context_store"]
    upstream_env_passthrough: list[str] = [
        "OPENAI_API_KEY",
        "CONTEXT_STORE_DB_PATH",
        "GRAPH_ENABLED",
        "EMBEDDING_PROVIDER",
    ]
```

`new_string`:
```python
    upstream_command: list[str] = ["python", "-m", "context_store"]
    upstream_env_passthrough: list[str] = [
        "OPENAI_API_KEY",
        "CONTEXT_STORE_DB_PATH",
        "GRAPH_ENABLED",
        "EMBEDDING_PROVIDER",
        "CHRONOS_INGESTION_MODE",
    ]

    # ── ingestion ───────────────────────────────────────────────
    # 共通 SSOT (chronos_shared.ingestion_mode) を参照。MCP_GATEWAY_ プレフィックス
    # を validation_alias でバイパスし、Settings (context_store) と同じ env を読む。
    ingestion_mode: IngestionMode = Field(
        default=DEFAULT_INGESTION_MODE,
        validation_alias=CHRONOS_INGESTION_MODE_ENV,
        description=(
            "記憶保存の挙動。'all' は全量保存 (ツール隠蔽併用)、"
            "'selective' は従来判定。"
        ),
    )
```

- [ ] **Step 8: テストが緑になることを確認**

```bash
uv run pytest tests/unit/test_settings_ingestion_mode.py -v
```

期待出力: 全 9 件 PASS。

- [ ] **Step 9: 静的解析パス確認**

```bash
uv run ruff check src/context_store/config.py src/mcp_gateway/config.py tests/unit/test_settings_ingestion_mode.py
uv run ruff format --check src/context_store/config.py src/mcp_gateway/config.py tests/unit/test_settings_ingestion_mode.py
uv run mypy src/context_store/config.py src/mcp_gateway/config.py
```

期待出力: いずれもエラー 0。

- [ ] **Step 10: アーキテクチャ原則の物理的確認 (AC-9 補足: mcp_gateway → context_store の import が増えていないこと)**

```bash
grep -rn "from context_store" src/mcp_gateway/ || echo "OK: no cross-package import"
```

期待出力: `OK: no cross-package import` が表示される (1 件もマッチしない)。マッチがあれば設計違反のため修正必須。

- [ ] **Step 11: 既存 unit test の regression 確認**

```bash
uv run pytest tests/unit -v
```

期待出力: 既存テストすべて緑、追加 9 件も緑。

- [ ] **Step 12: コミット**

```bash
git add src/context_store/config.py src/mcp_gateway/config.py tests/unit/test_settings_ingestion_mode.py
git commit -m "$(cat <<'EOF'
feat(config): Settings / GatewaySettings に ingestion_mode と env 伝達を追加

- 両 Settings は chronos_shared.ingestion_mode から型・デフォルト・env 名を import (SSOT)。
- MCP_GATEWAY_ プレフィックスを validation_alias でバイパスし、両プロセスで同一 env を読む。
- GatewaySettings.upstream_env_passthrough のデフォルトに CHRONOS_INGESTION_MODE を追加し、
  build_upstream_env 経由で context_store サブプロセスへ伝達する。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 13: Draft PR 作成 (派生元: `feat/chronos-shared-ingestion-mode`) と URL 記録**

```bash
git push -u origin feat/settings-ingestion-mode
gh pr create --draft --base feat/chronos-shared-ingestion-mode --title "feat(config): Settings / GatewaySettings に ingestion_mode と env 伝達を追加" --body "$(cat <<'EOF'
## Summary
- `context_store.Settings` と `mcp_gateway.GatewaySettings` の両方に `ingestion_mode` フィールドを追加 (共通 SSOT を import)。
- `GatewaySettings.upstream_env_passthrough` のデフォルトに `"CHRONOS_INGESTION_MODE"` を追加し、context_store サブプロセスへ env を伝達。
- AC-9 (SSOT への集約) / AC-10 (env 伝達) を満たす。
- スタック: 派生元は `feat/chronos-shared-ingestion-mode` (Task 1.1)。マージは Task 1.1 → master → 本 PR の順。

## Test plan
- [ ] `uv run pytest tests/unit/test_settings_ingestion_mode.py -v` が緑
- [ ] `grep -rn "from context_store" src/mcp_gateway/` で 0 件 (アーキ原則維持)
- [ ] `uv run mypy src/context_store/config.py src/mcp_gateway/config.py` が pass

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

PR URL を **「Draft PR URL 記録欄」の Task 2.1 行** に追記する。

---

## Phase 3: ツール隠蔽

### Task 3.1: `ToolRegistry.hidden_tools` の追加

**派生元ブランチ:** `master`
**実行モード:** 並列可能 (Task 0.1 / 1.1 / 4.1 と並列。Task 2.1 とも並列可だが、Task 3.2 の前提として両方が必要)
**前提条件:** なし
**Files:**
- Modify: `src/mcp_gateway/tools/registry.py`
- Create: `tests/unit/test_tool_registry_hidden.py`

- [ ] **Step 1: ブランチ作成と派生元検証 (Devcontainer 内で実行)**

```bash
git fetch origin master
git checkout -b feat/tool-registry-hidden-tools origin/master

EXPECTED_BASE="origin/master"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git merge-base --is-ancestor "$EXPECTED_BASE" "$CURRENT_BRANCH" || { echo "ERROR: 派生元ブランチが $EXPECTED_BASE ではありません。スタック構造が壊れています。"; exit 1; }
```

- [ ] **Step 2: 失敗するテストを先に書く** (`tests/unit/test_tool_registry_hidden.py` 新規)

```python
"""ToolRegistry.hidden_tools のフィルタ挙動検証。"""

from __future__ import annotations

from mcp_gateway.tools.registry import ToolRegistry


def _make_tool(name: str) -> dict[str, object]:
    return {"name": name, "description": f"tool {name}", "inputSchema": {"type": "object"}}


def test_default_hidden_tools_is_empty_and_preserves_all_tools() -> None:
    """hidden_tools 未指定時は従来通り全 tool を保持する (後方互換)。"""
    tools = [_make_tool("memory_save"), _make_tool("memory_search")]
    r = ToolRegistry(tools)
    names = [t["name"] for t in r.all_tools]
    assert names == ["memory_save", "memory_search"]


def test_hidden_tools_excludes_named_tools_from_all_tools() -> None:
    tools = [
        _make_tool("memory_save"),
        _make_tool("memory_save_url"),
        _make_tool("memory_search"),
    ]
    r = ToolRegistry(tools, hidden_tools=frozenset({"memory_save"}))
    names = [t["name"] for t in r.all_tools]
    assert "memory_save" not in names
    assert {"memory_save_url", "memory_search"} == set(names)


def test_hidden_tools_excludes_named_tools_from_filter_by_caps() -> None:
    tools = [_make_tool("memory_save"), _make_tool("memory_search")]
    r = ToolRegistry(tools, hidden_tools=frozenset({"memory_save"}))
    filtered = r.filter_by_caps(caps={"memory_save", "memory_search"})
    names = [t["name"] for t in filtered]
    assert names == ["memory_search"]


def test_hidden_tools_unknown_names_are_silently_ignored() -> None:
    """存在しない tool 名を hidden_tools に渡しても警告無く何も除外しない。"""
    tools = [_make_tool("memory_save")]
    r = ToolRegistry(tools, hidden_tools=frozenset({"nonexistent_tool"}))
    names = [t["name"] for t in r.all_tools]
    assert names == ["memory_save"]


def test_replace_tools_does_not_clear_hidden_tools() -> None:
    """replace_tools は _all のみ差し替え、hidden_tools は不変。"""
    initial = [_make_tool("memory_save")]
    r = ToolRegistry(initial, hidden_tools=frozenset({"memory_save"}))
    r.replace_tools([_make_tool("memory_save"), _make_tool("memory_search")])
    names = [t["name"] for t in r.all_tools]
    assert "memory_save" not in names
    assert "memory_search" in names


def test_hidden_tools_keyword_only_argument() -> None:
    """hidden_tools は keyword-only argument として渡される (誤って positional で渡せない)。"""
    import pytest

    tools = [_make_tool("memory_save")]
    with pytest.raises(TypeError):
        ToolRegistry(tools, frozenset({"memory_save"}))  # type: ignore[misc]
```

- [ ] **Step 3: 失敗を確認 (`hidden_tools` 引数が未実装のため TypeError 等で FAIL)**

```bash
uv run pytest tests/unit/test_tool_registry_hidden.py -v
```

期待出力: `test_default_hidden_tools_is_empty_and_preserves_all_tools` は既存実装で偶然 PASS する可能性あり (引数を渡していないため)。他 5 件は FAIL (`TypeError: __init__() got an unexpected keyword argument 'hidden_tools'` 等)。

- [ ] **Step 4: `src/mcp_gateway/tools/registry.py` に `hidden_tools` を実装**

ファイル全体を以下に書き換える (現状 22 行のため、`Write` で完全置換が安全。`Read` で現状を確認してから `Write`):

```python
"""ToolRegistry: cache the upstream's tools/list and apply Default Deny filtering."""

from __future__ import annotations

import copy
from typing import AbstractSet, Any


class ToolRegistry:
    def __init__(
        self,
        all_tools: list[dict[str, Any]],
        *,
        hidden_tools: AbstractSet[str] = frozenset(),
    ) -> None:
        self._all = copy.deepcopy(all_tools)
        self._hidden: frozenset[str] = frozenset(hidden_tools)

    @property
    def all_tools(self) -> list[dict[str, Any]]:
        return [copy.deepcopy(t) for t in self._all if t.get("name") not in self._hidden]

    def filter_by_caps(self, *, caps: AbstractSet[str]) -> list[dict[str, Any]]:
        return [
            copy.deepcopy(t)
            for t in self._all
            if t.get("name") in caps and t.get("name") not in self._hidden
        ]

    def replace_tools(self, all_tools: list[dict[str, Any]]) -> None:
        self._all = copy.deepcopy(all_tools)
```

- [ ] **Step 5: テストが緑になることを確認**

```bash
uv run pytest tests/unit/test_tool_registry_hidden.py -v
```

期待出力: 全 6 件 PASS。

- [ ] **Step 6: 静的解析パス確認**

```bash
uv run ruff check src/mcp_gateway/tools/registry.py tests/unit/test_tool_registry_hidden.py
uv run ruff format --check src/mcp_gateway/tools/registry.py tests/unit/test_tool_registry_hidden.py
uv run mypy src/mcp_gateway/tools/registry.py
```

期待出力: いずれもエラー 0。

- [ ] **Step 7: 既存テストの regression 確認 (特に既存の registry / gateway 経路)**

```bash
uv run pytest tests/unit -v -k "registry or gateway"
```

期待出力: 既存テストすべて緑、追加 6 件も緑。`replace_tools` を使うテストが既にあれば後方互換性を確認。

- [ ] **Step 8: コミット**

```bash
git add src/mcp_gateway/tools/registry.py tests/unit/test_tool_registry_hidden.py
git commit -m "$(cat <<'EOF'
feat(gateway): ToolRegistry に hidden_tools 引数を追加し tools/list から物理的に除外

- __init__ に keyword-only argument hidden_tools: AbstractSet[str] を追加。
- all_tools / filter_by_caps の戻り値から hidden 名を除外。
- replace_tools は _all のみ差し替え、hidden_tools は不変。
- デフォルト引数 frozenset() で従来挙動を完全維持 (後方互換)。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 9: Draft PR 作成 (派生元: `master`) と URL 記録**

```bash
git push -u origin feat/tool-registry-hidden-tools
gh pr create --draft --base master --title "feat(gateway): ToolRegistry に hidden_tools 引数を追加" --body "$(cat <<'EOF'
## Summary
- `ToolRegistry.__init__` に keyword-only な `hidden_tools` を追加し、`all_tools` / `filter_by_caps` の戻り値から該当名を除外する。
- 後方互換: `hidden_tools` 未指定時は従来挙動 (フィルタ無し)。
- 後続 Task 3.2 (`build_app()` での `memory_save` 隠蔽) の前提となる。

## Test plan
- [ ] `uv run pytest tests/unit/test_tool_registry_hidden.py -v` が緑
- [ ] 既存の registry / gateway 関連 test に regression 無し
- [ ] `uv run mypy src/mcp_gateway/tools/registry.py` が pass

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

PR URL を **「Draft PR URL 記録欄」の Task 3.1 行** に追記する。

---

### Task 3.2: `build_app()` で `memory_save` を隠蔽

**派生元ブランチ:** `master`
**実行モード:** 直列必須 (Task 2.1 と Task 3.1 の両 PR が **master へマージ済み** であること)
**前提条件:**
1. Task 2.1 の Draft PR URL が存在し、レビュー通過後に master へマージ済み (これにより `GatewaySettings.ingestion_mode` が master に存在する)
2. Task 3.1 の Draft PR URL が存在し、レビュー通過後に master へマージ済み (これにより `ToolRegistry.hidden_tools` が master に存在する)
**Files:**
- Modify: `src/mcp_gateway/app.py` (設計書 §11 では行 100-108 / 110-124 周辺)

- [ ] **Step 1: ブランチ作成と派生元検証 (Devcontainer 内で実行)**

```bash
git fetch origin master
git checkout -b feat/build-app-hide-memory-save origin/master

EXPECTED_BASE="origin/master"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git merge-base --is-ancestor "$EXPECTED_BASE" "$CURRENT_BRANCH" || { echo "ERROR: 派生元ブランチが $EXPECTED_BASE ではありません。スタック構造が壊れています。"; exit 1; }
```

- [ ] **Step 2: master に Task 2.1 / Task 3.1 が取り込まれていることを物理確認**

```bash
# Task 2.1 が master に取り込まれていれば GatewaySettings.ingestion_mode が存在するはず
uv run python -c "from mcp_gateway.config import GatewaySettings; assert 'ingestion_mode' in GatewaySettings.model_fields, 'Task 2.1 not yet merged'"
# Task 3.1 が master に取り込まれていれば ToolRegistry に hidden_tools 引数があるはず
uv run python -c "import inspect; from mcp_gateway.tools.registry import ToolRegistry; sig = inspect.signature(ToolRegistry.__init__); assert 'hidden_tools' in sig.parameters, 'Task 3.1 not yet merged'"
```

期待出力: いずれも assertion 通過 (例外無し)。assertion 失敗 → master を待ってから本 Task を再開する。

- [ ] **Step 3: 既存 `src/mcp_gateway/app.py` の `build_app()` 内で `ToolRegistry(...)` を呼んでいる行を特定**

`Read` で `src/mcp_gateway/app.py` を読み、`ToolRegistry(initial_tools or [])` のような行を見つける (設計書 §11 では行 110-124 付近)。前後 5 行を `Edit` 用にメモする。

- [ ] **Step 4: `build_app()` で `settings.ingestion_mode == "all"` 時に `hidden_tools` を渡す**

`Edit` で以下のパターンに沿って変更する (Step 3 で確認した実際の前後コンテキストに合わせる):

`old_string`:
```python
    registry = ToolRegistry(initial_tools or [])
```

`new_string`:
```python
    hidden_tools: frozenset[str] = (
        frozenset({"memory_save"}) if settings.ingestion_mode == "all" else frozenset()
    )
    registry = ToolRegistry(initial_tools or [], hidden_tools=hidden_tools)
```

注意: `settings` 変数は同関数内で既に `GatewaySettings` インスタンスを保持していることを Step 3 で必ず確認する。変数名が `settings` 以外であればそれに合わせる。

- [ ] **Step 5: 軽い integration テストを追加 (任意だが推奨)**

新規 `tests/unit/test_build_app_hidden_tools.py`:

```python
"""build_app() が ingestion_mode に応じて hidden_tools を渡すことを検証。"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def policy_file(tmp_path: Path) -> Path:
    p = tmp_path / "policy.yaml"
    p.write_text("version: 1\nallow: []\n", encoding="utf-8")
    return p


def test_selective_mode_does_not_hide_memory_save(
    monkeypatch: pytest.MonkeyPatch, policy_file: Path
) -> None:
    monkeypatch.delenv("CHRONOS_INGESTION_MODE", raising=False)
    monkeypatch.setenv("MCP_GATEWAY_POLICY_PATH", str(policy_file))
    from mcp_gateway.app import build_app

    app = build_app(initial_tools=[{"name": "memory_save", "description": "x"}])
    registry = app.state.tool_registry  # type: ignore[attr-defined]
    names = [t["name"] for t in registry.all_tools]
    assert "memory_save" in names


def test_all_mode_hides_memory_save(
    monkeypatch: pytest.MonkeyPatch, policy_file: Path
) -> None:
    monkeypatch.setenv("CHRONOS_INGESTION_MODE", "all")
    monkeypatch.setenv("MCP_GATEWAY_POLICY_PATH", str(policy_file))
    from mcp_gateway.app import build_app

    app = build_app(
        initial_tools=[
            {"name": "memory_save", "description": "x"},
            {"name": "memory_save_url", "description": "y"},
        ]
    )
    registry = app.state.tool_registry  # type: ignore[attr-defined]
    names = [t["name"] for t in registry.all_tools]
    assert "memory_save" not in names
    assert "memory_save_url" in names
```

注意: `app.state.tool_registry` の保持名は `build_app` の実装に依存するため、Step 3 で確認した上で属性名を合わせる。実装と異なれば fixture でアクセス手段を調整する。

- [ ] **Step 6: テストが緑になることを確認**

```bash
uv run pytest tests/unit/test_build_app_hidden_tools.py -v
```

期待出力: 2 件とも PASS。

- [ ] **Step 7: 静的解析パス確認**

```bash
uv run ruff check src/mcp_gateway/app.py tests/unit/test_build_app_hidden_tools.py
uv run ruff format --check src/mcp_gateway/app.py tests/unit/test_build_app_hidden_tools.py
uv run mypy src/mcp_gateway/app.py
```

期待出力: いずれもエラー 0。

- [ ] **Step 8: 既存 test の regression 確認**

```bash
uv run pytest tests/unit -v
```

期待出力: 既存テストすべて緑、追加 2 件も緑。

- [ ] **Step 9: Classifier / Pipeline コードに差分が無いことを物理確認 (AC-7)**

```bash
git diff origin/master -- src/context_store/ingestion/classifier.py src/context_store/ingestion/pipeline.py 2>/dev/null | wc -l
```

期待出力: `0` (差分 0 行)。Pipeline ファイル名は環境により異なる可能性があるため、対象ファイルが存在しなければ `find src/context_store/ingestion/ -name 'pipeline*.py'` で位置を確認する。

- [ ] **Step 10: コミット**

```bash
git add src/mcp_gateway/app.py tests/unit/test_build_app_hidden_tools.py
git commit -m "$(cat <<'EOF'
feat(gateway): build_app() で ingestion_mode=all のとき memory_save を隠蔽

- settings.ingestion_mode == "all" の場合のみ ToolRegistry に
  hidden_tools={"memory_save"} を渡す。
- selective モードでは従来通り memory_save を tools/list に公開 (AC-1)。
- tools/call 経路は無修正のため、フックからの隠し API 呼び出しは引き続き成立 (AC-3)。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 11: Draft PR 作成 (派生元: `master`) と URL 記録**

```bash
git push -u origin feat/build-app-hide-memory-save
gh pr create --draft --base master --title "feat(gateway): build_app() で ingestion_mode=all のとき memory_save を隠蔽" --body "$(cat <<'EOF'
## Summary
- `GatewaySettings.ingestion_mode == "all"` のとき `ToolRegistry` に `hidden_tools={"memory_save"}` を渡す。
- AC-1 (selective で memory_save 公開) / AC-2 (all で memory_save 非公開・memory_save_url 公開) / AC-3 (tools/call は引き続き通る) を満たす。
- スタック: Task 2.1 + Task 3.1 の両 PR が master へマージ済みであることが前提。

## Test plan
- [ ] `uv run pytest tests/unit/test_build_app_hidden_tools.py -v` が緑
- [ ] `git diff origin/master -- src/context_store/ingestion/classifier.py src/context_store/ingestion/pipeline.py` が空 (AC-7)
- [ ] 既存 test に regression 無し

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

PR URL を **「Draft PR URL 記録欄」の Task 3.2 行** に追記する。

---

## Phase 4: ターン終了フック

### Task 4.1: `scripts/agent_turn_hook.py` 実装

**派生元ブランチ:** `master`
**実行モード:** 並列可能 (他のすべての Task と並列実行可。Gateway 側の隠蔽 (Task 3.2) と完全独立)
**前提条件:** なし
**Files:**
- Create: `scripts/agent_turn_hook.py`
- Create: `tests/unit/test_agent_turn_hook_truncate.py`

- [ ] **Step 1: ブランチ作成と派生元検証 (Devcontainer 内で実行)**

```bash
git fetch origin master
git checkout -b feat/agent-turn-hook-script origin/master

EXPECTED_BASE="origin/master"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git merge-base --is-ancestor "$EXPECTED_BASE" "$CURRENT_BRANCH" || { echo "ERROR: 派生元ブランチが $EXPECTED_BASE ではありません。スタック構造が壊れています。"; exit 1; }
```

- [ ] **Step 2: 失敗するテストを先に書く** (`tests/unit/test_agent_turn_hook_truncate.py` 新規)

```python
"""scripts/agent_turn_hook.py の truncate_log 純関数の検証。"""

from __future__ import annotations

import importlib.util
import pathlib
import sys


def _load_hook_module():
    """scripts/agent_turn_hook.py を tests から動的に import するヘルパ。"""
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    script_path = repo_root / "scripts" / "agent_turn_hook.py"
    spec = importlib.util.spec_from_file_location("agent_turn_hook", script_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["agent_turn_hook"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_truncate_log_short_input_returns_unchanged() -> None:
    mod = _load_hook_module()
    text = "hello world"
    out, was_truncated = mod.truncate_log(text, max_bytes=1024)
    assert out == text
    assert was_truncated is False


def test_truncate_log_long_ascii_input_keeps_tail() -> None:
    mod = _load_hook_module()
    text = "a" * 5000
    out, was_truncated = mod.truncate_log(text, max_bytes=1024)
    assert was_truncated is True
    assert len(out.encode("utf-8")) <= 1024
    # 末尾保持ポリシー: 最後の "a" は必ず含まれる
    assert out.endswith("a")
    # マーカー行が冒頭に付与されている
    assert out.startswith("[truncated to last ")


def test_truncate_log_marker_is_prefixed_and_bytes_stay_under_limit() -> None:
    mod = _load_hook_module()
    text = "x" * 10_000
    max_bytes = 200
    out, was_truncated = mod.truncate_log(text, max_bytes=max_bytes)
    assert was_truncated is True
    assert len(out.encode("utf-8")) <= max_bytes
    assert "[truncated to last " in out.splitlines()[0]


def test_truncate_log_multibyte_utf8_does_not_corrupt() -> None:
    """日本語 (3 バイト/文字) を含む長文を切り詰めても、不完全シーケンスを残さない。"""
    mod = _load_hook_module()
    # 3 バイト文字 × 1000 = 3000 バイト
    text = "あ" * 1000
    out, was_truncated = mod.truncate_log(text, max_bytes=500)
    assert was_truncated is True
    # decode("utf-8", errors="ignore") のため、結果は必ず妥当な UTF-8
    out.encode("utf-8").decode("utf-8")  # 例外なし
    # 結果バイト数は上限以下
    assert len(out.encode("utf-8")) <= 500


def test_truncate_log_exactly_at_limit_is_not_truncated() -> None:
    mod = _load_hook_module()
    text = "y" * 100
    out, was_truncated = mod.truncate_log(text, max_bytes=100)
    assert was_truncated is False
    assert out == text
```

- [ ] **Step 3: 失敗を確認 (`scripts/agent_turn_hook.py` 未作成のため import エラー)**

```bash
uv run pytest tests/unit/test_agent_turn_hook_truncate.py -v
```

期待出力: 全 5 件 FAIL (主に `FileNotFoundError` または `AssertionError` で `spec is not None` が false)。

- [ ] **Step 4: `scripts/agent_turn_hook.py` を実装** (新規)

```python
"""ターン終了時に会話ログを MCP Gateway へ fire-and-forget で送信するフック。

呼び出し例:
    echo "$CONVERSATION_LOG" | python scripts/agent_turn_hook.py &
    # または
    python scripts/agent_turn_hook.py --content "..." &

設計書: docs/superpowers/specs/2026-05-27-hybrid-ingestion-mode-design.md §4.5
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from typing import Final

import httpx

LOG_FORMAT: Final[str] = "%(asctime)s [%(levelname)s] agent_turn_hook: %(message)s"

DEFAULT_GATEWAY_URL: Final[str] = "http://127.0.0.1:9100"
DEFAULT_INTENT: Final[str] = "memory.ingest"
DEFAULT_TIMEOUT_SECONDS: Final[float] = 2.0
DEFAULT_MAX_LOG_BYTES: Final[int] = 8 * 1024 * 1024  # 8 MiB
TRUNCATION_MARKER_TEMPLATE: Final[str] = "[truncated to last {n} bytes]\n"


def truncate_log(content: str, max_bytes: int) -> tuple[str, bool]:
    """会話ログを送信前に末尾保持で切り詰める純関数。

    - 末尾保持: 古い側 (先頭) を捨て、新しい側 (末尾) を残す。
    - 切り詰めが発生した場合、冒頭に "[truncated to last N bytes]\\n" マーカーを付加。
    - マーカー込みで ``max_bytes`` を超えない範囲で末尾を切り出す。
    - UTF-8 境界の不完全シーケンスは ``errors="ignore"`` で破棄する。
    """
    encoded = content.encode("utf-8")
    if len(encoded) <= max_bytes:
        return content, False

    # マーカー長を見積もるため一度フォーマット
    marker = TRUNCATION_MARKER_TEMPLATE.format(n=max_bytes)
    marker_bytes = marker.encode("utf-8")
    # 末尾から (max_bytes - marker_bytes) バイト分を残す
    tail_budget = max_bytes - len(marker_bytes)
    if tail_budget <= 0:
        # max_bytes がマーカー自体より小さい異常ケース: マーカーのみ返す
        return marker[:max_bytes], True

    tail_bytes = encoded[-tail_budget:]
    tail = tail_bytes.decode("utf-8", errors="ignore")
    result = marker + tail
    return result, True


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="ChronosGraph turn-end memory ingestion hook")
    p.add_argument(
        "--content",
        default=None,
        help="会話ログ本文。未指定時は stdin から読み取る。",
    )
    return p


def _read_input(args: argparse.Namespace) -> str:
    if args.content is not None:
        return args.content
    return sys.stdin.read()


async def _send(
    gateway_url: str,
    api_key: str,
    intent: str,
    payload: str,
    timeout: float,
) -> None:
    """SSE handshake → tools/call memory_save。例外は呼び出し側で握りつぶす。"""
    headers = {
        "authorization": f"Bearer {api_key}",
        "x-mcp-intent": intent,
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=1.0)) as client:
        # SSE で session_id を取得
        session_id: str | None = None
        async with client.stream("GET", f"{gateway_url}/sse", headers=headers) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data: ") and "/messages?session_id=" in line:
                    # 例: "data: /messages?session_id=abc123"
                    fragment = line.split("session_id=", 1)[1].strip()
                    session_id = fragment
                    break
        if session_id is None:
            logging.warning("SSE handshake did not yield a session_id")
            return

        # tools/call memory_save
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "memory_save",
                "arguments": {"content": payload},
            },
        }
        post_resp = await client.post(
            f"{gateway_url}/messages",
            params={"session_id": session_id},
            json=body,
            headers={"content-type": "application/json", **headers},
        )
        if post_resp.status_code == 413:
            logging.warning(
                "Gateway returned 413 Payload Too Large; "
                "consider lowering MCP_HOOK_MAX_LOG_BYTES (currently %d)",
                int(os.environ.get("MCP_HOOK_MAX_LOG_BYTES", DEFAULT_MAX_LOG_BYTES)),
            )
        elif post_resp.status_code >= 400:
            logging.warning("Gateway returned HTTP %d", post_resp.status_code)
        # body は読まず close (fire-and-forget)


async def _main_async(payload: str) -> None:
    gateway_url = os.environ.get("MCP_GATEWAY_URL", DEFAULT_GATEWAY_URL)
    api_key = os.environ.get("MCP_GATEWAY_API_KEY")
    intent = os.environ.get("MCP_INTENT", DEFAULT_INTENT)
    timeout = float(os.environ.get("MCP_HOOK_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))

    if not api_key:
        logging.error("MCP_GATEWAY_API_KEY is not set; aborting hook (no-op)")
        return

    try:
        await asyncio.wait_for(
            _send(gateway_url, api_key, intent, payload, timeout),
            timeout=timeout,
        )
    except TimeoutError as exc:
        logging.info("turn hook timed out: %s", exc)
    except httpx.HTTPError as exc:
        logging.warning("turn hook failed (HTTP error): %s", exc)
    except Exception as exc:  # broad: fire-and-forget; must never raise
        logging.warning("turn hook failed (unexpected): %s", exc, exc_info=True)


def main() -> int:
    log_level = os.environ.get("LOG_LEVEL", "INFO")
    logging.basicConfig(level=log_level, format=LOG_FORMAT, stream=sys.stderr)

    parser = _build_parser()
    args = parser.parse_args()

    try:
        raw = _read_input(args)
    except Exception as exc:
        logging.warning("failed to read input: %s", exc)
        return 0

    if not raw:
        logging.debug("empty input; skipping hook invocation")
        return 0

    max_bytes = int(os.environ.get("MCP_HOOK_MAX_LOG_BYTES", DEFAULT_MAX_LOG_BYTES))
    payload, was_truncated = truncate_log(raw, max_bytes)
    if was_truncated:
        logging.warning(
            "payload truncated: original=%d bytes, sent=%d bytes",
            len(raw.encode("utf-8")),
            len(payload.encode("utf-8")),
        )

    try:
        asyncio.run(_main_async(payload))
    except Exception as exc:  # noqa: BLE001 - intentional broad catch
        logging.warning("turn hook failed at top level: %s", exc, exc_info=True)

    return 0  # 常に 0: メインプロセスをクラッシュさせない


if __name__ == "__main__":
    sys.exit(main())
```

注意:
- `scripts/*.py` は `pyproject.toml` で `T201` (print) を許可されているが、本スクリプトは `logging` のみ使用 (print 不要)。
- `Exception` の broad catch は `# noqa: BLE001` で ruff の警告を抑制。

- [ ] **Step 5: テストが緑になることを確認**

```bash
uv run pytest tests/unit/test_agent_turn_hook_truncate.py -v
```

期待出力: 全 5 件 PASS。

- [ ] **Step 6: 静的解析パス確認**

```bash
uv run ruff check scripts/agent_turn_hook.py tests/unit/test_agent_turn_hook_truncate.py
uv run ruff format --check scripts/agent_turn_hook.py tests/unit/test_agent_turn_hook_truncate.py
uv run mypy scripts/agent_turn_hook.py
```

期待出力: いずれもエラー 0。

- [ ] **Step 7: フェイルソフト挙動の手動 smoke test**

Gateway が起動していない状態でも exit 0 で終わることを確認:

```bash
MCP_GATEWAY_API_KEY="dummy" \
  MCP_GATEWAY_URL="http://127.0.0.1:65535" \
  MCP_HOOK_TIMEOUT_SECONDS="1.0" \
  echo "test conversation log" | uv run python scripts/agent_turn_hook.py
echo "exit code: $?"
```

期待出力: `exit code: 0`。stderr に WARNING ログが 1 行表示される (`turn hook failed (HTTP error): ...` 等)。

- [ ] **Step 8: 既存 test の regression 確認**

```bash
uv run pytest tests/unit -v
```

期待出力: 既存テストすべて緑、追加 5 件も緑。

- [ ] **Step 9: コミット**

```bash
git add scripts/agent_turn_hook.py tests/unit/test_agent_turn_hook_truncate.py
git commit -m "$(cat <<'EOF'
feat(scripts): ターン終了フック agent_turn_hook.py を新設

- stdin または --content から会話ログを受け取り、末尾保持で切り詰めて
  MCP Gateway HTTP に fire-and-forget で memory_save を呼ぶ独立スクリプト。
- 切り詰めは pure 関数 truncate_log として単体テスト可能に分離。
- UTF-8 境界は errors="ignore" で破棄し、不完全マルチバイトを残さない。
- 全例外を握りつぶし常に exit 0。メインエージェントをクラッシュさせない。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 10: Draft PR 作成 (派生元: `master`) と URL 記録**

```bash
git push -u origin feat/agent-turn-hook-script
gh pr create --draft --base master --title "feat(scripts): ターン終了フック agent_turn_hook.py を新設" --body "$(cat <<'EOF'
## Summary
- 会話ログを末尾保持で切り詰めて MCP Gateway HTTP に fire-and-forget で送信する独立スクリプト。
- `truncate_log` は pure 関数として切り出し、単体テスト可能。
- AC-5 (Gateway 到達不可・タイムアウト・認証失敗のいずれでも exit 0) / AC-8 (切り詰め + 413 グレースフル) を満たす。

## Test plan
- [ ] `uv run pytest tests/unit/test_agent_turn_hook_truncate.py -v` が緑
- [ ] Gateway 到達不可の手動 smoke test で exit code 0
- [ ] `uv run mypy scripts/agent_turn_hook.py` が pass

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

PR URL を **「Draft PR URL 記録欄」の Task 4.1 行** に追記する。

---

## Phase 5: 統合検証

### Task 5.1: E2E 統合検証

**派生元ブランチ:** `master`
**実行モード:** 直列必須 (Task 0.1 / 1.1 / 2.1 / 3.1 / 3.2 / 4.1 の **全 PR が master へマージ済み** であること)
**前提条件:** 上記 6 PR すべてのマージ完了
**Files:**
- なし (検証スクリプト実行 + 結果記録のみ)
- (任意) Create: `docs/superpowers/specs/2026-05-27-hybrid-ingestion-mode-verification.md` (検証結果サマリ)

- [ ] **Step 1: ブランチ作成と派生元検証 (Devcontainer 内で実行)**

```bash
git fetch origin master
git checkout -b feat/hybrid-ingestion-integration-verify origin/master

EXPECTED_BASE="origin/master"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git merge-base --is-ancestor "$EXPECTED_BASE" "$CURRENT_BRANCH" || { echo "ERROR: 派生元ブランチが $EXPECTED_BASE ではありません。スタック構造が壊れています。"; exit 1; }
```

- [ ] **Step 2: master に必要な全変更が取り込まれていることを物理確認**

```bash
test -f src/chronos_shared/ingestion_mode.py && echo "OK: Task 1.1"
uv run python -c "from mcp_gateway.config import GatewaySettings; assert 'ingestion_mode' in GatewaySettings.model_fields" && echo "OK: Task 2.1 (gw)"
uv run python -c "from context_store.config import Settings; assert 'ingestion_mode' in Settings.model_fields" && echo "OK: Task 2.1 (ctx)"
uv run python -c "import inspect; from mcp_gateway.tools.registry import ToolRegistry; assert 'hidden_tools' in inspect.signature(ToolRegistry.__init__).parameters" && echo "OK: Task 3.1"
test -f scripts/agent_turn_hook.py && echo "OK: Task 4.1"
```

期待出力: 5 行とも "OK: ..."。

- [ ] **Step 3: 静的解析・型チェック (設計書 §8 Step 2/3)**

```bash
uv run ruff check src/chronos_shared/ingestion_mode.py \
                  src/context_store/config.py \
                  src/mcp_gateway/config.py \
                  src/mcp_gateway/tools/registry.py \
                  src/mcp_gateway/app.py \
                  scripts/agent_turn_hook.py \
                  tests/unit/test_tool_registry_hidden.py \
                  tests/unit/test_settings_ingestion_mode.py \
                  tests/unit/test_agent_turn_hook_truncate.py

uv run mypy src/chronos_shared/ingestion_mode.py \
            src/context_store/config.py \
            src/mcp_gateway/config.py \
            src/mcp_gateway/tools/registry.py \
            src/mcp_gateway/app.py \
            scripts/agent_turn_hook.py
```

期待出力: いずれもエラー 0 (AC-6)。

- [ ] **Step 4: 追加ユニットテスト (設計書 §8 Step 4)**

```bash
uv run pytest tests/unit/test_chronos_shared_ingestion_mode.py -v
uv run pytest tests/unit/test_tool_registry_hidden.py -v
uv run pytest tests/unit/test_settings_ingestion_mode.py -v
uv run pytest tests/unit/test_agent_turn_hook_truncate.py -v
uv run pytest tests/unit/test_build_app_hidden_tools.py -v
```

期待出力: 全タスクのテストが緑 (合計 27 件)。

- [ ] **Step 5: 既存テストのリグレッション確認 (設計書 §8 Step 5)**

```bash
uv run pytest tests/unit/ -k "registry or settings or gateway" -v
uv run pytest tests/unit/ -v
```

期待出力: 失敗 0。

- [ ] **Step 6: 手動 E2E (設計書 §8 Step 6 を Devcontainer 内で実行)**

```bash
# 必要環境変数を準備 (TEST_API_KEY は事前にエージェントが知っている dummy 値で OK)
export CHRONOS_INGESTION_MODE=all
export MCP_GATEWAY_POLICY_PATH=./policies/default.yaml  # リポジトリの既存ポリシーパスに合わせる
export TEST_API_KEY="dummy-test-key"
export MCP_GATEWAY_API_KEYS_JSON="{\"hook\":\"$TEST_API_KEY\"}"

# Gateway 起動 (background)
uv run python -m mcp_gateway &
GATEWAY_PID=$!
sleep 3

# SSE で session_id 取得
SESSION_LINE=$(curl -s -N http://127.0.0.1:9100/sse \
     -H "authorization: Bearer $TEST_API_KEY" \
     -H "x-mcp-intent: memory.ingest" | head -1)
echo "SSE first line: $SESSION_LINE"

# tools/list 確認 (AC-2)
SESSION_ID=$(echo "$SESSION_LINE" | sed -n 's/.*session_id=\([^[:space:]]*\).*/\1/p')
curl -s -X POST "http://127.0.0.1:9100/messages?session_id=$SESSION_ID" \
     -H "authorization: Bearer $TEST_API_KEY" \
     -H "content-type: application/json" \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | jq '.result.tools[].name'

# クリーンアップ
kill "$GATEWAY_PID" 2>/dev/null || true
wait "$GATEWAY_PID" 2>/dev/null || true
```

期待出力: `tools[].name` 一覧に `"memory_save"` が **含まれず**、`"memory_save_url"` が **含まれる** (AC-2)。`MCP_GATEWAY_POLICY_PATH` のパスはリポジトリ実体に合わせて調整。

- [ ] **Step 7: フック経由の `tools/call memory_save` が成立することを確認 (AC-3)**

Step 6 で起動した Gateway に対して以下を実行 (Step 6 をもう一度起動し直しても OK):

```bash
export CHRONOS_INGESTION_MODE=all
uv run python -m mcp_gateway &
GATEWAY_PID=$!
sleep 3

MCP_GATEWAY_API_KEY="$TEST_API_KEY" \
  MCP_GATEWAY_URL="http://127.0.0.1:9100" \
  echo "[📜 Episodic] manual E2E test from agent_turn_hook" | \
  uv run python scripts/agent_turn_hook.py
echo "hook exit code: $?"

kill "$GATEWAY_PID" 2>/dev/null || true
wait "$GATEWAY_PID" 2>/dev/null || true
```

期待出力: `hook exit code: 0`、stderr に ERROR ログ無し (WARNING はネットワーク状況により出る可能性あり)。

- [ ] **Step 8: AC チェックリストの照合**

設計書 §9 の AC-1 〜 AC-10 を一つずつ確認し、本ブランチに「検証結果サマリ」コミット (空コミットでも可) を残す。

検証結果サマリの例 (オプション、`docs/superpowers/specs/2026-05-27-hybrid-ingestion-mode-verification.md` 新規):

```markdown
# Hybrid Ingestion Mode 統合検証結果 (2026-05-27)

| AC | 内容 | 結果 | 検証コマンド |
|---|---|---|---|
| AC-1 | selective で memory_save 公開 | PASS | Step 6 (selective env で確認) |
| AC-2 | all で memory_save 非公開 / memory_save_url 公開 | PASS | Step 6 |
| AC-3 | tools/call memory_save 可能 | PASS | Step 7 |
| AC-4 | invalid value で fail-fast | PASS | test_gateway_settings_rejects_invalid_value |
| AC-5 | フック exit 0 | PASS | Task 4.1 smoke test |
| AC-6 | ruff + mypy パス | PASS | Step 3 |
| AC-7 | Classifier / Pipeline 差分 0 | PASS | git diff |
| AC-8 | 切り詰め + 413 グレースフル | PASS | test_agent_turn_hook_truncate.py |
| AC-9 | SSOT 一元化 / cross-pkg import 0 | PASS | grep |
| AC-10 | env passthrough 伝達 | PASS | test_build_upstream_env_propagates_ingestion_mode |
```

- [ ] **Step 9: コミット**

```bash
git add docs/superpowers/specs/2026-05-27-hybrid-ingestion-mode-verification.md 2>/dev/null || true
git commit --allow-empty -m "$(cat <<'EOF'
chore(verify): hybrid ingestion mode 統合検証通過 (AC-1〜AC-10 全項目 PASS)

設計書 docs/superpowers/specs/2026-05-27-hybrid-ingestion-mode-design.md
§9 の受け入れ条件をすべて満たすことを確認。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 10: Draft PR 作成と URL 記録**

```bash
git push -u origin feat/hybrid-ingestion-integration-verify
gh pr create --draft --base master --title "chore(verify): hybrid ingestion mode 統合検証通過" --body "$(cat <<'EOF'
## Summary
- 設計書 §9 の AC-1〜AC-10 すべての受け入れ条件が満たされていることを統合検証。
- すべての先行 Task (0.1 / 1.1 / 2.1 / 3.1 / 3.2 / 4.1) が master へマージ済みであることを Step 2 で物理確認済み。

## Test plan
- [ ] 設計書 §8 の全検証コマンドを Devcontainer 内で再実行して緑
- [ ] AC-1 〜 AC-10 のすべての項目が verification.md にて PASS と記録されている

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

PR URL を **「Draft PR URL 記録欄」の Task 5.1 行** に追記する。

---

## Acceptance Criteria 対応マップ

| AC | 設計書 §9 | 担当 Task | 検証手段 |
|---|---|---|---|
| AC-1 | selective で memory_save 公開 | Task 3.2 | `test_build_app_hidden_tools.py::test_selective_mode_does_not_hide_memory_save` |
| AC-2 | all で memory_save 非公開 | Task 3.1 + 3.2 | `test_build_app_hidden_tools.py::test_all_mode_hides_memory_save` + Task 5.1 Step 6 |
| AC-3 | tools/call memory_save 可能 | Task 3.1 (実装) + Task 5.1 (E2E) | Task 5.1 Step 7 |
| AC-4 | invalid value で fail-fast | Task 2.1 | `test_settings_ingestion_mode.py::test_*_rejects_invalid_value` |
| AC-5 | フック exit 0 | Task 4.1 | Task 4.1 Step 7 smoke test |
| AC-6 | ruff + mypy パス | 全 Task | 各 Task の Step 6 / Step 9 |
| AC-7 | Classifier / Pipeline 差分 0 | Task 3.2 | Task 3.2 Step 9 |
| AC-8 | 切り詰め + 413 グレースフル | Task 4.1 | `test_agent_turn_hook_truncate.py` 全 5 件 |
| AC-9 | SSOT 一元化 + cross-pkg import 0 | Task 1.1 + Task 2.1 | `test_settings_ingestion_mode.py::test_both_settings_use_same_ssot_type` + Task 2.1 Step 10 grep |
| AC-10 | env passthrough 伝達 | Task 2.1 | `test_settings_ingestion_mode.py::test_gateway_upstream_passthrough_includes_ingestion_mode` + `test_build_upstream_env_propagates_ingestion_mode` |

---

## 想定実行順 (並列性を最大化した場合)

```text
Day 1 (並列):
  ├── Task 0.1 (devcontainer/CI baseline check)
  ├── Task 1.1 (chronos_shared)
  ├── Task 3.1 (ToolRegistry hidden_tools)
  └── Task 4.1 (agent_turn_hook.py)

Day 1 後半 (Task 1.1 マージ後):
  └── Task 2.1 (Settings 両方拡張)

Day 2 (Task 2.1 + Task 3.1 が master にマージ済み):
  └── Task 3.2 (build_app)

Day 2 後半 (全 PR マージ済み):
  └── Task 5.1 (統合検証)
```

並列実行不可な依存:
- Task 2.1 は Task 1.1 の **ブランチ存在** が必須 (派生元として)
- Task 3.2 は Task 2.1 + Task 3.1 の **master マージ済み** が必須
- Task 5.1 は全 Task の **master マージ済み** が必須
