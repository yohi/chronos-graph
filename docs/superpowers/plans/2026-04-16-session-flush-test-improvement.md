# session_flush test improvement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve test robustness in `tests/unit/test_session_flush_tools.py` by verifying the specific error message returned by the mock.

**Architecture:** Update the assertion in `test_session_flush_empty_log_returns_error` to compare the `error` field value against the expected string.

**Tech Stack:** Python, pytest

---

## Task 1: Verify current tests

**Files:**
- Test: `tests/unit/test_session_flush_tools.py`

### Step 1: Run existing unit tests to ensure baseline is green

Run: `uv run pytest tests/unit/test_session_flush_tools.py -v`
Expected: PASS

---

## Task 2: Improve assertion specificity

**Files:**
- Modify: `tests/unit/test_session_flush_tools.py:75-76`

### Step 1: Update the assertion to check for specific error message

```python
        result = json.loads(result_str)
        assert result["error"] == "conversation_log must not be empty"
```

### Step 2: Run the test to verify it passes with the stricter assertion

Run: `uv run pytest tests/unit/test_session_flush_tools.py -v`
Expected: PASS

### Step 3: Commit the change

```bash
git add tests/unit/test_session_flush_tools.py
git commit -m "test: improve assertion specificity in session_flush tool test"
```
