"""模型榜：LMArena 文本榜 + Artificial Analysis 智能指数。

这是「只对 AI 行业有意义」的功能，所以做成模块（不在框架里）。
数据来自 `collector/leaderboards.py` 的本地缓存（每天抓一次）。
"""

from __future__ import annotations

import html
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


def _delta(now: int | None, before: int | None) -> str:
    if not now or not before:
        return '<span class="muted">—</span>'
    if now < before:
        return f'<span style="color:var(--ok)">▲{before - now}</span>'
    if now > before:
        return f'<span style="color:var(--hot)">▼{now - before}</span>'
    return '<span class="muted">·</span>'


def build(root: Path, payload: dict[str, Any] | None = None,
          day: str | None = None) -> dict[str, Any]:
    sections = []
    for title, path, cols in (
        ("LMArena 文本榜", lb.PATH, ("评分", "票数")),
        ("Artificial Analysis 智能指数", lb.AA_PATH, ("智能分", "输出价")),
    ):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            sections.append(f'<h2 class="sec">{theme.esc(title)}</h2>'
                            '<p class="muted">还没有数据，跑一次 <code>python run.py</code>。</p>')
            continue
        models = (data.get("models") or [])[: getattr(lb, "TOP_N", 20)]
        rows = []
        for m in models:
            rank = m.get("rank")
            if title.startswith("LMArena"):
                v1, v2 = m.get("rating"), m.get("votes")
                v1s = f"{v1:.1f}" if isinstance(v1, (int, float)) else "—"
                v2s = f"{v2:,}" if isinstance(v2, int) else "—"
            else:
                v1, v2 = m.get("intelligence"), m.get("price_out")
                v1s = f"{v1:.1f}" if isinstance(v1, (int, float)) else "—"
                v2s = f"${v2:g}" if isinstance(v2, (int, float)) else "—"
            rows.append(
                f'<tr><td class="num" style="width:38px">{rank}</td>'
                f'<td>{theme.esc(m.get("model"))}'
                f'<span class="muted small"> · {theme.esc(m.get("org") or "")}</span></td>'
                f'<td class="num">{v1s}</td><td class="num">{v2s}</td>'
                f'<td class="num">{_delta(rank, m.get("prev_rank"))}</td></tr>')
        sections.append(
            f'<h2 class="sec">{theme.esc(title)}'
            f'<span class="muted" style="font-size:11px">'
            f'{theme.esc(str(data.get("date") or ""))}</span></h2>'
            '<div class="scroll"><table><thead><tr><th>#</th><th>模型</th>'
            f'<th>{cols[0]}</th><th>{cols[1]}</th><th>名次变化</th>'
            f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div>')

    body = ('<h1 class="title">模型榜<small>每天同步一次</small></h1>'
            + "".join(sections)
            + '<p class="muted small" style="margin-top:20px;">'
              'LMArena 取自官方每日同步的 HF 数据集；智能分与价格取自 '
              'Artificial Analysis 免费接口。名次变化对比的是这个模型自己上一次的名次。</p>')
    doc = theme.page(f"模型榜 · {theme.BRAND}", body, active=HREF,
                     subtitle=f"模型榜 · {theme.BRAND}", own_heading=True)
    root.mkdir(parents=True, exist_ok=True)
    (root / "leaderboard.html").write_text(doc, encoding="utf-8")
    return {"file": str(root / "leaderboard.html"), "sections": len(sections)}
