# 埋め込みプロバイダー規約準拠と安定性向上 実装計画

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 埋め込みベクトルの次元数バリデーションを追加し、リソースの適切なクリーンアップを保証し、リトライ戦略をドキュメントと同期させ、フォーマット不備を解消する。

**Architecture:** Pydantic による設定時のバリデーション、`EmbeddingProvider` プロトコルへのライフサイクルメソッド (`close`) の追加、および静的解析警告 (RUF003) の修正。

**Tech Stack:** Python, Pydantic, Tenacity, Pytest, Ruff

---

### Task 1: 設定クラスのバリデーション強化

**Files:**
- Modify: `src/context_store/config.py`
- Test: `tests/unit/test_config.py`

**Step 1: 失敗するテストを書く**

`tests/unit/test_config.py` に `test_embedding_dimension_must_be_positive` を追加。

```python
def test_embedding_dimension_must_be_positive():
    from context_store.config import Settings
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError, match="embedding_dimension"):
        Settings(embedding_dimension=0)
```

**Step 2: テストを実行して失敗を確認**

Run: `pytest tests/unit/test_config.py -v`

**Step 3: 実装の修正**

`src/context_store/config.py` の `embedding_dimension` を以下のように修正：
`embedding_dimension: int = Field(default=1536, ge=1)`

**Step 4: テストを実行して成功を確認**

**Step 5: コミット**

```bash
git add src/context_store/config.py tests/unit/test_config.py
git commit -m "feat: add validation for embedding_dimension"
```

---

### Task 2: EmbeddingProvider への close メソッド追加

**Files:**
- Modify: `src/context_store/embedding/protocols.py`
- Modify: `src/context_store/embedding/litellm.py`
- Modify: `src/context_store/embedding/local_model.py`
- Modify: `src/context_store/embedding/openai.py`
- Modify: `src/context_store/ingestion/pipeline.py`

**Step 1: プロトコルに close を追加**

`src/context_store/embedding/protocols.py` の `EmbeddingProvider` に `async def close(self) -> None:` を追加。

**Step 2: 各実装に close を追加 (空実装含む)**

- `src/context_store/embedding/litellm.py`: `async def close(self) -> None: pass`
- `src/context_store/embedding/local_model.py`: `async def close(self) -> None: pass`
- `src/context_store/embedding/openai.py`: `async def close(self) -> None: pass`

**Step 3: IngestionPipeline.dispose() の更新**

`src/context_store/ingestion/pipeline.py` の `dispose()` メソッドを整理し、`self._embedding_provider.close()` を確実に呼び出すようにする。

**Step 4: 各プロバイダーのテストで close を呼んでもエラーにならないことを確認**

**Step 5: コミット**

```bash
git add src/context_store/embedding/protocols.py src/context_store/embedding/litellm.py src/context_store/embedding/local_model.py src/context_store/embedding/openai.py src/context_store/ingestion/pipeline.py
git commit -m "feat: add close() method to EmbeddingProvider protocol and implementations"
```

---

### Task 3: LiteLLM リトライ戦略の同期 (Jitter 追加)

**Files:**
- Modify: `src/context_store/embedding/litellm.py`
- Test: `tests/unit/test_embedding_litellm.py`

**Step 1: 実装の修正**

`src/context_store/embedding/litellm.py` の `wait_exponential` に `jitter=True` を追加。

**Step 2: テストコメントの修正**

`tests/unit/test_embedding_litellm.py` L148-149 付近の `min=2` を `min=1` に修正。

**Step 3: テストを実行して成功を確認**

Run: `pytest tests/unit/test_embedding_litellm.py -v`

**Step 4: コミット**

```bash
git add src/context_store/embedding/litellm.py tests/unit/test_embedding_litellm.py
git commit -m "fix: align LiteLLM retry strategy with documentation (add jitter)"
```

---

### Task 4: Local Model のバリデーションと全角括弧修正

**Files:**
- Modify: `src/context_store/embedding/local_model.py`
- Test: `tests/unit/test_embedding_local.py`

**Step 1: LocalModel.__init__ バリデーション追加**

`src/context_store/embedding/local_model.py` の `__init__` で `dimension` のチェックを追加。

**Step 2: 全角括弧置換 (RUF003 対応)**

`src/context_store/embedding/local_model.py` および `tests/unit/test_embedding_local.py` 内の全角括弧を半角に置換。

**Step 3: テストを実行して成功を確認**

Run: `pytest tests/unit/test_embedding_local.py -v`

**Step 4: コミット**

```bash
git add src/context_store/embedding/local_model.py tests/unit/test_embedding_local.py
git commit -m "fix: add LocalModel dimension validation and fix RUF003 warnings"
```

---

### Task 5: フォーマット修正

**Files:**
- Modify: `src/context_store/config.py`
- Modify: `tests/unit/test_embedding_litellm.py`

**Step 1: Ruff フォーマット実行**

```bash
ruff format src/context_store/config.py tests/unit/test_embedding_litellm.py
```

**Step 2: コミット**

```bash
git add src/context_store/config.py tests/unit/test_embedding_litellm.py
git commit -m "style: apply ruff format to config.py and test_embedding_litellm.py"
```
