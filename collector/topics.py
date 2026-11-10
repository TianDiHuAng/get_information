"""主题页与标签页：把结构化结果变成可以翻的页面。

数据早就有了（`structures` 表里 8 个分类 + 标签 + 主体），但之前只以 feed 的形式存在。
这里补上"人怎么逛"：

- `/topics.html`：分类与标签的总览，各带条数与最近几条；
- `/topics/<key>.html`：单个分类/标签的历史列表。

只读库、不调模型。分类名用 `config/taxonomy.yaml` 里的中文标签，
没配到的 key 原样显示（不猜、不改写用户数据）。
"""

from __future__ import annotations

import html
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from . import store, structure

ROOT = Path(__file__).parent.parent
SITE = ROOT / "site"
MAX_ITEMS = 40


def _label(category: str, tax: dict[str, Any]) -> str:
    cats = tax.get("categories") or {}
    return str((cats.get(category) or {}).get("label") or category)


def _slug(key: str) -> str:
    """分类 key 直接用在网址里；标签和主体要转成安全文件名。"""
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "-", key).strip("-") or "topic"


def compute(rows: Iterable[dict[str, Any]], *, days: int = 30,
            per_topic: int = MAX_ITEMS) -> dict[str, Any]:
    """按分类和标签分组。同一个条目可以同时出现在分类页和多个标签页里。"""
    tax = structure.taxonomy()
    cats: dict[str, list[dict[str, Any]]] = defaultdict(list)
    tags: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in rows:
        entry = {
            "title": row.get("title") or "",
            "url": row.get("url") or "",
            "source": row.get("source") or "",
            "published": row.get("published") or row.get("day") or "",
            "scope": row.get("scope") or "",
        }
        category = row.get("category") or ""
        if category:
            cats[category].append(entry)
        for tag in row.get("tags") or []:
            tags[str(tag)].append(entry)

    def pack(group: dict[str, list[dict[str, Any]]], label_of) -> list[dict[str, Any]]:
        out = []
        for key, items in group.items():
            out.append({
                "key": key,
                "label": label_of(key),
                "slug": _slug(key),
                "count": len(items),
                "latest": items[0]["published"][:10] if items else "",
                "items": items[:per_topic],
            })
        out.sort(key=lambda g: (-g["count"], g["key"]))
        return out

    return {
        "days": days,
        "categories": pack(cats, lambda k: _label(k, tax)),
        "tags": pack(tags, lambda k: k),
        "total": len(list(rows)) if not isinstance(rows, list) else len(rows),
    }


# --------------------------------------------------------------------------- #
# 渲染
# --------------------------------------------------------------------------- #

_CSS = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin:0; background:#0b0f14; color:#e6edf3;
       font:14px/1.6 -apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; }
.wrap { max-width:1080px; margin:0 auto; padding:28px 18px 60px; }
h1 { font-size:19px; margin:0 0 4px; }
.sub { color:#6b7785; font-size:12px; margin-bottom:22px; }
a { color:#7dd3fc; text-decoration:none; }
h2 { font-size:14px; color:#b7c3d0; margin:28px 0 10px; padding-bottom:6px; border-bottom:1px solid #1f2a37; }
.grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(220px,1fr)); gap:10px; }
.tile { border:1px solid #1f2a37; border-radius:10px; padding:12px 14px; background:#0f151d; }
.tile .t { font-weight:600; }
.tile .n { color:#6b7785; font-size:12px; margin-left:6px; }
.tile ul { margin:8px 0 0; padding-left:14px; }
.tile li { font-size:12px; margin:2px 0; color:#9fb0c0; }
ul.list { margin:8px 0 0; padding-left:18px; }
ul.list li { margin:6px 0; }
.src { color:#4b5563; margin-left:6px; font-size:12px; }
.muted { color:#6b7785; }
"""


def _page(title: str, sub: str, body: str) -> str:
    from .share import og_tags

    desc = re.sub(r"<[^>]+>", " ", sub)
    return (f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{html.escape(title)}</title>{og_tags(title, desc)}<style>{_CSS}</style></head><body><div class="wrap">'
            f'<h1>{html.escape(title)}</h1><div class="sub">{sub}</div>{body}'
            f'<div class="muted" style="font-size:11px;margin-top:30px;">'
            f'只读数据库生成；分类与标签来自结构化抽取（config/prompts/structure.md）。</div>'
            f'</div></body></html>')


def _tile(group: dict[str, Any], href: str) -> str:
    tops = "".join(
        f'<li><a href="{html.escape(i["url"], quote=True)}" target="_blank" rel="noopener">'
        f'{html.escape(i["title"][:46])}</a></li>'
        for i in group["items"][:3])
    return (f'<div class="tile"><a href="{href}"><span class="t">{html.escape(group["label"])}</span>'
            f'<span class="n">{group["count"]} 条</span></a><ul>{tops}</ul></div>')


def render_index(data: dict[str, Any]) -> str:
    cats = "".join(_tile(g, f"/topics/{g['slug']}.html") for g in data["categories"]) \
        or '<div class="muted">还没有结构化结果</div>'
    tags = "".join(_tile(g, f"/topics/{g['slug']}.html") for g in data["tags"][:24]) \
        or '<div class="muted">还没有标签</div>'
    body = (f'<h2>分类</h2><div class="grid">{cats}</div>'
            f'<h2>标签</h2><div class="grid">{tags}</div>')
    sub = (f'近 {data["days"]} 天 · {len(data["categories"])} 个分类 · '
           f'{len(data["tags"])} 个标签 · <a href="/">今日要闻</a> · '
           f'<a href="/board.html">看板</a> · <a href="/timeline.html">时间线</a>')
    return _page("信息雷达 · 主题", sub, body)


def render_topic(group: dict[str, Any], data: dict[str, Any]) -> str:
    items = "".join(
        f'<li><a href="{html.escape(i["url"], quote=True)}" target="_blank" rel="noopener">'
        f'{html.escape(i["title"])}</a>'
        f'<span class="src">{html.escape(i["source"])} · {html.escape(i["published"][:10])}</span></li>'
        for i in group["items"])
    body = f'<ul class="list">{items}</ul>'
    sub = (f'{group["count"]} 条 · 近 {data["days"]} 天 · '
           f'<a href="/topics.html">全部主题</a>')
    return _page(f'信息雷达 · {group["label"]}', sub, body)


def build(site_root: Path | None = None, days: int = 30) -> dict[str, Any]:
    rows = store.structure_history(days=days)
    data = compute(rows, days=days)
    root = (site_root or SITE)
    root.mkdir(parents=True, exist_ok=True)
    (root / "topics.html").write_text(render_index(data), encoding="utf-8")

    written = 1
    seen: set[str] = set()
    for group in data["categories"] + data["tags"]:
        if group["slug"] in seen:      # 分类和标签撞名时，先写的赢
            continue
        seen.add(group["slug"])
        target = root / "topics" / f"{group['slug']}.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_topic(group, data), encoding="utf-8")
        written += 1
    return {
        "file": str(root / "topics.html"),
        "pages": written,
        "categories": len(data["categories"]),
        "tags": len(data["tags"]),
        "rows": len(rows),
    }
