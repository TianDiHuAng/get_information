"""分享图：一条新闻被转发出去时，得有个像样的预览。

为什么值得做：邮件和 RSS 分享到微信/Telegram/X 时，没有 `og:image` 就是一条光秃秃的链接。
这里用 Pillow 直接画一张 1200×630 的卡片（各平台的大图预览标准尺寸），
内容就是当天的头条 —— 不调模型、不联网，一次几十毫秒。

字体用系统自带的微软雅黑（Windows）并做了几级回退；找不到中文字体时**不画图**，
而不是画一堆方块 —— 宁可没有预览图，也不要一张乱码卡片。
"""

from __future__ import annotations

import html
import textwrap
from pathlib import Path
from typing import Any

from . import edition

SITE = Path(__file__).parent.parent / "site"
WIDTH, HEIGHT = 1200, 630

BG = (11, 15, 20)
CARD = (17, 24, 32)
TEXT = (230, 237, 243)
MUTED = (139, 152, 168)
ACCENT = (56, 189, 248)
GREEN = (34, 197, 94)

# 依次尝试；都不行就返回 None（调用方跳过出图）
FONT_CANDIDATES = (
    ("C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/msyh.ttc"),
    ("/System/Library/Fonts/PingFang.ttc",),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
     "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
)


def _font(size: int, bold: bool = False):
    """按平台找一款中文字体。找不到返回 None。"""
    from PIL import ImageFont

    for group in FONT_CANDIDATES:
        path = group[0] if bold else (group[-1] if group else None)
        if not path:
            continue
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return None


def _wrap(text: str, font, max_width: int, max_lines: int) -> list[str]:
    """按像素宽度折行。中文没有空格，用逐字测量而不是 textwrap。"""
    text = " ".join(str(text or "").split())
    if not text:
        return []
    lines: list[str] = []
    cur = ""
    for ch in text:
        if font.getlength(cur + ch) <= max_width:
            cur += ch
            continue
        lines.append(cur)
        cur = ch
        if len(lines) >= max_lines:
            break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    if len(lines) == max_lines:
        # 末行超出就截断加省略号
        last = lines[-1]
        while last and font.getlength(last + "…") > max_width:
            last = last[:-1]
        lines[-1] = last + "…" if last != text else last
    return lines


def og_tags(title: str, description: str = "", path: str = "/") -> str:
    """给页面用的 Open Graph / Twitter 卡片标签。

    `og:image` 指向同一张 `og.png`：多页面共用一张图，比自己各画一张省事，
    而且转发时永远有图。
    """
    try:
        from .export import config as export_config

        base = str(export_config().get("base_url") or "").rstrip("/")
    except Exception:
        base = ""
    image = f"{base}/og.png" if base else "/og.png"
    url = f"{base}{path}" if base else path
    desc = " ".join(str(description or "").split())[:180]
    return "\n".join([
        '<meta property="og:type" content="website">',
        f'<meta property="og:title" content="{html.escape(title, quote=True)}">',
        f'<meta property="og:description" content="{html.escape(desc, quote=True)}">',
        f'<meta property="og:image" content="{html.escape(image, quote=True)}">',
        f'<meta property="og:url" content="{html.escape(url, quote=True)}">',
        '<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:title" content="{html.escape(title, quote=True)}">',
        f'<meta name="twitter:image" content="{html.escape(image, quote=True)}">',
    ])


def build(payload: dict[str, Any], site_root: Path | None = None) -> dict[str, Any]:
    """画一张当天头条的分享图，写到 `site/og.png`。失败不抛异常。"""
    try:
        from PIL import Image, ImageDraw
    except Exception as e:
        return {"skipped": f"no-pillow: {type(e).__name__}"}

    title_font = _font(52, bold=True)
    meta_font = _font(26)
    small_font = _font(24)
    brand_font = _font(30, bold=True)
    if not (title_font and meta_font and small_font and brand_font):
        return {"skipped": "no-cjk-font"}

    plan = edition.arrange(payload)
    lead = plan.get("lead") or {}
    stats = payload.get("stats") or {}
    day = (stats.get("generated_at") or "")[:10] or ""
    total = len(payload.get("items") or [])
    sources = stats.get("sources_ok") or 0

    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)

    # 左侧强调条 + 顶部品牌行
    draw.rectangle([0, 0, 10, HEIGHT], fill=ACCENT)
    draw.text((64, 56), "Z-Bit", font=brand_font, fill=TEXT)
    draw.text((64, 100), f"{day} · {total} 条 · {sources} 个源", font=small_font, fill=MUTED)

    # 头条卡片
    draw.rounded_rectangle([64, 150, WIDTH - 64, HEIGHT - 64], radius=18, fill=CARD)
    lines = _wrap(lead.get("title") or "今天还没有选出头条", title_font,
                  WIDTH - 160, max_lines=3)
    y = 196
    for line in lines:
        draw.text((100, y), line, font=title_font, fill=TEXT)
        y += 68

    # 来源与摘要。摘要太短（"548 条评论"这种）就不占位置，把空间留给看点
    source = lead.get("source") or ""
    crowd = ""
    size = int((lead.get("extra") or {}).get("event_size") or 1)
    if size > 1:
        crowd = f" · {size} 篇报道"
    if source:
        draw.text((100, y + 4), f"{source}{crowd}", font=small_font, fill=ACCENT)
        y += 46

    summary = " ".join(str(lead.get("summary") or "").split())
    if len(summary) >= 24:
        for line in _wrap(summary, meta_font, WIDTH - 200, max_lines=2):
            draw.text((100, y + 8), line, font=meta_font, fill=MUTED)
            y += 36

    # 看点放在卡片里：既填满空间，也让一张图说得清"今天还有什么"
    bullets = plan["highlights"][:3]
    if bullets:
        sep = max(y + 34, HEIGHT - 96 - 44 * len(bullets) - 18)
        draw.line([100, sep, WIDTH - 100, sep], fill=(31, 42, 55), width=1)
        by = sep + 18
        for it in bullets:
            text = _wrap(it.get("title") or "", small_font, WIDTH - 260, max_lines=1)
            if not text:
                continue
            draw.ellipse([100, by + 11, 108, by + 19], fill=GREEN)
            draw.text((124, by), text[0], font=small_font, fill=MUTED)
            by += 44

    footer = "每天 09:00 更新 · RSS / API / llms.txt"
    footer_x = WIDTH - 64 - int(small_font.getlength(footer))
    draw.text((footer_x, HEIGHT - 50), footer, font=small_font, fill=(75, 85, 99))

    target = (site_root or SITE) / "og.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    img.save(target, "PNG", optimize=True)
    return {"file": str(target), "bytes": target.stat().st_size,
            "lead": (lead.get("title") or "")[:60]}
