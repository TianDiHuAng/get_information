"""单文件离线归档：把"这一天"装进一个 HTML，双击就能看。

为什么不是把整站打包：站点各页有各自的内联样式，合并时类名会打架（`.wrap` / `.card`
在四个页面里含义不同），硬拼出来的东西一改就坏。这里**重新画一页**：
只挑四块最该带走的 —— 今日要闻、本周要闻、主题分布、时间线要点，
用一套自带的样式，不引用任何外部文件。

产物是 `site/offline.html`：断网、换机、发给同事，都是一个文件。
"""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path
from typing import Any

from . import edition, report, store, timeline, topics

SITE = Path(__file__).parent.parent / "site"

_CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { margin:0; background:#0b0f14; color:#e6edf3;
       font:15px/1.7 -apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; }
.wrap { max-width:860px; margin:0 auto; padding:32px 20px 80px; }
h1 { font-size:22px; margin:0 0 4px; }
.sub { color:#6b7785; font-size:12px; margin-bottom:26px; }
a { color:#7dd3fc; text-decoration:none; }
a:hover { text-decoration:underline; }
h2 { font-size:15px; color:#b7c3d0; margin:34px 0 12px; padding-bottom:7px;
     border-bottom:1px solid #1f2a37; }
ol, ul { padding-left:20px; margin:0; }
li { margin:9px 0; }
.lead { font-size:17px; font-weight:600; }
.meta { color:#6b7785; font-size:12px; margin-left:6px; }
.sum { color:#9fb0c0; font-size:13px; margin:2px 0 0 0; }
.chips { display:flex; flex-wrap:wrap; gap:6px; }
.chip { border:1px solid #22303d; background:#16202b; border-radius:999px;
        padding:2px 10px; font-size:12px; color:#9fb0c0; }
table { width:100%; border-collapse:collapse; font-size:13px; }
th, td { text-align:left; padding:4px 8px; border-bottom:1px solid #18212b; }
th { color:#6b7785; font-weight:500; }
.muted { color:#6b7785; }
footer { margin-top:44px; color:#4b5563; font-size:11px; }
"""


def _esc(text: Any) -> str:
    return html.escape(str(text or ""))


def _item_line(item: dict[str, Any], *, lead: bool = False) -> str:
    title = _esc(item.get("title"))
    url = _esc(item.get("url"))
    meta = []
    if item.get("source"):
        meta.append(_esc(item["source"]))
    if int(item.get("event_sources") or 0) > 1:
        meta.append(f"{item['event_sources']} 家")
    if int(item.get("days_seen") or 1) > 1:
        meta.append(f"{item['days_seen']} 天")
    meta_html = f'<span class="meta">{" · ".join(meta)}</span>' if meta else ""
    summary = " ".join(str(item.get("summary") or "").split())[:200]
    sum_html = f'<div class="sum">{_esc(summary)}</div>' if summary and len(summary) >= 20 else ""
    cls = ' class="lead"' if lead else ""
    return (f'<li><a{cls} href="{url}" target="_blank" rel="noopener">{title}</a>'
            f'{meta_html}{sum_html}</li>')


def _today(payload: dict[str, Any]) -> str:
    plan = edition.arrange(payload)
    lead = plan.get("lead")
    if not lead:
        return '<p class="muted">今天没有选出要闻。</p>'
    parts = ["<ol>", _item_line(lead, lead=True)]
    parts += [_item_line(it) for it in plan["highlights"] + plan["body"]]
    parts.append("</ol>")
    if plan["briefs"]:
        parts.append('<p class="muted" style="font-size:12px;margin-top:14px;">快讯</p>')
        parts.append("<ul>" + "".join(_item_line(it) for it in plan["briefs"]) + "</ul>")
    return "".join(parts)


def _week(day: str | None) -> str:
    try:
        data = report.compose("weekly", day)
    except Exception:
        return '<p class="muted">本周回顾暂不可用。</p>'
    if not data["top"]:
        return '<p class="muted">本周还没有进过日报的内容。</p>'
    start, end = data["range"]
    head = (f'<p class="muted" style="font-size:12px;margin:0 0 10px;">'
            f'{start} ~ {end} · {data["reports"]} 条报道 · {data["events"]} 个事件</p>')
    return head + "<ol>" + "".join(_item_line(it) for it in data["top"][:12]) + "</ol>"


def _topics(day: str | None) -> str:
    try:
        rows = store.structure_history(days=30, day=day)
        data = topics.compute(rows, days=30)
    except Exception:
        return '<p class="muted">主题暂不可用。</p>'
    if not data["categories"]:
        return '<p class="muted">还没有结构化结果。</p>'
    chips = "".join(
        f'<span class="chip">{_esc(g["label"])} {g["count"]}</span>'
        for g in data["categories"])
    return f'<div class="chips">{chips}</div>'


def _timeline(day: str | None) -> str:
    try:
        rows = store.event_dump(days=120, day=day)
        data = timeline.compute(rows)
    except Exception:
        return '<p class="muted">时间线暂不可用。</p>'
    if not data["monthly"]["subjects"]:
        return '<p class="muted">还没有足够的事件。</p>'
    body = "".join(
        f'<tr><td>{_esc(s["subject"])}</td><td>{s["total"]}</td>'
        f'<td class="muted">{_esc("、".join(sorted(s["months"])))}</td></tr>'
        for s in data["monthly"]["subjects"][:12])
    return ("<table><thead><tr><th>主体</th><th>事件数</th><th>出现月份</th></tr></thead>"
            f"<tbody>{body}</tbody></table>")


def _override():
    from .theme import override_css
    return override_css()


def _nav():
    from .theme import bottom_nav, nav_html
    return nav_html("") + bottom_nav("")


def _self_contained(doc: str) -> str:
    """离线版必须一个文件自洽：去掉外部引用的图标与品牌图，品牌退回文字。"""
    import re as _re

    doc = _re.sub(r'<link rel="(icon|apple-touch-icon|manifest)"[^>]*>', "", doc)
    doc = _re.sub(r'<img[^>]*class="brand[^"]*"[^>]*>', "", doc)
    doc = doc.replace("@@ROOT@@", "")
    doc = doc.replace('<a class="brand"', '<a class="brand brand-text"')
    return doc


def build(payload: dict[str, Any], site_root: Path | None = None,
          day: str | None = None) -> dict[str, Any]:
    """生成 `site/offline.html`。任何一块失败都只影响那一块。"""
    day = day or store.today_str()
    stats = payload.get("stats") or {}
    generated = stats.get("generated_at") or datetime.now().isoformat(timespec="seconds")

    doc = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Z-Bit · 离线版 {_esc(day)}</title>
<style>{_CSS}{_override()}</style></head><body>{_nav()}<div class="wrap">
<h1>Z-Bit · 离线版</h1>
<div class="sub">{_esc(day)} · {len(payload.get('items') or [])} 条 ·
{_esc(stats.get('sources_ok') or 0)} 个源 · 生成于 {_esc(generated[:19].replace('T', ' '))}</div>

<h2>今日要闻</h2>
{_today(payload)}

<h2>本周要闻</h2>
{_week(day)}

<h2>主题分布（近 30 天）</h2>
{_topics(day)}

<h2>时间线（近 120 天）</h2>
{_timeline(day)}

<footer>单文件归档：不引用任何外部样式或脚本，断网可看。链接指向原文，需要联网。</footer>
</div></body></html>"""

    target = (site_root or SITE) / "offline.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_self_contained(doc), encoding="utf-8")
    return {"file": str(target), "bytes": target.stat().st_size, "day": day}
