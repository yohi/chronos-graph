from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _add_scripts_to_path(monkeypatch):
    scripts_path = str(Path(__file__).resolve().parents[2] / "scripts")
    monkeypatch.syspath_prepend(scripts_path)


@pytest.fixture(autouse=True)
def _mock_opensandbox_import():
    # Mock the top-level package and all submodules imported by sandbox_runner.
    # CI may not have 'opensandbox' installed as a proper package, so we stub
    # every dotted path the script imports at module level.
    #
    # RunCommandOpts uses a real dataclass-like factory via side_effect so that
    # each call produces a distinct object whose fields can be compared by value.
    # Without this, MagicMock.__call__ always returns the same return_value,
    # making opts= comparisons vacuously true regardless of the arguments passed.
    @dataclass
    class _RunCommandOpts:
        working_directory: str = ""
        envs: dict = field(default_factory=dict)

    @dataclass
    class _Host:
        path: str

    @dataclass
    class _NetworkRule:
        action: str
        target: str

    @dataclass
    class _NetworkPolicy:
        defaultAction: str = "deny"
        egress: list[_NetworkRule] | None = None

    @dataclass
    class _Volume:
        name: str
        host: _Host | None
        mountPath: str
        readOnly: bool = False

    mock_opensandbox = MagicMock()
    mock_config_sync = MagicMock()
    mock_models_execd = MagicMock()
    mock_models_sandboxes = MagicMock()
    mock_models_execd.RunCommandOpts.side_effect = _RunCommandOpts
    mock_models_sandboxes.Host = _Host
    mock_models_sandboxes.NetworkPolicy = _NetworkPolicy
    mock_models_sandboxes.NetworkRule = _NetworkRule
    mock_models_sandboxes.Volume = _Volume
    mock_modules = {
        "opensandbox": mock_opensandbox,
        "opensandbox.config": MagicMock(),
        "opensandbox.config.connection_sync": mock_config_sync,
        "opensandbox.models": MagicMock(),
        "opensandbox.models.execd": mock_models_execd,
        "opensandbox.models.sandboxes": mock_models_sandboxes,
    }
    with patch.dict("sys.modules", mock_modules):
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
        mock_sandbox = MagicMock()
        mock_sandbox.commands.run.return_value.exit_code = 0
        runner.install_dependencies(mock_sandbox, ["uv", "run", "pytest", "tests/unit/"])
        mock_sandbox.commands.run.assert_called_once_with(
            "uv sync --frozen --all-extras",
            opts=runner.RunCommandOpts(working_directory="/workspace"),
        )

    def test_frontend_keywords_trigger_pnpm_install(self, runner):
        mock_sandbox = MagicMock()
        mock_sandbox.commands.run.return_value.exit_code = 0
        runner.install_dependencies(
            mock_sandbox,
            ["bash", "-c", "cd frontend && pnpm lint"],
        )
        mock_sandbox.commands.run.assert_called_once_with(
            "bash -c 'cd /workspace/frontend && pnpm install --frozen-lockfile'",
            opts=runner.RunCommandOpts(working_directory="/workspace"),
        )

    def test_ruff_triggers_uv_sync(self, runner):
        mock_sandbox = MagicMock()
        mock_sandbox.commands.run.return_value.exit_code = 0
        runner.install_dependencies(mock_sandbox, ["ruff", "check", "src/"])
        mock_sandbox.commands.run.assert_called_once_with(
            "uv sync --frozen --all-extras",
            opts=runner.RunCommandOpts(working_directory="/workspace"),
        )

    def test_uv_sync_failure_raises_runtime_error(self, runner):
        mock_sandbox = MagicMock()
        mock_sandbox.commands.run.return_value.exit_code = 1
        with pytest.raises(RuntimeError, match=r"uv sync failed"):
            runner.install_dependencies(mock_sandbox, ["ruff", "check", "src/"])

    def test_pnpm_install_failure_raises_runtime_error(self, runner):
        mock_sandbox = MagicMock()
        mock_sandbox.commands.run.return_value.exit_code = 1
        with pytest.raises(RuntimeError, match=r"pnpm install failed"):
            runner.install_dependencies(
                mock_sandbox,
                ["bash", "-c", "cd frontend && pnpm lint"],
            )

    def test_no_matching_keywords(self, runner):
        mock_sandbox = MagicMock()
        runner.install_dependencies(mock_sandbox, ["echo", "hello"])
        mock_sandbox.commands.run.assert_not_called()


class TestSetupSandbox:
    def test_success_first_try(self, runner):
        mock_sandbox = MagicMock()
        mock_cfg = MagicMock()
        with patch.object(runner.SandboxSync, "create", return_value=mock_sandbox) as mock_create:
            result = runner.setup_sandbox(mock_cfg, "lite")
        assert result is mock_sandbox
        mock_create.assert_called_once_with(
            image=runner.PROFILE_IMAGES["lite"],
            env={"OPENSANDBOX": "1"},
            metadata={"profile": "lite"},
            resource={"cpu": "2", "memory": "2Gi"},
            network_policy=runner.NetworkPolicy(
                defaultAction="deny",
                egress=[
                    runner.NetworkRule(action="allow", target="pypi.org"),
                    runner.NetworkRule(action="allow", target="files.pythonhosted.org"),
                    runner.NetworkRule(action="allow", target="registry.npmjs.org"),
                ],
            ),
            volumes=[
                runner.Volume(
                    name="workspace",
                    host=runner.Host(path=runner.resolve_project_root()),
                    mountPath="/workspace",
                    readOnly=False,
                )
            ],
            connection_config=mock_cfg,
        )

    def test_integration_profile_expands_db_env_and_network_policy(self, runner, monkeypatch):
        monkeypatch.delenv("TEST_DB_HOST", raising=False)
        monkeypatch.delenv("TEST_DB_PORT", raising=False)
        monkeypatch.delenv("TEST_DB_NAME", raising=False)
        monkeypatch.delenv("TEST_DB_USER", raising=False)
        monkeypatch.delenv("TEST_DB_PASSWORD", raising=False)
        monkeypatch.delenv("TEST_NEO4J_URI", raising=False)
        monkeypatch.delenv("TEST_NEO4J_USER", raising=False)
        monkeypatch.delenv("TEST_NEO4J_PASSWORD", raising=False)
        monkeypatch.delenv("TEST_REDIS_URL", raising=False)

        mock_sandbox = MagicMock()
        mock_cfg = MagicMock()
        with patch.object(runner.SandboxSync, "create", return_value=mock_sandbox) as mock_create:
            result = runner.setup_sandbox(mock_cfg, "integration")

        assert result is mock_sandbox
        mock_create.assert_called_once_with(
            image=runner.PROFILE_IMAGES["integration"],
            env={
                "OPENSANDBOX": "1",
                "POSTGRES_HOST": "host.docker.internal",
                "POSTGRES_PORT": "5435",
                "POSTGRES_DB": "context_store_test",
                "POSTGRES_USER": "context_store",
                "POSTGRES_PASSWORD": "dev_password",
                "NEO4J_URI": "bolt://host.docker.internal:7687",
                "NEO4J_USER": "neo4j",
                "NEO4J_PASSWORD": "dev_password",
                "REDIS_URL": "redis://host.docker.internal:6379/1",
            },
            metadata={"profile": "integration"},
            resource={"cpu": "2", "memory": "2Gi"},
            network_policy=runner.NetworkPolicy(
                defaultAction="deny",
                egress=[
                    runner.NetworkRule(action="allow", target="pypi.org"),
                    runner.NetworkRule(action="allow", target="files.pythonhosted.org"),
                    runner.NetworkRule(action="allow", target="registry.npmjs.org"),
                    runner.NetworkRule(action="allow", target="host.docker.internal"),
                ],
            ),
            volumes=[
                runner.Volume(
                    name="workspace",
                    host=runner.Host(path=runner.resolve_project_root()),
                    mountPath="/workspace",
                    readOnly=False,
                )
            ],
            connection_config=mock_cfg,
        )

    def test_retry_on_pool_exhaustion(self, runner):
        mock_sandbox = MagicMock()
        mock_cfg = MagicMock()
        with patch.object(
            runner.SandboxSync,
            "create",
            side_effect=[RuntimeError("pool exhausted"), mock_sandbox],
        ) as mock_create:
            with patch("sandbox_runner.time.sleep"):
                result = runner.setup_sandbox(mock_cfg, "lite")
        assert result is mock_sandbox
        assert mock_create.call_count == 2

    def test_raises_after_max_retries(self, runner):
        mock_cfg = MagicMock()
        with patch.object(
            runner.SandboxSync,
            "create",
            side_effect=RuntimeError("pool exhausted"),
        ) as mock_create:
            with patch("sandbox_runner.time.sleep"), pytest.raises(RuntimeError, match="pool"):
                runner.setup_sandbox(mock_cfg, "lite")
        assert mock_create.call_count == runner.MAX_RETRIES + 1


class TestExecuteInSandbox:
    def test_direct_python_tool_commands_run_through_uv(self, runner):
        mock_sandbox = MagicMock()
        mock_sandbox.commands.run.return_value.exit_code = 0

        runner.execute_in_sandbox(mock_sandbox, ["ruff", "check", "src/"])

        mock_sandbox.commands.run.assert_called_once_with(
            "uv run ruff check src/",
            opts=runner.RunCommandOpts(
                working_directory="/workspace",
                envs={"OPENSANDBOX": "1"},
            ),
        )

    def test_execute_forwards_stdout_and_stderr(self, runner, capsys):
        mock_sandbox = MagicMock()
        mock_sandbox.commands.run.return_value.exit_code = 0
        mock_sandbox.commands.run.return_value.stdout = "command output\n"
        mock_sandbox.commands.run.return_value.stderr = "command warning\n"

        exit_code = runner.execute_in_sandbox(mock_sandbox, ["echo", "test"])

        captured = capsys.readouterr()
        assert exit_code == 0
        assert captured.out == "command output\n"
        assert captured.err == "command warning\n"

    def test_execute_parameters_and_exit_code_propagation(self, runner):
        mock_sandbox = MagicMock()
        mock_sandbox.commands.run.return_value.exit_code = 42

        exit_code = runner.execute_in_sandbox(
            mock_sandbox,
            ["echo", "test"],
            working_dir="/workspace/subdir",
        )

        assert exit_code == 42
        mock_sandbox.commands.run.assert_called_once_with(
            "echo test",
            opts=runner.RunCommandOpts(
                working_directory="/workspace/subdir",
                envs={"OPENSANDBOX": "1"},
            ),
        )

    def test_execute_default_working_dir(self, runner):
        mock_sandbox = MagicMock()
        mock_sandbox.commands.run.return_value.exit_code = 0

        runner.execute_in_sandbox(mock_sandbox, ["echo", "test"])

        mock_sandbox.commands.run.assert_called_once_with(
            "echo test",
            opts=runner.RunCommandOpts(
                working_directory="/workspace",
                envs={"OPENSANDBOX": "1"},
            ),
        )


class TestTeardownSandbox:
    def test_successful_teardown(self, runner):
        mock_sandbox = MagicMock()
        runner.teardown_sandbox(mock_sandbox)
        mock_sandbox.kill.assert_called_once_with()

    def test_teardown_failure_does_not_raise(self, runner, capsys):
        mock_sandbox = MagicMock()
        mock_sandbox.kill.side_effect = RuntimeError("kill failed")
        mock_sandbox.id = "sandbox-123"
        runner.teardown_sandbox(mock_sandbox)
        captured = capsys.readouterr()
        assert "Warning" in captured.err
        assert "kill failed" in captured.err


class TestValidateDbHostConsistency:
    def test_all_default_hosts_match(self, runner, monkeypatch):
        monkeypatch.delenv("TEST_DB_HOST", raising=False)
        monkeypatch.delenv("TEST_NEO4J_URI", raising=False)
        monkeypatch.delenv("TEST_REDIS_URL", raising=False)

        env = runner.build_profile_env("integration")
        runner._validate_db_host_consistency(env)

    def test_all_custom_hosts_match(self, runner, monkeypatch):
        monkeypatch.setenv("TEST_DB_HOST", "my-host")
        monkeypatch.setenv("TEST_NEO4J_URI", "bolt://my-host:7687")
        monkeypatch.setenv("TEST_REDIS_URL", "redis://my-host:6379/1")

        env = runner.build_profile_env("integration")
        runner._validate_db_host_consistency(env)

    def test_mismatch_postgres_neo4j_raises(self, runner, monkeypatch):
        monkeypatch.setenv("TEST_DB_HOST", "pg-host")
        monkeypatch.setenv("TEST_NEO4J_URI", "bolt://neo4j-host:7687")
        monkeypatch.setenv("TEST_REDIS_URL", "redis://pg-host:6379/1")

        with pytest.raises(ValueError, match="Integration profile requires all DB hosts to match"):
            runner.build_profile_env("integration")

    def test_mismatch_postgres_redis_raises(self, runner, monkeypatch):
        monkeypatch.setenv("TEST_DB_HOST", "pg-host")
        monkeypatch.setenv("TEST_NEO4J_URI", "bolt://pg-host:7687")
        monkeypatch.setenv("TEST_REDIS_URL", "redis://redis-host:6379/1")

        with pytest.raises(ValueError, match="Integration profile requires all DB hosts to match"):
            runner.build_profile_env("integration")

    def test_build_profile_env_validates_via_integration(self, runner, monkeypatch):
        monkeypatch.setenv("TEST_DB_HOST", "pg-host")
        monkeypatch.setenv("TEST_NEO4J_URI", "bolt://pg-host:7687")
        monkeypatch.setenv("TEST_REDIS_URL", "redis://pg-host:6379/1")

        env = runner.build_profile_env("integration")
        assert env["POSTGRES_HOST"] == "pg-host"
        assert env["NEO4J_URI"] == "bolt://pg-host:7687"
        assert env["REDIS_URL"] == "redis://pg-host:6379/1"
