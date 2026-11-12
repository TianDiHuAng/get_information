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
import os
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from . import store, theme

ROOT = Path(__file__).parent.parent
SITE = ROOT / "site"
DATA = Path(os.environ.get("RADAR_DATA") or (ROOT / "data"))

FEED_DIVIDER_CSS = """
.feed-divider{list-style:none;margin:34px 0 16px;padding-top:22px;border-top:1px solid var(--line);font-size:12px;color:var(--ink-4);letter-spacing:.03em;text-align:center}
"""

REPORT_CSS = """
/* 日报：按参考站的“报纸”排版 —— 大号衬线报头、头条加大、编号用等宽粗体 */
.report{max-width:760px;margin:0 auto}
.report h2{display:block;font-size:19px;font-weight:700;
           letter-spacing:-.01em;line-height:1.35;margin:38px 0 16px;padding-bottom:10px;
           border-bottom:1px solid var(--line)}
.report h3{font-size:14px;font-weight:700;letter-spacing:.04em;color:var(--ink-3);
           margin:26px 0 10px}
.report ul.list,.report ol.list{list-style:none;margin:0;padding:0}
.report li{position:relative;margin:0 0 15px;padding:0 0 15px;
           border-bottom:1px solid var(--line-soft);font-size:15px;line-height:1.75;
           color:var(--ink-2)}
.report ul.list>li:last-child,.report ol.list>li:last-child{border-bottom:0;padding-bottom:0}
/* 头条：今日要闻第一条 */
.report ul.list:first-of-type>li:first-of-type{font-size:19px;line-height:1.5;font-weight:700;color:var(--ink)}
.report ul.list>li:first-of-type a{color:var(--ink)}
/* 编号：01 02 03，等宽粗体、强调色 */
.report ol.list{counter-reset:item}
.report ol.list>li{counter-increment:item;padding-left:36px;min-height:30px}
.report ol.list>li::before{content:counter(item,decimal-leading-zero);position:absolute;
  left:0;top:2px;font:800 20px/1 var(--font-mono);color:var(--accent);letter-spacing:-.03em}
.report strong{font-weight:700}
.report strong a{color:var(--ink)}
.report strong a:hover{color:var(--accent)}
.report code{font:11.5px var(--font-mono);color:var(--ink-4);background:none;
  padding:0;margin-left:6px;white-space:nowrap;opacity:.85}
.report blockquote{margin:12px 0;padding:8px 14px;border-left:2px solid var(--line-strong);
  color:var(--ink-3);font-size:14px}
.report hr{border:0;border-top:1px solid var(--line);margin:26px 0}
@media(max-width:640px){
  .report ul.list:first-of-type>li:first-of-type{font-size:17px}
  .report li{font-size:14.5px;line-height:1.7}
}
"""

NAMEPLATE_CSS = """
.nameplate{font-family:"Songti SC","Noto Serif CJK SC",Georgia,serif;font-size:34px;
           font-weight:700;letter-spacing:.06em;color:var(--ink);line-height:1.2;
           padding:10px 0 12px;margin:4px 0 8px;border-bottom:2px solid var(--ink)}
@media(max-width:640px){.nameplate{font-size:26px}}
"""

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


def _slot(it: dict[str, Any]) -> str:
    """一条内容的时间轴单元 —— 首页与 /all 共用同一套 DOM。

    桌面端时间只在左侧时间轴上（参考站如此），header 里的日期只在手机上显示。
    """
    att = it.get("attention") or {}
    cat = (it.get("structure") or {}).get("category") or ""
    published = (it.get("published") or "")[:16].replace("T", " ")
    hhmm = published[11:16] if len(published) >= 16 else "--:--"
    first = "1" if it.get("layer") == "primary" else "0"

    score = ""
    if att.get("available") and att.get("score") is not None:
        score = (f'<span class="scorelabel" title="AI 评分 {att["score"]}/100">'
                 f'<span class="k">AI 评分</span><span class="sep"></span>'
                 f'<b>{att["score"]}</b></span>')
    pick = '<span class="badge-pick">精选</span>' if att.get("selected") else ""
    crowd = ""
    if int(it.get("event_size") or 0) > 1:
        crowd = f'<span class="badge">{it["event_size"]} 篇</span>'

    summary = " ".join(str(it.get("summary") or "").split())
    reason = (att.get("reason") or "").strip()
    text = (str(it.get("title") or "") + " " + summary + " " + cat).lower()

    also = ""
    size = int(it.get("event_size") or 0)
    if size > 1 and it.get("event_id"):
        also = (f'<p class="also">另外 {size - 1} 家也报道了'
                f'<a href="/events/{it["event_id"]}.html"> 看各方说法 →</a></p>')

    parts = [
        f'<li class="slot" data-id="{it["id"]}" data-cat="{theme.esc(cat)}" '
        f'data-first="{first}" data-text="{theme.esc(text)}">',
        f'<time datetime="{theme.esc(published)}">{theme.esc(hhmm)}</time>',
        '<span class="rail" aria-hidden="true"></span>',
        '<article class="cardrow"><header class="hd"><span class="src">',
        f'<span>{theme.esc(it["source"])}</span>',
        f'<span class="dot"></span><span class="when">{theme.esc(published[5:16])}</span>',
        f'{pick}{crowd}</span>',
        f'<span class="rt">{score}',
        f'<button class="star" data-star="{theme.esc(it.get("url") or "")}" '
        f'aria-label="收藏" title="收藏">☆</button></span></header>',
        f'<h3><a href="/items/{it["id"]}.html">{theme.esc(it["title"])}</a></h3>',
    ]
    if summary:
        parts.append(f'<p class="sum">{theme.esc(summary[:200])}</p>')
    if reason:
        parts.append(f'<p class="reason">推荐理由：{theme.esc(reason[:140])}</p>')
    if also:
        parts.append(also)
    parts.append('</article></li>')
    return "".join(parts)


def _day_header(day: str, count: int) -> str:
    head, week = _day_label(day)
    return (f'<div class="daybar" data-day="{theme.esc(day)}">'
            f'<span class="d" data-abs="{theme.esc(head)}">{theme.esc(head)}</span>'
            f'<span class="w">{theme.esc(week)}</span>'
            f'<span class="aside"><b>{count}</b> 条</span></div>')


def build_all(day: str | None = None, site_root: Path | None = None) -> dict[str, Any]:
    """`/all.html` + `/all/<n>.html`：当天全部条目，分页。

    与首页共用同一套 slot/cardrow —— 点进「全部动态」不该像换了一个站。
    """
    root = site_root or SITE
    day = store.content_day(day)
    rows = store.all_items(day)
    pages = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
    written = 0
    for page in range(1, pages + 1):
        chunk = rows[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]
        slots = "".join(_slot(it) for it in chunk)
        pager = []
        if page > 1:
            prev = "/all.html" if page == 2 else f"/all/{page - 1}.html"
            pager.append(f'<a class="fb" href="{prev}">← 上一页</a>')
        pager.append(f'<span class="muted small">第 {page} / {pages} 页</span>')
        if page < pages:
            pager.append(f'<a class="fb" href="/all/{page + 1}.html">下一页 →</a>')
        body = (_day_header(day, len(rows))
                + (f'<ol class="feed">{slots}</ol>' if slots
                   else '<p class="muted">今天还没有条目。</p>')
                + f'<div class="pager">{"".join(pager)}</div>')
        target = root / "all.html" if page == 1 else root / "all" / f"{page}.html"
        _write(target, theme.page(
            "全部动态", body, active="/all.html",
            lead=f'今天 <b>{len(rows)}</b> 条，按排序分从高到低；'
                 f'想只看入选的看 <a href="/">精选</a>。',
            extra_css=PAGER_CSS).replace("</body>", _STAR_JS + "</body>"))
        written += 1
    return {"file": str(root / "all.html"), "items": len(rows), "pages": written}


PAGER_CSS = """
.pager{display:flex;gap:14px;align-items:center;justify-content:space-between;margin-top:22px}
"""


HOT_CSS = """
.rank{list-style:none;margin:0;padding:0}
.rank li{display:grid;grid-template-columns:56px minmax(0,1fr);gap:14px;
         padding:18px 0;border-bottom:1px solid var(--line-soft)}
.rank li:last-child{border-bottom:0}
@media(max-width:640px){.rank li{grid-template-columns:44px minmax(0,1fr);gap:10px}}
.rank .no{font:700 13px var(--font-mono);color:var(--ink-4);padding-top:3px;white-space:nowrap}
.rank li:nth-child(1) .no{color:var(--rank-1)}
.rank li:nth-child(2) .no{color:var(--rank-2)}
.rank li:nth-child(3) .no{color:var(--rank-3)}
.rank h3{margin:0;font-size:18px;font-weight:650;line-height:1.45}
@media(max-width:640px){.rank h3{font-size:16.5px}}
.rank .why{margin:6px 0 0;font-size:14px;line-height:1.75;color:var(--ink-3);
           display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.rank .who{display:flex;align-items:center;gap:10px;margin-top:10px;font-size:12.5px;color:var(--ink-4)}
.rank .who{margin-left:0}
.rank .ev{color:var(--ink-3);font-size:13px}
.rank .ev b{font:700 15px var(--font-mono);color:var(--ink);font-variant-numeric:tabular-nums}
.rank .heat{margin-left:auto;white-space:nowrap;font-size:12px;color:var(--ink-4)}
.compact{list-style:none;margin:6px 0 0;padding:0}
.compact li{display:grid;grid-template-columns:40px minmax(0,1fr) auto;gap:12px;align-items:baseline;
            padding:10px 0;border-bottom:1px solid var(--line-soft);font-size:14px}
.compact li:last-child{border-bottom:0}
.compact .no{font:600 12px var(--font-mono);color:var(--ink-4)}
.compact .heat{font:600 13px var(--font-mono);color:var(--ink-3)}
"""


def build_hot(day: str | None = None, site_root: Path | None = None) -> dict[str, Any]:
    """`/hot.html`：按事件热度排的榜。

    做成真正的排行榜（NO.01 大卡 + 其余紧凑行），而不是又一个列表 ——
    AIHOT 的 /hot 就是这样，读者一眼能看出名次差别。
    """
    root = site_root or SITE
    day = store.content_day(day)
    try:
        heat = store.latest_heat()
        rows = store.event_dump(days=14, day=day)
    except Exception as e:
        _write(root / "hot.html", theme.page(
            "热点榜", f'<p class="muted">暂不可用：{theme.esc(e)}</p>',
            active="/hot.html"))
        return {"file": str(root / "hot.html"), "events": 0, "error": str(e)}

    buckets: dict[int, dict[str, Any]] = {}
    for row in rows:
        eid = row.get("event_id")
        if eid is None:
            continue
        b = buckets.setdefault(int(eid), {
            "id": int(eid), "title": row.get("event_title") or "",
            "first": (row.get("first_at") or "")[:10], "sources": set(),
            "summary": "", "members": 0,
        })
        b["sources"].add(row.get("source") or "")
        b["members"] += 1
        if not b["summary"]:
            b["summary"] = " ".join(str(row.get("item_summary") or "").split())
    ranked = sorted(buckets.values(), key=lambda b: -heat.get(b["id"], 0.0))

    def digest(eid: int) -> str:
        try:
            from . import story

            return (story.get(eid) or {}).get("text") or ""
        except Exception:
            return ""

    top, rest = ranked[:3], ranked[3:]
    items = []
    for idx, b in enumerate(top, 1):
        text = digest(b["id"]) or b["summary"]
        items.append(
            f'<li><div class="no">NO.{idx:02d}</div><div>'
            f'<h3><a href="/events/{b["id"]}.html">{theme.esc(b["title"])}</a></h3>'
            + (f'<p class="why">{theme.esc(text[:260])}</p>' if text else "")
            + '<div class="who">'
              f'<span class="ev"><b>{len(b["sources"])}</b> 家在说'
              f' · <b>{b["members"]}</b> 篇</span>'
              '<a class="heat" href="/events/%d.html">看各方说法 →</a>'
              '</div></div></li>' % b["id"])
    body = (f'<p class="lead">过去 48 小时讨论最多的 {len(ranked)} 件事 —— '
            f'按「有多少家独立来源在说」和「说了多久」排序，'
            f'同一件事的多篇报道合并成一个。</p>'
            f'<ol class="rank">{"".join(items)}</ol>')
    if rest:
        compact = "".join(
            f'<li><span class="no">{idx:02d}</span>'
            f'<a href="/events/{b["id"]}.html">{theme.esc(b["title"])}</a>'
            f'<span class="heat">{int(heat.get(b["id"], 0))}</span></li>'
            for idx, b in enumerate(rest, 4))
        body += (f'<h2 class="sec">继续看 No.04–{len(ranked):02d}'
                 f'<span class="muted small">按独立来源数与时间衰减排序</span></h2>'
                 f'<ul class="compact">{compact}</ul>')
    if not ranked:
        body = '<p class="muted">还没有聚合出事件。跑一轮 python run.py 就会有。</p>'
    _write(root / "hot.html", theme.page("热点榜", body, active="/hot.html",
                                         own_heading=False, extra_css=HOT_CSS))
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
        # 合规：站内是否展示正文由信源的 site_fulltext 决定，默认关（只给摘要与原文链接）
        from .sources import source_meta

        allow_fulltext = bool(source_meta(detail.get("source") or "").get("site_fulltext"))
        body = (detail.get("body") or "") if allow_fulltext else ""
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


ISSUE_CSS = """
.dl-front{background:var(--surface);border:1px solid var(--line);border-radius:var(--r-card);
          box-shadow:var(--shadow-card);padding:22px 24px;margin:0 0 24px}
.dl-front .kicker{font-size:12px;letter-spacing:.08em;color:var(--ink-4);text-transform:uppercase}
.dl-front h2{font-size:24px;font-weight:700;line-height:1.35;margin:8px 0 10px;letter-spacing:-.01em}
.dl-front h2 a{color:var(--ink)}
.dl-front .lead{margin:0;font-size:15px;line-height:1.8;color:var(--ink-3)}
.dl-front .cols{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}
.dl-front .cols span{font-size:12px;color:var(--ink-3);background:var(--bg-sunk);
                     border-radius:999px;padding:3px 11px}
.dl-stats{display:flex;flex-wrap:wrap;gap:18px;margin-top:16px;padding-top:14px;
          border-top:1px solid var(--line-soft);font-size:13px;color:var(--ink-4)}
.dl-stats b{font:700 16px var(--font-mono);color:var(--ink);margin-right:3px}
.dl-grid{display:grid;grid-template-columns:minmax(0,1fr) 260px;gap:28px;align-items:start}
@media(max-width:820px){.dl-grid{grid-template-columns:1fr}}
.dl-month{margin:0 0 20px}
.dl-month h3{font-size:12px;font-weight:600;letter-spacing:.07em;text-transform:uppercase;
             color:var(--ink-4);margin:0 0 8px;padding-bottom:7px;border-bottom:1px solid var(--line)}
.dl-row{display:grid;grid-template-columns:86px minmax(0,1fr) auto;gap:12px;align-items:baseline;
        padding:9px 0;border-bottom:1px solid var(--line-soft);font-size:14px}
.dl-row:last-child{border-bottom:0}
.dl-row .d{font-family:var(--font-mono);font-size:12.5px;color:var(--ink-4)}
.dl-row a{color:var(--ink-2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;display:block}
.dl-row a:hover{color:var(--accent)}
.dl-row .n{font-size:11.5px;color:var(--ink-4);white-space:nowrap}
.dl-side{background:var(--surface);border:1px solid var(--line);border-radius:var(--r-card);
         box-shadow:var(--shadow-card);padding:18px 20px}
.dl-side h4{font-size:12px;font-weight:600;letter-spacing:.07em;text-transform:uppercase;
            color:var(--ink-4);margin:0 0 10px}
.dl-side ol{list-style:none;margin:0;padding:0;counter-reset:i}
.dl-side li{counter-increment:i;display:grid;grid-template-columns:26px minmax(0,1fr);gap:8px;
            padding:8px 0;border-bottom:1px solid var(--line-soft);font-size:13px;line-height:1.5}
.dl-side li:last-child{border-bottom:0}
.dl-side li::before{content:counter(i,decimal-leading-zero);font:700 12px var(--font-mono);
                    color:var(--accent)}
.dl-side li a{color:var(--ink-2)}
"""


def _issue_stats(day: str) -> dict[str, Any]:
    """当期统计行 + 今日看点，全部从 db 现算。"""
    try:
        rows = store.all_items(day)
    except Exception:
        return {}
    srcs = {r.get("source") for r in rows if r.get("source")}
    models = sum(1 for r in rows
                 if ((r.get("structure") or {}).get("category") or "") == "model_release")
    firsts = sum(1 for r in rows if r.get("layer") == "primary")
    scored = [r for r in rows if (r.get("attention") or {}).get("score") is not None]
    scored.sort(key=lambda r: -(r["attention"]["score"]))
    top = [{"title": r.get("title") or "", "id": r.get("id"),
            "score": r["attention"]["score"], "source": r.get("source") or ""}
           for r in scored[:3]]
    return {"items": len(rows), "sources": len(srcs), "models": models,
            "firsts": firsts, "top": top}


def _issue_meta(p: Path) -> dict[str, Any]:
    """从一期 Markdown 里抽出标题、板块、头条，用来做索引卡片。"""
    try:
        md = p.read_text(encoding="utf-8")
    except OSError:
        return {}
    lines = md.splitlines()
    title = next((l[2:].strip() for l in lines if l.startswith("# ")), "")
    heads = [l[3:].strip() for l in lines if l.startswith("## ")]
    lead = ""
    for l in lines:
        t = l.strip()
        if (t.startswith("- ") or re.match(r"^\d+\. ", t)) and len(t) > 14:
            lead = re.sub(r"^[-\d.\s]+", "", t)
            lead = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", lead)
            lead = re.sub(r"[*_`#>]", "", lead)
            break
    items = sum(1 for l in lines
                if l.strip().startswith("- ") or re.match(r"^\d+\. ", l.strip()))
    return {"date": p.stem.split("-", 1)[-1], "title": title, "heads": heads,
            "lead": lead[:110], "items": items}


def build_issue_index(kind: str, *, site_root: Path | None = None) -> dict[str, Any]:
    root = site_root or SITE
    prefix = {"daily": "digest", "weekly": "weekly", "monthly": "monthly"}[kind]
    label = {"daily": "日报", "weekly": "周报", "monthly": "月报"}[kind]
    files = _issues(prefix)
    metas = [m for m in (_issue_meta(p) for p in files) if m]
    latest = metas[0] if metas else None

    st = _issue_stats(latest["date"]) if latest else {}
    front = ""
    if latest:
        chips = "".join(f"<span>{theme.esc(h)}</span>" for h in latest["heads"][:6])
        front = (f'<div class="dl-front"><div class="kicker">最新一期 · {theme.esc(latest["date"])}'
                 f' · {latest["items"]} 条</div>'
                 f'<h2><a href="/{kind}/{theme.esc(latest["date"])}.html">'
                 f'{theme.esc(latest["title"] or label)}</a></h2>'
                 + (f'<p class="lead">{theme.esc(latest["lead"])}…</p>' if latest["lead"] else "")
                 + (f'<div class="cols">{chips}</div>' if chips else "")
                 + (f'<div class="dl-stats">'
                    f'<span><b>{st["items"]}</b> 条</span>'
                    f'<span><b>{st["sources"]}</b> 个来源</span>'
                    f'<span><b>{st["firsts"]}</b> 条一手</span>'
                    f'<span><b>{st["models"]}</b> 个新模型</span>'
                    f'<span>约 {max(2, st["items"] // 12)} 分钟读完</span></div>'
                    if st else "")
                 + '</div>')

    months: dict[str, list[dict[str, Any]]] = {}
    for m in metas:
        months.setdefault(m["date"][:7], []).append(m)
    blocks = []
    for month in sorted(months, reverse=True):
        rows = "".join(
            f'<div class="dl-row"><span class="d">{theme.esc(m["date"])}</span>'
            f'<a href="/{kind}/{theme.esc(m["date"])}.html">'
            f'{theme.esc(m["lead"] or m["title"] or "（无标题）")}</a>'
            f'<span class="n">{m["items"]} 条</span></div>'
            for m in months[month])
        y, mm = month.split("-")
        blocks.append(f'<div class="dl-month"><h3>{y} 年 {int(mm)} 月 · {len(months[month])} 期</h3>'
                      f'{rows}</div>')

    side = ""
    if st and st.get("top"):
        picks = "".join(
            f'<li><a href="/items/{t["id"]}.html">{theme.esc(t["title"][:64])}</a></li>'
            for t in st["top"])
        side += (f'<div class="dl-side" style="margin-bottom:16px;">'
                 f'<h4>今日看点</h4><ol>{picks}</ol></div>')
    if latest and latest["heads"]:
        items = "".join(f'<li>{theme.esc(h)}</li>' for h in latest["heads"][:6])
        side += f'<div class="dl-side"><h4>本期版面</h4><ol>{items}</ol></div>' 

    body = front + f'<div class="dl-grid"><div>{"".join(blocks)}</div>{side}</div>' \
        if metas else '<p class="muted">还没有出刊记录。跑一次 <code>python run.py</code> 就会生成。</p>'
    _write(root / f"{kind}.html", theme.page(
        label, body, active=f"/{kind}.html",
        lead=f"共 {len(metas)} 期 · 每期按日期倒序，点开是当期的报纸版面",
        extra_css=ISSUE_CSS))

    written = 1
    for p in files:
        day = p.stem.split("-", 1)[-1]
        try:
            md = p.read_text(encoding="utf-8")
        except OSError:
            continue
        plate = ""
        try:
            from . import industry

            plate = str((industry.settings().get("nameplate") or {}).get(kind) or "")
        except Exception:
            plate = ""
        plate_html = f'<div class="nameplate">{theme.esc(plate)}</div>' if plate else ""
        md_body = md
        first = md_body.lstrip().split("\n", 1)
        if first and first[0].lstrip().startswith("# "):
            md_body = first[1] if len(first) > 1 else ""
        doc = theme.page(f"{label} · {day}",
                         plate_html + f'<div class="report">{md_to_html(md_body)}</div>',
                         active=f"/{kind}.html",
                         lead=f'<a href="/{kind}.html">← 全部{label}</a>',
                         extra_css=NAMEPLATE_CSS + REPORT_CSS)
        _write(root / kind / f"{day}.html", doc)
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
        f'<li><span class="no">{i:02d}</span>'
        f'<a href="/events/{e["id"]}.html">{theme.esc(e["title"])}</a>'
        f'<span class="heat">{len({m["source"] for m in e["members"]})} 家 · '
        f'{len(e["members"])} 篇</span></li>'
        for i, e in enumerate(events, 1))
    body = (f'<ul class="compact">{cards}</ul>' if cards
            else '<p class="muted">还没有聚合出事件。跑一轮 python run.py 就会有。</p>')
    _write(root / "events.html", theme.page(
        "事件", body, active="/events.html",
        lead=f'共 {len(events)} 个事件 · 同一件事的多篇报道收在一起，点进去看各方说法',
        extra_css=HOT_CSS))

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
        digest_text = ""
        try:
            from . import story as _story

            row = _story.get(e["id"])
            digest_text = (row or {}).get("text") or ""
        except Exception:
            digest_text = ""
        digest_html = (f'<p class="lead" style="margin:0 0 18px;">{theme.esc(digest_text)}</p>'
                       if digest_text else "")
        _write(root / "events" / f'{e["id"]}.html', theme.page(
            e["title"], digest_html + "".join(blocks), active="/events.html",
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
        # about 由 collector/about.py 生成（带 canvas 示意图），这里不再覆盖
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
<h2>MCP（给 Agent 直接调用）</h2>
<p>除了读接口，还可以把本站挂成 MCP 服务，让 Claude Desktop / Cursor 直接调：</p>
<pre class="card flat small" style="overflow:auto;">{
  "mcpServers": {
    "zbit": {"command": "python", "args": ["<项目路径>/mcp_server.py"]}
  }
}</pre>
<p class="small muted">七个工具：最新、搜索、热点、事件、日报、周报、月报。
工具名前缀是 <code>zbit_</code>（在 <code>config/industry.yaml</code> 的 <code>mcp_prefix</code> 改）。</p>
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

    # 后台与归档只有根站一份：子站里指回根（用哨兵，前缀替换时不会被改写）
    root_only = {"/admin.html", "/archive/"}
    sentinel = "@@ROOT@@"
    parts = []
    for href, label in theme.MORE:
        target = f"{sentinel}{href}" if href in root_only else href
        parts.append(f'<li><a href="{target}">{label}</a></li>')
    more_links = "".join(parts)
    _write(root / "more.html", theme.page(
        "更多", f'<ul class="list">{more_links}</ul>', active="",
        lead="所有页面与出口"))
    return {"pages": 6}


# --------------------------------------------------------------------------- #
# 首页：布局照 aihot.news（精选 / 筛选条 / 搜索 / 当前热点 / 日期分组信息流）
def build_404(site_root: Path | None = None) -> dict[str, Any]:
    """自定义 404：比裸错误页有用 —— 给四个真出口，而不是让人回退。"""
    root = site_root or SITE
    cards = (("/", "今日精选", "当天入选的几条，带评分与理由"),
             ("/all.html", "全部动态", "所有条目，按分数排"),
             ("/search.html", "搜索", "按关键词找"),
             ("/daily.html", "日报", "按日期翻阅"))
    body = ('<h1 class="title">这个地址不存在</h1>'
            '<p class="lead">可能链接过期了，或者拼错了。下面是几个能用的入口。</p>'
            '<div class="grid two" style="margin-top:18px;">'
            + "".join(f'<a class="card" href="{href}"><h3>{theme.esc(title)}</h3>'
                      f'<div class="row">{theme.esc(desc)}</div></a>'
                      for href, title, desc in cards)
            + '</div>')
    _write(root / "404.html", theme.page("页面不存在", body, active="",
                                         subtitle="页面不存在"))
    return {"file": str(root / "404.html")}


def _build_about(root: Path) -> dict[str, Any]:
    from . import about as about_page

    return about_page.build(root)


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
        "modules": lambda: __import__("collector.modules", fromlist=["x"]).build_all(root, payload, day),
        "static": lambda: build_static(root),
        "notfound": lambda: build_404(root),
        "about": lambda: _build_about(root),
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


CHIPS = (("all", "全部"), ("first", "一手"), ("model_release", "模型"),
         ("product_launch", "产品"), ("industry_event", "行业"),
         ("research_paper", "论文"), ("tutorial_explainer", "教程"),
         ("opinion_analysis", "观点"))

_HOME_JS = """
<script>
// 日期条：构建时只能写绝对日期，这里按访客当下的日期改成「今天/昨天」；
// 数据不是今天的再补一条「数据截至」——静态站过了午夜不能继续说「今天」。
(function upgradeDay(){
  var bar = document.querySelector('.daybar[data-day]');
  if (!bar) return;
  var parts = (bar.dataset.day || '').split('-');
  if (parts.length !== 3) return;
  var target = new Date(+parts[0], +parts[1] - 1, +parts[2]);
  var now = new Date();
  var today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  var diff = Math.round((today - target) / 86400000);
  var d = bar.querySelector('.d');
  var abs = d ? (d.dataset.abs || d.textContent) : '';
  if (diff === 0 && d) d.textContent = '今天';
  else if (diff === 1 && d) d.textContent = '昨天';
  if (diff > 0) {
    var aside = bar.querySelector('.aside');
    if (aside) {
      var tag = document.createElement('span');
      tag.className = 'stale';
      tag.textContent = '数据截至 ' + abs + ' · ';
      aside.insertBefore(tag, aside.firstChild);
    }
  }
})();
(function(){
  var q=document.getElementById('q');
  var pills=Array.prototype.slice.call(document.querySelectorAll('.pillbar a[data-cat]'));
  var items=Array.prototype.slice.call(document.querySelectorAll('.slot'));
  var cat='all';
  function apply(){
    var k=(q&&q.value||'').trim().toLowerCase(), shown=0;
    items.forEach(function(el){
      var okPill = cat==='all' || el.dataset.cat===cat ||
                   (cat==='first' && el.dataset.first==='1');
      var okText = !k || (el.dataset.text||'').indexOf(k)>=0;
      var vis = okPill && okText;
      el.style.display = vis ? '' : 'none';
      if(vis) shown++;
    });
    var c=document.getElementById('cnt'); if(c) c.textContent=shown;
  }
  pills.forEach(function(p){p.addEventListener('click',function(e){
    e.preventDefault();
    pills.forEach(function(x){x.classList.remove('on')});
    p.classList.add('on'); cat=p.dataset.cat; apply();
  });});
  if(q){q.addEventListener('input',apply);
    document.addEventListener('keydown',function(e){
      if(e.key==='/'&&document.activeElement!==q){e.preventDefault();q.focus();}
    });}
  apply();
})();
</script>"""


def _day_label(day: str) -> tuple[str, str]:
    """返回（'11月10日', '周二'）。

    **不在这里判断"今天"** —— 站点是静态的，构建时的"今天"过了午夜就变成谎话。
    绝对日期照写，页面里的脚本再按访客当下的日期改成"今天/昨天"。
    """
    from datetime import date

    try:
        d = date.fromisoformat(day)
    except Exception:
        return day, ""
    return f"{d.month}月{d.day}日", f"周{'一二三四五六日'[d.weekday()]}"


_AVATAR_COLORS = ("#176b75", "#b3402a", "#b8873a", "#3f6b52", "#5a5f8a", "#8a5a3f")


def _avatar_stack(sources: list[str], limit: int = 6) -> str:
    """来源头像叠放：没有真实 favicon 时用首字母 + 稳定配色，比空圆圈好看得多。"""
    out = []
    for name in sources[:limit]:
        label = (name or "?").strip()[:1].upper()
        color = _AVATAR_COLORS[sum(ord(c) for c in (name or "?")) % len(_AVATAR_COLORS)]
        out.append(f'<i style="background:{color}">{theme.esc(label)}</i>')
    return "".join(out)


def build_home(day: str | None = None, site_root: Path | None = None,
               limit: int = 60) -> dict[str, Any]:
    """生成 `site/index.html`：结构对齐 aihot.news 的精选页。"""
    root = site_root or SITE
    day = store.content_day(day)
    rows = store.all_items(day)
    try:
        heat = store.latest_heat()
    except Exception:
        heat = {}

    # —— 当前热点（热度前 5） —— #
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
        for eid, b in ranked:
            faces = _avatar_stack([x for x in b["sources"] if x])
            hot_rows.append(
                f'<li><a href="/events/{eid}.html"><span class="rk"></span>'
                f'<span class="tt">{theme.esc(b["title"])}</span>'
                f'<span class="faces">{faces}</span>'
                f'<span class="heat"><b>{len([x for x in b["sources"] if x])}</b> 家</span>'
                f'<span></span></a></li>')
        # 序号用 CSS 的 rank 颜色，但内容要显式写数字
        hot_rows = [r.replace('<span class="rk"></span>',
                              f'<span class="rk">{i}</span>', 1)
                    for i, r in enumerate(hot_rows, 1)]
    except Exception:
        hot_rows = []

    # —— 信息流：时间轴 + 卡片 —— #
    # 精选 = 过门槛的；其余按分数排在后面并明确标出来（不混在一起冒充精选）
    def _selected(row: dict) -> bool:
        return bool((row.get("attention") or {}).get("selected"))

    ordered = [r for r in rows if _selected(r)] + [r for r in rows if not _selected(r)]
    first_unselected = sum(1 for r in ordered if _selected(r))

    slots = []
    for index, it in enumerate(ordered[:limit]):
        if index == first_unselected and first_unselected and index > 0:
            slots.append('<li class="feed-divider">更多动态 · 未过门槛，按分数排列</li>')
        slots.append(_slot(it))

    day_head, week = _day_label(day)
    pill_parts = []
    for key, label in CHIPS:
        cls = ' class="on"' if key == "all" else ""
        pill_parts.append(f'<a href="#" data-cat="{key}"{cls}>{label}</a>')
    pills = "".join(pill_parts)

    body = (
        '<h1 class="title">精选</h1>'
        f'<div class="pillbar">{pills}</div>'
        '<div class="searchrow"><div class="box">'
        f'<span class="ic">{theme.icon("list", 16)}</span>'
        '<input id="q" type="search" placeholder="搜索标题、摘要…"><kbd>/</kbd></div></div>'
        + (f'<section class="hotcard"><div class="hd">'
           f'<h2><span class="dotlive"><i></i><b></b></span>当前热点</h2>'
           f'<a class="more" href="/hot.html">完整榜单 →</a></div>'
           f'<ol>{"".join(hot_rows)}</ol></section>' if hot_rows else "")
        + _day_header(day, len(slots)).replace(
            '条</span></div>', f'条</span></div>', 1)
        + f'<ol class="feed">{"".join(slots)}</ol>'
        + (f'<p class="muted small" style="margin-top:16px;">'
           f'<a href="/all.html">查看全部 {len(rows)} 条 →</a></p>'
           if len(rows) > limit else "")
        + _HOME_JS + _STAR_JS)

    _write(root / "index.html",
           theme.page(f"精选 · {theme.BRAND}", body, active="/",
                      subtitle=f"{theme.BRAND} · {theme.TAGLINE}", own_heading=True))
    return {"file": str(root / "index.html"), "items": min(len(rows), limit),
            "hot": len(hot_rows), "total": len(rows)}


DEAL_WORDS = ("免费", "赠送", "白嫖", "羊毛", "额度", "体验金", "注册送", "试用",
              "优惠", "折扣", "降价", "限免", "free", "trial", "credit")
