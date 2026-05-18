#!/usr/bin/env python3
"""Assist Prisma Accelerate setup for ChronosGraph.

This helper does not magically rewrite a PostgreSQL URL into a Prisma URL.
It treats a PostgreSQL URL as the direct database URL that Prisma Data Platform
uses to enable Accelerate in Prisma Console, then helps operators capture the
issued ``prisma://`` / ``prismas://`` connection string for ChronosGraph.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ACCELERATE_URL_RE = re.compile(r"\bprismas?://[^\s'\"<>]+")


def is_postgres_direct_url(url: str) -> bool:
    """Return true when URL is a direct PostgreSQL connection string."""
    return url.startswith(("postgresql://", "postgres://"))


def extract_accelerate_url(text: str) -> str | None:
    """Extract the first Prisma Accelerate connection string from CLI output."""
    match = ACCELERATE_URL_RE.search(text)
    return match.group(0).rstrip(".,)") if match else None


def mask_url(url: str) -> str:
    """Mask password and API key portions of a URL for safe display."""
    parts = urlsplit(url)
    netloc = parts.netloc
    if "@" in netloc and ":" in netloc.split("@", 1)[0]:
        userinfo, host = netloc.rsplit("@", 1)
        user = userinfo.split(":", 1)[0]
        netloc = f"{user}:****@{host}"

    query_items = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        masked = "****" if key.lower() in {"api_key", "apikey", "password"} else value
        query_items.append((key, masked))
    query = urlencode(query_items, safe="*")
    return urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment))


def read_direct_url(env_name: str, file_path: str | None) -> str | None:
    """Read a direct PostgreSQL URL from file first, then environment."""
    if file_path:
        return Path(file_path).read_text(encoding="utf-8").strip()
    return os.environ.get(env_name)


def build_chronos_env(
    *,
    accelerate_url: str,
    cache_backend: str,
    redis_url: str | None = None,
) -> dict[str, str]:
    """Build ChronosGraph environment variables for Prisma backend."""
    env = {
        "STORAGE_BACKEND": "prisma",
        "PRISMA_DATABASE_URL": accelerate_url,
        "GRAPH_ENABLED": "false",
        "CACHE_BACKEND": cache_backend,
    }
    if cache_backend == "redis":
        effective_redis_url = (
            redis_url or "rediss://default:your-password@your-instance.upstash.io:6379"
        )
        env["REDIS_URL"] = effective_redis_url
        env["REDIS_SSL"] = "true" if effective_redis_url.startswith("rediss://") else "false"
    return env


def platform_command(*args: str) -> list[str]:
    """Build a Prisma platform command using npx."""
    return ["npx", "prisma", "platform", *args]


def render_command(command: list[str]) -> str:
    """Render a shell command for documentation output."""
    return " ".join(f'"{part}"' if " " in part else part for part in command)


def run_command(command: list[str]) -> str:
    """Run a Prisma CLI command and return combined output."""
    result = subprocess.run(  # noqa: S603,S607 - operator-selected Prisma CLI helper
        command,
        text=True,
        capture_output=True,
        check=False,
    )
    output = f"{result.stdout}\n{result.stderr}".strip()
    if result.returncode != 0:
        rendered = render_command(command)
        raise RuntimeError(f"Command failed ({result.returncode}): {rendered}\n{output}")
    return output


def print_env(env: dict[str, str]) -> None:
    """Print env lines without masking because they are meant for local .env files."""
    for key, value in env.items():
        print(f'{key}="{value}"')


def load_env_file(file_path: str | None = ".env") -> None:
    """Load environment variables from a .env file."""
    if file_path is None or not Path(file_path).is_file():
        return

    try:
        from dotenv import load_dotenv

        load_dotenv(file_path)
    except ImportError:
        # Simple manual fallback if python-dotenv is not installed
        content = Path(file_path).read_text(encoding="utf-8")
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip("'\"")
                if key and key not in os.environ:
                    os.environ[key] = value


def build_parser() -> argparse.ArgumentParser:
    """Build CLI parser."""
    parser = argparse.ArgumentParser(
        description="Assist Prisma Accelerate connection string setup for ChronosGraph."
    )
    parser.add_argument("--env-file", default=".env", help="Path to .env file to load")
    parser.add_argument("--direct-url-env", default="DIRECT_DATABASE_URL")
    parser.add_argument("--direct-url-file")
    parser.add_argument("--accelerate-url")
    parser.add_argument("--environment-id")
    parser.add_argument("--connection-name", default="chronos-graph")
    parser.add_argument("--region")
    parser.add_argument("--cache", choices=["redis", "inmemory"], default="redis")
    parser.add_argument("--redis-url")
    parser.add_argument("--run-help", action="store_true")
    parser.add_argument("--create-apikey", action="store_true")
    return parser


def main() -> None:
    """Run the setup helper."""
    # First pass to get --env-file without full parsing
    temp_args, _ = build_parser().parse_known_args()
    load_env_file(temp_args.env_file)

    args = build_parser().parse_args()
    # If accelerate-url or redis-url are missing from args, try environment
    accelerate_url_arg = args.accelerate_url or os.environ.get("ACCELERATE_URL")
    redis_url_arg = args.redis_url or os.environ.get("REDIS_URL")

    direct_url = read_direct_url(args.direct_url_env, args.direct_url_file)

    if args.run_help:
        for command in (
            ["npx", "prisma", "--version"],
            platform_command("--help"),
            platform_command("status", "--json"),
        ):
            print(f"$ {render_command(command)}")
            print(run_command(command))

    if direct_url:
        if not is_postgres_direct_url(direct_url):
            raise SystemExit("Direct database URL must start with postgresql:// or postgres://")
        print(f"Direct database URL loaded: {mask_url(direct_url)}")
        print("Use this URL as the source database URL when enabling Prisma Accelerate.")

    if not accelerate_url_arg:
        print("Create a Prisma Accelerate connection string in Prisma Console.")
        print("Use the loaded direct database URL as the Console database connection string.")
        print("Then rerun this helper with --accelerate-url 'prisma://...'")
        print("or set ACCELERATE_URL in .env.")
        return

    accelerate_url = extract_accelerate_url(accelerate_url_arg) or accelerate_url_arg
    if not accelerate_url.startswith(("prisma://", "prismas://")):
        raise SystemExit("Accelerate URL must start with prisma:// or prismas://")

    if args.create_apikey:
        if not args.environment_id:
            raise SystemExit("--environment-id is required with --create-apikey")
        output = run_command(
            platform_command(
                "apikey",
                "create",
                "--environment",
                args.environment_id,
                "--name",
                args.connection_name,
            )
        )
        parsed = extract_accelerate_url(output)
        if parsed:
            accelerate_url = parsed

    print("ChronosGraph Prisma environment:")
    print_env(
        build_chronos_env(
            accelerate_url=accelerate_url,
            cache_backend=args.cache,
            redis_url=redis_url_arg,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
