from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Final

from .models import AgentId, PlannedAction, PlannedTarget, SyncRequest
from .preflight_errors import PreflightCollisionError

OPENCODE_PLUGIN: Final = "@yohi/opencode-plugin-chronos-turn-end"
_POSIX_MARKER: Final = b"# chronosgraph-managed: turn-hook-wrapper format=1"
_WINDOWS_MARKER: Final = b"rem chronosgraph-managed: turn-hook-wrapper format=1"
_METADATA_URL: Final = "https://npm.pkg.github.com/@yohi%2fopencode-plugin-chronos-turn-end"


class HookConfigCollision(PreflightCollisionError):
    pass


class PluginRegistryPrerequisiteError(RuntimeError):
    def __init__(self, category: str) -> None:
        self.category = category
        super().__init__(category)


def updated_plugin_config(original: bytes | None) -> bytes:
    try:
        config = {} if original is None else json.loads(original.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HookConfigCollision(Path("opencode.json"), "opencode-json") from error
    if not isinstance(config, dict):
        raise HookConfigCollision(Path("opencode.json"), "opencode-config-root")
    plugin = config.get("plugin", [])
    if not isinstance(plugin, list) or not all(isinstance(entry, str) for entry in plugin):
        raise HookConfigCollision(Path("opencode.json"), "opencode-plugin-list")
    if OPENCODE_PLUGIN not in plugin:
        plugin = [*plugin, OPENCODE_PLUGIN]
    config["plugin"] = plugin
    return (json.dumps(config, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def plan_hook_targets(request: SyncRequest) -> tuple[PlannedTarget, ...]:
    if request.ingestion_mode.value != "all":
        return ()
    targets: list[PlannedTarget] = []
    if {AgentId.CLAUDECODE, AgentId.CODEX}.intersection(request.agent_ids):
        targets.append(_plan_wrapper(request.repo_root))
    if AgentId.OPENCODE in request.agent_ids:
        _validate_plugin_registry(request.home)
        targets.append(_plan_opencode_config(request.home))
    return tuple(targets)


def _plan_wrapper(repo_root: Path) -> PlannedTarget:
    filename = "chronos-turn-hook.cmd" if os.name == "nt" else "chronos-turn-hook.sh"
    path = repo_root / "scripts" / filename
    content = _wrapper_content()
    if path.exists():
        lines = path.read_bytes().splitlines()
        marker = _WINDOWS_MARKER if os.name == "nt" else _POSIX_MARKER
        if len(lines) < 2 or lines[1] != marker:
            raise HookConfigCollision(path, "wrapper-not-owned")
        action = PlannedAction.UNCHANGED if path.read_bytes() == content else PlannedAction.UPDATE
    else:
        action = PlannedAction.CREATE
    return PlannedTarget(path, action, (), content)


def _plan_opencode_config(home: Path) -> PlannedTarget:
    root = home / ".config" / "opencode"
    for filename in ("oh-my-opencode.jsonc", "opencode.jsonc"):
        collision = root / filename
        if collision.exists():
            raise HookConfigCollision(collision, "opencode-jsonc-collision")
    path = root / "opencode.json"
    original = path.read_bytes() if path.exists() else None
    content = updated_plugin_config(original)
    action = PlannedAction.CREATE if original is None else PlannedAction.UPDATE
    if original == content:
        action = PlannedAction.UNCHANGED
    return PlannedTarget(path, action, (), content)


def _wrapper_content() -> bytes:
    if os.name == "nt":
        return (
            b"@echo off\r\n"
            + _WINDOWS_MARKER
            + b"\r\nset SCRIPT_DIR=%~dp0\r\n"
            + b'if exist "%SCRIPT_DIR%..\\.venv\\Scripts\\python.exe" (\r\n'
            + b'  "%SCRIPT_DIR%..\\.venv\\Scripts\\python.exe" '
            + b'"%SCRIPT_DIR%agent_turn_hook.py" %*\r\n'
            + b") else (\r\n"
            + b'  where uv >nul 2>nul && (uv run python "%SCRIPT_DIR%agent_turn_hook.py" %*) || '
            + b'(python "%SCRIPT_DIR%agent_turn_hook.py" %*)\r\n)\r\n'
        )
    return (
        b"#!/usr/bin/env sh\n"
        + _POSIX_MARKER
        + b'\nscript_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
        + b'if [ -x "$script_dir/../.venv/bin/python" ]; then\n'
        + b'  exec "$script_dir/../.venv/bin/python" "$script_dir/agent_turn_hook.py" "$@"\n'
        + b"elif command -v uv >/dev/null 2>&1; then\n"
        + b'  exec uv run python "$script_dir/agent_turn_hook.py" "$@"\n'
        + b'else\n  exec python "$script_dir/agent_turn_hook.py" "$@"\nfi\n'
    )


def _validate_plugin_registry(home: Path) -> None:
    token = _registry_token(home / ".npmrc")
    probe_package_metadata(token)


def _registry_token(path: Path) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        values = dict(line.split("=", 1) for line in lines if "=" in line)
        registry = values.get("@yohi:registry", "").rstrip("/")
        raw_token = values.get("//npm.pkg.github.com/:_authToken", "")
    except OSError as error:
        raise PluginRegistryPrerequisiteError("registry-probe-credential") from error
    if registry != "https://npm.pkg.github.com":
        raise PluginRegistryPrerequisiteError("registry-probe-credential")
    token = _expand_environment_token(raw_token)
    if not token:
        raise PluginRegistryPrerequisiteError("registry-probe-credential")
    return token


def _expand_environment_token(value: str) -> str:
    if value.startswith("${") and value.endswith("}"):
        return os.environ.get(value[2:-1], "")
    return value


def probe_package_metadata(token: str) -> None:
    request = urllib.request.Request(  # noqa: S310 - fixed HTTPS registry URL
        _METADATA_URL, headers={"Authorization": f"Bearer {token}"}
    )
    try:
        # The endpoint is the fixed HTTPS GitHub Packages registry URL above.
        # nosemgrep
        with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310 - fixed request URL
            if response.status < 200 or response.status >= 300:
                raise PluginRegistryPrerequisiteError("registry-probe-access")
    except urllib.error.HTTPError as error:
        category = "registry-probe-access" if error.code in {401, 403} else "registry-probe-network"
        raise PluginRegistryPrerequisiteError(category) from error
    except PluginRegistryPrerequisiteError:
        raise
    except Exception as error:
        raise PluginRegistryPrerequisiteError("registry-probe-network") from error
