# Design Document: Update Pre-commit Hooks

## Status
Proposed

## Context
Current Git hooks are configured to run linting and formatting only at the `pre-push` stage. This delays feedback on code quality until the push attempt. We want to move these checks to the `pre-commit` stage for faster feedback.

## Requirements
- Move `ruff-check`, `ruff-format-check`, and `mypy` from `pre-push` to `pre-commit`.
- Use standard `pre-commit` behavior for `ruff` (checking only modified files).
- Keep `mypy` checking the entire `src/` directory to ensure type consistency across the project.

## Proposed Changes

### 1. Update `.pre-commit-config.yaml`
Modify each hook definition:
- Remove `stages: [pre-push]` to use the default `pre-commit` stage.
- Update `ruff-check` and `ruff-format-check` entries to remove explicit directory arguments, allowing `pre-commit` to pass only modified files.
- Keep `mypy` entry as `mypy src/` with `pass_filenames: false` to ensure full project context.

## Success Criteria
- Running `pre-commit run --all-files` passes correctly.
- Committing a file triggers the checks.
- `ruff` checks only the committed files (indicated by `pre-commit` logs).
- `mypy` checks the entire `src/` directory.

## Implementation Plan
1. Update `.pre-commit-config.yaml` as described.
2. Run `pre-commit install` (or ensure it's installed) to update local hooks.
3. Verify with `pre-commit run --all-files`.
