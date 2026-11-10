"""整站页面：对齐 AIHOT 的信息架构，视觉换成本项目的纸感风格。

AIHOT 的公开站是这些模块（按 `apps/web/app/routes.ts`）：
精选 / 全部动态 / 文章页 / 原文 / 热门 / 事件页 / 日报(列表·详情·归档) /
周报 / 月报 / 主题(列表·详情·分页) / 关于 / 条款 / 隐私 / 更新日志 /
反馈 / 更多 / 收藏 / 给 Agent 用。

这里逐个对上，另外加上本项目的四块：时间线、运行看板、离线版、纯前端搜索。

约定：
- 页面只读已有结果，不调模型；
- 每页自带样式（`theme.py`），不依赖外部资源；
- 任何一页失败只影响它自己。
"""

from __future__ import annotations

import html
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from . import store, theme

ROOT = Path(__file__).parent.parent
SITE = ROOT / "site"
DATA = ROOT / "data"

PAGE_SIZE = 20           # 全部动态：每页多少条
HOT_LIMIT = 40           # 热门：多少个事件

# --------------------------------------------------------------------------- #
# Markdown → HTML（只支持日报/周报用到的语法）
# --------------------------------------------------------------------------- #

_INLINE = (
    (re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)"), r'<a href="\2" target="_blank" rel="noopener">\1</a>'),
    (re.compile(r"\*\*([^*]+)\*\*"), r"<strong>\1</strong>"),
    (re.compile(r"`([^`]+)`"), r"<code>\1</code>"),
)
ORDERED = re.compile(r"^\d+\.\s")


def md_to_html(text: str) -> str:
    """把日报/周报的 Markdown 转成 HTML。刻意只支持实际用到的语法。"""
    out: list[str] = []
    in_ul = in_ol = False

    def close_lists() -> None:
        nonlocal in_ul, in_ol
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if in_ol:
            out.append("</ol>")
            in_ol = False

    def inline(s: str) -> str:
        s = theme.esc(s)
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
            out.append(f'<p class="muted">{inline(line[2:])}</p>')
        elif ORDERED.match(line):
            if not in_ol:
                close_lists()
                out.append('<ol class="list">')
                in_ol = True
            out.append("<li>" + inline(ORDERED.sub("", line)) + "</li>")
        elif line.startswith("- "):
            if not in_ul:
                close_lists()
                out.append('<ul class="list">')
                in_ul = True
            out.append(f"<li>{inline(line[2:])}</li>")
        elif line.startswith("   ") and (in_ul or in_ol) and out:
            out[-1] = out[-1][: -len("</li>")] + " " + inline(line.strip()) + "</li>"
        elif line.strip() == "---":
            close_lists()
            out.append("<hr>")
        else:
            close_lists()
            out.append(f"<p>{inline(line)}</p>")
    close_lists()
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# 公共片段
# --------------------------------------------------------------------------- #

def _write(path: Path, doc: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc, encoding="utf-8")


def _axes(att: dict[str, Any]) -> str:
    axes = att.get("axes") or {}
    if not axes:
        return ""
    cells = []
    for key, label in (("sig", "份量"), ("nov", "增量"), ("cred", "证据"),
                       ("reson", "共鸣"), ("act", "可用")):
        value = float(axes.get(key) or 0)
        cells.append(f'<div class="axis"><div class="bar"><i style="width:{value * 10:.0f}%"></i></div>'
                     f'{label} {value:g}</div>')
    return f'<div class="axes">{"".join(cells)}</div>'


def _score_block(att: dict[str, Any]) -> str:
    if not att.get("available"):
        return ""
    score = att.get("score")
    thr = att.get("threshold")
    reason = theme.esc(att.get("reason") or "")
    return (f'<div class="row" style="margin-top:10px;">'
            f'<span class="score">{theme.esc(score)}<small> / 门槛 {theme.esc(thr)}</small></span>'
            f'<span class="badge">{theme.esc(att.get("itype") or "")}</span>'
            f'</div>{_axes(att)}'
            + (f'<div class="reason">{reason}</div>' if reason else ""))


_FB_JS = """
<script>
document.addEventListener('click', function (e) {
  var el = e.target.closest('.fb');
  if (!el) return;
  e.preventDefault(); e.stopPropagation();
  var url = el.dataset.url, kind = el.dataset.kind;
  fetch('/api/feedback', {method:'POST', headers:{'content-type':'application/json'},
    body: JSON.stringify({url:url, kind:kind})})
    .then(function(r){return r.json()}).then(function(j){
      if (!j.ok) return;
      el.parentNode.querySelectorAll('.fb').forEach(function(b){b.classList.remove('on')});
      el.classList.add('on');
    }).catch(function(){});
});
</script>"""


def _fb_buttons(url: str) -> str:
    u = theme.esc(url)
    return (f'<span class="fb" data-url="{u}" data-kind="up" title="有用：以后多推这类">👍</span>'
            f'<span class="fb" data-url="{u}" data-kind="down" title="没用：以后少推这类">👎</span>'
            f'<span class="fb" data-star="{u}" title="收藏到本机">☆</span>')


_STAR_JS = """
<script>
(function(){
  var key='radar.starred';
  function load(){try{return JSON.parse(localStorage.getItem(key)||'[]')}catch(e){return []}}
  function save(v){try{localStorage.setItem(key,JSON.stringify(v))}catch(e){}}
  document.addEventListener('click', function(e){
    var el=e.target.closest('[data-star]'); if(!el) return;
    e.preventDefault(); e.stopPropagation();
    var url=el.dataset.star;
    var list=load(), i=list.indexOf(url);
    if(i<0){list.push(url); el.textContent='★'; el.classList.add('on');}
    else{list.splice(i,1); el.textContent='☆'; el.classList.remove('on');}
    save(list);
  });
  var list=load();
  if(list.length){document.querySelectorAll('[data-star]').forEach(function(el){
    if(list.indexOf(el.dataset.star)>=0){el.textContent='★'; el.classList.add('on');}});}
})();
</script>"""


# --------------------------------------------------------------------------- #
# 精选之外的三条主列表
# --------------------------------------------------------------------------- #

def build_all(day: str | None = None, site_root: Path | None = None) -> dict[str, Any]:
    """`/all.html` + `/all/<n>.html`：当天全部条目，带分页。"""
    root = site_root or SITE
    rows = store.all_items(day)
    pages = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
    written = 0
    for page in range(1, pages + 1):
        chunk = rows[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]
        cards = []
        for it in chunk:
            att = it.get("attention") or {}
            cats = (it.get("structure") or {}).get("category")
            badge = f'<span class="badge">{theme.esc(cats)}</span>' if cats else ""
            crowd = ""
            if int(it.get("event_size") or 0) > 1:
                crowd = f'<span class="badge hot">{it["event_size"]} 篇</span>'
            score = f'<span>{theme.esc(att.get("score"))}</span>' if att.get("available") else ""
            cards.append(
                f'<div class="card"><h3><a href="/items/{it["id"]}.html">{theme.esc(it["title"])}</a></h3>'
                f'<div class="row">{theme.esc(it["source"])}<span class="dot"></span>'
                f'{theme.esc((it.get("published") or "")[:10])}{badge}{crowd}{score}</div>'
                f'<div class="sum">{theme.esc(" ".join(str(it.get("summary") or "").split())[:150])}</div>'
                f'</div>')
        pager = []
        if page > 1:
            prev = "/all.html" if page == 2 else f"/all/{page - 1}.html"
            pager.append(f'<a href="{prev}">← 上一页</a>')
        if page < pages:
            pager.append(f'<a href="/all/{page + 1}.html">下一页 →</a>')
        body = ("".join(cards) or '<p class="muted">今天还没有条目。</p>') + \
               (f'<div class="row" style="justify-content:space-between;margin-top:18px;">'
                f'{"".join(pager)}</div>' if pager else "")
        target = root / "all.html" if page == 1 else root / "all" / f"{page}.html"
        _write(target, theme.page(
            "全部动态", body, active="/all.html",
            lead=f'今天 <b>{len(rows)}</b> 条 · 第 {page}/{pages} 页 · 按排序分从高到低'))
        written += 1
    return {"file": str(root / "all.html"), "items": len(rows), "pages": written}


def build_hot(day: str | None = None, site_root: Path | None = None) -> dict[str, Any]:
    """`/hot.html`：按事件热度排的榜（不是按文章数）。"""
    root = site_root or SITE
    try:
        rows = store.event_dump(days=14, day=day)
        heat = store.latest_heat()
    except Exception as e:
        _write(root / "hot.html", theme.page("热门事件", f'<p class="muted">暂不可用：{theme.esc(e)}</p>',
                                             active="/hot.html"))
        return {"file": str(root / "hot.html"), "events": 0, "error": str(e)}

    buckets: dict[int, dict[str, Any]] = {}
    for row in rows:
        eid = row.get("event_id")
        if eid is None:
            continue
        b = buckets.setdefault(int(eid), {"id": int(eid), "title": row.get("event_title") or "",
                                          "first": row.get("first_at") or "", "sources": set()})
        b["sources"].add(row.get("source") or "")
    ranked = sorted(buckets.values(),
                    key=lambda b: (-(heat.get(b["id"], 0.0)), -len(b["sources"]), b["first"]))
    ranked = ranked[:HOT_LIMIT]

    items = []
    for i, b in enumerate(ranked, 1):
        h = heat.get(b["id"], 0.0)
        items.append(
            f'<div class="card"><div class="row"><span class="score">{i:02d}</span>'
            f'<span>热度 {h:g}</span><span class="dot"></span>'
            f'<span>{len(b["sources"])} 家</span></div>'
            f'<h3><a href="/events/{b["id"]}.html">{theme.esc(b["title"])}</a></h3></div>')
    _write(root / "hot.html", theme.page(
        "热门事件", "".join(items) or '<p class="muted">还没有可以排的事件。</p>',
        active="/hot.html", lead="按事件热度排序：48 小时窗口、每个独立来源算一次、24 小时减半"))
    return {"file": str(root / "hot.html"), "events": len(ranked)}


def build_items(day: str | None = None, site_root: Path | None = None) -> dict[str, Any]:
    """`/items/<id>.html`：单条详情（评分理由 + 正文 + 同事件其他报道）。"""
    root = site_root or SITE
    rows = store.all_items(day)
    written = 0
    for it in rows:
        detail = store.item_detail(int(it["id"]))
        if not detail:
            continue
        att = detail.get("attention") or {}
        st = detail.get("structure") or {}
        tags = "".join(f'<span class="tag">{theme.esc(t)}</span>' for t in (st.get("tags") or []))
        subjects = "".join(f'<span class="tag">{theme.esc(s)}</span>' for s in (st.get("subjects") or []))
        body = detail.get("body") or ""
        body_html = ""
        if body:
            paras = [p for p in body.split("\n") if p.strip()]
            body_html = ('<h2>正文摘录</h2>' +
                         "".join(f"<p>{theme.esc(p)}</p>" for p in paras[:20]))

        sib = ""
        if detail.get("siblings") and len(detail["siblings"]) > 1:
            lis = "".join(
                f'<li><a href="{theme.esc(s["url"])}" target="_blank" rel="noopener">'
                f'{theme.esc(s["title"])}</a><span class="muted small"> · {theme.esc(s["source"])}</span></li>'
                for s in detail["siblings"] if int(s["id"]) != int(detail["id"]))
            if lis:
                sib = (f'<h2>同一件事的其他报道 <small>'
                       f'<a href="/events/{detail["event_id"]}.html">事件页 →</a></small></h2>'
                       f'<ul class="list">{lis}</ul>')

        inner = (
            f'<div class="row">{theme.esc(detail["source"])}<span class="dot"></span>'
            f'{theme.esc((detail.get("published") or "")[:10])}'
            f'<span class="badge">{theme.esc(detail.get("layer") or "")}</span>'
            f'{_fb_buttons(detail.get("url") or "")}</div>'
            + (f'<p class="sum">{theme.esc(detail.get("summary") or "")}</p>'
               if detail.get("summary") else "")
            + (f'<div style="margin-top:8px;">{tags}{subjects}</div>' if tags or subjects else "")
            + _score_block(att)
            + f'<p class="small" style="margin-top:14px;">'
              f'<a href="{theme.esc(detail["url"])}" target="_blank" rel="noopener">阅读原文 →</a></p>'
            + body_html + sib)
        _write(root / "items" / f'{detail["id"]}.html', theme.page(
            detail["title"], inner, active="/all.html",
            lead=f'<a href="/all.html">← 全部动态</a>'))
        written += 1
    return {"dir": str(root / "items"), "items": written}


# --------------------------------------------------------------------------- #
# 日报 / 周报 / 月报
# --------------------------------------------------------------------------- #

def _issues(prefix: str) -> list[Path]:
    return sorted((DATA).glob(f"{prefix}-*.md"), reverse=True)


def build_issue_index(kind: str, *, site_root: Path | None = None) -> dict[str, Any]:
    root = site_root or SITE
    prefix = {"daily": "digest", "weekly": "weekly", "monthly": "monthly"}[kind]
    label = {"daily": "日报", "weekly": "周报", "monthly": "月报"}[kind]
    files = _issues(prefix)
    cards = "".join(
        f'<div class="card"><h3><a href="/{kind}/{theme.esc(p.stem.split("-", 1)[1])}.html">'
        f'{theme.esc(p.stem.split("-", 1)[1])}</a></h3>'
        f'<div class="row">{p.stat().st_size // 1024} KB</div></div>' for p in files)
    _write(root / f"{kind}.html", theme.page(
        label, cards or '<p class="muted">还没有出刊记录。跑一次 <code>python run.py</code> 就会生成。</p>',
        active=f"/{kind}.html", lead=f'共 {len(files)} 期 · 按日期倒序'))
    written = 1
    for p in files:
        day = p.stem.split("-", 1)[1]
        try:
            md = p.read_text(encoding="utf-8")
        except OSError:
            continue
        _write(root / kind / f"{day}.html", theme.page(
            f"{label} · {day}", md_to_html(md), active=f"/{kind}.html",
            lead=f'<a href="/{kind}.html">← 全部{label}</a>'))
        written += 1
    return {"file": str(root / f"{kind}.html"), "issues": len(files), "pages": written}


# --------------------------------------------------------------------------- #
# 事件页
# --------------------------------------------------------------------------- #

def _event_rows() -> list[dict[str, Any]]:
    try:
        return store.event_dump(days=120)
    except Exception:
        return []


def build_events(site_root: Path | None = None) -> dict[str, Any]:
    root = site_root or SITE
    rows = _event_rows()
    buckets: dict[int, dict[str, Any]] = {}
    for row in rows:
        eid = row.get("event_id")
        if eid is None:
            continue
        b = buckets.setdefault(int(eid), {"id": int(eid), "title": row.get("event_title") or "",
                                          "first": row.get("first_at") or "", "members": []})
        b["members"].append({"title": row.get("item_title") or "", "url": row.get("url") or "",
                             "source": row.get("source") or "", "layer": row.get("layer") or "",
                             "published": row.get("published") or ""})
    events = sorted(buckets.values(), key=lambda b: (-len(b["members"]), b["first"]))

    cards = "".join(
        f'<div class="card"><h3><a href="/events/{e["id"]}.html">{theme.esc(e["title"])}</a></h3>'
        f'<div class="row">{theme.esc(e["first"][:10])}<span class="dot"></span>'
        f'{len(e["members"])} 篇<span class="dot"></span>'
        f'{len({m["source"] for m in e["members"]})} 家</div></div>' for e in events)
    _write(root / "events.html", theme.page(
        "事件", cards or '<p class="muted">还没有聚合出事件。</p>', active="/events.html",
        lead=f'共 {len(events)} 个事件 · 同一件事的多篇报道收在一起'))

    written = 1
    for e in events:
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for m in e["members"]:
            key = "官方" if m["layer"] == "primary" else (
                "媒体" if m["layer"] in ("rank", "broad", "search") else "社区")
            groups[key].append(m)
        blocks = []
        for name in ("官方", "媒体", "社区"):
            items = groups.get(name) or []
            if not items:
                continue
            lis = "".join(
                f'<li><a href="{theme.esc(m["url"])}" target="_blank" rel="noopener">'
                f'{theme.esc(m["title"])}</a>'
                f'<span class="muted small"> · {theme.esc(m["source"])} · '
                f'{theme.esc(m["published"][:10])}</span></li>' for m in items)
            blocks.append(f"<h2>{name} <small>{len(items)} 篇</small></h2><ul class=\"list\">{lis}</ul>")
        _write(root / "events" / f'{e["id"]}.html', theme.page(
            e["title"], "".join(blocks), active="/events.html",
            lead=f'{theme.esc(e["first"][:10])} · {len(e["members"])} 篇报道 · '
                 f'<a href="/events.html">← 全部事件</a>'))
        written += 1
    return {"file": str(root / "events.html"), "events": len(events), "pages": written}


# --------------------------------------------------------------------------- #
# 搜索
# --------------------------------------------------------------------------- #

def build_search(day: str | None = None, site_root: Path | None = None) -> dict[str, Any]:
    root = site_root or SITE
    rows = store.all_items(day)
    data = json.dumps([{
        "t": it.get("title") or "", "u": it.get("url") or "", "i": it.get("id"),
        "s": it.get("source") or "", "d": (it.get("published") or "")[:10],
        "c": (it.get("structure") or {}).get("category") or "",
        "x": " ".join(str(it.get("summary") or "").split())[:160],
    } for it in rows], ensure_ascii=False).replace("</", "<\\/")

    body = (
        '<input type="search" id="q" placeholder="搜标题、摘要、分类…" autofocus '
        'style="width:100%;padding:12px 14px;font-size:16px;border:1px solid var(--rule);'
        'border-radius:10px;background:var(--card);color:var(--ink)">'
        '<div id="out" style="margin-top:18px;"></div>'
        f'<script>const DATA={data};'
        "const q=document.getElementById('q'),out=document.getElementById('out');"
        "const esc=s=>String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));"
        "function run(){const k=q.value.trim().toLowerCase();"
        "const hit=k?DATA.filter(d=>(d.t+' '+d.x+' '+d.c).toLowerCase().includes(k)):DATA.slice(0,30);"
        "out.innerHTML='<p class=\"muted small\">'+(k?'命中 '+hit.length+' 条':'今天 '+DATA.length+' 条，先看 30 条')+'</p>'+"
        "hit.map(d=>'<div class=\"card\"><h3><a href=\"/items/'+d.i+'.html\">'+esc(d.t)+'</a></h3>"
        "+'<div class=\"row\">'+esc(d.s)+' · '+esc(d.d)+(d.c?' · '+esc(d.c):'')+'</div>"
        "+(d.x?'<div class=\"sum\">'+esc(d.x)+'</div>':'')+'</div>').join('');}"
        "q.addEventListener('input',run);run();</script>")
    _write(root / "search.html", theme.page("搜索", body, active="/search.html",
                                            lead=f"在今天 {len(rows)} 条里搜（纯前端，离线可用）"))
    return {"file": str(root / "search.html"), "items": len(rows)}


# --------------------------------------------------------------------------- #
# 静态页与"更多"
# --------------------------------------------------------------------------- #

_ABOUT = """
<p>这是一个跑在本机的 AI 情报站。它每天从二十多个信源抓一次，去重、补正文、
用模型按五个维度打分、把同一件事的多篇报道聚成一个事件，再按规则编成日报、
周报和月报。</p>
<h2>它和普通聚合站的区别</h2>
<ul class="list">
  <li><b>有判断，不是只排序</b>：每条都有五轴分与入选门槛，分数旁边写着理由。</li>
  <li><b>按事件，不按文章</b>：同一件事只出一条代表稿，热度按独立来源算。</li>
  <li><b>能校准</b>：可以用自己的金标样本算准确率、扫门槛，改提示词不靠感觉。</li>
  <li><b>给机器也留了出口</b>：RSS、JSON、llms.txt，同一个读取层，同样的内容。</li>
</ul>
<h2>它不做什么</h2>
<ul class="list">
  <li>不转载全文，只留摘要与原文链接（全文是否展示由信源许可决定）。</li>
  <li>不追踪读者：收藏与阅读偏好只存在你自己的浏览器里。</li>
</ul>
"""

_TERMS = """
<p class="muted">下面是模板文字，上线前请按你的实际情况改写。</p>
<h2>内容来源</h2><p>本站内容来自公开信源，版权归原作者与发布方所有。本站只做摘要与链接，
不主张对原文的任何权利。</p>
<h2>使用</h2><p>你可以自由阅读、订阅与分享链接。批量抓取本站页面请改用 RSS 或 JSON 接口，
并遵守合理的请求频率。</p>
<h2>免责</h2><p>摘要由模型生成，可能有误。涉及事实判断请以原文为准。</p>
"""

_PRIVACY = """
<p class="muted">下面是模板文字，上线前请按你的实际情况改写。</p>
<h2>本站收集什么</h2><p>没有账号，不收集个人信息，不使用第三方统计脚本。</p>
<h2>存在你浏览器里的东西</h2>
<p>收藏（<code>localStorage</code>）和点赞/踩的临时状态只存在你的浏览器里，不会上传。
点赞/踩会写进本机的 SQLite，用来微调你自己的排序。</p>
<h2>日志</h2><p>抓取日志留在本机 <code>logs/</code>，不外发。</p>
"""


def build_static(site_root: Path | None = None) -> dict[str, Any]:
    root = site_root or SITE
    pages = {
        "about": ("关于", _ABOUT, "每天一份自己去判断的日报"),
        "terms": ("使用条款", _TERMS, "内容来源、使用方式与免责"),
        "privacy": ("隐私", _PRIVACY, "不追踪、不统计、不外发"),
    }
    for slug, (title, body, lead) in pages.items():
        _write(root / f"{slug}.html", theme.page(title, body, active="", lead=lead))

    # 更新日志：从 git 不方便读，这里用固定文案 + 版本表
    changelog = """
<h2>最近的改动</h2>
<ul class="list">
  <li><b>站点</b>：补齐「全部动态 / 热门 / 文章页 / 日报 / 周报 / 月报 / 事件页 / 搜索」，
      换成纸感配色，手机加了底栏。</li>
  <li><b>判断</b>：五轴评分 + 双次打分 + 分信源门槛；理由随分数一起展示。</li>
  <li><b>聚簇</b>：向量/文字召回 + 四类关系判定 + 低置信度复核；事件页并列三种说法。</li>
  <li><b>成本</b>：付费请求走回执，同输入不重复计费；有每日预算与备用模型。</li>
  <li><b>运维</b>：断点续跑、信源健康、缺期与失败率告警。</li>
</ul>
"""
    _write(root / "changelog.html", theme.page("更新日志", changelog, active="",
                                               lead="这个站自己是怎么长出来的"))

    agent = """
<p>同一个读取层，五个出口。选一个适合你的：</p>
<h2>订阅</h2>
<ul class="list">
  <li><a href="/feed.xml">今日要闻 RSS</a></li>
  <li><a href="/feed-all.xml">全部动态 RSS</a></li>
  <li><a href="/llms.txt">llms.txt</a> —— 给大模型看的站点说明</li>
</ul>
<h2>接口</h2>
<ul class="list">
  <li><code>GET /api/v1/latest.json</code> —— 当天条目，含五轴分、理由、结构化与事件归属</li>
  <li><code>POST /api/feedback</code> —— <code>{"url":"…","kind":"up|down"}</code>，给一条打分</li>
  <li><code>GET /api/prefs</code> —— 当前学到的偏好权重（调试用）</li>
</ul>
<h2>给 Agent 的提示</h2>
<pre class="card flat small" style="overflow:auto;">读 /llms.txt 了解这个站；
要最新内容用 /api/v1/latest.json（结构化，带分数与理由）；
要订阅用 /feed.xml；不要抓 HTML 页面，接口更稳定。</pre>
"""
    _write(root / "agent.html", theme.page("给 Agent 用", agent, active="",
                                           lead="RSS / JSON / llms.txt，同一个读取层"))

    starred = """
<p>收藏存在你自己的浏览器里（<code>localStorage</code>），不上传、不同步。</p>
<div id="list"><p class="muted">还没有收藏。在任意条目上点 ☆ 就会出现在这里。</p></div>
<script>
(function(){
  var key='radar.starred';
  var list=[];try{list=JSON.parse(localStorage.getItem(key)||'[]')}catch(e){}
  var box=document.getElementById('list');
  if(!list.length) return;
  box.innerHTML='<ul class="list">'+list.map(function(u){
    return '<li><a href="'+u.replace(/"/g,'&quot;')+'" target="_blank" rel="noopener">'+u.replace(/</g,'&lt;')+'</a></li>';
  }).join('')+'</ul><p class="muted small">清空：<a href="#" onclick="localStorage.removeItem(\\'radar.starred\\');location.reload();return false;">移除全部</a></p>';
})();
</script>
"""
    _write(root / "starred.html", theme.page("我的收藏", starred, active="",
                                             lead="只存在本机浏览器"))

    feedback = """
<p>每条卡片右下角的 👍 / 👎，就是反馈入口。点一下会写进本机数据库，
下一轮生成时按「分类 / 标签 / 主体」微调排序。</p>
<h2>它怎么影响排序</h2>
<ul class="list">
  <li>动作有权重：👍 +1、👎 −1.2、点开原文 +0.25（在 <code>config/prefs.yaml</code> 里改）</li>
  <li>按词累计，取平均；同一个词至少 3 次证据才参与</li>
  <li>只微调排序（默认 ±8%），<b>不动入选门槛</b> —— 免得日报只剩你本来就爱看的</li>
</ul>
<h2>现在学到了什么</h2>
<div id="prefs"><p class="muted">读取中…</p></div>
<script>
fetch('/api/prefs').then(r=>r.json()).then(function(j){
  var box=document.getElementById('prefs');
  if(!j.ok){box.innerHTML='<p class="muted">接口不可用（需要用 python serve.py 起站）。</p>';return;}
  var keys=Object.keys(j.top||{});
  box.innerHTML = keys.length
    ? '<p class="muted small">共 '+j.terms+' 个词有证据，前 '+keys.length+' 个：</p><div>'+
      keys.map(k=>'<span class="tag">'+k+' '+(j.top[k]>0?'+':'')+j.top[k]+'</span>').join('')+'</div>'
    : '<p class="muted">还没有足够的证据。多点几次 👍/👎 就来了。</p>';
}).catch(function(){document.getElementById('prefs').innerHTML='<p class="muted">接口不可用。</p>'});
</script>
"""
    _write(root / "feedback.html", theme.page("反馈", feedback, active="",
                                              lead="点一下就记，不用登录"))

    more_links = "".join(f'<li><a href="{href}">{label}</a></li>' for href, label in theme.MORE)
    _write(root / "more.html", theme.page(
        "更多", f'<ul class="list">{more_links}</ul>', active="",
        lead="所有页面与出口"))
    return {"pages": 7}


# --------------------------------------------------------------------------- #
# 首页：布局照 aihot.news（精选 / 筛选条 / 搜索 / 当前热点 / 日期分组信息流）
# --------------------------------------------------------------------------- #

CHIPS = (("all", "全部"), ("first", "一手"), ("model_release", "模型"),
         ("product_launch", "产品"), ("industry_event", "行业"),
         ("research_paper", "论文"), ("tutorial_explainer", "教程"),
         ("opinion_analysis", "观点"))

_HOME_JS = """
<script>
(function(){
  var q = document.getElementById('q');
  var chips = Array.prototype.slice.call(document.querySelectorAll('.chip[data-cat]'));
  var items = Array.prototype.slice.call(document.querySelectorAll('.item'));
  var unread = document.getElementById('unread');
  var cat = 'all', unreadOnly = false;
  function readSet(){ try { return JSON.parse(localStorage.getItem('zbit.read')||'[]') } catch(e){ return [] } }
  function apply(){
    var k = (q && q.value || '').trim().toLowerCase();
    var seen = readSet();
    var shown = 0;
    items.forEach(function(el){
      var okCat = cat === 'all' || el.dataset.cat === cat ||
                  (cat === 'first' && el.dataset.first === '1');
      var okText = !k || (el.dataset.text || '').indexOf(k) >= 0;
      var okUnread = !unreadOnly || seen.indexOf(el.dataset.id) < 0;
      var vis = okCat && okText && okUnread;
      el.style.display = vis ? '' : 'none';
      if (vis) shown++;
    });
    var bar = document.getElementById('count');
    if (bar) bar.textContent = shown;
  }
  chips.forEach(function(c){ c.addEventListener('click', function(){
    chips.forEach(function(x){ x.classList.remove('on') });
    c.classList.add('on'); cat = c.dataset.cat; apply();
  }); });
  if (q){ q.addEventListener('input', apply);
    document.addEventListener('keydown', function(e){
      if (e.key === '/' && document.activeElement !== q){ e.preventDefault(); q.focus(); }
    }); }
  if (unread){ unread.addEventListener('click', function(){
    unreadOnly = !unreadOnly; unread.classList.toggle('on', unreadOnly); apply();
  }); }
  items.forEach(function(el){
    var a = el.querySelector('h3 a');
    if (a) a.addEventListener('click', function(){
      var seen = readSet(); if (seen.indexOf(el.dataset.id) < 0){ seen.push(el.dataset.id);
        try { localStorage.setItem('zbit.read', JSON.stringify(seen)) } catch(e){} }
    });
  });
  apply();
})();
</script>"""


def build_home(day: str | None = None, site_root: Path | None = None,
               limit: int = 40) -> dict[str, Any]:
    """生成 `site/index.html`：结构对齐 aihot.news 首页。"""
    root = site_root or SITE
    day = day or store.today_str()
    rows = store.all_items(day)
    try:
        heat = store.latest_heat()
    except Exception:
        heat = {}

    # —— 当前热点：按热度取前 5 —— #
    hot_rows = []
    try:
        buckets: dict[int, dict[str, Any]] = {}
        for r in store.event_dump(days=3, day=day):
            eid = r.get("event_id")
            if eid is None:
                continue
            b = buckets.setdefault(int(eid), {"title": r.get("event_title") or "",
                                              "sources": set()})
            b["sources"].add(r.get("source") or "")
        ranked = sorted(buckets.items(), key=lambda kv: -heat.get(kv[0], 0.0))[:5]
        for i, (eid, b) in enumerate(ranked, 1):
            avatars = "".join("<i></i>" for _ in list(b["sources"])[:6])
            hot_rows.append(
                f'<a href="/events/{eid}.html"><span class="n">{i}</span>'
                f'<span class="t">{theme.esc(b["title"])}</span>'
                f'<span class="av">{avatars}</span>'
                f'<span class="h">+{int(heat.get(eid, 0))} 热度</span></a>')
    except Exception:
        hot_rows = []

    # —— 信息流：按时间倒序 —— #
    feed = []
    for it in rows[:limit]:
        att = it.get("attention") or {}
        cat = (it.get("structure") or {}).get("category") or ""
        published = (it.get("published") or "")[:16].replace("T", " ")
        hhmm = published[11:16] if len(published) >= 16 else "--:--"
        first = "1" if it.get("layer") == "primary" else "0"
        picked = "".join(
            ['<span class="pick">精选</span>'] if att.get("selected") else [])
        score = (f'<span class="score">AI 评分 {att["score"]}</span>'
                 if att.get("available") and att.get("score") is not None else "")
        summary = " ".join(str(it.get("summary") or "").split())
        reason = (att.get("reason") or "").strip()
        text = (str(it.get("title") or "") + " " + summary + " " + cat).lower()
        feed.append(
            f'<li class="item" data-id="{it["id"]}" data-cat="{theme.esc(cat)}" '
            f'data-first="{first}" data-text="{theme.esc(text)}">'
            f'<div class="time">{theme.esc(hhmm)}</div><div>'
            f'<div class="src"><span>{theme.esc(it["source"])}</span>'
            f'<span class="dot"></span><span>{theme.esc(published[5:16])}</span>'
            f'{picked}{score}</div>'
            f'<h3><a href="/items/{it["id"]}.html">{theme.esc(it["title"])}</a></h3>'
            + (f'<p class="sum">{theme.esc(summary[:180])}</p>' if summary else "")
            + (f'<p class="reason">推荐理由：{theme.esc(reason[:110])}</p>' if reason else "")
            + '</div></li>')

    chips = "".join(
        f'<a class="chip{" on" if key == "all" else ""}" data-cat="{key}" href="#" '
        f'onclick="return false">{label}</a>' for key, label in CHIPS)

    body = (
        f'<h1 class="title">精选<small>{theme.esc(day)} · {len(rows)} 条</small></h1>'
        f'<div class="chips">{chips}</div>'
        '<div class="searchrow"><input id="q" type="search" '
        'placeholder="搜索标题和摘要"><kbd>/</kbd></div>'
        + ('<h2 class="sec">当前热点<a href="/hot.html">完整榜单 →</a></h2>'
           f'<div class="hot">{"".join(hot_rows)}</div>' if hot_rows else "")
        + '<h2 class="sec">今日动态'
          f'<a href="#" id="unread" class="fb">只看未读</a></h2>'
        + f'<ol class="feed">{"".join(feed)}</ol>'
        + (f'<p class="muted small" style="margin-top:18px;">'
           f'<a href="/all.html">查看全部 {len(rows)} 条 →</a></p>'
           if len(rows) > limit else "")
        + _HOME_JS)

    doc = theme.page(f"精选 · {theme.BRAND}", body, active="/",
                     subtitle=f"{theme.BRAND} · 今日 AI 精选", own_heading=True)
    _write(root / "index.html", doc)
    return {"file": str(root / "index.html"), "items": min(len(rows), limit),
            "hot": len(hot_rows), "total": len(rows)}


# --------------------------------------------------------------------------- #
# 一把生成
# --------------------------------------------------------------------------- #

def build(payload: dict[str, Any] | None = None, site_root: Path | None = None,
          day: str | None = None) -> dict[str, Any]:
    """生成全部页面。任何一页失败只影响它自己。"""
    root = site_root or SITE
    stats: dict[str, Any] = {}
    jobs = {
        "home": lambda: build_home(day, root),
        "all": lambda: build_all(day, root),
        "hot": lambda: build_hot(day, root),
        "items": lambda: build_items(day, root),
        "events": lambda: build_events(root),
        "search": lambda: build_search(day, root),
        "static": lambda: build_static(root),
        "daily": lambda: build_issue_index("daily", site_root=root),
        "weekly": lambda: build_issue_index("weekly", site_root=root),
        "monthly": lambda: build_issue_index("monthly", site_root=root),
    }
    for name, job in jobs.items():
        try:
            stats[name] = job()
        except Exception as e:
            stats[name] = {"error": f"{type(e).__name__}: {e}"}
    total = 0
    for v in stats.values():
        if isinstance(v, dict):
            total += int(v.get("pages") or v.get("items") or v.get("events") or 1)
    stats["pages"] = total
    return stats
