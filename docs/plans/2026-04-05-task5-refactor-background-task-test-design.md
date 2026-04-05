# Design Doc: Task 5 - Refactor Background Task Test

## 1. Goal
Refactor `test_spawn_background_task_no_leak` in `tests/unit/test_lifecycle_manager.py` to use a `MagicMock` or `AsyncMock` as a spy instead of a boolean flag. This improves consistency and follows standard testing practices.

## 2. Approach
Use `AsyncMock` for `task_factory` to verify it is not called when the manager is shutting down.

### Architecture
- **Component**: `tests/unit/test_lifecycle_manager.py`
- **Logic**: 
  - Initialize `LifecycleManager` with mocks.
  - Set `manager._shutting_down = True`.
  - Replace the local `called` flag and `dummy_task` coroutine with an `AsyncMock`.
  - Invoke `_spawn_background_task(task_factory)`.
  - Assert `task_factory.assert_not_called()`.

## 3. Data Flow
1. `LifecycleManager` is instantiated.
2. `_shutting_down` state is modified.
3. `AsyncMock` is passed as a factory.
4. `_spawn_background_task` checks `_shutting_down` and returns early.
5. Mock assertion verifies no interaction.

## 4. Testing
- Verify the test passes using `pytest`.
