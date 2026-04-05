"""MCP Server (FastMCP) - ChronosGraph の MCP エントリーポイント。

FastMCP を使用して 7 ツールと 2 リソースを公開する。
Orchestrator は初回ツール呼び出し時に遅延初期化する（MCPハンドシェイク時は
重いモジュールをロードしない）。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp import FastMCP

if TYPE_CHECKING:
    from context_store.config import Settings
    from context_store.orchestrator import Orchestrator

logger = logging.getLogger(__name__)

# FastMCP インスタンス（グローバル）
mcp: FastMCP = FastMCP("chronos-graph")

# ---------------------------------------------------------------------------
# ChronosServer クラス（状態管理 + ビジネスロジック）
# ---------------------------------------------------------------------------


class ChronosServer:
    """ChronosGraph MCP サーバーの状態と操作を管理するクラス。

    遅延初期化パターンを採用し、MCPハンドシェイク時には重いモジュールを
    ロードしない。

    Note:
        _url_semaphore は asyncio.Semaphore によるプロセスレベルの制限です。
        MCPサーバーが複数プロセスで起動された場合、この Semaphore はプロセス単位
        での制限となり、システム全体の真の制限にはなりません。
    """

    def __init__(self) -> None:
        self._orchestrator: "Orchestrator | None" = None
        self._init_lock: asyncio.Lock = asyncio.Lock()
        self._initialized: bool = False
        self._settings: "Settings | None" = None
        # URLフェッチ用 asyncio.Semaphore はプロセスレベルの制限です。
        # MCPサーバーが複数プロセスで起動された場合、この Semaphore はプロセス単位
        # での制限となり、システム全体の真の制限にはなりません。
        self._url_semaphore: asyncio.Semaphore | None = None

    async def _do_initialize(self) -> None:
        """Orchestrator を実際に初期化する。"""
        from context_store.config import Settings
        from context_store.orchestrator import create_orchestrator

        self._settings = Settings()
        self._orchestrator = await create_orchestrator(self._settings)

    async def _ensure_initialized(self) -> None:
        """Orchestrator を遅延初期化する（二重初期化を防ぐ）。

        asyncio.Lock を使用して複数の同時非同期呼び出し時でも
        デッドロック・重複初期化を防ぐ。
        """
        async with self._init_lock:
            if not self._initialized:
                await self._do_initialize()
                if self._url_semaphore is None:
                    # 指摘に基づき、Orchestrator が提供する公開プロパティを再利用する
                    assert self._orchestrator is not None
                    self._url_semaphore = asyncio.Semaphore(
                        self._orchestrator.url_fetch_concurrency
                    )
                    logger.warning(
                        "現在のURLフェッチ制限はプロセススコープです。"
                        "マルチプロセス実行時は制限を超過する可能性があります。"
                    )
                self._initialized = True
                # ライフサイクルマネージャーを開始
                await self._orchestrator.start_lifecycle()

    # ---------------------------------------------------------------------------
    # ツールハンドラ
    # ---------------------------------------------------------------------------

    async def memory_save(
        self,
        content: str,
        source: str = "conversation",
        project: str | None = None,
        tags: list[str] | None = None,
        importance: float | None = None,
    ) -> str:
        """テキストコンテンツを記憶として保存する。

        Args:
            content: 保存するテキスト。
            source: ソース種別（"conversation", "manual", "url"）。デフォルト "conversation"。
            project: プロジェクト名。
            tags: タグのリスト。
            importance: 重要度スコア（0.0〜1.0）。

        Returns:
            保存結果の JSON 文字列。
        """
        await self._ensure_initialized()
        assert self._orchestrator is not None

        from context_store.models.memory import SourceType

        try:
            source_type = SourceType(source)
        except ValueError:
            logger.warning(
                "無効なソース種別が指定されました: %r。'conversation' を使用します。", source
            )
            source_type = SourceType.CONVERSATION

        effective_tags: list[str] = tags if tags is not None else []
        metadata: dict[str, Any] = {
            "tags": effective_tags,
        }
        if project is not None:
            metadata["project"] = project
        if importance is not None:
            metadata["importance"] = importance

        results = await self._orchestrator.save(
            content,
            source_type=source_type,
            metadata=metadata,
        )
        return json.dumps({"saved": len(results), "results": [str(r) for r in results]})

    async def memory_save_url(
        self,
        url: str,
        project: str | None = None,
        tags: list[str] | None = None,
    ) -> str:
        """URL からコンテンツを取得して記憶として保存する。

        Note:
            asyncio.Semaphore によりプロセスレベルで URL 取得の並行数を制限する。
            MCPサーバーが複数プロセスで起動された場合は制限を超過する可能性がある。

        Args:
            url: 取得する URL。
            project: プロジェクト名。
            tags: タグのリスト。

        Returns:
            保存結果の JSON 文字列。
        """
        await self._ensure_initialized()
        assert self._orchestrator is not None
        assert self._url_semaphore is not None

        effective_tags: list[str] = tags if tags is not None else []
        metadata: dict[str, Any] = {"tags": effective_tags}
        if project is not None:
            metadata["project"] = project

        async with self._url_semaphore:
            results = await self._orchestrator.save_url(url, metadata=metadata)

        return json.dumps({"saved": len(results), "results": [str(r) for r in results]})

    async def memory_search(
        self,
        query: str,
        project: str | None = None,
        memory_type: str | None = None,
        top_k: int = 10,
        max_tokens: int | None = None,
    ) -> str:
        """コンテキストを検索する。

        Args:
            query: 検索クエリ。
            project: プロジェクトフィルタ。
            memory_type: 記憶種別フィルタ（"episodic", "semantic", "procedural"）。
            top_k: 返す最大件数。
            max_tokens: 最大トークン数。

        Returns:
            検索結果の JSON 文字列。
        """
        await self._ensure_initialized()
        assert self._orchestrator is not None

        result = await self._orchestrator.search(
            query,
            project=project,
            memory_type=memory_type,
            top_k=top_k,
            max_tokens=max_tokens,
        )
        return json.dumps(result, default=str)

    async def memory_search_graph(
        self,
        query: str,
        edge_types: list[str] | None = None,
        depth: int = 2,
        project: str | None = None,
    ) -> str:
        """グラフトラバーサル検索を実行する。

        Args:
            query: 起点となるクエリ。
            edge_types: フィルタするエッジ種別。
            depth: トラバーサル深さ。
            project: プロジェクトフィルタ。

        Returns:
            グラフ検索結果の JSON 文字列。
        """
        await self._ensure_initialized()
        assert self._orchestrator is not None

        result = await self._orchestrator.search_graph(
            query,
            edge_types=edge_types,
            depth=depth,
            project=project,
        )
        return json.dumps(result, default=str)

    async def memory_delete(self, memory_id: str) -> str:
        """記憶を削除する。

        Args:
            memory_id: 削除する記憶の ID。

        Returns:
            削除結果の JSON 文字列。
        """
        await self._ensure_initialized()
        assert self._orchestrator is not None

        deleted = await self._orchestrator.delete(memory_id)
        return json.dumps({"deleted": deleted, "memory_id": memory_id})

    async def memory_prune(
        self,
        older_than_days: int = 90,
        dry_run: bool = True,
    ) -> str:
        """古い記憶を削除する。

        Args:
            older_than_days: この日数より古い記憶を削除対象とする。
            dry_run: True の場合は削除せず対象件数のみを返す（デフォルト True）。

        Returns:
            削除結果の JSON 文字列。
        """
        await self._ensure_initialized()
        assert self._orchestrator is not None

        count = await self._orchestrator.prune(
            older_than_days=older_than_days,
            dry_run=dry_run,
        )
        return json.dumps(
            {
                "count": count,
                "dry_run": dry_run,
                "older_than_days": older_than_days,
            }
        )

    async def memory_stats(self, project: str | None = None) -> str:
        """ストレージの統計情報を返す。

        Args:
            project: プロジェクトフィルタ（None の場合は全体）。

        Returns:
            統計情報の JSON 文字列。
        """
        await self._ensure_initialized()
        assert self._orchestrator is not None

        result = await self._orchestrator.stats(project=project)
        return json.dumps(result, default=str)

    async def memory_list_projects(self) -> str:
        """プロジェクト一覧を返す。"""
        await self._ensure_initialized()
        assert self._orchestrator is not None

        projects = await self._orchestrator.list_projects()
        return json.dumps({"projects": projects})


# ---------------------------------------------------------------------------
# グローバルサーバーインスタンス
# ---------------------------------------------------------------------------

_server = ChronosServer()


# ---------------------------------------------------------------------------
# FastMCP ツール登録
# ---------------------------------------------------------------------------


@mcp.tool()
async def memory_save(
    content: str,
    source: str = "conversation",
    project: str | None = None,
    tags: list[str] | None = None,
    importance: float | None = None,
) -> str:
    """テキストコンテンツを記憶として保存する。

    Args:
        content: 保存するテキスト。
        source: ソース種別（"conversation", "manual", "url"）。デフォルト "conversation"。
        project: プロジェクト名。
        tags: タグのリスト。
        importance: 重要度スコア（0.0〜1.0）。
    """
    return await _server.memory_save(
        content=content,
        source=source,
        project=project,
        tags=tags,
        importance=importance,
    )


@mcp.tool()
async def memory_save_url(
    url: str,
    project: str | None = None,
    tags: list[str] | None = None,
) -> str:
    """URL からコンテンツを取得して記憶として保存する。

    Args:
        url: 取得する URL。
        project: プロジェクト名。
        tags: タグのリスト。
    """
    return await _server.memory_save_url(url=url, project=project, tags=tags)


@mcp.tool()
async def memory_search(
    query: str,
    project: str | None = None,
    memory_type: str | None = None,
    top_k: int = 10,
    max_tokens: int | None = None,
) -> str:
    """コンテキストを検索する。

    Args:
        query: 検索クエリ。
        project: プロジェクトフィルタ。
        memory_type: 記憶種別フィルタ（"episodic", "semantic", "procedural"）。
        top_k: 返す最大件数。
        max_tokens: 最大トークン数。
    """
    return await _server.memory_search(
        query=query,
        project=project,
        memory_type=memory_type,
        top_k=top_k,
        max_tokens=max_tokens,
    )


@mcp.tool()
async def memory_search_graph(
    query: str,
    edge_types: list[str] | None = None,
    depth: int = 2,
    project: str | None = None,
) -> str:
    """グラフトラバーサル検索を実行する。

    Args:
        query: 起点となるクエリ。
        edge_types: フィルタするエッジ種別。
        depth: トラバーサル深さ。
        project: プロジェクトフィルタ。
    """
    return await _server.memory_search_graph(
        query=query,
        edge_types=edge_types,
        depth=depth,
        project=project,
    )


@mcp.tool()
async def memory_delete(memory_id: str) -> str:
    """記憶を削除する。

    Args:
        memory_id: 削除する記憶の ID。
    """
    return await _server.memory_delete(memory_id=memory_id)


@mcp.tool()
async def memory_prune(
    older_than_days: int = 90,
    dry_run: bool = True,
) -> str:
    """古い記憶を削除する。

    Args:
        older_than_days: この日数より古い記憶を削除対象とする。
        dry_run: True の場合は削除せず対象件数のみを返す（デフォルト True）。
    """
    return await _server.memory_prune(
        older_than_days=older_than_days,
        dry_run=dry_run,
    )


@mcp.tool()
async def memory_stats(project: str | None = None) -> str:
    """ストレージの統計情報を返す。

    Args:
        project: プロジェクトフィルタ（None の場合は全体）。
    """
    return await _server.memory_stats(project=project)


# ---------------------------------------------------------------------------
# FastMCP リソース登録
# ---------------------------------------------------------------------------


@mcp.resource("memory://stats")
async def stats_resource() -> str:
    """記憶ストレージの統計情報リソース。"""
    return await _server.memory_stats()


@mcp.resource("memory://projects")
async def projects_resource() -> str:
    """プロジェクト一覧リソース。"""
    return await _server.memory_list_projects()


__all__ = ["ChronosServer", "mcp"]
