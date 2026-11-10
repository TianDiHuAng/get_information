"""MCP 服务：JSON-RPC 协议正确性 + 工具真的能取到数据。

协议部分最容易错的是：通知（没有 id）不能有响应、坏 JSON 不能把循环打断、
未知方法要回 -32601。这三条都有测试。
"""

import io
import json

import pytest

from collector import mcp, store
from collector.model import Item


@pytest.fixture(autouse=True)
def seeded(tmpdb):
    items = [
        Item(source="anthropic", title="Anthropic 发布 Claude Fable 5.2",
             url="https://a/1", layer="primary", summary="官方公告，价格下调",
             published="2026-11-11T08:00:00+08:00"),
        Item(source="hackernews", title="Fable 5.2 登顶榜单",
             url="https://a/2", layer="rank", summary="190 条评论",
             published="2026-11-11T09:00:00+08:00"),
    ]
    for score, it in zip((90, 85), items):
        it.extra["attention"] = {"available": True, "score": score, "itype": "model_release",
                                 "reason": "正式发布且价格变化清楚"}
        it.extra["structure"] = {"category": "model_release", "tags": ["开源"]}
    store.upsert_items(items)


def test_tool_names_share_prefix():
    names = mcp.tool_names()
    assert len(set(names.values())) == 7
    assert all(n.startswith(mcp.prefix() + "_") for n in names.values())


def test_initialize_declares_tools():
    r = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert r["result"]["capabilities"]["tools"]
    assert r["result"]["protocolVersion"]


def test_tools_list_has_schemas():
    r = mcp.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    tools = r["result"]["tools"]
    assert len(tools) == 7
    for t in tools:
        assert t["name"] and t["description"] and t["inputSchema"]["type"] == "object"


def test_notification_has_no_response():
    assert mcp.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_unknown_method_returns_error():
    r = mcp.handle({"jsonrpc": "2.0", "id": 3, "method": "nope"})
    assert r["error"]["code"] == -32601


def test_latest_returns_items():
    r = mcp.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                    "params": {"name": mcp.tool_names()["latest"], "arguments": {"limit": 5}}})
    data = json.loads(r["result"]["content"][0]["text"])
    assert data["count"] == 2
    assert data["items"][0]["title"].startswith("Anthropic")
    assert data["items"][0]["score"] == 90


def test_latest_respects_limit():
    r = mcp.handle({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                    "params": {"name": mcp.tool_names()["latest"], "arguments": {"limit": 1}}})
    assert json.loads(r["result"]["content"][0]["text"])["count"] == 1


def test_search_finds_by_keyword():
    r = mcp.handle({"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                    "params": {"name": mcp.tool_names()["search"],
                               "arguments": {"query": "Fable"}}})
    data = json.loads(r["result"]["content"][0]["text"])
    assert data["count"] >= 1


def test_search_requires_query():
    text = mcp.call_tool(mcp.tool_names()["search"], {})
    assert "query" in json.loads(text)["error"]


def test_unknown_tool_returns_error_text():
    text = mcp.call_tool("nope_tool", {})
    assert "未知工具" in json.loads(text)["error"]


def test_story_requires_id():
    text = mcp.call_tool(mcp.tool_names()["story"], {})
    assert "id" in json.loads(text)["error"]


def test_serve_round_trip():
    """stdio 循环：一行一个 JSON，坏行不打断。"""
    lines = "\n".join([
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}),
        "这不是 JSON",
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
    ]) + "\n"
    out = io.StringIO()
    mcp.serve(io.StringIO(lines), out)
    responses = [json.loads(x) for x in out.getvalue().splitlines() if x.strip()]
    assert len(responses) == 3
    assert responses[0]["result"]["serverInfo"]["name"] == "zbit"
    assert responses[1]["error"]["code"] == -32700
    assert len(responses[2]["result"]["tools"]) == 7


def test_daily_report_tool(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp, "DATA", tmp_path)
    (tmp_path / "digest-2026-11-10.md").write_text("# 日报\n\n- 一条新闻\n", encoding="utf-8")
    text = mcp.call_tool(mcp.tool_names()["daily"], {"date": "2026-11-10"})
    data = json.loads(text)
    assert data["kind"] == "daily" and "一条新闻" in data["markdown"]


def test_daily_report_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp, "DATA", tmp_path)
    assert "error" in json.loads(mcp.call_tool(mcp.tool_names()["daily"], {}))
