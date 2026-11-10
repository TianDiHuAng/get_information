"""整站页面：仿 AIHOT 的网站结构，把已经算好的东西都摊开来。

AIHOT 的站是"一个公开读取层，多个出口"，页面大致是：
精选 / 全部 / 热门(事件) / 主题 / 日报 / 周报 / 月报 / 事件页 / 搜索。

我们之前只有首页 + 主题 + 时间线 + 看板 —— 数据和接口都在，但没人能点进去看。
这个模块补齐剩下的：日报（按期）、周报月报、事件榜与事件页、搜索页，以及一条统一导航。

三条原则：
1. **只读已有结果**，不在这里重新判断、不调模型；
2. 每页自带样式与导航，不依赖外部资源（`python -m http.server` 也能看）；
3. 任何一页失败不影响其他页 —— 整站生成是"尽力而为"，不是全有或全无。
"""

from __future__ import annotations

import html
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from . import edition, report, store, timeline

ROOT = Path(__file__).parent.parent
SITE = ROOT / "site"
DATA = ROOT / "data"

NAV = (
    ("/", "今日"),
    ("/topics.html", "主题"),
    ("/events.html", "事件"),
    ("/daily.html", "日报"),
    ("/weekly.html", "周报"),
    ("/monthly.html", "月报"),
    ("/timeline.html", "时间线"),
    ("/search.html", "搜索"),
    ("/board.html", "看板"),
)

_CSS = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin:0; background:#0b0f14; color:#e6edf3;
       font:15px/1.7 -apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; }
a { color:#7dd3fc; text-decoration:none; }
a:hover { text-decoration:underline; }
.nav { display:flex; flex-wrap:wrap; gap:14px; align-items:center;
       padding:12px 20px; border-bottom:1px solid #1f2a37; background:#0d131b;
       position:sticky; top:0; z-index:10; }
.nav .brand { font-weight:700; color:#e6edf3; margin-right:8px; }
.nav a { font-size:13px; color:#9fb0c0; }
.nav a.on { color:#7dd3fc; font-weight:600; }
.wrap { max-width:900px; margin:0 auto; padding:26px 20px 70px; }
h1 { font-size:21px; margin:0 0 4px; }
.sub { color:#6b7785; font-size:12px; margin-bottom:24px; }
h2 { font-size:15px; color:#b7c3d0; margin:30px 0 12px; padding-bottom:7px;
     border-bottom:1px solid #1f2a37; }
ol, ul { padding-left:20px; margin:0; }
li { margin:8px 0; }
.meta { color:#6b7785; font-size:12px; margin-left:6px; }
.sum { color:#9fb0c0; font-size:13px; margin:2px 0 0; }
.muted { color:#6b7785; }
.card { border:1px solid #1f2a37; border-radius:10px; padding:13px 15px; background:#0f151d;
        margin-bottom:12px; }
.card h3 { font-size:15px; margin:0 0 6px; }
.tag { display:inline-block; border:1px solid #22303d; background:#16202b; color:#9fb0c0;
       border-radius:999px; padding:1px 9px; font-size:11px; margin:2px 5px 2px 0; }
.kv { color:#6b7785; font-size:12px; }
blockquote { margin:10px 0; padding:8px 14px; border-left:3px solid #1f2a37; color:#9fb0c0; }
table { width:100%; border-collapse:collapse; font-size:13px; }
th, td { text-align:left; padding:5px 8px; border-bottom:1px solid #18212b; }
th { color:#6b7785; font-weight:500; }
input[type=search] { width:100%; padding:10px 12px; font-size:15px; border-radius:8px;
                     border:1px solid #22303d; background:#0f151d; color:#e6edf3; }
footer { margin-top:40px; color:#4b5563; font-size:11px; }
"""


# --------------------------------------------------------------------------- #
# Markdown → HTML（只支持我们自己的日报用到的语法）
# --------------------------------------------------------------------------- #

_INLINE = (
    (re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)"), r'<a href="\2" target="_blank" rel="noopener">\1</a>'),
    (re.compile(r"\*\*([^*]+)\*\*"), r"<strong>\1</strong>"),
    (re.compile(r"`([^`]+)`"), r"<code>\1</code>"),
)
# 有序列表的 "12. " 前缀（Python 3.11 的 f-string 里不能写反斜杠，所以提到外面）
ORDERED = re.compile(r"^\d+\.\s")


def md_to_html(text: str) -> str:
    """把日报/周报的 Markdown 转成 HTML。

    刻意只支持我们实际用到的几种语法（标题、列表、引用、表格不需要），
    引第三方 Markdown 库会把一件小事变成一个依赖。
    """
    out: list[str] = []
    in_ul = False
    in_ol = False

    def close_lists() -> None:
        nonlocal in_ul, in_ol
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if in_ol:
            out.append("</ol>")
            in_ol = False

    def inline(s: str) -> str:
        s = html.escape(s)
        for pattern, repl in _INLINE:
            s = pattern.sub(repl, s)
        return s

    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            close_lists()
            continue
        if line.startswith("# "):
            close_lists()
            out.append(f"<h1>{inline(line[2:])}</h1>")
        elif line.startswith("## "):
            close_lists()
            out.append(f"<h2>{inline(line[3:])}</h2>")
        elif line.startswith("### "):
            close_lists()
            out.append(f"<h3>{inline(line[4:])}</h3>")
        elif line.startswith("> "):
            close_lists()
            out.append(f"<blockquote>{inline(line[2:])}</blockquote>")
        elif re.match(r"^\d+\.\s", line):
            if not in_ol:
                close_lists()
                out.append("<ol>")
                in_ol = True
            out.append("<li>" + inline(ORDERED.sub("", line)) + "</li>")
        elif line.startswith("- "):
            if not in_ul:
                close_lists()
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{inline(line[2:])}</li>")
        elif line.startswith("   ") and (in_ul or in_ol):
            # 缩进续行：并到上一条里
            if out:
                out[-1] = out[-1][:-5] + " " + inline(line.strip()) + "</li>"
        elif line.strip() == "---":
            close_lists()
            out.append("<hr>")
        else:
            close_lists()
            out.append(f"<p>{inline(line)}</p>")
    close_lists()
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# 页面骨架
# --------------------------------------------------------------------------- #

def _esc(text: Any) -> str:
    return html.escape(str(text or ""))


def nav_html(active: str) -> str:
    links = []
    for href, label in NAV:
        cls = ' class="on"' if href == active else ""
        links.append(f'<a href="{href}"{cls}>{label}</a>')
    return f'<div class="nav"><span class="brand">信息雷达</span>{"".join(links)}</div>'


def shell(title: str, body: str, *, active: str = "", sub: str = "") -> str:
    sub_html = f'<div class="sub">{sub}</div>' if sub else ""
    return (f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{_esc(title)}</title><style>{_CSS}</style></head><body>'
            f'{nav_html(active)}<div class="wrap"><h1>{_esc(title)}</h1>{sub_html}{body}'
            f'<footer>只读生成，不调模型。数据来自每日采集与评分结果。</footer>'
            f'</div></body></html>')


# --------------------------------------------------------------------------- #
# 日报 / 周报 / 月报
# --------------------------------------------------------------------------- #

def _issues(prefix: str, folder: Path | None = None) -> list[Path]:
    # 用模块级 DATA 的当前值（而不是定义时的默认值），测试和换目录才生效
    base = folder or DATA
    return sorted(base.glob(f"{prefix}-*.md"), reverse=True)


def build_issue_index(kind: str, *, site_root: Path | None = None) -> dict[str, Any]:
    """`/daily.html` / `/weekly.html` / `/monthly.html`：期号列表。"""
    root = site_root or SITE
    files = _issues({"daily": "digest", "weekly": "weekly", "monthly": "monthly"}[kind])
    label = {"daily": "日报", "weekly": "周报", "monthly": "月报"}[kind]
    rows = []
    for path in files:
        day = path.stem.split("-", 1)[1]
        size = path.stat().st_size // 1024
        rows.append(
            f'<div class="card"><h3><a href="/{kind}/{_esc(day)}.html">{_esc(day)} · {label}</a></h3>'
            f'<div class="kv">{size} KB</div></div>')
    body = "".join(rows) or '<p class="muted">还没有出刊记录。跑一次 python run.py 就会生成。</p>'
    out = root / f"{kind}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(shell(f"信息雷达 · {label}", body, active=f"/{kind}.html",
                         sub=f"共 {len(files)} 期"), encoding="utf-8")

    written = 1
    for path in files:
        day = path.stem.split("-", 1)[1]
        target = root / kind / f"{day}.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            md = path.read_text(encoding="utf-8")
        except OSError:
            continue
        target.write_text(shell(f"{label} · {day}", md_to_html(md), active=f"/{kind}.html",
                                sub=f'<a href="/{kind}.html">← 全部{label}</a>'),
                          encoding="utf-8")
        written += 1
    return {"file": str(out), "issues": len(files), "pages": written}


# --------------------------------------------------------------------------- #
# 事件页
# --------------------------------------------------------------------------- #

def _event_rows() -> list[dict[str, Any]]:
    """事件 + 成员数/来源数。用 event_dump 一次拿全，避免 N+1 查询。"""
    try:
        rows = store.event_dump(days=120)
    except Exception:
        return []
    buckets: dict[int, dict[str, Any]] = {}
    for row in rows:
        eid = row.get("event_id")
        if eid is None:
            continue
        bucket = buckets.setdefault(int(eid), {
            "id": int(eid), "title": row.get("event_title") or "",
            "first_at": row.get("first_at") or "", "last_at": row.get("last_at") or "",
            "members": [],
        })
        bucket["members"].append({
            "title": row.get("item_title") or "", "url": row.get("url") or "",
            "source": row.get("source") or "", "layer": row.get("layer") or "",
            "published": row.get("published") or "",
        })
    for bucket in buckets.values():
        bucket["sources"] = len({m["source"] for m in bucket["members"] if m["source"]})
        bucket["layer"] = "primary" if any(m["layer"] == "primary" for m in bucket["members"]) else "rank"
    return sorted(buckets.values(), key=lambda b: (-b["sources"], b["first_at"]), reverse=False)


def build_events(site_root: Path | None = None) -> dict[str, Any]:
    root = site_root or SITE
    events = _event_rows()

    cards = []
    for ev in events:
        cards.append(
            f'<div class="card"><h3><a href="/events/{ev["id"]}.html">{_esc(ev["title"])}</a></h3>'
            f'<div class="kv">{_esc(ev["first_at"][:10])} · {len(ev["members"])} 篇 · '
            f'{ev["sources"]} 家</div></div>')
    out = root / "events.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(shell("信息雷达 · 事件", "".join(cards) or '<p class="muted">还没有聚合出事件。</p>',
                         active="/events.html", sub=f"共 {len(events)} 个事件"),
                   encoding="utf-8")

    written = 1
    for ev in events:
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for m in ev["members"]:
            key = "官方" if m["layer"] == "primary" else ("媒体" if m["layer"] in ("rank", "broad", "search") else "社区")
            groups[key].append(m)
        blocks = []
        for name in ("官方", "媒体", "社区"):
            items = groups.get(name) or []
            if not items:
                continue
            lis = "".join(
                f'<li><a href="{_esc(m["url"])}" target="_blank" rel="noopener">{_esc(m["title"])}</a>'
                f'<span class="meta">{_esc(m["source"])} · {_esc(m["published"][:10])}</span></li>'
                for m in items)
            blocks.append(f"<h2>{name}（{len(items)}）</h2><ul>{lis}</ul>")
        target = root / "events" / f"{ev['id']}.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(shell(ev["title"], "".join(blocks), active="/events.html",
                                sub=f'{_esc(ev["first_at"][:10])} · {len(ev["members"])} 篇报道 · '
                                    f'<a href="/events.html">← 全部事件</a>'),
                          encoding="utf-8")
        written += 1
    return {"file": str(out), "events": len(events), "pages": written}


# --------------------------------------------------------------------------- #
# 搜索页
# --------------------------------------------------------------------------- #

def build_search(payload: dict[str, Any], site_root: Path | None = None) -> dict[str, Any]:
    """客户端搜索：把当天的条目嵌进页面，不依赖接口（离线也能用）。"""
    root = site_root or SITE
    rows = []
    for it in payload.get("items") or []:
        extra = it.get("extra") or {}
        st = extra.get("structure") or {}
        rows.append({
            "t": it.get("title") or "",
            "u": it.get("url") or "",
            "s": it.get("source") or "",
            "d": (it.get("published") or "")[:10],
            "c": st.get("category") or "",
            "x": " ".join(str(it.get("summary") or "").split())[:160],
        })
    data = json.dumps(rows, ensure_ascii=False).replace("</", "<\\/")
    body = (
        '<p class="muted" style="margin-bottom:10px;">在今天的 '
        f'{len(rows)} 条里搜标题与摘要（纯前端，不联网）。</p>'
        '<input type="search" id="q" placeholder="输入关键词，例如「模型」「开源」「芯片」" autofocus>'
        '<div id="out" style="margin-top:16px;"></div>'
        f'<script>const DATA={data};'
        "const q=document.getElementById('q'),out=document.getElementById('out');"
        "function esc(s){return String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}"
        "function run(){const k=q.value.trim().toLowerCase();out.innerHTML='';"
        "if(!k){out.innerHTML='<p class=\"muted\">今天共 '+DATA.length+' 条。</p>';return;}"
        "const hit=DATA.filter(d=>(d.t+' '+d.x+' '+d.c).toLowerCase().includes(k));"
        "out.innerHTML='<p class=\"muted\">命中 '+hit.length+' 条</p>'+hit.map(d=>"
        "'<div class=\"card\"><h3><a href=\"'+esc(d.u)+'\" target=\"_blank\" rel=\"noopener\">'+esc(d.t)"
        "+'</a></h3><div class=\"kv\">'+esc(d.s)+' · '+esc(d.d)+'</div>"
        "+(d.x?'<p class=\"sum\">'+esc(d.x)+'</p>':'')+'</div>').join('');}"
        "q.addEventListener('input',run);run();</script>")
    out = root / "search.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(shell("信息雷达 · 搜索", body, active="/search.html",
                         sub="今天采集到的全部条目"), encoding="utf-8")
    return {"file": str(out), "items": len(rows)}


# --------------------------------------------------------------------------- #
# 一把生成
# --------------------------------------------------------------------------- #

def build(payload: dict[str, Any], site_root: Path | None = None) -> dict[str, Any]:
    """生成所有页面。任何一页失败都只影响它自己。"""
    root = site_root or SITE
    stats: dict[str, Any] = {}
    for kind in ("daily", "weekly", "monthly"):
        try:
            stats[kind] = build_issue_index(kind, site_root=root)
        except Exception as e:
            stats[kind] = {"error": f"{type(e).__name__}: {e}"}
    try:
        stats["events"] = build_events(root)
    except Exception as e:
        stats["events"] = {"error": f"{type(e).__name__}: {e}"}
    try:
        stats["search"] = build_search(payload, root)
    except Exception as e:
        stats["search"] = {"error": f"{type(e).__name__}: {e}"}
    stats["pages"] = sum(int(v.get("pages") or 1) for v in stats.values() if isinstance(v, dict))
    return stats
