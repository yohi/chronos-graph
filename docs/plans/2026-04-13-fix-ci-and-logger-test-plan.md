# Fix CI and Logger Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore GitHub Actions CI by fixing the `setup-uv` SHA and fix the failing logger unit test.

**Architecture:** Update CI configuration to use a valid action version and adjust the logger test to use a non-reserved field for serialization verification.

**Tech Stack:** GitHub Actions, Python, pytest

---

### Task 1: Fix CI Workflow

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Update setup-uv SHA**

Replace the invalid SHA with the correct one for `v5.3.0`.

```yaml
<<<<
      - name: Install uv
        uses: astral-sh/setup-uv@f986551839d10c000263e2f5fd59750083519b96 # v5.3.0
====
      - name: Install uv
        uses: astral-sh/setup-uv@8830571d65107811586634a4d3f788f9d47330da # v5.3.0
>>>>
```

- [ ] **Step 2: Commit changes**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: fix invalid SHA for setup-uv action"
```

---

### Task 2: Fix Logger Unit Test

**Files:**
- Modify: `tests/unit/test_logger.py:60-76`

- [ ] **Step 1: Write the failing test (Verify failure)**

Run the existing test to confirm it fails as expected.

Run: `uv run pytest tests/unit/test_logger.py::test_context_serializes_non_json_values -v`
Expected: FAIL (AssertionError: timestamp mismatch)

- [ ] **Step 2: Update test case to use non-reserved field**

Modify the test to use `event_time` instead of `timestamp`.

```python
def test_context_serializes_non_json_values(capsys):
    clear_context()
    uid = uuid4()
    # Use 'event_time' instead of 'timestamp' which is now a reserved field
    set_context(event_time=datetime(2026, 4, 1, 12, 34, 56), uid=uid, custom=object())
    logger = get_logger("test_non_json_context")
    logger.info("serialized context")

    captured = capsys.readouterr()
    output = json.loads(captured.out)

    assert output["event_time"] == "2026-04-01T12:34:56"
    assert output["uid"] == str(uid)
    assert isinstance(output["custom"], str)
    clear_context()
```

- [ ] **Step 3: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_logger.py::test_context_serializes_non_json_values -v`
Expected: PASS

- [ ] **Step 4: Commit changes**

```bash
git add tests/unit/test_logger.py
git commit -m "test(logger): fix context serialization test to use non-reserved field"
```
