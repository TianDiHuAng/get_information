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


_GROUP_LABELS = (("company", "公司与机构"), ("field", "方向"), ("genre", "内容形态"))


def grouped_topics(rows: Iterable[dict[str, Any]], *, per_topic: int = MAX_ITEMS) -> list[dict[str, Any]]:
    """按 topic_groups.yaml 的三组收主题。

    company 用 entity 收"以这家为主体"的报道；field / genre 用 tags 收。
    这和 `compute()` 的分类/标签是两套视角：那边是"内容属于哪类"，
    这边是"读者想按什么线索翻"。
    """
    from . import industry

    conf = industry.load("topic_groups.yaml") or {}
    rows = list(rows)
    # subjects 存的是显示名（"Anthropic" / "英伟达"），不是实体 id；
    # 用 taxonomy 里的 name + aliases + label 建一张"名字 → 命中词"表
    tax = structure.taxonomy()
    names_of: dict[str, set[str]] = {}
    for eid, ent in (tax.get("entities") or {}).items():
        names = {str(ent.get("name") or ""), str(ent.get("label") or ""), str(eid)}
        names.update(str(a) for a in (ent.get("aliases") or []))
        names_of[str(eid)] = {n.lower() for n in names if n}
    out = []
    for key, label in _GROUP_LABELS:
        entries = []
        for topic in (conf.get(key) or []):
            if not isinstance(topic, dict):
                continue
            slug = _slug(str(topic.get("slug") or topic.get("title") or ""))
            entity = str(topic.get("entity") or "")
            tags = {str(t) for t in (topic.get("tags") or [])}
            picked = []
            for row in rows:
                hit = False
                if entity and str(row.get("entity") or "") == entity:
                    hit = True
                if not hit and entity:
                    subjects = {str(x).lower() for x in (row.get("subjects") or [])}
                    wanted = set(names_of.get(entity) or {entity.lower()})
                    wanted.update(str(a).lower() for a in (topic.get("aliases") or []))
                    hit = bool(wanted & subjects)
                if not hit and tags:
                    hit = bool(tags & {str(t) for t in (row.get("tags") or [])})
                if hit:
                    picked.append({
                        "title": row.get("title") or "", "url": row.get("url") or "",
                        "source": row.get("source") or "",
                        "published": row.get("published") or row.get("day") or "",
                        "scope": row.get("scope") or "",
                    })
            if not picked:
                continue
            entries.append({"key": slug, "label": str(topic.get("title") or slug),
                            "slug": slug, "count": len(picked),
                            "latest": picked[0]["published"][:10],
                            "items": picked[:per_topic],
                            "aliases": topic.get("aliases") or []})
        entries.sort(key=lambda g: -g["count"])
        out.append({"key": key, "label": label, "topics": entries})
    return out


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
        "groups": grouped_topics(rows, per_topic=per_topic),
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


def _override():
    from .theme import override_css
    return override_css()


def _nav():
    from .theme import bottom_nav, nav_html
    return nav_html("/topics.html") + bottom_nav("/topics.html")


def _page(title: str, sub: str, body: str) -> str:
    from .share import og_tags

    desc = re.sub(r"<[^>]+>", " ", sub)
    return (f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{html.escape(title)}</title>{og_tags(title, desc)}<style>{_CSS}{_override()}</style></head><body>{_nav()}<div class="wrap">'
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
    groups_html = ""
    for group in (data.get("groups") or []):
        if not group["topics"]:
            continue
        tiles = "".join(_tile(t, f"/topics/{t['slug']}.html") for t in group["topics"])
        groups_html += f'<h2>{group["label"]}</h2><div class="grid">{tiles}</div>'
    body = (groups_html
            + f'<h2>分类</h2><div class="grid">{cats}</div>'
            + f'<h2>标签</h2><div class="grid">{tags}</div>')
    sub = (f'近 {data["days"]} 天 · {len(data["categories"])} 个分类 · '
           f'{len(data["tags"])} 个标签 · <a href="/">今日要闻</a> · '
           f'<a href="/board.html">看板</a> · <a href="/timeline.html">时间线</a>')
    return _page("Z-Bit · 主题", sub, body)


def render_topic(group: dict[str, Any], data: dict[str, Any]) -> str:
    items = "".join(
        f'<li><a href="{html.escape(i["url"], quote=True)}" target="_blank" rel="noopener">'
        f'{html.escape(i["title"])}</a>'
        f'<span class="src">{html.escape(i["source"])} · {html.escape(i["published"][:10])}</span></li>'
        for i in group["items"])
    body = f'<ul class="list">{items}</ul>'
    sub = (f'{group["count"]} 条 · 近 {data["days"]} 天 · '
           f'<a href="/topics.html">全部主题</a>')
    return _page(f'Z-Bit · {group["label"]}', sub, body)


def build(site_root: Path | None = None, days: int = 30) -> dict[str, Any]:
    rows = store.structure_history(days=days)
    data = compute(rows, days=days)
    root = (site_root or SITE)
    root.mkdir(parents=True, exist_ok=True)
    (root / "topics.html").write_text(render_index(data), encoding="utf-8")

    written = 1
    seen: set[str] = set()
    flat_groups = [t for g in (data.get("groups") or []) for t in g["topics"]]
    for group in data["categories"] + data["tags"] + flat_groups:
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
        "groups": len([g for g in (data.get("groups") or []) if g["topics"]]),
        "rows": len(rows),
    }
