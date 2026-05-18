#!/usr/bin/env python3
"""MCP クライアント設定生成スクリプト。

Claude Desktop / Cursor / その他 MCP クライアント用の設定 JSON を標準出力に出力する。

Usage:
    python scripts/generate_config.py                    # SQLite (デフォルト)
    python scripts/generate_config.py --backend postgres # PostgreSQL モード
    python scripts/generate_config.py --backend prisma   # Prisma Accelerate モード
    python scripts/generate_config.py --output claude    # Claude Desktop 形式
    python scripts/generate_config.py --method uv       # uv モード

Examples:
    # Claude Desktop 設定ファイルへ追記
    python scripts/generate_config.py > /tmp/chronos-config.json
    python -m json.tool /tmp/chronos-config.json  # 検証

    # uv を使用したワンライナー設定
    python scripts/generate_config.py --method uv --output claude
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from typing import Any, Literal, get_args

# src を sys.path に追加して context_store をインポート可能にする
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

try:
    from context_store.config import Settings as RealSettings
except ImportError:
    # インポート失敗時のフォールバック(スタンドアロン実行用)
    class SettingsFallback:
        @property
        def model_fields(self) -> dict[str, Any]:
            """イミュータブルな定義を返すプロパティ。"""
            return {
                "embedding_provider": type(
                    "obj",
                    (),
                    {
                        "annotation": Literal["openai", "local-model", "litellm", "custom-api"],
                        "default": "local-model",
                    },
                )
            }

    # インスタンス化して使用
    settings: Any = SettingsFallback()
else:
    # Pydantic Settings はインスタンス化しても model_fields にアクセス可能
    settings = RealSettings()


def str_to_bool(value: str) -> bool:
    """文字列をブール値に変換する。"""
    if isinstance(value, bool):
        return value
    if value.lower() in ("yes", "true", "t", "y", "1", "on"):
        return True
    if value.lower() in ("no", "false", "f", "n", "0", "off"):
        return False
    raise argparse.ArgumentTypeError(f"Boolean value expected, got {value}")


def find_python() -> str:
    """現在アクティブな Python インタープリタのパスを返す。"""
    python = shutil.which("python3") or shutil.which("python") or sys.executable
    return python


def get_embedding_envs(provider: str) -> dict[str, str]:
    """プロバイダーに応じた埋め込み設定の環境変数を返す。"""
    envs = {"EMBEDDING_PROVIDER": provider}
    if provider == "openai":
        api_key = "<your-openai-api-key>"
        if hasattr(settings, "openai_api_key"):
            raw = settings.openai_api_key
            if raw is not None:
                val = raw.get_secret_value()
                if val:
                    api_key = val
        envs["OPENAI_API_KEY"] = api_key
    elif provider == "local-model":
        envs["LOCAL_MODEL_NAME"] = getattr(settings, "local_model_name", "cl-nagoya/ruri-v3-310m")
        envs["EMBEDDING_DIMENSION"] = str(getattr(settings, "embedding_dimension", "1024"))
    elif provider == "litellm":
        envs["LITELLM_API_BASE"] = getattr(settings, "litellm_api_base", "http://localhost:4000")
        envs["LITELLM_MODEL"] = getattr(settings, "litellm_model", "openai/text-embedding-3-small")
    elif provider == "custom-api":
        envs["CUSTOM_API_ENDPOINT"] = getattr(
            settings, "custom_api_endpoint", "http://localhost:8080/embed"
        )
        envs["CUSTOM_API_MODEL_NAME"] = getattr(settings, "custom_api_model_name", "custom-model")
    return envs


def build_start_command(
    method: str, uv_from: str | None, python_path: str
) -> tuple[str, list[str]]:
    """起動コマンドと引数を生成する。"""

    def _is_url(s: str) -> bool:
        return s.startswith(("http://", "https://", "git+")) or "://" in s or s.endswith(".git")

    def _with_extras(pkg: str | None) -> str | None:
        if pkg is None:
            return None
        return f"context-store-mcp[all] @ {pkg}" if _is_url(pkg) else f"{pkg}[all]"

    if method == "uv":
        command = "uv"
        args = ["run", "--quiet"]
        uv_from_extras = _with_extras(uv_from)
        if uv_from_extras:
            args.extend(["--from", uv_from_extras])
        args.append("context-store")
    elif method == "uvx":
        command = "uvx"
        args = ["--quiet"]
        uv_from_extras = _with_extras(uv_from)
        if uv_from_extras:
            args.extend(["--from", uv_from_extras])
        args.append("context-store")
    else:
        command = python_path
        args = ["-m", "context_store"]
    return command, args


def generate_sqlite_config(
    python_path: str,
    embedding: str,
    graph: bool,
    method: str = "python",
    uv_from: str | None = None,
) -> dict[str, Any]:
    """SQLite ライトウェイトモードの設定を生成する。"""
    env = {
        "STORAGE_BACKEND": "sqlite",
        "SQLITE_DB_PATH": getattr(settings, "sqlite_db_path", "~/.context-store/memories.db"),
        "GRAPH_ENABLED": "true" if graph else "false",
        "DECAY_HALF_LIFE_DAYS": str(getattr(settings, "decay_half_life_days", "30")),
        "SIMILARITY_THRESHOLD": f"{getattr(settings, 'similarity_threshold', 0.70):.2f}",
        "DEDUP_THRESHOLD": f"{getattr(settings, 'dedup_threshold', 0.90):.2f}",
    }
    env.update(get_embedding_envs(embedding))

    command, args = build_start_command(method, uv_from, python_path)

    return {
        "mcpServers": {
            "chronos-graph": {
                "command": command,
                "args": args,
                "env": env,
            }
        }
    }


def generate_postgres_config(
    python_path: str,
    embedding: str,
    graph: bool,
    ssl: bool,
    cache: str,
    method: str = "python",
    uv_from: str | None = None,
) -> dict[str, Any]:
    """PostgreSQL + Neo4j + Redis フルモードの設定を生成する。"""

    # helper for secret strings
    def get_secret(name: str, default: str) -> str:
        if hasattr(settings, name):
            raw = getattr(settings, name)
            if raw is not None:
                if hasattr(raw, "get_secret_value"):
                    val = raw.get_secret_value()
                    if isinstance(val, str) and val:
                        return val
                elif isinstance(raw, str) and raw:
                    return raw
        return default

    env = {
        "STORAGE_BACKEND": "postgres",
        "POSTGRES_HOST": getattr(settings, "postgres_host", "your-project-id.supabase.co"),
        "POSTGRES_PORT": str(getattr(settings, "postgres_port", "5432")),
        "POSTGRES_DB": getattr(settings, "postgres_db", "postgres"),
        "POSTGRES_USER": getattr(settings, "postgres_user", "postgres"),
        "POSTGRES_PASSWORD": get_secret("postgres_password", "<your-postgres-password>"),
        "POSTGRES_SSL": "true" if ssl else "false",
        "GRAPH_ENABLED": "true" if graph else "false",
        "NEO4J_URI": getattr(settings, "neo4j_uri", "neo4j+s://your-instance.databases.neo4j.io"),
        "NEO4J_USER": getattr(settings, "neo4j_user", "neo4j"),
        "NEO4J_PASSWORD": get_secret("neo4j_password", "<your-neo4j-password>"),
        "CACHE_BACKEND": cache,
        "REDIS_URL": getattr(
            settings, "redis_url", "rediss://default:your-password@your-instance.upstash.io:6379"
        ),
        "REDIS_SSL": "true" if ssl or getattr(settings, "redis_ssl", False) else "false",
        "DECAY_HALF_LIFE_DAYS": str(getattr(settings, "decay_half_life_days", "30")),
        "SIMILARITY_THRESHOLD": f"{getattr(settings, 'similarity_threshold', 0.70):.2f}",
        "DEDUP_THRESHOLD": f"{getattr(settings, 'dedup_threshold', 0.90):.2f}",
    }
    # Cache configuration:
    # - Single instance / Local: CACHE_BACKEND=inmemory
    # - Multi-instance / Cloud: CACHE_BACKEND=redis (e.g., Upstash)
    env.update(get_embedding_envs(embedding))

    command, args = build_start_command(method, uv_from, python_path)

    return {
        "mcpServers": {
            "chronos-graph": {
                "command": command,
                "args": args,
                "env": env,
            }
        }
    }


def generate_prisma_config(
    python_path: str,
    embedding: str,
    cache: str,
    method: str = "python",
    uv_from: str | None = None,
) -> dict[str, Any]:
    """Prisma Accelerate モードの設定を生成する。"""

    prisma_url = "<your-prisma-accelerate-url>"
    if hasattr(settings, "prisma_database_url"):
        raw = settings.prisma_database_url
        if raw is not None:
            val = raw.get_secret_value()
            if val:
                prisma_url = val

    env = {
        "STORAGE_BACKEND": "prisma",
        "PRISMA_DATABASE_URL": prisma_url,
        "GRAPH_ENABLED": "false",
        "CACHE_BACKEND": cache,
        "DECAY_HALF_LIFE_DAYS": str(getattr(settings, "decay_half_life_days", "30")),
        "SIMILARITY_THRESHOLD": f"{getattr(settings, 'similarity_threshold', 0.70):.2f}",
        "DEDUP_THRESHOLD": f"{getattr(settings, 'dedup_threshold', 0.90):.2f}",
    }
    if cache == "redis":
        redis_url = getattr(settings, "redis_url", "redis://localhost:6379")
        if redis_url == "redis://localhost:6379":
            redis_url = "rediss://default:your-password@your-instance.upstash.io:6379"
        redis_ssl = getattr(settings, "redis_ssl", False) or redis_url.startswith("rediss://")
        env.update(
            {
                "REDIS_URL": redis_url,
                "REDIS_SSL": "true" if redis_ssl else "false",
            }
        )
    env.update(get_embedding_envs(embedding))

    command, args = build_start_command(method, uv_from, python_path)

    return {
        "mcpServers": {
            "chronos-graph": {
                "command": command,
                "args": args,
                "env": env,
            }
        }
    }


def generate_cursor_config(base_config: dict[str, Any]) -> dict[str, Any]:
    """Cursor 用の設定形式に変換する (mcpServers キーがそのまま使える)。"""
    # Cursor は Claude Desktop と同じ形式
    return base_config


def main() -> None:
    """メインエントリポイント。"""
    # Settings インスタンスから埋め込みプロバイダーの選択肢を取得
    class_model_fields = getattr(type(settings), "model_fields", None)
    model_fields = (
        class_model_fields if isinstance(class_model_fields, dict) else settings.model_fields
    )
    provider_field = model_fields["embedding_provider"]
    embedding_choices = list(get_args(provider_field.annotation))
    if not embedding_choices:
        # get_args が解決できない場合の明示的なフォールバック
        embedding_choices = ["openai", "local-model", "litellm", "custom-api"]
    default_embedding = provider_field.default

    parser = argparse.ArgumentParser(description="ChronosGraph MCP client config generator")
    parser.add_argument(
        "--backend",
        choices=["sqlite", "postgres", "prisma"],
        default="sqlite",
        help="Storage backend",
    )
    parser.add_argument(
        "--cache",
        choices=["inmemory", "redis"],
        default=None,
        help="Cache backend (postgres: inmemory, or redis if --ssl is set; prisma: redis)",
    )
    parser.add_argument(
        "--embedding",
        choices=embedding_choices,
        default=default_embedding,
        help=f"Embedding provider (default: {default_embedding})",
    )
    parser.add_argument("--graph", type=str_to_bool, default=True, help="Enable graph features")
    parser.add_argument("--ssl", action="store_true", help="Enable SSL for PostgreSQL/Redis")
    parser.add_argument(
        "--method", choices=["python", "uv", "uvx"], default="python", help="Execution method"
    )
    parser.add_argument("--uv-from", help="Package to run with uv (e.g. chronos-graph)")
    parser.add_argument(
        "--output",
        choices=["claude", "cursor", "generic"],
        default="claude",
        help="Config output format",
    )
    parser.add_argument("--indent", type=int, default=2, help="JSON indentation")

    args = parser.parse_args()

    python_path = find_python()

    if args.backend == "sqlite":
        config = generate_sqlite_config(
            python_path, args.embedding, args.graph, args.method, args.uv_from
        )
    elif args.backend == "postgres":
        # ユーザーが指定していない場合のみ、デフォルト値を決定する
        # --ssl があれば redis、なければ inmemory をデフォルトにする
        cache_backend = args.cache
        if cache_backend is None:
            cache_backend = "redis" if args.ssl else "inmemory"

        config = generate_postgres_config(
            python_path,
            args.embedding,
            args.graph,
            args.ssl,
            cache_backend,
            args.method,
            args.uv_from,
        )
    else:
        cache_backend = args.cache or "redis"
        config = generate_prisma_config(
            python_path,
            args.embedding,
            cache_backend,
            args.method,
            args.uv_from,
        )

    if args.output == "cursor":
        config = generate_cursor_config(config)

    print(json.dumps(config, indent=args.indent))


if __name__ == "__main__":
    main()
