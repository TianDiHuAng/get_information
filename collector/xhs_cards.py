"""小红书 3:4 图文卡片生成：把深度稿拆成封面 + 内容卡，输出可直接上传的 PNG。

设计要点：
- 尺寸 1080×1440（3:4），缩略图状态下标题仍可读
- 每张卡只放一个信息点，长文自动分页，绝不溢出
- 三套视觉风格（编辑风 / 深色 / 瑞士风），一处切换
"""

from __future__ import annotations

import re
from pathlib import Path

CARD_W, CARD_H = 1080, 1440

# ---------------------------------------------------------------- 解析稿件


def parse_post(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")

    def block(start: str, end: str) -> str:
        if start not in text:
            return ""
        seg = text.split(start, 1)[1]
        if end and end in seg:
            seg = seg.split(end, 1)[0]
        return seg.strip()

    cover = re.findall(r"^\*\*(.+?)\*\*$", block("## 封面文案", "## 标题"), re.M)
    titles = re.findall(r"^\d+\.\s*(.+?)（\d+ 字）", block("## 标题", "## 正文"), re.M)
    body = block("## 正文", "## 标签")
    tags = block("## 标签", "\n---").splitlines()[0].strip() if "## 标签" in text else ""
    meta_line = block("---", "").splitlines()
    refs = [ln.strip(" -") for ln in meta_line if ln.startswith(("主打", "陪跑"))]

    sections: list[dict] = []
    cur = None
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = re.match(r"^([\U0001F300-\U0001FAFF\u2600-\u27BF])\s*(.+)$", line)
        if m and len(line) < 26:
            cur = {"emoji": m.group(1), "title": m.group(2).strip(), "lines": [], "raw": True}
            sections.append(cur)
        elif cur is not None:
            cur["lines"].append(line)
        else:
            sections.append({"emoji": "", "title": "", "lines": [line], "raw": False, "lead": True})

    date = ""
    dm = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if dm:
        date = dm.group(1)

    return {
        "cover": cover,
        "titles": titles,
        "sections": sections,
        "tags": tags,
        "refs": refs,
        "date": date,
        "raw_body": body,
    }


# ---------------------------------------------------------------- 分页


def _chunk(lines: list[str], max_chars: int = 150) -> list[list[str]]:
    """把一段正文按字数切成多页，尽量保持整句。"""
    pages, cur, total = [], [], 0
    for ln in lines:
        ln_len = len(ln)
        if cur and total + ln_len > max_chars:
            pages.append(cur)
            cur, total = [], 0
        cur.append(ln)
        total += ln_len
    if cur:
        pages.append(cur)
    return pages or [[]]


def build_cards(post: dict, max_chars: int = 150, figs: list[dict] | None = None) -> list[dict]:
    """把稿件转成卡片序列：封面 → 每段一到多张 → 结尾；有论文图时插入图卡。"""
    cards: list[dict] = []
    cover = post["cover"] or []
    lead_para = next((s for s in post["sections"] if s.get("lead")), None)

    cards.append(
        {
            "type": "cover",
            "kicker": "AI × DRUG DISCOVERY",
            "title": cover[0] if cover else (post["titles"][0] if post["titles"] else ""),
            "sub": cover[1:],
            "footer": f"arXiv 精读 · {post['date']}",
        }
    )

    if lead_para:
        cards.append(
            {
                "type": "quote",
                "text": " ".join(lead_para["lines"])[:110],
                "footer": "为什么值得聊",
            }
        )

    figs = figs or []
    fig_queue = list(figs)
    if fig_queue:
        f = fig_queue.pop(0)
        cards.append(
            {"type": "figure", "path": f["path"], "caption": f["caption"], "label": "论文长这样", "footer": post["date"]}
        )

    idx = 0
    closing: list[str] = []
    extras_card: dict | None = None

    def is_bullet(x: str) -> bool:
        return x.startswith(("·", "-", "•"))

    body_sections = []
    for sec in post["sections"]:
        if not sec.get("raw"):
            continue
        # 「顺带」段里，要点之后的非要点行其实是结尾判断
        if "顺带" in sec["title"]:
            items: list[dict] = []
            tail_lines: list[str] = []
            after_bullet = False
            for x in sec["lines"]:
                if is_bullet(x):
                    items.append({"t": x.lstrip("·-• ").strip(), "s": ""})
                    after_bullet = True
                    continue
                if after_bullet and items:
                    items[-1]["s"] = x
                    after_bullet = False
                    continue
                tail_lines.append(x)
            if tail_lines:
                closing = tail_lines
            if items:
                extras_card = {
                    "type": "list",
                    "emoji": sec["emoji"],
                    "title": sec["title"],
                    "items": items,
                    "footer": post["date"],
                }
            continue
        body_sections.append(sec)

    total = len(body_sections)
    for sec in body_sections:
        pages = _chunk(sec["lines"], max_chars)
        for pi, page in enumerate(pages):
            idx += 1
            title = sec["title"] if pi == 0 else f"{sec['title']}（续）"
            cards.append(
                {
                    "type": "content",
                    "num": f"{idx:02d}",
                    "emoji": sec["emoji"],
                    "title": title,
                    "lines": page,
                    "footer": post["date"],
                }
            )
            if pi == len(pages) - 1 and "结果" in sec["title"] and fig_queue:
                # 结果图优先选接近 4:3 的，避免超宽图缩成一条
                fig_queue.sort(key=lambda x: abs((x["w"] / max(x["h"], 1)) - 1.4))
                f = fig_queue.pop(0)
                cards.append(
                    {"type": "figure", "path": f["path"], "caption": f["caption"],
                     "label": "论文原图", "footer": post["date"]}
                )

    if extras_card:
        cards.append(extras_card)

    if not closing:
        lead_like = [s for s in post["sections"] if s.get("lead")]
        if len(lead_like) > 1:
            closing = lead_like[-1]["lines"]
    if closing:
        cards.append(
            {
                "type": "closing",
                "title": "我的判断",
                "text": " ".join(closing)[:150],
                "footer": post["tags"][:60] if post["tags"] else "评论区聊聊",
            }
        )
    for i, c in enumerate(cards, 1):
        c["pos"] = i
    return cards


# ---------------------------------------------------------------- 样式


THEMES = {
    "editorial": {
        "bg": "linear-gradient(160deg,#fdfcf9 0%,#f4f1ea 100%)",
        "fg": "#1a1a1a",
        "muted": "#8a8578",
        "accent": "#c8452f",
        "line": "rgba(26,26,26,.12)",
        "cover_bg": "linear-gradient(160deg,#141414 0%,#1f1a16 60%,#2b1f18 100%)",
        "cover_fg": "#fdfcf9",
        "cover_accent": "#e8b04b",
        "font": "'Source Han Serif SC','Songti SC','SimSun',serif",
        "font_sans": "-apple-system,'PingFang SC','Microsoft YaHei',sans-serif",
    },
    "dark": {
        "bg": "linear-gradient(160deg,#0f1720 0%,#16222e 100%)",
        "fg": "#e9eef4",
        "muted": "#7d8b99",
        "accent": "#4ec9b0",
        "line": "rgba(233,238,244,.14)",
        "cover_bg": "linear-gradient(160deg,#101c2b 0%,#1c3category 50%,#27506e 100%)",
        "cover_fg": "#eaf2fa",
        "cover_accent": "#57d3a8",
        "font": "'PingFang SC','Microsoft YaHei',sans-serif",
        "font_sans": "'PingFang SC','Microsoft YaHei',sans-serif",
    },
    "swiss": {
        "bg": "#ffffff",
        "fg": "#111111",
        "muted": "#9b9b9b",
        "accent": "#e2231a",
        "line": "rgba(17,17,17,.14)",
        "cover_bg": "#111111",
        "cover_fg": "#ffffff",
        "cover_accent": "#ffd400",
        "font": "'Helvetica Neue',Arial,'PingFang SC',sans-serif",
        "font_sans": "'Helvetica Neue',Arial,'PingFang SC',sans-serif",
    },
}
THEMES["dark"]["cover_bg"] = "linear-gradient(160deg,#101c2b 0%,#1b3550 50%,#27506e 100%)"


def _fs_title(text: str) -> int:
    n = len(text)
    if n <= 8:
        return 104
    if n <= 12:
        return 88
    if n <= 16:
        return 72
    if n <= 22:
        return 60
    return 50


def _fs_body(total_chars: int, area_h: int = 820) -> int:
    """按可用面积反推字号：字多则小，字少则大，夹在 28~58 之间。"""
    import math

    if total_chars <= 0:
        return 48
    fs = math.sqrt((area_h * 940) / (total_chars * 1.72))
    return int(max(26, min(58, fs)))


def card_html(card: dict, theme: str, total: int) -> str:
    t = THEMES.get(theme, THEMES["editorial"])
    base = (
        f"width:{CARD_W}px;height:{CARD_H}px;position:relative;overflow:hidden;"
        f"font-family:{t['font_sans']};color:{t['fg']};background:{t['bg']}"
    )

    def footer(text: str, color: str) -> str:
        return (
            f'<div style="position:absolute;left:88px;right:88px;bottom:70px;'
            f"display:flex;justify-content:space-between;align-items:center;"
            f'font-size:26px;color:{color};letter-spacing:.04em">'
            f'<span>信息雷达 · 每日 arXiv</span><span>{text}</span></div>'
        )

    if card["type"] == "cover":
        sub = card["sub"] or []
        sub_html = "".join(
            f'<div style="font-size:40px;line-height:1.6;color:{t["cover_fg"]};opacity:.86">{s}</div>'
            for s in sub[:2]
        )
        return (
            f'<div style="{base};background:{t["cover_bg"]};color:{t["cover_fg"]}">'
            f'<div style="position:absolute;left:88px;top:96px;font-size:28px;letter-spacing:.22em;'
            f'color:{t["cover_accent"]}">{card["kicker"]}</div>'
            f'<div style="position:absolute;left:88px;right:88px;top:330px;font-family:{t["font"]};'
            f'font-size:{_fs_title(card["title"])}px;font-weight:800;line-height:1.26;'
            f'letter-spacing:-.01em">{card["title"]}</div>'
            f'<div style="position:absolute;left:88px;right:88px;bottom:300px">{sub_html}</div>'
            f'<div style="position:absolute;left:88px;bottom:150px;width:120px;height:8px;'
            f'background:{t["cover_accent"]}"></div>'
            f"{footer(card['footer'], t['cover_accent'])}"
            f"</div>"
        )

    if card["type"] == "quote":
        txt = card["text"]
        return (
            f'<div style="{base}">'
            f'<div style="position:absolute;left:88px;top:200px;font-size:120px;'
            f'color:{t["accent"]};font-family:{t["font"]};line-height:1">“</div>'
            f'<div style="position:absolute;left:88px;right:120px;top:360px;font-family:{t["font"]};'
            f'font-size:{_fs_title(txt) - 26}px;line-height:1.62;font-weight:600">{txt}</div>'
            f"{footer(card['footer'], t['muted'])}"
            f"</div>"
        )

    if card["type"] == "closing":
        txt = card["text"]
        return (
            f'<div style="{base};background:{t["cover_bg"]};color:{t["cover_fg"]}">'
            f'<div style="position:absolute;left:88px;top:170px;font-size:30px;letter-spacing:.14em;'
            f'color:{t["cover_accent"]}">{card["title"]}</div>'
            f'<div style="position:absolute;left:88px;right:110px;top:270px;font-family:{t["font"]};'
            f'font-size:{_fs_title(txt) - 30}px;line-height:1.6;font-weight:600">{txt}</div>'
            f'<div style="position:absolute;left:88px;right:88px;bottom:170px;font-size:28px;'
            f'color:{t["cover_accent"]}">{card["footer"]}</div>'
            f"{footer('END', t['cover_accent'])}"
            f"</div>"
        )

    if card["type"] == "figure":
        from .paper_figs import data_uri

        uri = data_uri(card["path"])
        if not uri:
            return f'<div style="{base}"></div>'
        cap = card.get("caption") or ""
        return (
            f'<div style="{base}">'
            f'<div style="position:absolute;left:88px;top:96px;font-size:30px;color:{t["muted"]};'
            f'letter-spacing:.16em">{card.get("pos", 0):02d} / {total:02d}</div>'
            f'<div style="position:absolute;left:88px;right:88px;top:186px;font-size:34px;'
            f'color:{t["accent"]};letter-spacing:.06em">{card.get("label", "")}</div>'
            f'<div style="position:absolute;left:64px;right:64px;top:268px;height:760px;'
            f'display:flex;align-items:center;justify-content:center;'
            f'background:#fff;border:1px solid {t["line"]};border-radius:10px;overflow:hidden">'
            f'<img src="{uri}" style="max-width:100%;max-height:100%;object-fit:contain"></div>'
            f'<div style="position:absolute;left:88px;right:96px;top:1066px;font-size:25px;'
            f'line-height:1.62;color:{t["muted"]}">{cap}</div>'
            f"{footer(card['footer'], t['muted'])}"
            f"</div>"
        )

    if card["type"] == "list":
        rows = ""
        for it in card["items"]:
            title, _, link = it["t"].partition("｜")
            title = title.strip()
            link = link.strip()
            rows += (
                '<div style="margin-bottom:56px">'
                f'<div style="font-size:38px;font-weight:700;line-height:1.42">{title}</div>'
                + (
                    f'<div style="font-size:25px;line-height:1.5;color:{t["accent"]};'
                    f'margin-top:8px;letter-spacing:.02em;word-break:keep-all">{link}</div>'
                    if link
                    else ""
                )
                + (
                    f'<div style="font-size:25px;line-height:1.6;color:{t["muted"]};'
                    f'margin-top:10px">{it["s"]}</div>'
                    if it["s"]
                    else ""
                )
                + "</div>"
            )
        return (
            f'<div style="{base}">'
            f'<div style="position:absolute;left:88px;top:96px;font-size:30px;color:{t["muted"]};'
            f'letter-spacing:.16em">{card.get("pos", 0):02d} / {total:02d}</div>'
            f'<div style="position:absolute;left:88px;right:88px;top:190px;font-family:{t["font"]};'
            f'font-size:60px;font-weight:800;line-height:1.3">'
            f'<span style="color:{t["accent"]}">{card["emoji"]}</span> {card["title"]}</div>'
            f'<div style="position:absolute;left:88px;top:300px;width:110px;height:6px;'
            f'background:{t["accent"]}"></div>'
            f'<div style="position:absolute;left:88px;right:96px;top:430px">{rows}</div>'
            f"{footer(card['footer'], t['muted'])}"
            f"</div>"
        )

    # content
    lines = card["lines"]
    total_chars = sum(len(x) for x in lines)
    fs = _fs_body(total_chars)
    bullets = all(x.startswith(("·", "-", "•")) for x in lines) if lines else False
    parts = []
    for x in lines:
        if x.startswith(("📎", "📌")):
            parts.append(
                f'<div style="margin-top:34px;font-size:26px;line-height:1.6;'
                f'color:{t["muted"]};letter-spacing:.02em">{x}</div>'
            )
        else:
            indent = x.startswith(("·", "-", "•"))
            parts.append(
                f'<div style="margin-bottom:{26 if indent else 20}px;'
                f'{"padding-left:34px;text-indent:-34px;" if indent else ""}">{x}</div>'
            )
    body_html = "".join(parts)
    return (
        f'<div style="{base}">'
        f'<div style="position:absolute;left:88px;top:96px;font-size:30px;color:{t["muted"]};'
        f'letter-spacing:.16em">{card.get("pos", 0):02d} / {total:02d}</div>'
        f'<div style="position:absolute;left:88px;right:88px;top:190px;font-family:{t["font"]};'
        f'font-size:64px;font-weight:800;line-height:1.3">'
        f'<span style="color:{t["accent"]}">{card["emoji"]}</span> {card["title"]}</div>'
        f'<div style="position:absolute;left:88px;top:310px;width:110px;height:6px;'
        f'background:{t["accent"]}"></div>'
        f'<div id="content" data-fs="{fs}" style="position:absolute;left:88px;right:96px;'
        f'top:350px;height:880px;overflow:hidden;display:flex;align-items:center;'
        f'font-size:{fs}px;line-height:1.75;'
        f'text-wrap:pretty;word-break:normal;color:{t["fg"]}"><div id="inner" style="width:100%">{body_html}</div></div>'
        f"{footer(card['footer'], t['muted'])}"
        f"</div>"
    )


def render_pages(post: dict, theme: str = "editorial", max_chars: int = 150) -> list[str]:
    cards = build_cards(post, max_chars)
    n = len(cards)
    return [card_html(c, theme, n) for c in cards]
