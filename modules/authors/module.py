"""作者精选：XFeed 逐条审阅出的 16 位 AI 创作者。

为什么值得单独一页：读者真正缺的不是"更多链接"，而是**知道该关注谁**。
XFeed 的这份名单按"具体任务、方法信息、持续实践经验"选，不按曝光排名，
比按粉丝数排的榜单有参考价值。

头像在构建时下载到本地（site/assets/avatars/），不依赖外站热链。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from collector import theme, xfeedai

NAME = "authors"
TITLE = "作者精选"
HREF = "/authors.html"
SECTION = "更多"
ICON = "user"

CSS = """
.au-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px;margin:8px 0 22px}
.au-card{background:var(--surface);border:1px solid var(--line);border-radius:var(--r-card);
         box-shadow:var(--shadow-card);padding:16px 18px;display:flex;flex-direction:column;gap:10px}
.au-top{display:flex;align-items:center;gap:12px;min-width:0}
.au-top img{width:44px;height:44px;border-radius:50%;object-fit:cover;flex:none;
            background:var(--bg-sunk);border:1px solid var(--line)}
.au-id{min-width:0}
.au-id b{display:block;font-size:15px;font-weight:650;color:var(--ink);
         overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.au-id span{font:12px var(--font-mono);color:var(--ink-4)}
.au-focus{display:inline-flex;align-items:center;padding:2px 9px;border-radius:999px;
          background:var(--accent-soft);color:var(--accent);font-size:11.5px;font-weight:600;
          width:fit-content}
.au-sum{margin:0;font-size:13.5px;line-height:1.7;color:var(--ink-3)}
.au-meta{display:flex;flex-wrap:wrap;gap:10px;font-size:11.5px;color:var(--ink-4)}
.au-tools{display:flex;flex-wrap:wrap;gap:6px}
.au-tools span{font-size:11px;padding:2px 8px;border-radius:999px;background:var(--bg-sunk);
               color:var(--ink-3)}
.au-pick{margin:0;padding-top:10px;border-top:1px solid var(--line-soft);font-size:12.5px;
         color:var(--ink-3);line-height:1.6}
.au-pick b{color:var(--ink-4);font-weight:600;margin-right:5px}
"""


def _avatars(root: Path, authors: list[dict[str, Any]]) -> dict[str, str]:
    """下载头像到本地，返回 handle → 站内路径。失败就跳过（不显示图片）。"""
    folder = root / "assets" / "avatars"
    out: dict[str, str] = {}
    for a in authors:
        handle = str(a.get("handle") or "")
        if not handle:
            continue
        target = folder / f"{handle}.jpg"
        if not target.is_file():
            data = xfeedai.avatar_bytes(str(a.get("avatar") or ""))
            if not data:
                continue
            folder.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        out[handle] = f"/assets/avatars/{handle}.jpg"
    return out


def build(root: Path, payload: dict[str, Any] | None = None,
          day: str | None = None) -> dict[str, Any]:
    authors = xfeedai.authors()
    if not authors:
        _write(root, theme.page("作者精选", '<p class="muted">暂时取不到作者名单。</p>', active=HREF))
        return {"file": str(root / "authors.html"), "authors": 0}

    avatars = _avatars(root, authors)
    cards = []
    for a in authors:
        handle = str(a.get("handle") or "")
        img = avatars.get(handle, "")
        tools = "".join(f"<span>{theme.esc(t.get('name') or '')}</span>"
                        for t in (a.get("topTools") or [])[:5])
        cards.append(
            '<div class="au-card"><div class="au-top">'
            + (f'<img src="{img}" alt="" loading="lazy">' if img else "")
            + f'<div class="au-id"><b>{theme.esc(a.get("name") or handle)}</b>'
              f'<span>@{theme.esc(handle)}</span></div></div>'
            + (f'<span class="au-focus">{theme.esc(a.get("focus") or "")}</span>'
               if a.get("focus") else "")
            + f'<p class="au-sum">{theme.esc(a.get("summary") or "")}</p>'
            + (f'<div class="au-tools">{tools}</div>' if tools else "")
            + '<div class="au-meta">'
              f'<span>收录 {int(a.get("postCount") or 0)} 条</span>'
              f'<span>近况 {int(a.get("recentCount") or 0)} 条</span>'
              + (f'<span>{"海外" if a.get("isOverseas") else "国内"}</span>')
              + (f'<span>{theme.esc(a.get("addedAt") or "")} 入选</span>' if a.get("addedAt") else "")
              + '</div>'
            + (f'<p class="au-pick"><b>代表作</b>{theme.esc(a.get("selectionTitle") or "")}</p>'
               if a.get("selectionTitle") else "")
            + "</div>")

    body = ('<p class="lead">XFeed 从已收录内容里逐条审阅选出的创作者 —— '
            '按「具体任务、方法信息、持续实践经验」选，不按曝光排名。'
            '共 16 位，头像与简介随构建缓存到本地。</p>'
            f'<div class="au-grid">{"".join(cards)}</div>'
            '<p class="muted small">名单来源 xfeed.ai 的 author-manifest.json，'
            '每位作者的完整内容请点开其 X 主页查看。</p>')
    _write(root, theme.page("作者精选", body, active=HREF, extra_css=CSS))
    return {"file": str(root / "authors.html"), "authors": len(authors)}


def _write(root: Path, doc: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "authors.html").write_text(doc, encoding="utf-8")
