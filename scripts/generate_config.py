#!/usr/bin/env python3
"""MCP クライアント設定生成スクリプト。

Claude Desktop / Cursor / その他 MCP クライアント用の設定 JSON を標準出力に出力する。

Usage:
    python scripts/generate_config.py                    # SQLite (デフォルト)
    python scripts/generate_config.py --backend postgres # PostgreSQL モード
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
        envs["OPENAI_API_KEY"] = "<your-openai-api-key>"
    elif provider == "local-model":
        envs["LOCAL_MODEL_NAME"] = "cl-nagoya/ruri-v3-310m"
    elif provider == "litellm":
        envs["LITELLM_API_BASE"] = "http://localhost:4000"
        envs["LITELLM_MODEL"] = "openai/text-embedding-3-small"
    elif provider == "custom-api":
        envs["CUSTOM_API_ENDPOINT"] = os.environ.get(
            "CUSTOM_API_ENDPOINT", "http://localhost:8080/embed"
        )
        envs["CUSTOM_API_MODEL_NAME"] = os.environ.get("CUSTOM_API_MODEL_NAME", "custom-model")
    return envs


def build_start_command(
    method: str, uv_from: str | None, python_path: str
) -> tuple[str, list[str]]:
    """起動コマンドと引数を生成する。"""
    if method == "uv":
        command = "uv"
        args = ["run", "--quiet"]
        if uv_from:
            args.extend(["--from", uv_from])
        args.append("context-store")
    elif method == "uvx":
        command = "uvx"
        args = ["--quiet"]
        if uv_from:
            args.extend(["--from", uv_from])
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
        "SQLITE_DB_PATH": "~/.context-store/memories.db",
        "GRAPH_ENABLED": "true" if graph else "false",
        "DECAY_HALF_LIFE_DAYS": "30",
        "SIMILARITY_THRESHOLD": "0.70",
        "DEDUP_THRESHOLD": "0.90",
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
    method: str = "python",
    uv_from: str | None = None,
) -> dict[str, Any]:
    """PostgreSQL + Neo4j + Redis フルモードの設定を生成する。"""
    env = {
        "STORAGE_BACKEND": "postgres",
        "POSTGRES_HOST": "localhost",
        "POSTGRES_PORT": "5432",
        "POSTGRES_DB": "context_store",
        "POSTGRES_USER": "context_store",
        "POSTGRES_PASSWORD": "<your-postgres-password>",
        "GRAPH_ENABLED": "true" if graph else "false",
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_USER": "neo4j",
        "NEO4J_PASSWORD": "<your-neo4j-password>",
        "CACHE_BACKEND": "redis",
        "REDIS_URL": "redis://localhost:6379",
        "DECAY_HALF_LIFE_DAYS": "30",
        "SIMILARITY_THRESHOLD": "0.70",
        "DEDUP_THRESHOLD": "0.90",
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


def generate_cursor_config(base_config: dict[str, Any]) -> dict[str, Any]:
    """Cursor 用の設定形式に変換する (mcpServers キーがそのまま使える)。"""
    # Cursor は Claude Desktop と同じ形式
    return base_config


def main() -> None:
    """メインエントリポイント。"""
    # Settings インスタンスから埋め込みプロバイダーの選択肢を取得
    provider_field = settings.model_fields["embedding_provider"]
    embedding_choices = list(get_args(provider_field.annotation))
    if not embedding_choices:
        # get_args が解決できない場合の明示的なフォールバック
        embedding_choices = ["openai", "local-model", "litellm", "custom-api"]
    default_embedding = provider_field.default

    parser = argparse.ArgumentParser(description="ChronosGraph MCP client config generator")
    parser.add_argument(
        "--backend", choices=["sqlite", "postgres"], default="sqlite", help="Storage backend"
    )
    parser.add_argument(
        "--embedding",
        choices=embedding_choices,
        default=default_embedding,
        help=f"Embedding provider (default: {default_embedding})",
    )
    parser.add_argument("--graph", type=str_to_bool, default=True, help="Enable graph features")
    parser.add_argument(
        "--method", choices=["python", "uv", "uvx"], default="python", help="Execution method"
    )
    parser.add_argument("--uv-from", help="Package to run with uv (e.g. chronos-graph)")
    parser.add_argument(
        "--output", choices=["claude", "cursor"], default="claude", help="Config output format"
    )
    parser.add_argument("--indent", type=int, default=2, help="JSON indentation")

    args = parser.parse_args()

    python_path = find_python()

    if args.backend == "sqlite":
        config = generate_sqlite_config(
            python_path, args.embedding, args.graph, args.method, args.uv_from
        )
    else:
        config = generate_postgres_config(
            python_path, args.embedding, args.graph, args.method, args.uv_from
        )

    if args.output == "cursor":
        config = generate_cursor_config(config)

    print(json.dumps(config, indent=args.indent))


if __name__ == "__main__":
    main()
