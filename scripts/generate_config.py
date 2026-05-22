#!/usr/bin/env python3
"""MCP クライアント設定生成スクリプト。

Claude Desktop / Cursor / その他 MCP クライアント用の設定 JSON を標準出力に出力する。

Usage:
    python scripts/generate_config.py                    # SQLite (デフォルト)
    python scripts/generate_config.py --backend postgres # PostgreSQL モード
    python scripts/generate_config.py --backend supabase   # Supabase モード
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
from functools import lru_cache
from typing import Any, Literal, get_args

# src を sys.path に追加して context_store をインポート可能にする
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


@lru_cache
def get_settings() -> Any:
    """Settings インスタンスを遅延ロードして返す。"""
    env_file: str | None = os.environ.get("ENV_FILE", ".env")
    if env_file == "/dev/null":
        env_file = None

    try:
        from context_store.config import Settings as RealSettings

        return RealSettings(_env_file=env_file)
    except ImportError:
        # インポート失敗時のフォールバック(スタンドアロン実行用)
        class SettingsFallback:
            DEFAULT_REDIS_URL = "redis://localhost:6379"

            def __init__(self, _env_file: str | None = None):
                pass

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

        return SettingsFallback(_env_file=env_file)


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
    settings = get_settings()
    envs = {"EMBEDDING_PROVIDER": provider}
    if provider == "openai":
        envs["OPENAI_API_KEY"] = get_secret(settings, "openai_api_key", "<your-openai-api-key>")
    elif provider == "local-model":
        envs["LOCAL_MODEL_NAME"] = getattr(settings, "local_model_name", "cl-nagoya/ruri-v3-310m")
        envs["EMBEDDING_DIMENSION"] = str(getattr(settings, "embedding_dimension", 768))
    elif provider == "litellm":
        envs["LITELLM_API_BASE"] = getattr(settings, "litellm_api_base", "http://localhost:4000")
        envs["LITELLM_MODEL"] = getattr(settings, "litellm_model", "openai/text-embedding-3-small")
    elif provider == "custom-api":
        envs["CUSTOM_API_ENDPOINT"] = getattr(
            settings, "custom_api_endpoint", "http://localhost:8080/embed"
        )
        envs["CUSTOM_API_MODEL_NAME"] = getattr(settings, "custom_api_model_name", "custom-model")
    return envs


def _resolve_redis_config(ssl: bool) -> tuple[str, bool]:
    """Redis の接続 URL と SSL 設定を解決する。"""
    settings = get_settings()
    default_redis = getattr(settings, "DEFAULT_REDIS_URL", "redis://localhost:6379")
    redis_url = getattr(settings, "redis_url", default_redis)

    # ユーザーが明示的に環境変数や引数で指定していない、
    # かつデフォルト値のままの場合はクラウド用プレースホルダを提示する
    if redis_url == default_redis and not os.environ.get("REDIS_URL"):
        redis_url = "rediss://default:your-password@your-instance.upstash.io:6379"

    # SSL設定の優先順位:
    # 1. settings.redis_ssl (デフォルト値 False 以外なら明示的な指定とみなす)
    # 2. SSL引数
    # 3. URLスキーム
    redis_ssl_val = getattr(settings, "redis_ssl", False)
    if redis_ssl_val:  # 明示的に True の場合のみ優先
        redis_ssl = True
    else:
        # デフォルトの False の場合は、引数や URL スキームから判断する
        redis_ssl = ssl or redis_url.startswith("rediss://")

    return redis_url, redis_ssl


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


def get_secret(settings: Any, name: str, default: str) -> str:
    """Settings から秘密情報を安全に取得する。"""
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


def generate_sqlite_config(
    python_path: str,
    embedding: str,
    graph: bool,
    method: str = "python",
    uv_from: str | None = None,
) -> dict[str, Any]:
    """SQLite ライトウェイトモードの設定を生成する。"""
    settings = get_settings()
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
    settings = get_settings()
    # Redis 設定の解決
    redis_url, redis_ssl = _resolve_redis_config(ssl)

    env = {
        "STORAGE_BACKEND": "postgres",
        "POSTGRES_HOST": getattr(settings, "postgres_host", "your-project-id.supabase.co"),
        "POSTGRES_PORT": str(getattr(settings, "postgres_port", "5432")),
        "POSTGRES_DB": getattr(settings, "postgres_db", "postgres"),
        "POSTGRES_USER": getattr(settings, "postgres_user", "postgres"),
        "POSTGRES_PASSWORD": get_secret(settings, "postgres_password", "<your-postgres-password>"),
        "POSTGRES_SSL": "true" if ssl else "false",
        "GRAPH_ENABLED": "true" if graph else "false",
        "NEO4J_URI": getattr(settings, "neo4j_uri", "neo4j+s://your-instance.databases.neo4j.io"),
        "NEO4J_USER": getattr(settings, "neo4j_user", "neo4j"),
        "NEO4J_PASSWORD": get_secret(settings, "neo4j_password", "<your-neo4j-password>"),
        "CACHE_BACKEND": cache,
        "REDIS_URL": redis_url,
        "REDIS_SSL": "true" if redis_ssl else "false",
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


def generate_supabase_config(
    python_path: str,
    embedding: str,
    cache: str,
    ssl: bool,
    method: str = "python",
    uv_from: str | None = None,
) -> dict[str, Any]:
    """Supabase モードの設定を生成する。"""
    settings = get_settings()
    supabase_url = get_secret(settings, "supabase_url", "<your-supabase-project-url>")
    supabase_key = get_secret(settings, "supabase_key", "<your-supabase-service-role-key>")

    env = {
        "STORAGE_BACKEND": "supabase",
        "SUPABASE_URL": supabase_url,
        "SUPABASE_KEY": supabase_key,
        "GRAPH_ENABLED": "false",
        "CACHE_BACKEND": cache,
        "DECAY_HALF_LIFE_DAYS": str(getattr(settings, "decay_half_life_days", "30")),
        "SIMILARITY_THRESHOLD": f"{getattr(settings, 'similarity_threshold', 0.70):.2f}",
        "DEDUP_THRESHOLD": f"{getattr(settings, 'dedup_threshold', 0.90):.2f}",
    }
    if cache == "redis":
        # Redis 設定の解決
        redis_url, redis_ssl = _resolve_redis_config(ssl)

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
    settings = get_settings()
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
        choices=["sqlite", "postgres", "supabase"],
        default="sqlite",
        help="Storage backend",
    )
    parser.add_argument(
        "--cache",
        choices=["inmemory", "redis"],
        default=None,
        help="Cache backend (postgres: inmemory, or redis if --ssl is set; supabase: redis)",
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
        config = generate_supabase_config(
            python_path,
            args.embedding,
            cache_backend,
            args.ssl,
            args.method,
            args.uv_from,
        )

    if args.output == "cursor":
        config = generate_cursor_config(config)

    print(json.dumps(config, indent=args.indent))


if __name__ == "__main__":
    main()
