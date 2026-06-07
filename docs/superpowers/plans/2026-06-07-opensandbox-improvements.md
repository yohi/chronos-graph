# OpenSandbox Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix sandbox dependencies, Docker safety issues, environment configurations, and add unit test coverage for sandbox runner execution.

**Architecture:** Use multi-stage Docker builds to securely copy Node.js binaries instead of unsafe curl pipelines, use pytest monkeypatch to prevent global sys.path leaks, check subprocess exit codes for dependency installation steps, and document/prevent security & fallback risks.

**Tech Stack:** Docker, Python (pytest, opensandbox client), Docker Compose, YAML

---

### Task 1: Dockerfile Improvements
**Files:**
- Modify: `.devcontainer/opensandbox/lite.Dockerfile`

- [ ] **Step 1: Update the Dockerfile to use pinned versions and multi-stage Node.js copying**
  Modify `.devcontainer/opensandbox/lite.Dockerfile` to pin `uv` to `0.5.0` (or another stable version), use multi-stage build `node:22.11.0-slim` to copy Node.js binaries, and pin `pnpm` to `9.15.4`.

  ```dockerfile
  # syntax=docker/dockerfile:1
  FROM node:22.11.0-slim AS node_source
  FROM python:3.12-slim

  ENV PYTHONDONTWRITEBYTECODE=1 \
      PYTHONUNBUFFERED=1 \
      UV_PROJECT_ENVIRONMENT=/tmp/.venv

  COPY --from=ghcr.io/astral-sh/uv:0.5.0 /uv /usr/local/bin/uv
  COPY --from=ghcr.io/astral-sh/uv:0.5.0 /uvx /usr/local/bin/uvx

  # Copy Node.js from node_source instead of downloading via curl | bash
  COPY --from=node_source /usr/local/bin/node /usr/local/bin/node
  COPY --from=node_source /usr/local/lib/node_modules /usr/local/lib/node_modules
  RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm

  RUN apt-get update && apt-get install -y --no-install-recommends \
          ca-certificates \
      && corepack enable && corepack prepare pnpm@9.15.4 --activate \
      && rm -rf /var/lib/apt/lists/*

  RUN groupadd -g 1000 sandbox && \
      useradd -m -u 1000 -g sandbox -s /bin/bash sandbox
  USER sandbox

  WORKDIR /workspace
  CMD ["bash"]
  ```

---

### Task 2: Sandbox Runner Error Handling
**Files:**
- Modify: `scripts/sandbox_runner.py:41-48`

- [ ] **Step 1: Modify `install_dependencies` to check execution exit codes**
  Modify `scripts/sandbox_runner.py` so that it captures the return value of `client.execute()` and raises a `RuntimeError` if the exit code is non-zero.

  ```python
  def install_dependencies(
      client: SandboxClient,
      sandbox_id: str,
      command: list[str],
  ) -> None:
      """Install project dependencies based on the command context."""
      cmd_str = " ".join(command)

      if any(kw in cmd_str for kw in ["ruff", "mypy", "pytest", "uv"]):
          result = client.execute(sandbox_id, ["uv", "sync", "--frozen", "--all-extras"])
          if result.exit_code != 0:
              raise RuntimeError(f"[sandbox] uv sync failed (exit {result.exit_code})")

      if any(kw in cmd_str for kw in ["pnpm", "tsc", "eslint", "frontend"]):
          result = client.execute(
              sandbox_id,
              ["bash", "-c", "cd /workspace/frontend && pnpm install --frozen-lockfile"],
          )
          if result.exit_code != 0:
              raise RuntimeError(f"[sandbox] pnpm install failed (exit {result.exit_code})")
  ```

---

### Task 3: Security comments & YAML Defaults
**Files:**
- Modify: `docker-compose.yml`
- Modify: `.devcontainer/opensandbox/sandbox.yaml`

- [ ] **Step 1: Add a security warning comment to docker-compose.yml**
  Add a comment explaining the privilege escalation risk of mounting `/var/run/docker.sock` in `docker-compose.yml` around line 115.
  
  ```yaml
      # WARNING: Mounting docker.sock allows container escape / privilege escalation.
      # This service is protected by 'profiles: [sandbox]' and only run when debugging sandboxes.
      volumes:
        - /var/run/docker.sock:/var/run/docker.sock
  ```

- [ ] **Step 2: Add fallback defaults for postgres and neo4j environment variables in sandbox.yaml**
  Set fallbacks for `POSTGRES_PASSWORD` and `NEO4J_AUTH` in `.devcontainer/opensandbox/sandbox.yaml`.

  ```yaml
        POSTGRES_PASSWORD: "${TEST_DB_PASSWORD:-dev_password}"
        NEO4J_URI: "${TEST_NEO4J_URI:-bolt://host.docker.internal:7687}"
        NEO4J_AUTH: "${TEST_NEO4J_AUTH:-neo4j/dev_password}"
  ```

---

### Task 4: Unit Test Adjustments and New Contract Test
**Files:**
- Modify: `tests/unit/test_sandbox_runner.py`

- [ ] **Step 1: Use pytest monkeypatch fixture to scope sys.path modification**
  Remove the global `sys.path.insert(0, ...)` at the top level and prepend the scripts path inside an autouse fixture using `monkeypatch.syspath_prepend`.

  ```python
  @pytest.fixture(scope="session", autouse=True)
  def _setup_sys_path(pytestconfig):
      # We can use a session-scoped or module-scoped monkeypatch or modify sys.path within fixture
      import sys
      from pathlib import Path
      scripts_path = str(Path(__file__).resolve().parents[2] / "scripts")
      if scripts_path not in sys.path:
          sys.path.insert(0, scripts_path)
  ```

- [ ] **Step 2: Add contract tests for `execute_in_sandbox`**
  Add a test class `TestExecuteInSandbox` inside `tests/unit/test_sandbox_runner.py` verifying that `execute_in_sandbox` passes correct parameters (environment and working directory) and propagates the exit code.

  ```python
  class TestExecuteInSandbox:
      """execute_in_sandbox() のテスト。"""

      def test_execute_in_sandbox_passes_params(self):
          runner = _import_runner()
          mock_client = MagicMock()
          mock_result = MagicMock()
          mock_result.exit_code = 42
          mock_client.execute.return_value = mock_result

          exit_code = runner.execute_in_sandbox(
              mock_client,
              "sandbox-123",
              ["pytest", "tests/unit/"],
              working_dir="/workspace/custom"
          )

          assert exit_code == 42
          mock_client.execute.assert_called_once_with(
              "sandbox-123",
              ["pytest", "tests/unit/"],
              working_dir="/workspace/custom",
              stream=True,
              env={"OPENSANDBOX": "1"}
          )
  ```

- [ ] **Step 3: Run unit tests inside the devcontainer**
  Run pytest to verify the changes:
  `uv run pytest tests/unit/test_sandbox_runner.py -v`
