# Embedding プロバイダーの不具合修正 実装計画

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** LiteLLM プロバイダーの設定とリトライロジックを修正し、ローカルモデルのブロッキング問題を解消する。

**Architecture:** `Settings` クラスに詳細な設定を追加し、各プロバイダーに明示的に渡す「設定主導型」アプローチ。LiteLLM には `tenacity` によるリトライを導入し、Local Model はコンストラクタで次元数を受け取ることでブロッキングを回避する。

**Tech Stack:** Python, Pydantic, LiteLLM, Tenacity, Sentence-Transformers, Pytest

---

### Task 1: Settings の拡張

**Files:**
- Modify: `src/context_store/config.py`
- Test: `tests/unit/test_config.py`

**Step 1: 失敗するテストを書く**

```python
def test_litellm_settings_validation():
    from context_store.config import Settings
    # LITELLM_API_BASE があっても LITELLM_MODEL がない場合に失敗するか確認
    with pytest.raises(ValueError, match="LITELLM_MODEL"):
        Settings(embedding_provider="litellm", litellm_api_base="http://localhost")
```

**Step 2: テストを実行して失敗を確認**

Run: `pytest tests/unit/test_config.py -v`

**Step 3: 実装を追加**

`Settings` クラスに `litellm_model` と `embedding_dimension` を追加し、バリデーションを更新。

**Step 4: テストを実行して成功を確認**

**Step 5: コミット**

```bash
git add src/context_store/config.py
git commit -m "feat: add litellm_model and embedding_dimension to settings"
```

---

### Task 2: プロバイダー生成ロジックの更新

**Files:**
- Modify: `src/context_store/embedding/__init__.py`
- Test: `tests/unit/test_embedding_factory.py`

**Step 1: 失敗するテストを書く**

プロバイダーが新しい設定値（特に `embedding_dimension`）を使用しているか確認するテスト。

**Step 2: テストを実行して失敗を確認**

**Step 3: 実装を更新**

`create_embedding_provider` で `settings.litellm_model` と `settings.embedding_dimension` を各プロバイダーに渡す。

**Step 4: テストを実行して成功を確認**

**Step 5: コミット**

```bash
git add src/context_store/embedding/__init__.py
git commit -m "refactor: use new settings in embedding provider factory"
```

---

### Task 3: LiteLLM プロバイダーのリトライ実装

**Files:**
- Modify: `src/context_store/embedding/litellm.py`
- Test: `tests/unit/test_embedding_litellm.py`

**Step 1: 失敗するテストを書く**

API が一時的に失敗（429等）した際にリトライされることを確認するテスト。

**Step 2: テストを実行して失敗を確認**

**Step 3: リトライロジックを実装**

`tenacity` を導入し、`_is_retryable` に基づくリトライを `embed_batch` に適用。

**Step 4: テストを実行して成功を確認**

**Step 5: コミット**

```bash
git add src/context_store/embedding/litellm.py
git commit -m "feat: add retry logic to LiteLLM provider using tenacity"
```

---

### Task 4: Local Model プロバイダーの非ブロッキング化

**Files:**
- Modify: `src/context_store/embedding/local_model.py`
- Test: `tests/unit/test_embedding_local.py`

**Step 1: 失敗するテストを書く**

`dimension` プロパティを呼んでもモデルがロードされない（`_model` が `None` のまま）ことを確認するテスト。

**Step 2: テストを実行して失敗を確認**

**Step 3: 実装を更新**

コンストラクタで `dimension` を受け取り、プロパティで優先的に返すようにする。

**Step 4: テストを実行して成功を確認**

**Step 5: コミット**

```bash
git add src/context_store/embedding/local_model.py
git commit -m "perf: avoid blocking model load in LocalModel.dimension"
```
