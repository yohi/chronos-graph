import argparse
import os
import re
import signal
import sys
import time
from urllib.parse import urlparse

from opensandbox import SandboxSync
from opensandbox.config.connection_sync import ConnectionConfigSync
from opensandbox.models.execd import RunCommandOpts

ROUTING_RULES: list[tuple[str, str]] = [
    (r"tests/integration", "integration"),
    (r"\btest_postgres\b", "integration"),
    (r"\btest_neo4j\b", "integration"),
    (r"\btest_redis\b", "integration"),
]
DEFAULT_PROFILE = "lite"
MAX_RETRIES = 2

# Maps sandbox.yaml profile names to their container image references.
PROFILE_IMAGES: dict[str, str] = {
    "lite": "chronos-graph-sandbox-lite:latest",
    "integration": "chronos-graph-sandbox-lite:latest",
}


def resolve_profile(command: list[str], explicit: str | None) -> str:
    if explicit:
        return explicit
    cmd_str = " ".join(command)
    for pattern, profile in ROUTING_RULES:
        if re.search(pattern, cmd_str):
            return profile
    return DEFAULT_PROFILE


def install_dependencies(
    sandbox: SandboxSync,
    command: list[str],
) -> None:
    cmd_str = " ".join(command)

    if any(kw in cmd_str for kw in ["ruff", "mypy", "pytest", "uv"]):
        result = sandbox.commands.run(
            "uv sync --frozen --all-extras",
            opts=RunCommandOpts(working_directory="/workspace"),
        )
        if (result.exit_code or 0) != 0:
            raise RuntimeError(f"[sandbox] uv sync failed (exit {result.exit_code})")

    if any(kw in cmd_str for kw in ["pnpm", "tsc", "eslint", "frontend"]):
        result = sandbox.commands.run(
            "bash -c 'cd /workspace/frontend && pnpm install --frozen-lockfile'",
            opts=RunCommandOpts(working_directory="/workspace"),
        )
        if (result.exit_code or 0) != 0:
            raise RuntimeError(f"[sandbox] pnpm install failed (exit {result.exit_code})")


def setup_sandbox(connection_config: ConnectionConfigSync, profile: str) -> SandboxSync:
    image = PROFILE_IMAGES.get(profile, PROFILE_IMAGES[DEFAULT_PROFILE])
    for attempt in range(MAX_RETRIES + 1):
        try:
            return SandboxSync.create(
                image=image,
                metadata={"profile": profile},
                connection_config=connection_config,
            )
        except Exception as exc:
            if "pool" in str(exc).lower() and attempt < MAX_RETRIES:
                wait = 2**attempt
                print(f"[sandbox] Pool exhausted, retry in {wait}s", file=sys.stderr)
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("Failed to acquire sandbox")  # pragma: no cover


def execute_in_sandbox(
    sandbox: SandboxSync,
    command: list[str],
    working_dir: str = "/workspace",
) -> int:
    result = sandbox.commands.run(
        " ".join(command),
        opts=RunCommandOpts(
            working_directory=working_dir,
            envs={"OPENSANDBOX": "1"},
        ),
    )
    return result.exit_code if result.exit_code is not None else 1


def teardown_sandbox(sandbox: SandboxSync) -> None:
    try:
        sandbox.kill()
    except Exception as exc:
        print(
            f"[sandbox] Warning: failed to destroy {sandbox.id}: {exc}",
            file=sys.stderr,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run commands in OpenSandbox")
    parser.add_argument("--profile", choices=["lite", "integration"], default=None)
    parser.add_argument(
        "--server-url",
        default=os.environ.get("OPENSANDBOX_URL", "http://localhost:8090"),
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        print("Error: No command specified", file=sys.stderr)
        return 1

    profile = resolve_profile(command, args.profile)
    print(f"[sandbox] Profile: {profile}", file=sys.stderr)

    parsed = urlparse(args.server_url)
    connection_config = ConnectionConfigSync(
        domain=parsed.netloc,
        protocol=parsed.scheme or "http",
    )

    sandbox: SandboxSync | None = None
    _cleaned_up = False

    def _cleanup(signum: int, frame: object) -> None:
        nonlocal _cleaned_up
        if sandbox and not _cleaned_up:
            _cleaned_up = True
            teardown_sandbox(sandbox)
        sys.exit(128 + signum)

    signal.signal(signal.SIGTERM, _cleanup)
    signal.signal(signal.SIGINT, _cleanup)

    try:
        sandbox = setup_sandbox(connection_config, profile)
        install_dependencies(sandbox, command)
        return execute_in_sandbox(sandbox, command)
    finally:
        if sandbox and not _cleaned_up:
            _cleaned_up = True
            teardown_sandbox(sandbox)


if __name__ == "__main__":
    sys.exit(main())
