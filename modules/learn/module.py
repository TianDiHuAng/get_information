"""工具实操：每个工具"能做什么"与"坑在哪"。

insights.json 把每条帖子按 beginner / practice / limitations / discussion 分组。
discussion 有 2571 条（噪音多），practice 有 374 条（真正的做法），
limitations 只有 8 条 —— 但恰恰是最稀缺、最值钱的那类信息：
大家都是怎么用错的、什么地方不靠谱。

所以这页只取 practice 与 limitations，不堆 discussion。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from collector import theme, xfeedai

NAME = "learn"
TITLE = "工具实操"
HREF = "/learn.html"
SECTION = "更多"
ICON = "book"

CSS = """
.tg-card{background:var(--surface);border:1px solid var(--line);border-radius:var(--r-card);
         box-shadow:var(--shadow-card);padding:18px 20px;margin:0 0 16px}
.tg-hd{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin-bottom:10px}
.tg-hd h2{margin:0;font-size:17px;font-weight:680;color:var(--ink)}
.tg-hd .n{font-size:12px;color:var(--ink-4)}
.tg-sec{margin:0 0 4px;font-size:11.5px;font-weight:600;letter-spacing:.06em;
        text-transform:uppercase;color:var(--ink-4)}
.tg-card ul{list-style:none;margin:4px 0 14px;padding:0;display:flex;flex-direction:column;gap:6px}
.tg-card li{font-size:13.5px;line-height:1.6;color:var(--ink-2);padding-left:16px;position:relative}
.tg-card li::before{content:"";position:absolute;left:0;top:9px;width:5px;height:5px;
                    border-radius:50%;background:var(--accent);opacity:.5}
.tg-card.lim li::before{background:var(--hot);opacity:.7}
.tg-card ul:last-child{margin-bottom:0}
.tg-src{font-size:11.5px;color:var(--ink-4);margin-left:6px}
@media(max-width:640px){.tg-card{padding:14px 16px}.tg-card li{font-size:13px}}
"""


def build(root: Path, payload: dict[str, Any] | None = None,
          day: str | None = None) -> dict[str, Any]:
    tools = xfeedai.tool_guides(min_practice=3, limit=12)
    if not tools:
        _write(root, theme.page("工具实操", '<p class="muted">暂时取不到工具数据。</p>', active=HREF))
        return {"file": str(root / "learn.html"), "tools": 0}

    def pretty(key: str) -> str:
        return key[3:] if key.startswith("gh:") else key[:1].upper() + key[1:]

    cards = []
    for t in tools:
        practice = "".join(
            f'<li>{theme.esc(str(p.get("title") or "")[:90])}'
            f'<span class="tg-src">@{theme.esc(str(p.get("handle") or ""))}</span></li>'
            for p in t["practice"][:4])
        limits = "".join(
            f'<li>{theme.esc(str(p.get("title") or "")[:90])}'
            f'<span class="tg-src">@{theme.esc(str(p.get("handle") or ""))}</span></li>'
            for p in t["limitations"][:2])
        cards.append(
            f'<div class="tg-card"><div class="tg-hd"><h2>{theme.esc(pretty(t["key"]))}</h2>'
            f'<span class="n">{t["total"]} 位创作者提到</span></div>'
            f'<p class="tg-sec">怎么用</p><ul>{practice}</ul>'
            + (f'<p class="tg-sec">坑在哪</p><ul class="lim">{limits}</ul>' if limits else "")
            + "</div>")

    body = ('<p class="lead">按「有多少位创作者在实操」排序，每个工具取 4 条具体做法；'
            '有局限讨论的另外单列 —— 那部分最稀缺。</p>'
            f'{"".join(cards)}'
            '<p class="muted small">数据来自 xfeed.ai 的 insights.json，'
            '按 practice / limitations 分组；完整内容请点开原帖。</p>')
    _write(root, theme.page("工具实操", body, active=HREF, extra_css=CSS))
    return {"file": str(root / "learn.html"), "tools": len(tools)}


def _write(root: Path, doc: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "learn.html").write_text(doc, encoding="utf-8")
