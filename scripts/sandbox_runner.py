import argparse
import os
import re
import signal
import sys
import time

from opensandbox import SandboxClient

ROUTING_RULES: list[tuple[str, str]] = [
    (r"tests/integration", "integration"),
    (r"\btest_postgres\b", "integration"),
    (r"\btest_neo4j\b", "integration"),
    (r"\btest_redis\b", "integration"),
]
DEFAULT_PROFILE = "lite"
MAX_RETRIES = 2


def resolve_profile(command: list[str], explicit: str | None) -> str:
    if explicit:
        return explicit
    cmd_str = " ".join(command)
    for pattern, profile in ROUTING_RULES:
        if re.search(pattern, cmd_str):
            return profile
    return DEFAULT_PROFILE


def install_dependencies(
    client: SandboxClient,
    sandbox_id: str,
    command: list[str],
) -> None:
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


def setup_sandbox(client: SandboxClient, profile: str) -> str:
    for attempt in range(MAX_RETRIES + 1):
        try:
            return client.create(profile=profile)
        except Exception as exc:
            if "pool" in str(exc).lower() and attempt < MAX_RETRIES:
                wait = 2**attempt
                print(f"[sandbox] Pool exhausted, retry in {wait}s", file=sys.stderr)
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("Failed to acquire sandbox")  # pragma: no cover


def execute_in_sandbox(
    client: SandboxClient,
    sandbox_id: str,
    command: list[str],
    working_dir: str = "/workspace",
) -> int:
    result = client.execute(
        sandbox_id,
        command,
        working_dir=working_dir,
        stream=True,
        env={"OPENSANDBOX": "1"},
    )
    return result.exit_code


def teardown_sandbox(client: SandboxClient, sandbox_id: str) -> None:
    try:
        client.destroy(sandbox_id)
    except Exception as exc:
        print(
            f"[sandbox] Warning: failed to destroy {sandbox_id}: {exc}",
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

    client = SandboxClient(base_url=args.server_url)
    sandbox_id: str | None = None
    _cleaned_up = False

    def _cleanup(signum: int, frame: object) -> None:
        nonlocal _cleaned_up
        if sandbox_id and not _cleaned_up:
            _cleaned_up = True
            teardown_sandbox(client, sandbox_id)
        sys.exit(128 + signum)

    signal.signal(signal.SIGTERM, _cleanup)
    signal.signal(signal.SIGINT, _cleanup)

    try:
        sandbox_id = setup_sandbox(client, profile)
        install_dependencies(client, sandbox_id, command)
        return execute_in_sandbox(client, sandbox_id, command)
    finally:
        if sandbox_id and not _cleaned_up:
            _cleaned_up = True
            teardown_sandbox(client, sandbox_id)


if __name__ == "__main__":
    sys.exit(main())
