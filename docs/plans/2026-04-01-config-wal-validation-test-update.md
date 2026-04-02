# Config WAL Validation Test Update Implementation Plan

**Goal:** Add missing WAL-related numeric boundary cases to the configuration
validation tests.

**Architecture:** Update the existing parametrized test
`test_numeric_settings_reject_out_of_range_values` in
`tests/unit/test_config.py`.

**Tech Stack:** Python, Pytest, Pydantic (Settings)

---

## Task 1: Update Test Parametrization

**Files:**

- Modify: `tests/unit/test_config.py`

### Step 1: Write the updated test cases

Add the following entries to the `parametrize` list in
`test_numeric_settings_reject_out_of_range_values`:

- `("wal_truncate_size_bytes", -1)`
- `("wal_passive_fail_consecutive_threshold", 0)`
- `("wal_passive_fail_window_count_threshold", 0)`

### Step 2: Run test to verify it passes

Verify with `pytest tests/unit/test_config.py`.
Expected: ALL PASS (including the newly added cases).
