"""模型榜：LMArena 文本榜 + Artificial Analysis 智能指数。

只对 AI 行业有意义，所以做成模块（不在框架里）。
数据来自 `collector/leaderboards.py` 的本地缓存（每天抓一次）。

版面：每个榜一张卡片，行内含分数条（看得见强弱）、前三名用名次色、
机构做成小标签 —— 纯表格读起来只剩数字，没有层次。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from collector import leaderboards as lb
from collector import theme

NAME = "leaderboard"
TITLE = "模型榜"
HREF = "/leaderboard.html"
SECTION = "模型"
ICON = "chart"

CSS = """
.lb-card{background:var(--surface);border:1px solid var(--line);border-radius:var(--r-card);
         box-shadow:var(--shadow-card);padding:6px 6px 2px;margin:0 0 20px;overflow:hidden}
.lb-head{display:flex;align-items:baseline;justify-content:space-between;gap:12px;
         padding:10px 12px 8px}
.lb-head h2{font-size:15px;font-weight:700;margin:0;color:var(--ink)}
.lb-head .d{font:11.5px var(--font-mono);color:var(--ink-4)}
.lb{list-style:none;margin:0;padding:0}
.lb li{display:grid;grid-template-columns:34px minmax(0,1fr) auto 34px;gap:10px;align-items:center;
       padding:9px 12px;border-top:1px solid var(--line-soft);position:relative}
.lb li:hover{background:var(--bg-sunk)}
/* 分数条：宽度按榜内最高分归一，一眼看出强弱 */
.lb .bar{grid-column:1/-1;height:3px;border-radius:2px;background:var(--line-soft);
         margin-top:7px;overflow:hidden}
.lb .bar i{display:block;height:100%;background:var(--accent);opacity:.55}
.lb .rk{font:700 13px var(--font-mono);color:var(--ink-4);text-align:right}
.lb li:nth-child(1) .rk{color:var(--rank-1)}
.lb li:nth-child(2) .rk{color:var(--rank-2)}
.lb li:nth-child(3) .rk{color:var(--rank-3)}
.lb .nm{min-width:0}
.lb .nm b{display:block;font-size:14px;font-weight:600;color:var(--ink);
          overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.lb .nm span{font-size:11.5px;color:var(--ink-4)}
.lb .val{display:flex;align-items:baseline;gap:8px;white-space:nowrap}
.lb .val b{font:700 15px var(--font-mono);color:var(--ink);font-variant-numeric:tabular-nums}
.lb .val span{font-size:11.5px;color:var(--ink-4)}
.lb .delta{font-size:12px;font-family:var(--font-mono);width:34px;text-align:right}
.lb .up{color:var(--ok)}
.lb .down{color:var(--hot)}
@media(max-width:640px){
  .lb li{grid-template-columns:28px minmax(0,1fr) auto 30px;padding:8px 10px}
  .lb .nm b{font-size:13.5px}
  .lb .val b{font-size:14px}
}
"""


def _delta(now: int | None, before: int | None) -> str:
    if not now or not before:
        return '<span class="delta muted">·</span>'
    if now < before:
        return f'<span class="delta up">▲{before - now}</span>'
    if now > before:
        return f'<span class="delta down">▼{now - before}</span>'
    return '<span class="delta muted">·</span>'


def _board(title: str, path: Path, kind: str) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return (f'<div class="lb-card"><div class="lb-head"><h2>{theme.esc(title)}</h2></div>'
                '<p class="muted" style="padding:0 12px 12px;">还没有数据，跑一次 '
                '<code>python run.py</code>。</p></div>')

    models = (data.get("models") or [])[: getattr(lb, "TOP_N", 20)]
    if kind == "lma":
        values = [float(m.get("rating") or 0) for m in models]
        top = max(values) if values else 1.0
        floor = min(values) if values else 0.0
    else:
        values = [float(m.get("intelligence") or 0) for m in models]
        top = max(values) if values else 1.0
        floor = min(values) if values else 0.0

    rows = []
    for idx, m in enumerate(models, 1):
        raw = values[idx - 1]
        # 条长归一：榜内最低分给 12%，最高给 100%，差距才看得出来
        span = max(top - floor, 0.001)
        width = 12 + 88 * (raw - floor) / span
        if kind == "lma":
            main = f"{raw:.1f}"
            sub = f'{m.get("votes") or 0:,} 票'
        else:
            main = f"{raw:.1f}"
            price = m.get("price_out")
            sub = f"${price:g} /M" if isinstance(price, (int, float)) else "—"
        rows.append(
            f'<li><span class="rk">{idx}</span>'
            f'<span class="nm"><b>{theme.esc(m.get("model"))}</b>'
            f'<span>{theme.esc(m.get("org") or "")}</span></span>'
            f'<span class="val"><b>{main}</b><span>{sub}</span></span>'
            f'{_delta(m.get("rank"), m.get("prev_rank"))}'
            f'<span class="bar"><i style="width:{width:.0f}%"></i></span></li>')
    return (f'<div class="lb-card"><div class="lb-head"><h2>{theme.esc(title)}</h2>'
            f'<span class="d">{theme.esc(str(data.get("date") or ""))}</span></div>'
            f'<ol class="lb">{"".join(rows)}</ol></div>')


def build(root: Path, payload: dict[str, Any] | None = None,
          day: str | None = None) -> dict[str, Any]:
    body = ('<h1 class="title">模型榜<small>每天同步一次</small></h1>'
            '<p class="lead">LMArena 文本榜与 Artificial Analysis 智能指数并列。'
            '名次变化对比的是这个模型自己上一次的名次。</p>'
            + _board("LMArena 文本榜", lb.PATH, "lma")
            + _board("Artificial Analysis 智能指数", lb.AA_PATH, "aa")
            + '<p class="muted small">LMArena 取自官方每日同步的 HF 数据集；'
              '智能分与输出价取自 Artificial Analysis 免费接口。</p>')
    doc = theme.page(f"模型榜 · {theme.BRAND}", body, active=HREF,
                     subtitle=f"模型榜 · {theme.BRAND}", own_heading=True,
                     extra_css=CSS)
    root.mkdir(parents=True, exist_ok=True)
    (root / "leaderboard.html").write_text(doc, encoding="utf-8")
    return {"file": str(root / "leaderboard.html"), "boards": 2}
