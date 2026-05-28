# Fix Tool Hiding Test Issues

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix code review issues in `tests/unit/test_build_app_hidden_tools.py` by decoupling from `UpstreamClient` and adding persistence verification.

**Architecture:** Use `upstream_override` to provide a dummy object in tests, and add a test case that manually invokes `replace_tools` on the app's registry to verify hidden tools are not lost.

**Tech Stack:** Python, pytest, FastAPI

---

### Task 1: Decouple existing tests from UpstreamClient

**Files:**
- Modify: `tests/unit/test_build_app_hidden_tools.py`

- [ ] **Step 1: Update `test_selective_mode_does_not_hide_memory_save` to use `upstream_override`**

```python
def test_selective_mode_does_not_hide_memory_save(
    monkeypatch: pytest.MonkeyPatch,
    policy_file: Path,
) -> None:
    monkeypatch.delenv("CHRONOS_INGESTION_MODE", raising=False)
    monkeypatch.setenv("MCP_GATEWAY_POLICY_PATH", str(policy_file))

    from mcp_gateway.app import build_app

    # Use upstream_override=object() to avoid side effects of UpstreamClient
    app = build_app(
        initial_tools=[{"name": "memory_save", "description": "x"}],
        upstream_override=object(),
    )
    registry = app.state.tool_registry

    names = [tool["name"] for tool in registry.all_tools]
    assert "memory_save" in names
```

- [ ] **Step 2: Update `test_all_mode_hides_memory_save` to use `upstream_override`**

```python
def test_all_mode_hides_memory_save(
    monkeypatch: pytest.MonkeyPatch,
    policy_file: Path,
) -> None:
    monkeypatch.setenv("CHRONOS_INGESTION_MODE", "all")
    monkeypatch.setenv("MCP_GATEWAY_POLICY_PATH", str(policy_file))

    from mcp_gateway.app import build_app

    # Use upstream_override=object() to avoid side effects of UpstreamClient
    app = build_app(
        initial_tools=[
            {"name": "memory_save", "description": "x"},
            {"name": "memory_save_url", "description": "y"},
        ],
        upstream_override=object(),
    )
    registry = app.state.tool_registry

    names = [tool["name"] for tool in registry.all_tools]
    assert "memory_save" not in names
    assert "memory_save_url" in names
```

- [ ] **Step 3: Run tests to verify they still pass**

Run: `pytest tests/unit/test_build_app_hidden_tools.py -v`
Expected: 2 PASS

- [ ] **Step 4: Commit changes**

```bash
git add tests/unit/test_build_app_hidden_tools.py
git commit -m "test: decouple build_app hidden tool tests from UpstreamClient"
```

### Task 2: Verify hidden tools persistence after replacement

**Files:**
- Modify: `tests/unit/test_build_app_hidden_tools.py`

- [ ] **Step 1: Add `test_hidden_tools_persists_after_replace` to `tests/unit/test_build_app_hidden_tools.py`**

```python
def test_hidden_tools_persists_after_replace(
    monkeypatch: pytest.MonkeyPatch,
    policy_file: Path,
) -> None:
    monkeypatch.setenv("CHRONOS_INGESTION_MODE", "all")
    monkeypatch.setenv("MCP_GATEWAY_POLICY_PATH", str(policy_file))

    from mcp_gateway.app import build_app

    app = build_app(
        initial_tools=[{"name": "memory_save", "description": "x"}],
        upstream_override=object(),
    )
    registry = app.state.tool_registry

    # Initial state check
    assert "memory_save" not in [t["name"] for t in registry.all_tools]

    # Simulate upstream providing new tools including the hidden one
    new_tools = [
        {"name": "memory_save", "description": "updated"},
        {"name": "other_tool", "description": "new"},
    ]
    registry.replace_tools(new_tools)

    # memory_save should still be hidden even after replacement
    names = [tool["name"] for tool in registry.all_tools]
    assert "memory_save" not in names
    assert "other_tool" in names
```

- [ ] **Step 2: Run all tests in the file**

Run: `pytest tests/unit/test_build_app_hidden_tools.py -v`
Expected: 3 PASS

- [ ] **Step 3: Commit changes**

```bash
git add tests/unit/test_build_app_hidden_tools.py
git commit -m "test: verify hidden tools persistence after replace_tools"
```
