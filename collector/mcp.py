"""MCP 服务：把公开读取层包成 Agent 能调用的工具。

对齐 AIHOT 的 MCP（`apps/api/src/routes/mcp.ts` + `packages/contracts/src/mcp.ts`）：

- 工具名 = `<前缀>_<能力>`，前缀在 `config/industry.yaml` 的 `mcp_prefix`；
- 七个工具与 `/api/v1/agent` 的能力一一对应；
- 只读，不调模型，不写库；
- 走 stdio，一行一个 JSON-RPC 对象（MCP 的标准传输）。

用法（在 Claude Desktop / Cursor 的 MCP 配置里）：

```json
{"mcpServers": {"zbit": {"command": "python", "args": ["D:/AI/project/Get_Information/mcp_server.py"]}}}
```

或者手动试：

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python mcp_server.py
```
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Callable

from . import store

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"


def prefix() -> str:
    try:
        from . import industry

        return str(industry.settings().get("mcp_prefix") or "zbit")
    except Exception:
        return "zbit"


def tool_names() -> dict[str, str]:
    p = prefix()
    return {
        "latest": f"{p}_get_latest",
        "search": f"{p}_search",
        "hot": f"{p}_get_hot_topics",
        "story": f"{p}_get_story",
        "daily": f"{p}_get_daily",
        "weekly": f"{p}_get_weekly",
        "monthly": f"{p}_get_monthly",
    }


def _schema(**props: Any) -> dict[str, Any]:
    return {"type": "object", "properties": props, "additionalProperties": False}


def tool_specs() -> list[dict[str, Any]]:
    """工具清单。顺序固定，描述写清楚「什么时候该用」。"""
    names = tool_names()
    limit = {"type": "integer", "minimum": 1, "maximum": 100,
             "description": "最多返回几条，默认 20"}
    return [
        {"name": names["latest"], "description": "今天精选的条目，含评分与推荐理由。想知道「今天有什么值得看」时用这个。",
         "inputSchema": _schema(limit=limit)},
        {"name": names["search"], "description": "按关键词搜最近 14 天的条目（标题、摘要、分类）。",
         "inputSchema": _schema(query={"type": "string", "description": "关键词"},
                                limit=limit)},
        {"name": names["hot"], "description": "按热度排序的事件榜：同一件事的多篇报道合成一个事件。",
         "inputSchema": _schema(limit=limit)},
        {"name": names["story"], "description": "一个事件的详情：官方、媒体、社区各说了什么，附原文链接。",
         "inputSchema": _schema(id={"type": "integer", "description": "事件 id（从 get_hot_topics 拿）"})},
        {"name": names["daily"], "description": "某天的日报全文（Markdown）。不传日期取最新一期。",
         "inputSchema": _schema(date={"type": "string", "description": "YYYY-MM-DD"})},
        {"name": names["weekly"], "description": "某周的周报全文（Markdown）。",
         "inputSchema": _schema(date={"type": "string", "description": "YYYY-MM-DD（周内任意一天）"})},
        {"name": names["monthly"], "description": "某月的月报全文（Markdown）。",
         "inputSchema": _schema(date={"type": "string", "description": "YYYY-MM-DD（月内任意一天）"})},
    ]


# --------------------------------------------------------------------------- #
# 取数
# --------------------------------------------------------------------------- #

def _item_brief(row: dict[str, Any]) -> dict[str, Any]:
    att = row.get("attention") or {}
    st = row.get("structure") or {}
    return {
        "title": row.get("title"),
        "url": row.get("url"),
        "source": row.get("source"),
        "published": (row.get("published") or "")[:10],
        "summary": " ".join(str(row.get("summary") or "").split())[:300],
        "score": att.get("score"),
        "reason": att.get("reason"),
        "category": st.get("category"),
        "tags": st.get("tags") or [],
    }


def _latest(args: dict[str, Any]) -> dict[str, Any]:
    limit = min(int(args.get("limit") or 20), 100)
    rows = store.all_items(limit=limit)
    return {"date": store.content_day(), "count": len(rows),
            "items": [_item_brief(r) for r in rows]}


def _search(args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query") or "").strip().lower()
    if not query:
        return {"error": "query 不能为空"}
    limit = min(int(args.get("limit") or 20), 100)
    hits = []
    for offset in range(14):
        try:
            day = store.shift_day(store.content_day(), -offset) if offset else store.content_day()
            rows = store.all_items(day, limit=500, include_archived=True)
        except Exception:
            rows = []
        for row in rows:
            text = f'{row.get("title") or ""} {row.get("summary") or ""} ' \
                   f'{(row.get("structure") or {}).get("category") or ""}'.lower()
            if query in text:
                hits.append((day, row))
        if len(hits) >= limit:
            break
    out = []
    for day, row in hits[:limit]:
        brief = _item_brief(row)
        brief["day"] = day
        out.append(brief)
    return {"query": query, "count": len(out), "items": out}


def _hot(args: dict[str, Any]) -> dict[str, Any]:
    limit = min(int(args.get("limit") or 20), 100)
    try:
        heat = store.latest_heat()
        rows = store.event_dump(days=14)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    buckets: dict[int, dict[str, Any]] = {}
    for row in rows:
        eid = row.get("event_id")
        if eid is None:
            continue
        b = buckets.setdefault(int(eid), {"id": int(eid), "title": row.get("event_title") or "",
                                          "first": (row.get("first_at") or "")[:10],
                                          "sources": set(), "count": 0})
        b["sources"].add(row.get("source") or "")
        b["count"] += 1
    ranked = sorted(buckets.values(), key=lambda b: -heat.get(b["id"], 0.0))[:limit]
    return {"count": len(ranked), "events": [
        {"id": b["id"], "title": b["title"], "heat": round(heat.get(b["id"], 0.0), 1),
         "sources": len(b["sources"]), "reports": b["count"], "first": b["first"]}
        for b in ranked]}


def _story(args: dict[str, Any]) -> dict[str, Any]:
    eid = args.get("id")
    if eid is None:
        return {"error": "id 不能为空"}
    try:
        rows = [r for r in store.event_dump(days=365) if int(r.get("event_id") or 0) == int(eid)]
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    if not rows:
        return {"error": f"没有这个事件：{eid}"}
    groups: dict[str, list[dict[str, Any]]] = {"官方": [], "媒体": [], "社区": []}
    for row in rows:
        layer = row.get("layer") or ""
        key = "官方" if layer == "primary" else ("媒体" if layer in ("rank", "broad", "search") else "社区")
        groups[key].append({"title": row.get("item_title"), "url": row.get("url"),
                            "source": row.get("source"),
                            "published": (row.get("published") or "")[:10]})
    return {"id": int(eid), "title": rows[0].get("event_title"),
            "first": (rows[0].get("first_at") or "")[:10],
            "reports": len(rows), "by_channel": groups}


def _report(kind: str, args: dict[str, Any]) -> dict[str, Any]:
    prefix_map = {"daily": "digest", "weekly": "weekly", "monthly": "monthly"}
    pattern = prefix_map[kind]
    date = str(args.get("date") or "").strip()
    files = sorted(DATA.glob(f"{pattern}-*.md"), reverse=True)
    if date:
        files = [f for f in files if date in f.name]
    if not files:
        return {"error": f"没有找到{kind}（date={date or '最新'}）"}
    target = files[0]
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as e:
        return {"error": str(e)}
    return {"kind": kind, "date": target.stem.split("-", 1)[1], "markdown": text}


def call_tool(name: str, args: dict[str, Any] | None = None) -> str:
    """执行一个工具，返回给 Agent 的文本。"""
    args = args or {}
    names = tool_names()
    handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
        names["latest"]: _latest,
        names["search"]: _search,
        names["hot"]: _hot,
        names["story"]: _story,
        names["daily"]: lambda a: _report("daily", a),
        names["weekly"]: lambda a: _report("weekly", a),
        names["monthly"]: lambda a: _report("monthly", a),
    }
    fn = handlers.get(name)
    if fn is None:
        return json.dumps({"error": f"未知工具：{name}"}, ensure_ascii=False)
    try:
        result = fn(args)
    except Exception as e:
        result = {"error": f"{type(e).__name__}: {e}"}
    return json.dumps(result, ensure_ascii=False)


# --------------------------------------------------------------------------- #
# JSON-RPC
# --------------------------------------------------------------------------- #

def handle(request: dict[str, Any]) -> dict[str, Any] | None:
    """处理一条 JSON-RPC 请求。通知（没有 id）返回 None。"""
    method = str(request.get("method") or "")
    rid = request.get("id")
    params = request.get("params") or {}

    def ok(result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": rid, "result": result}

    def err(code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}

    if method == "initialize":
        return ok({
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "zbit", "version": "1.0"},
        })
    if method in ("notifications/initialized", "initialized"):
        return None
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": tool_specs()})
    if method == "tools/call":
        name = str(params.get("name") or "")
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            return err(-32602, "arguments 必须是对象")
        text = call_tool(name, args)
        return ok({"content": [{"type": "text", "text": text}], "isError": False})
    return err(-32601, f"不支持的方法：{method}")


def serve(stream_in=None, stream_out=None) -> None:
    """stdio 主循环：一行一个 JSON。任何一行坏掉都不退出。"""
    stream_in = stream_in or sys.stdin
    stream_out = stream_out or sys.stdout
    for line in stream_in:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            stream_out.write(json.dumps(
                {"jsonrpc": "2.0", "id": None,
                 "error": {"code": -32700, "message": "JSON 解析失败"}}, ensure_ascii=False) + "\n")
            stream_out.flush()
            continue
        response = handle(request)
        if response is None:
            continue
        stream_out.write(json.dumps(response, ensure_ascii=False) + "\n")
        stream_out.flush()
