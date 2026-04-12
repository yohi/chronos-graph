# Design: Fix CI and Logger Test Failure

## Background
PR #53 introduced new dashboard backend features, including enhanced logging with a circular buffer and a specific `timestamp` field in `src/context_store/logger.py`.
However, this caused the following issues:
1.  **CI Failure**: The GitHub Actions workflow is failing at the setup step because the commit SHA for `astral-sh/setup-uv` is invalid.
2.  **Logger Test Failure**: `tests/unit/test_logger.py` fails because it expects to overwrite the `timestamp` field via context, which is now a reserved field always populated by the logger with the current system time.

## Proposed Changes

### 1. Fix CI Workflow (`.github/workflows/ci.yml`)
- Update the `astral-sh/setup-uv` action's SHA to the correct one for `v5.3.0`.
- **Target SHA**: `8830571d65107811586634a4d3f788f9d47330da`

### 2. Fix Logger Unit Test (`tests/unit/test_logger.py`)
- Modify `test_context_serializes_non_json_values` to use a non-reserved field for testing context serialization.
- Change `timestamp` to `event_time` in the test case.
- This ensures the test verifies context serialization logic without conflicting with the logger's reserved `timestamp` field.

## Verification Strategy
- **Local**: Run `uv run pytest tests/unit/test_logger.py` to ensure the test passes.
- **CI**: Push changes and verify that GitHub Actions successfully runs the `test` job.
