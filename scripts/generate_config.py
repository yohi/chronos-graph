#!/usr/bin/env python3
"""MCP クライアント設定生成スクリプト。

Claude Desktop / Cursor / その他 MCP クライアント用の設定 JSON を標準出力に出力する。

Usage:
    python scripts/generate_config.py                    # SQLite (デフォルト)
    python scripts/generate_config.py --backend postgres # PostgreSQL モード
    python scripts/generate_config.py --output claude    # Claude Desktop 形式

Examples:
    # Claude Desktop 設定ファイルへ追記
    python scripts/generate_config.py > /tmp/chronos-config.json
    python -m json.tool /tmp/chronos-config.json  # 検証

    # Cursor 設定へ統合
    python scripts/generate_config.py --output cursor
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


def find_python() -> str:
    """現在アクティブな Python インタープリタのパスを返す。"""
    python = shutil.which("python3") or shutil.which("python") or sys.executable
    return python


def generate_sqlite_config(python_path: str) -> dict:
    """SQLite ライトウェイトモードの設定を生成する。"""
    return {
        "mcpServers": {
            "chronos-graph": {
                "command": python_path,
                "args": ["-m", "context_store"],
                "env": {
                    "STORAGE_BACKEND": "sqlite",
                    "SQLITE_DB_PATH": "~/.context-store/memories.db",
                    "EMBEDDING_PROVIDER": "openai",
                    "OPENAI_API_KEY": "<your-openai-api-key>",
                    "GRAPH_ENABLED": "true",
                    "DECAY_HALF_LIFE_DAYS": "30",
                    "SIMILARITY_THRESHOLD": "0.70",
                    "DEDUP_THRESHOLD": "0.90",
                },
            }
        }
    }


def generate_postgres_config(python_path: str) -> dict:
    """PostgreSQL + Neo4j + Redis フルモードの設定を生成する。"""
    return {
        "mcpServers": {
            "chronos-graph": {
                "command": python_path,
                "args": ["-m", "context_store"],
                "env": {
                    "STORAGE_BACKEND": "postgres",
                    "POSTGRES_HOST": "localhost",
                    "POSTGRES_PORT": "5432",
                    "POSTGRES_DB": "context_store",
                    "POSTGRES_USER": "context_store",
                    "POSTGRES_PASSWORD": "<your-postgres-password>",
                    "GRAPH_ENABLED": "true",
                    "NEO4J_URI": "bolt://localhost:7687",
                    "NEO4J_USER": "neo4j",
                    "NEO4J_PASSWORD": "<your-neo4j-password>",
                    "CACHE_BACKEND": "redis",
                    "REDIS_URL": "redis://localhost:6379",
                    "EMBEDDING_PROVIDER": "openai",
                    "OPENAI_API_KEY": "<your-openai-api-key>",
                    "DECAY_HALF_LIFE_DAYS": "30",
                    "SIMILARITY_THRESHOLD": "0.70",
                    "DEDUP_THRESHOLD": "0.90",
                },
            }
        }
    }


def generate_cursor_config(base_config: dict) -> dict:
    """Cursor 用の設定形式に変換する（mcpServers キーがそのまま使える）。"""
    # Cursor は Claude Desktop と同じ形式
    return base_config


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ChronosGraph MCP クライアント設定を生成する",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--backend",
        choices=["sqlite", "postgres"],
        default="sqlite",
        help="ストレージバックエンド (デフォルト: sqlite)",
    )
    parser.add_argument(
        "--output",
        choices=["claude", "cursor", "generic"],
        default="generic",
        help="出力形式 (デフォルト: generic)",
    )
    parser.add_argument(
        "--python",
        default=None,
        help="使用する Python インタープリタのパス (デフォルト: 自動検出)",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="JSON インデント幅 (デフォルト: 2)",
    )
    args = parser.parse_args()

    python_path = args.python or find_python()

    if args.backend == "postgres":
        config = generate_postgres_config(python_path)
    else:
        config = generate_sqlite_config(python_path)

    if args.output == "cursor":
        config = generate_cursor_config(config)

    print(json.dumps(config, indent=args.indent, ensure_ascii=False))


if __name__ == "__main__":
    main()
