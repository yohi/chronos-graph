"""ToolRegistry.hidden_tools のフィルタ挙動検証。"""

from __future__ import annotations

import pytest

from mcp_gateway.tools.registry import ToolRegistry


def _make_tool(name: str) -> dict[str, object]:
    return {"name": name, "description": f"tool {name}", "inputSchema": {"type": "object"}}


def test_default_hidden_tools_is_empty_and_preserves_all_tools() -> None:
    """hidden_tools 未指定時は従来通り全 tool を保持する (後方互換)。"""
    tools = [_make_tool("memory_save"), _make_tool("memory_search")]
    r = ToolRegistry(tools)
    names = [t["name"] for t in r.all_tools]
    assert names == ["memory_save", "memory_search"]


def test_hidden_tools_excludes_named_tools_from_all_tools() -> None:
    tools = [
        _make_tool("memory_save"),
        _make_tool("memory_save_url"),
        _make_tool("memory_search"),
    ]
    r = ToolRegistry(tools, hidden_tools=frozenset({"memory_save"}))
    names = [t["name"] for t in r.all_tools]
    assert "memory_save" not in names
    assert {"memory_save_url", "memory_search"} == set(names)


def test_hidden_tools_excludes_named_tools_from_filter_by_caps() -> None:
    tools = [_make_tool("memory_save"), _make_tool("memory_search")]
    r = ToolRegistry(tools, hidden_tools=frozenset({"memory_save"}))
    filtered = r.filter_by_caps(caps={"memory_save", "memory_search"})
    names = [t["name"] for t in filtered]
    assert names == ["memory_search"]


def test_hidden_tools_unknown_names_are_silently_ignored() -> None:
    """存在しない tool 名を hidden_tools に渡しても警告無く何も除外しない。"""
    tools = [_make_tool("memory_save")]
    r = ToolRegistry(tools, hidden_tools=frozenset({"nonexistent_tool"}))
    names = [t["name"] for t in r.all_tools]
    assert names == ["memory_save"]


def test_replace_tools_does_not_clear_hidden_tools() -> None:
    """replace_tools は _all のみ差し替え、hidden_tools は不変。"""
    initial = [_make_tool("memory_save")]
    r = ToolRegistry(initial, hidden_tools=frozenset({"memory_save"}))
    r.replace_tools([_make_tool("memory_save"), _make_tool("memory_search")])
    names = [t["name"] for t in r.all_tools]
    assert "memory_save" not in names
    assert "memory_search" in names


def test_hidden_tools_keyword_only_argument() -> None:
    """hidden_tools は keyword-only argument として渡される (誤って positional で渡せない)。"""
    tools = [_make_tool("memory_save")]
    with pytest.raises(TypeError):
        ToolRegistry(tools, frozenset({"memory_save"}))  # type: ignore[misc]
