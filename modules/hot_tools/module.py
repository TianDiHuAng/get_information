"""热门工具榜：近 7 天被 AI 创作者提到最多的工具。

数据来自 XFeed 的 insights.json（按"提及它的不同作者数"排序，不是按点赞），
比单看某条爆款更能反映"这个工具真的在被人用"。

为什么做成模块：只有 AI 行业有这种"工具热度"概念，
换到制药包时这个模块不会出现在导航里（模块清单按站点配置）。
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from collector import theme, xfeedai

NAME = "hot_tools"
TITLE = "热门工具"
HREF = "/hot-tools.html"
SECTION = "X 生态"
ICON = "grid"

CSS = """
.ht-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:14px;margin:8px 0 22px}
.ht-card{background:var(--surface);border:1px solid var(--line);border-radius:var(--r-card);
         box-shadow:var(--shadow-card);padding:16px 18px;display:flex;flex-direction:column;gap:8px}
.ht-card .hd{display:flex;align-items:baseline;justify-content:space-between;gap:10px}
.ht-card .nm{font-size:16px;font-weight:650;color:var(--ink);overflow:hidden;
             text-overflow:ellipsis;white-space:nowrap}
.ht-card .no{font:700 12px var(--font-mono);color:var(--ink-4)}
.ht-card .ct{font-size:12.5px;color:var(--ink-4)}
.ht-card .ct b{font:700 20px var(--font-mono);color:var(--accent);margin-right:3px}
.ht-card ul{list-style:none;margin:2px 0 0;padding:0;display:flex;flex-direction:column;gap:5px}
.ht-card li{font-size:12.5px;line-height:1.5;color:var(--ink-3);overflow:hidden;
            text-overflow:ellipsis;white-space:nowrap}
.ht-card li::before{content:"·";color:var(--ink-4);margin-right:6px}
.ht-bar{height:4px;border-radius:2px;background:var(--bg-sunk);overflow:hidden;margin-top:2px}
.ht-bar i{display:block;height:100%;background:linear-gradient(90deg,#9a9af2,var(--accent))}
"""

_GROUP_LABEL = {"beginner": "入门", "advanced": "进阶", "workflow": "工作流"}


def _pretty(key: str) -> str:
    """gh:owner/repo → owner/repo；其余原样但首字母大写。"""
    if key.startswith("gh:"):
        return key[3:]
    return key[:1].upper() + key[1:] if key else key


def build(root: Path, payload: dict[str, Any] | None = None,
          day: str | None = None) -> dict[str, Any]:
    rows = xfeedai.hot_tools(days=7, limit=18)
    if not rows:
        body = '<p class="muted">暂时取不到工具热度数据（xfeed.ai 的 insights.json 不可用）。</p>'
        _write(root, theme.page("热门工具", body, active=HREF))
        return {"file": str(root / "hot-tools.html"), "tools": 0}

    top = max((r["total"] for r in rows), default=1) or 1
    cards = []
    for idx, r in enumerate(rows, 1):
        samples = []
        for g in (r.get("groups") or []):
            for post in (g.get("posts") or [])[:1]:
                t = post.get("title") or ""
                if t:
                    samples.append(t)
        lis = "".join(f"<li>{theme.esc(t[:56])}</li>" for t in samples[:3])
        width = max(6, round(r["total"] / top * 100))
        cards.append(
            f'<div class="ht-card"><div class="hd"><span class="nm">{theme.esc(_pretty(r["key"]))}</span>'
            f'<span class="no">No.{idx:02d}</span></div>'
            f'<div class="ct"><b>{r["total"]}</b>位创作者提到</div>'
            f'<div class="ht-bar"><i style="width:{width}%"></i></div>'
            + (f'<ul>{lis}</ul>' if lis else "")
            + "</div>")

    body = ('<p class="lead">近 7 天被不同 AI 创作者提到最多的工具。'
            '按"有多少位作者在说"排序 —— 比单条爆款更能说明它真的在被人用。</p>'
            f'<div class="ht-grid">{"".join(cards)}</div>'
            '<p class="muted small">数据来自 xfeed.ai 的公开热度榜，每 7 天滚动一次。'
            '榜单只统计提及次数，不代表质量评价。</p>')
    _write(root, theme.page("热门工具", body, active=HREF, extra_css=CSS))
    return {"file": str(root / "hot-tools.html"), "tools": len(rows)}


def _write(root: Path, doc: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "hot-tools.html").write_text(doc, encoding="utf-8")
