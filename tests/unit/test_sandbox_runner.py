from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _add_scripts_to_path(monkeypatch):
    scripts_path = str(Path(__file__).resolve().parents[2] / "scripts")
    monkeypatch.syspath_prepend(scripts_path)


@pytest.fixture(autouse=True)
def _mock_opensandbox_import():
    mock_module = MagicMock()
    mock_module.SandboxClient = MagicMock
    with patch.dict("sys.modules", {"opensandbox": mock_module}):
        yield


def _import_runner():
    import importlib

    if "sandbox_runner" in sys.modules:
        return importlib.reload(sys.modules["sandbox_runner"])
    return importlib.import_module("sandbox_runner")


@pytest.fixture
def runner():
    return _import_runner()


class TestResolveProfile:
    def test_default_profile(self, runner):
        result = runner.resolve_profile(["ruff", "check", "src/"], None)
        assert result == "lite"

    def test_integration_path(self, runner):
        result = runner.resolve_profile(["uv", "run", "pytest", "tests/integration/", "-v"], None)
        assert result == "integration"

    def test_integration_test_postgres(self, runner):
        result = runner.resolve_profile(
            ["uv", "run", "pytest", "tests/unit/test_postgres.py"], None
        )
        assert result == "integration"

    def test_integration_test_neo4j(self, runner):
        result = runner.resolve_profile(["uv", "run", "pytest", "tests/unit/test_neo4j.py"], None)
        assert result == "integration"

    def test_integration_test_redis(self, runner):
        result = runner.resolve_profile(["uv", "run", "pytest", "tests/unit/test_redis.py"], None)
        assert result == "integration"

    def test_explicit_override(self, runner):
        result = runner.resolve_profile(["ruff", "check", "src/"], "integration")
        assert result == "integration"

    def test_explicit_override_lite(self, runner):
        result = runner.resolve_profile(["uv", "run", "pytest", "tests/integration/"], "lite")
        assert result == "lite"


class TestInstallDependencies:
    def test_python_keywords_trigger_uv_sync(self, runner):
        mock_client = MagicMock()
        mock_client.execute.return_value.exit_code = 0
        runner.install_dependencies(
            mock_client, "sandbox-123", ["uv", "run", "pytest", "tests/unit/"]
        )
        mock_client.execute.assert_called_once_with(
            "sandbox-123", ["uv", "sync", "--frozen", "--all-extras"]
        )

    def test_frontend_keywords_trigger_pnpm_install(self, runner):
        mock_client = MagicMock()
        mock_client.execute.return_value.exit_code = 0
        runner.install_dependencies(
            mock_client,
            "sandbox-123",
            ["bash", "-c", "cd frontend && pnpm lint"],
        )
        mock_client.execute.assert_called_once_with(
            "sandbox-123",
            ["bash", "-c", "cd /workspace/frontend && pnpm install --frozen-lockfile"],
        )

    def test_ruff_triggers_uv_sync(self, runner):
        mock_client = MagicMock()
        mock_client.execute.return_value.exit_code = 0
        runner.install_dependencies(mock_client, "sandbox-123", ["ruff", "check", "src/"])
        mock_client.execute.assert_called_once_with(
            "sandbox-123", ["uv", "sync", "--frozen", "--all-extras"]
        )

    def test_uv_sync_failure_raises_runtime_error(self, runner):
        mock_client = MagicMock()
        mock_client.execute.return_value.exit_code = 1
        with pytest.raises(RuntimeError, match=r"uv sync failed"):
            runner.install_dependencies(mock_client, "sandbox-123", ["ruff", "check", "src/"])

    def test_pnpm_install_failure_raises_runtime_error(self, runner):
        mock_client = MagicMock()
        mock_client.execute.return_value.exit_code = 1
        with pytest.raises(RuntimeError, match=r"pnpm install failed"):
            runner.install_dependencies(
                mock_client,
                "sandbox-123",
                ["bash", "-c", "cd frontend && pnpm lint"],
            )

    def test_no_matching_keywords(self, runner):
        mock_client = MagicMock()
        runner.install_dependencies(mock_client, "sandbox-123", ["echo", "hello"])
        mock_client.execute.assert_not_called()


class TestSetupSandbox:
    def test_success_first_try(self, runner):
        mock_client = MagicMock()
        mock_client.create.return_value = "sandbox-abc"
        result = runner.setup_sandbox(mock_client, "lite")
        assert result == "sandbox-abc"
        mock_client.create.assert_called_once_with(profile="lite")

    def test_retry_on_pool_exhaustion(self, runner):
        mock_client = MagicMock()
        mock_client.create.side_effect = [
            RuntimeError("pool exhausted"),
            "sandbox-xyz",
        ]
        with patch("sandbox_runner.time.sleep"):
            result = runner.setup_sandbox(mock_client, "lite")
        assert result == "sandbox-xyz"
        assert mock_client.create.call_count == 2

    def test_raises_after_max_retries(self, runner):
        mock_client = MagicMock()
        mock_client.create.side_effect = RuntimeError("pool exhausted")
        with patch("sandbox_runner.time.sleep"), pytest.raises(RuntimeError, match="pool"):
            runner.setup_sandbox(mock_client, "lite")
        assert mock_client.create.call_count == runner.MAX_RETRIES + 1


class TestExecuteInSandbox:
    def test_execute_parameters_and_exit_code_propagation(self, runner):
        mock_client = MagicMock()
        mock_client.execute.return_value.exit_code = 42

        exit_code = runner.execute_in_sandbox(
            mock_client,
            "sandbox-123",
            ["echo", "test"],
            working_dir="/workspace/subdir",
        )

        assert exit_code == 42
        mock_client.execute.assert_called_once_with(
            "sandbox-123",
            ["echo", "test"],
            working_dir="/workspace/subdir",
            stream=True,
            env={"OPENSANDBOX": "1"},
        )

    def test_execute_default_working_dir(self, runner):
        mock_client = MagicMock()
        mock_client.execute.return_value.exit_code = 0

        runner.execute_in_sandbox(
            mock_client,
            "sandbox-123",
            ["echo", "test"],
        )

        mock_client.execute.assert_called_once_with(
            "sandbox-123",
            ["echo", "test"],
            working_dir="/workspace",
            stream=True,
            env={"OPENSANDBOX": "1"},
        )


class TestTeardownSandbox:
    def test_successful_teardown(self, runner):
        mock_client = MagicMock()
        runner.teardown_sandbox(mock_client, "sandbox-123")
        mock_client.destroy.assert_called_once_with("sandbox-123")

    def test_teardown_failure_does_not_raise(self, runner, capsys):
        mock_client = MagicMock()
        mock_client.destroy.side_effect = RuntimeError("destroy failed")
        runner.teardown_sandbox(mock_client, "sandbox-123")
        captured = capsys.readouterr()
        assert "Warning" in captured.err
        assert "destroy failed" in captured.err
