# 未使用インポートと警告のクリーンアップ 実装プラン

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** テストコードから未使用のインポートや変数を削除し、警告を解消する。

**Architecture:** 
- `tests/unit/test_embedding_local.py` の未使用変数を `_provider` に変更する。
- `tests/unit/test_embedding.py` は既に `TokenCounter` が削除されているため、現状維持（または必要に応じて再確認）。

**Tech Stack:** 
- Python 3.12
- pytest
- ruff

---

### Task 1: `tests/unit/test_embedding_local.py` の未使用変数修正

**Files:**
- Modify: `tests/unit/test_embedding_local.py:50`

**Step 1: 修正前の状態確認**

Run: `cat -n tests/unit/test_embedding_local.py | sed -n '50p'`
Expected: `50              provider = LocalModelEmbeddingProvider(model_name="test-model")`

**Step 2: 変数名を `_provider` に変更**

```python
<<<<
            provider = LocalModelEmbeddingProvider(model_name="test-model")
====
            _provider = LocalModelEmbeddingProvider(model_name="test-model")
>>>>
```

**Step 3: 修正後のテスト実行**

Run: `uv run pytest tests/unit/test_embedding_local.py -v`
Expected: PASS

### Task 2: `tests/unit/test_embedding.py` の再確認

**Files:**
- Modify: `tests/unit/test_embedding.py` (必要であれば)

**Step 1: `TokenCounter` の存在を再確認**

Run: `grep "TokenCounter" tests/unit/test_embedding.py`
Expected: 空 (もし存在していれば削除する)
