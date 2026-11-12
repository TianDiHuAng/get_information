"""长期知识沉淀与叙事对比。

两件 AIHOT 结构上不做、而单用户值得做的事：

1. **长期时间线**：它的召回窗口是两周，归档即结束。但"这家公司这半年发布了什么"
   才是真正有用的东西 —— 靠 events + structures 攒出来的跨度，比多一个功能更值钱。
2. **叙事对比**：同一件事，官方公告、媒体报道、社区讨论的说法常常不一样。
   这里把它们并排放出来，不判断谁对 —— 只让你看见差异。

两个输出都只读库，不调模型。
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from . import store, theme

ROOT = Path(__file__).parent.parent
SITE = ROOT / "site"

# 叙事分组：官方一手 / 媒体 / 社区
OFFICIAL_LAYERS = ("primary",)
MEDIA_LAYERS = ("rank", "broad", "search")


def _month(published: str) -> str:
    m = re.match(r"(\d{4})-(\d{2})", published or "")
    return f"{m.group(1)}-{m.group(2)}" if m else "未知"


def _subjects(row: dict[str, Any]) -> set[str]:
    out = {str(s).strip() for s in (row.get("subjects") or []) if str(s).strip()}
    return out


def monthly(rows: Iterable[dict[str, Any]], top: int = 12) -> dict[str, Any]:
    """主体 × 月份的事件数。只统计真正成事件（多篇）的那些。"""
    per_subject: dict[str, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
    per_event: dict[str, set[str]] = defaultdict(set)
    months: set[str] = set()

    for row in rows:
        month = _month(row.get("first_at") or row.get("published") or "")
        event_id = row.get("event_id")
        if event_id is None:
            continue
        per_event[str(event_id)].add(month)
        months.add(month)
        for subject in _subjects(row):
            per_subject[subject][month].add(int(event_id))

    ranked = sorted(per_subject.items(),
                    key=lambda kv: (-len(set().union(*kv[1].values())), kv[0]))
    table = []
    for subject, buckets in ranked[:top]:
        total = len(set().union(*buckets.values()))
        table.append({
            "subject": subject,
            "total": total,
            "months": {m: len(ids) for m, ids in sorted(buckets.items())},
        })
    return {
        "months": sorted(m for m in months if m != "未知"),
        "subjects": table,
        "events": len(per_event),
    }


def narratives(rows: Iterable[dict[str, Any]], limit: int = 20) -> list[dict[str, Any]]:
    """同一事件里，官方 / 媒体 / 社区各说了什么。

    只做分组与并列，不做"哪边对"的判断 —— 那需要人看。
    """
    groups: dict[int, dict[str, Any]] = {}
    for row in rows:
        event_id = row.get("event_id")
        if event_id is None:
            continue
        bucket = groups.setdefault(int(event_id), {
            "event_id": int(event_id),
            "title": row.get("event_title") or "",
            "first_at": row.get("first_at") or "",
            "official": [], "media": [], "social": [],
        })
        layer = (row.get("layer") or "broad")
        entry = {"title": row.get("item_title") or "", "source": row.get("source") or "",
                 "url": row.get("url") or ""}
        if layer in OFFICIAL_LAYERS:
            bucket["official"].append(entry)
        elif layer in MEDIA_LAYERS:
            bucket["media"].append(entry)
        else:
            bucket["social"].append(entry)

    # 只保留"至少两个不同渠道"的事件：只有一个来源说明不了叙事差异
    interesting = [
        b for b in groups.values()
        if sum(1 for k in ("official", "media", "social") if b[k]) >= 2
    ]
    interesting.sort(key=lambda b: (-len(b["official"]) - len(b["media"]) - len(b["social"]),
                                    b["first_at"]))
    for bucket in interesting:
        bucket["sources"] = sum(len(bucket[k]) for k in ("official", "media", "social"))
    return interesting[:limit]


def compute(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(rows)
    return {"monthly": monthly(rows), "narratives": narratives(rows)}


# --------------------------------------------------------------------------- #
# 渲染
# --------------------------------------------------------------------------- #

def _override():
    from .theme import override_css
    return override_css()


def render(data: dict[str, Any]) -> str:
    from .share import og_tags

    monthly = data["monthly"]
    months = monthly["months"]
    rows_html = []
    for subj in monthly["subjects"]:
        cells = []
        for month in months:
            n = subj["months"].get(month, 0)
            opacity = min(1.0, 0.12 + n * 0.22) if n else 0.04
            cells.append(f'<td class="cell" style="--o:{opacity:.2f}" title="{month}: {n} 件">{n or ""}</td>')
        rows_html.append(
            f'<tr><th>{subj["subject"]}</th>{"".join(cells)}<td class="tot">{subj["total"]}</td></tr>')

    head = "".join(f'<th class="mh">{m[2:]}</th>' for m in months)

    cards = []
    for b in data["narratives"]:
        def col(name: str, key: str) -> str:
            items = b[key]
            if not items:
                return f'<div class="col"><h4>{name}</h4><div class="muted">—</div></div>'
            lis = "".join(
                f'<li><a href="{e["url"]}" target="_blank" rel="noopener">{e["title"][:60]}</a>'
                f'<span class="src">{e["source"]}</span></li>' for e in items[:4])
            return f'<div class="col"><h4>{name}<span class="n">{len(items)}</span></h4><ul>{lis}</ul></div>'

        cards.append(
            f'<div class="story"><div class="st">'
            f'<a href="@@ROOT@@/archive/">{b["title"][:70]}</a>'
            f'<span class="muted"> · {b["first_at"][:10]} · {b["sources"]} 篇</span></div>'
            f'<div class="cols">{col("官方", "official")}{col("媒体", "media")}{col("社区", "social")}</div>'
            f'</div>')

    # 页面专属组件样式：只用主题变量，不写死颜色
    page_css = """
.tl-table{width:100%;border-collapse:collapse;font-size:12.5px}
.tl-table th,.tl-table td{padding:5px 6px;text-align:center;border-bottom:1px solid var(--line-soft)}
.tl-table th{color:var(--ink-4);font-weight:500}
.tl-table tbody th{text-align:left;color:var(--ink-2);font-weight:600;white-space:nowrap}
.tl-table .cell{background:color-mix(in oklab,var(--accent) calc(var(--o) * 100%),transparent);
                border-radius:3px;color:var(--ink);min-width:34px}
.tl-table .tot{color:var(--ink-4)}
.story{background:var(--surface);border:1px solid var(--line);border-radius:var(--r-card);
       padding:13px 15px;margin-bottom:12px;box-shadow:var(--shadow-card)}
.story .st{font-weight:600;margin-bottom:9px;color:var(--ink)}
.cols{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
@media(max-width:700px){.cols{grid-template-columns:1fr}}
.cols h4{font-size:12px;color:var(--ink-3);margin:0 0 6px;font-weight:600}
.cols h4 .n{color:var(--ink-4);margin-left:6px;font-weight:400}
.cols ul{margin:0;padding-left:16px}
.cols li{font-size:12.5px;margin:3px 0;line-height:1.5;color:var(--ink-3)}
.cols li a{color:var(--ink-2)}
.cols .src{color:var(--ink-4);margin-left:6px}
"""

    rows_block = "".join(rows_html) or '<tr><td class="muted">还没有足够的事件</td></tr>'
    cards_block = "".join(cards) or '<p class="muted">今天没有跨渠道的事件</p>'
    body = (
        f'<h2 class="sec">谁在什么时候出现 '
        f'<span class="muted small">{len(months)} 个月 · {monthly["events"]} 个事件</span></h2>'
        f'<div class="scroll"><table class="tl-table"><thead><tr><th></th>{head}'
        f'<th>合计</th></tr></thead><tbody>{rows_block}</tbody></table></div>'
        '<h2 class="sec">同一件事，三种说法</h2>'
        + cards_block
        + '<p class="muted small" style="margin-top:26px;">'
          '只读数据库生成；叙事分组按信源层级（官方一手 / 媒体 / 社区），不代表哪边更可信。</p>'
    )
    return theme.page("时间线", body, active="/timeline.html",
                      lead="主体 × 月份跨度，以及同一件事在官方 / 媒体 / 社区三种渠道下的说法",
                      extra_css=page_css)


def build(site_root: Path | None = None, days: int = 120) -> dict[str, Any]:
    rows = store.event_dump(days=days)
    data = compute(rows)
    target = (site_root or SITE) / "timeline.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(data), encoding="utf-8")
    return {
        "file": str(target),
        "events": data["monthly"]["events"],
        "subjects": len(data["monthly"]["subjects"]),
        "narratives": len(data["narratives"]),
    }
