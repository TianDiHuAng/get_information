"""Token 羊毛：免费额度、赠送、限时白嫖。

只对 AI 行业有意义（别的行业没有"薅 token"这回事），所以做成模块。

吸收 freebie-radar 的 `obtain` 维度：**不把「抽奖」「试用」「推广」混进「真白嫖」**。
价格只回答要不要钱，回答不了能不能确定拿到 —— 抽 200 份会员、7 天试用、
注册送体验金但充值才用，价格都是 0 元，但一个靠运气、一个到期收费、一个是广告。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from collector import evidence, obtain, store, theme

NAME = "free_tokens"
TITLE = "Token 羊毛"
HREF = "/free-tokens.html"
SECTION = "模型"
ICON = "tag"

CSS = """
.ob-summary{display:flex;flex-wrap:wrap;gap:8px;margin:2px 0 20px}
.ob-summary a{display:inline-flex;align-items:baseline;gap:6px;padding:6px 13px;
              border-radius:999px;background:var(--surface);border:1px solid var(--line);
              font-size:12.5px;color:var(--ink-3);box-shadow:var(--shadow-card)}
.ob-summary a b{font:700 15px var(--font-mono);color:var(--ink)}
.ob-summary a.on{border-color:var(--accent);color:var(--accent)}
.ob-summary a.on b{color:var(--accent)}
.ob-sec{display:flex;align-items:baseline;gap:10px;margin:30px 0 10px;
        padding-bottom:8px;border-bottom:1px solid var(--line)}
.ob-sec:first-of-type{margin-top:8px}
.ob-sec h2{margin:0;font-size:16px;font-weight:680;color:var(--ink)}
.ob-sec .n{font:600 12px var(--font-mono);color:var(--ink-4)}
.ob-sec .hint{font-size:12px;color:var(--ink-4);margin-left:auto}
.ob-badge{display:inline-flex;align-items:center;height:18px;padding:0 8px;border-radius:999px;
          font-size:11px;font-weight:600;background:var(--bg-sunk);color:var(--ink-3)}
.ob-badge.lottery{background:rgba(211,178,106,.16);color:#8a6a1f}
.ob-badge.trial{background:rgba(91,91,214,.10);color:var(--accent)}
.ob-badge.conditional{background:rgba(184,135,58,.12);color:#7c5a24}
.ob-badge.promo{background:rgba(216,106,82,.12);color:var(--hot)}
@media(max-width:640px){.ob-sec .hint{display:none}}
"""


def _collect(day: str, days: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for offset in range(days):
        try:
            day_str = store.shift_day(day, -offset) if offset else day
            batch = store.all_items(day_str, limit=800, include_archived=True)
        except Exception:
            batch = []
        for it in batch:
            if not (it.get("source") in ("deals", "openrouter_free", "deepflood") or it.get("deal")):
                continue
            # 证据校验：deals 源也会发新闻（财报/期货/政策），
            # 没有价格或领取证据的一律不算羊毛。
            if not evidence.is_deal_like(str(it.get("title") or ""),
                                         str(it.get("summary") or "")):
                continue
            key = it.get("url") or str(it.get("id"))
            if key in seen:
                continue
            seen.add(key)
            it = dict(it)
            it["obtain"] = obtain.guess(str(it.get("title") or ""), str(it.get("summary") or ""))
            rows.append(it)
        if offset >= 2 and rows:
            break
    rows.sort(key=lambda r: str(r.get("published") or ""), reverse=True)
    return rows


def _card(it: dict[str, Any]) -> str:
    pub = (it.get("published") or "")[:16].replace("T", " ")
    level = it.get("obtain") or obtain.FREE
    badge = ""
    if level != obtain.FREE:
        badge = f'<span class="ob-badge {level}">{obtain.label(level)}</span>'
    return (
        f'<li class="slot"><time datetime="{theme.esc(pub)}">'
        f'{theme.esc(pub[11:16] or "--:--")}</time>'
        '<span class="rail" aria-hidden="true"></span>'
        '<article class="cardrow"><header class="hd"><span class="src">'
        f'<span>{theme.esc(it.get("source"))}</span>'
        f'<span class="dot"></span><span>{theme.esc(pub[5:16])}</span>'
        f'{badge}</span></header>'
        f'<h3><a href="{theme.esc(it.get("url"))}" target="_blank" rel="noopener">'
        f'{theme.esc(it.get("title"))}</a></h3>'
        + (f'<p class="sum">{theme.esc(" ".join(str(it.get("summary") or "").split())[:180])}</p>'
           if it.get("summary") else "")
        + "</article></li>")


def build(root: Path, payload: dict[str, Any] | None = None,
          day: str | None = None, days: int = 14) -> dict[str, Any]:
    day = store.content_day(day)
    rows = _collect(day, days)
    tally = obtain.counts(rows)

    summary = "".join(
        f'<a class="{("on" if k == obtain.FREE else "")}" href="#ob-{k}">'
        f'{theme.esc(obtain.label(k))} <b>{tally.get(k, 0)}</b></a>'
        for k in obtain.ORDER if tally.get(k))

    blocks = []
    for k in obtain.ORDER:
        group = [r for r in rows if r.get("obtain") == k]
        if not group:
            continue
        cards = "".join(_card(it) for it in group[:40])
        blocks.append(
            f'<h2 class="ob-sec" id="ob-{k}"><span>{theme.esc(obtain.label(k))}</span>'
            f'<span class="n">{len(group)} 条</span>'
            f'<span class="hint">{theme.esc(obtain.hint(k))}</span></h2>'
            f'<ol class="feed">{cards}</ol>')

    if not blocks:
        blocks.append('<p class="muted">近两周没有羊毛线索。跑一次 <code>python run.py</code> 看看。</p>')

    body = (f'<p class="lead">近 {days} 天 {len(rows)} 条。按「能不能确定拿到」分组 —— '
            '直接白嫖、有条件、抽奖、试用、推广分开列，不把运气和广告混进福利。</p>'
            f'<div class="ob-summary">{summary}</div>' + "".join(blocks)
            + '<p class="muted small">分类由关键词规则判定（顺序：抽奖 &gt; 推广 &gt; 试用 &gt; '
              '有条件 &gt; 白嫖），只做粗分，领取前请以原文条件为准。</p>')
    doc = theme.page("Token 羊毛", body, active=HREF, extra_css=CSS)
    root.mkdir(parents=True, exist_ok=True)
    (root / "free-tokens.html").write_text(doc, encoding="utf-8")
    return {"file": str(root / "free-tokens.html"), "items": len(rows), "obtain": tally}
