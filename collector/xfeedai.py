"""XFeed（xfeed.ai）抓取：中文 AI 创作者在 X 上的精选动态。

为什么单独接：现有的 `xfeed.py` 走 fxtwitter，只盯 config/x.yaml 里那 6 个账号。
XFeed 收录了 600+ 位 AI 创作者、按互动量排序、并且标题已经翻成中文 ——
同一件事我们只覆盖 6 个人的视角，它覆盖的是整个创作者生态。

数据源是站点自己的静态 JSON（无需 token）：
    https://xfeed.ai/data.json      条目，含 views / likes / bookmarks
    https://xfeed.ai/insights.json  工具热度榜（按提及作者数排序）

注意：
- data.json 里有重复 id（同一条被归到多个专题），按 id 去重
- 内容偏「教程 / 工具 / 开源项目」，不是行业新闻 —— 注册为 rank 层（门槛 54），
  不要放 social 层（64 会把绝大部分挡在外面，它们不是爆料型内容）
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from .model import Item
from .net import get_text

DATA_URL = "https://xfeed.ai/data.json"
INSIGHTS_URL = "https://xfeed.ai/insights.json"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ZBit/1.0)", "Accept": "application/json"}


def _get_json(url: str, timeout: int = 60) -> dict[str, Any]:
    text = get_text(url, headers=_HEADERS, timeout=timeout)
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        return {}


def fetch(days: int = 3, limit: int = 40, **_: object) -> list[Item]:
    """取最近 N 天的条目，按点赞数排序后返回。"""
    data = _get_json(DATA_URL, timeout=90)
    rows = data.get("items") or []
    if not rows:
        return []

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    seen: set[str] = set()
    picked: list[dict[str, Any]] = []
    for r in rows:
        rid = str(r.get("id") or "")
        if not rid or rid in seen:
            continue
        created = str(r.get("createdAt") or "")
        if created[:10] < cutoff:
            continue
        seen.add(rid)
        picked.append(r)

    picked.sort(key=lambda r: -(r.get("likes") or 0))
    items: list[Item] = []
    for r in picked[:limit]:
        title = str(r.get("displayTitle") or r.get("title") or "").strip()
        if not title:
            continue
        summary = str(r.get("displaySummary") or r.get("excerptZh")
                      or r.get("excerpt") or "").strip()
        extra = {
            "author": r.get("author") or "",
            "handle": r.get("handle") or "",
            "category": r.get("category") or "",
            "kind": r.get("type") or "",
            "views": r.get("views") or 0,
            "likes": r.get("likes") or 0,
            "bookmarks": r.get("bookmarks") or 0,
            "official": bool(r.get("isOfficial")),
        }
        items.append(Item(
            source="xfeedai",
            layer="rank",
            region="overseas",
            title=title,
            url=str(r.get("url") or ""),
            published=str(r.get("createdAt") or "")[:19].replace("Z", "+00:00"),
            summary=summary[:400],
            heat=float(r.get("likes") or 0),
            lang="zh",
            author=str(r.get("handle") or ""),
            extra=extra,
        ))
    return items


def hot_tools(days: int = 7, limit: int = 12) -> list[dict[str, Any]]:
    """工具热度榜：按近 N 天提及它的不同作者数排序。"""
    data = _get_json(INSIGHTS_URL, timeout=60)
    tools = data.get("tools") or {}
    rows = []
    for key, val in tools.items():
        rows.append({
            "key": key,
            "total": int(val.get("total") or 0),
            "groups": val.get("groups") or [],
        })
    rows.sort(key=lambda x: -x["total"])
    return rows[:limit]


def authors() -> list[dict[str, Any]]:
    """精选作者名单（16 位，逐条审阅过，不按曝光排名）。"""
    data = _get_json("https://xfeed.ai/author-manifest.json", timeout=60)
    return list(data.get("authors") or [])


def tool_guides(min_practice: int = 3, limit: int = 12) -> list[dict[str, Any]]:
    """工具实操手册：每个工具的 practice（能做什么）与 limitations（局限）。

    insights.json 的分组是 beginner / practice / limitations / discussion，
    其中 practice 与 limitations 对读者最有用 —— 一个讲怎么做，一个讲坑在哪。
    """
    data = _get_json(INSIGHTS_URL, timeout=60)
    tools = data.get("tools") or {}
    out = []
    for key, val in tools.items():
        groups = {g.get("key"): g for g in (val.get("groups") or [])}
        practice = (groups.get("practice") or {}).get("posts") or []
        limits = (groups.get("limitations") or {}).get("posts") or []
        if len(practice) < min_practice:
            continue
        out.append({
            "key": key,
            "total": int(val.get("total") or 0),
            "practice": practice,
            "limitations": limits,
        })
    out.sort(key=lambda x: -x["total"])
    return out[:limit]


def avatar_bytes(url: str, timeout: int = 20) -> bytes:
    """取创作者头像（相对路径补域名）。"""
    if not url:
        return b""
    if url.startswith("/"):
        url = "https://xfeed.ai" + url
    try:
        import requests

        r = requests.get(url, headers=_HEADERS, timeout=timeout)
        if r.status_code == 200 and 200 < len(r.content) < 400_000:
            return r.content
    except Exception:
        pass
    return b""
