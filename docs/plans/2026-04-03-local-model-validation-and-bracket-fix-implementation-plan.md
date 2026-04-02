# Local Model Validation and Bracket Fix Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement dimension validation for LocalModelEmbeddingProvider and fix RUF003 warnings by replacing full-width parentheses with half-width ones.

**Architecture:** Update the `__init__` method of `LocalModelEmbeddingProvider` to assert that `dimension` is a positive integer if provided. Clean up comments and docstrings in both source and test files to comply with Ruff linting rules.

**Tech Stack:** Python 3.12, pytest, ruff

---

### Task 1: Add dimension validation to LocalModelEmbeddingProvider

**Files:**
- Modify: `src/context_store/embedding/local_model.py`

**Step 1: Write the failing test**

Modify `tests/unit/test_embedding_local.py` to add a test case for invalid dimension.

```python
    def test_invalid_dimension(self) -> None:
        from context_store.embedding.local_model import LocalModelEmbeddingProvider
        
        with pytest.raises(ValueError, match="dimension must be a positive integer"):
            LocalModelEmbeddingProvider(dimension=-1)
            
        with pytest.raises(ValueError, match="dimension must be a positive integer"):
            LocalModelEmbeddingProvider(dimension=0)
            
        with pytest.raises(ValueError, match="dimension must be a positive integer"):
            LocalModelEmbeddingProvider(dimension="768")  # type: ignore
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_embedding_local.py::TestLocalModelEmbeddingProvider::test_invalid_dimension -v`
Expected: FAIL (AttributeError or similar because ValueError is not raised)

**Step 3: Implement validation in LocalModelEmbeddingProvider.__init__**

```python
    def __init__(
        self,
        model_name: str = _DEFAULT_MODEL_NAME,
        dimension: int | None = None,
    ) -> None:
        if dimension is not None:
            if not isinstance(dimension, int) or dimension <= 0:
                raise ValueError(f"dimension must be a positive integer, got {dimension}")

        self._model_name = model_name
        self._model: Any = None
        self._dimension: int | None = dimension
        self._model_lock = threading.Lock()
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_embedding_local.py::TestLocalModelEmbeddingProvider::test_invalid_dimension -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/context_store/embedding/local_model.py tests/unit/test_embedding_local.py
git commit -m "feat: add dimension validation to LocalModelEmbeddingProvider"
```

### Task 2: Fix RUF003 warnings (replace full-width brackets)

**Files:**
- Modify: `src/context_store/embedding/local_model.py`
- Modify: `tests/unit/test_embedding_local.py`

**Step 1: Replace brackets in src/context_store/embedding/local_model.py**

Replace `（` and `）` with `(` and `)`.

**Step 2: Replace brackets in tests/unit/test_embedding_local.py**

Replace `（` and `）` with `(` and `)`.

**Step 3: Run ruff to verify fixes**

Run: `uv run ruff check src/context_store/embedding/local_model.py tests/unit/test_embedding_local.py`
(If `uv` is not available, use `python -m ruff check`)
Expected: No RUF003 warnings.

**Step 4: Run all tests in test_embedding_local.py**

Run: `pytest tests/unit/test_embedding_local.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/context_store/embedding/local_model.py tests/unit/test_embedding_local.py
git commit -m "fix: replace full-width parentheses with ASCII ones to satisfy RUF003"
```
