"""Token 羊毛：免费额度、赠送、降价。

只对 AI 行业有意义（别的行业没有"薅token"这回事），所以做成模块。
口径只认 deals 源与已打标条目 —— 页面只归集，不判断真伪。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from collector import store, theme

NAME = "free_tokens"
TITLE = "Token 羊毛"
HREF = "/free-tokens.html"
SECTION = "模型"
ICON = "tag"

_WORDS = ("免费", "赠送", "白嫖", "羊毛", "额度", "体验金", "注册送", "试用",
          "优惠", "折扣", "降价", "限免")


def build(root: Path, payload: dict[str, Any] | None = None,
          day: str | None = None, days: int = 14) -> dict[str, Any]:
    day = store.content_day(day)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for offset in range(days):
        try:
            day_str = store.shift_day(day, -offset) if offset else day
            batch = store.all_items(day_str, limit=800, include_archived=True)
        except Exception:
            batch = []
        for it in batch:
            if not (it.get("source") == "deals" or it.get("deal")):
                continue
            key = it.get("url") or str(it.get("id"))
            if key in seen:
                continue
            seen.add(key)
            rows.append(it)
        if offset >= 2 and rows:
            break

    rows.sort(key=lambda r: str(r.get("published") or ""), reverse=True)
    cards = []
    for it in rows[:60]:
        text = f'{it.get("title") or ""}{it.get("summary") or ""}'
        tags = [w for w in _WORDS if w in text][:3]
        tag_html = "".join(f'<span class="tag">{theme.esc(t)}</span>' for t in dict.fromkeys(tags))
        cards.append(
            f'<li class="item"><div class="time">'
            f'{theme.esc((it.get("published") or "")[11:16] or "--:--")}</div><div>'
            f'<div class="src"><span>{theme.esc(it.get("source"))}</span>'
            f'<span class="dot"></span><span>{theme.esc((it.get("published") or "")[5:10])}</span>'
            f'</div><h3><a href="{theme.esc(it.get("url"))}" target="_blank" rel="noopener">'
            f'{theme.esc(it.get("title"))}</a></h3>'
            + (f'<p class="sum">{theme.esc(" ".join(str(it.get("summary") or "").split())[:160])}</p>'
               if it.get("summary") else "")
            + (f'<div style="margin-top:8px;">{tag_html}</div>' if tag_html else "")
            + "</div></li>")

    body = ('<h1 class="title">Token 羊毛'
            f'<small>近 {days} 天 · {len(rows)} 条</small></h1>'
            '<p class="lead">免费额度、赠送、降价。点标题去原文核对，'
            '能不能用、还剩多少以原文为准。</p>'
            + (f'<ol class="feed">{"".join(cards)}</ol>' if cards
               else '<p class="muted">这几天没抓到羊毛。</p>')
            + '<p class="muted small" style="margin-top:18px;">'
              '口径：只收 deals 源与已打标的条目 —— 上游用「免费 / 额度 / 白嫖 / 注册送」'
              '等词搜索，这里不再二次撒网。</p>')
    doc = theme.page(f"Token 羊毛 · {theme.BRAND}", body, active=HREF,
                     subtitle=f"Token 羊毛 · {theme.BRAND}", own_heading=True)
    root.mkdir(parents=True, exist_ok=True)
    (root / "free-tokens.html").write_text(doc, encoding="utf-8")
    return {"file": str(root / "free-tokens.html"), "items": len(rows)}
