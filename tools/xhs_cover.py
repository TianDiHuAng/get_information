"""手写笔记风封面（排版型，不依赖生图模型）。

设计原则：
- 只留一个强调色（朱红），其余用墨色与灰蓝，避免花
- 标题独占视觉重心，副标题降一级，图作为"佐证"不抢戏
- 装饰只做三件：荧光笔下划线、一条短红线、一枚印章；其余留白

用法：
  python tools/xhs_cover.py
  python tools/xhs_cover.py --text "【扩散模型】学ESM-2激活" --sub "一句话结论"
  python tools/xhs_cover.py --fig data/xhs/figs/xxx/pipeline.png --no-fig
"""

from __future__ import annotations

import argparse
import math
import random
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

W, H = 1080, 1440

PAPER_TOP = (250, 247, 240)
PAPER_BOTTOM = (241, 236, 226)
INK = (32, 38, 40)
INK_SOFT = (92, 104, 112)
GREY = (152, 148, 140)
ACCENT = (196, 58, 44)
HILITE = (246, 210, 92)
FONT_TITLE = "C:/Windows/Fonts/FZSTK.TTF"
FONT_KAI = "C:/Windows/Fonts/STKAITI.TTF"
FONT_SANS = "C:/Windows/Fonts/msyh.ttc"

MARGIN = 92


# ---------------------------------------------------------------- 基础


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    for p in (path, FONT_KAI, FONT_SANS):
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-+]*|\s+|.")


def wrap_tokens(text: str, font, max_w: int) -> list[str]:
    d = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    lines, cur = [], ""
    for tok in _TOKEN.findall(text):
        if not tok.strip():
            if cur:
                lines.append(cur)
                cur = ""
            continue
        if d.textlength(cur + tok, font=font) > max_w and cur:
            lines.append(cur)
            cur = tok
        else:
            cur += tok
    if cur:
        lines.append(cur)
    return lines or [text]


def paper_base() -> Image.Image:
    """暖白纸：上亮下暗的柔和渐变 + 细颗粒 + 轻微暗角。"""
    grad = Image.new("RGB", (1, H))
    for y in range(H):
        t = y / (H - 1)
        grad.putpixel((0, y), tuple(
            int(PAPER_TOP[i] + (PAPER_BOTTOM[i] - PAPER_TOP[i]) * (t ** 0.85)) for i in range(3)
        ))
    img = grad.resize((W, H))

    rnd = random.Random(21)
    noise = Image.new("L", (W // 2, H // 2))
    npx = noise.load()
    for y in range(H // 2):
        for x in range(W // 2):
            npx[x, y] = 128 + rnd.randint(-7, 7)
    noise = noise.resize((W, H), Image.BILINEAR).filter(ImageFilter.GaussianBlur(0.4))
    img = Image.composite(Image.new("RGB", (W, H), (255, 255, 255)), img,
                          noise.point(lambda v: max(0, min(255, int((v - 128) * 0.5 + 128)))))

    vig = Image.new("L", (W, H), 0)
    ImageDraw.Draw(vig).ellipse([-W * 0.30, -H * 0.20, W * 1.30, H * 1.20], fill=34)
    vig = vig.filter(ImageFilter.GaussianBlur(190))
    return Image.composite(Image.new("RGB", (W, H), (228, 221, 208)), img, vig)


# ---------------------------------------------------------------- 元素


def draw_title(img: Image.Image, text: str, top: int, size: int,
               hl: list[tuple[int, int]], rnd: random.Random) -> int:
    font = _font(FONT_TITLE, size)
    lines = wrap_tokens(text, font, W - MARGIN * 2 - 40)

    # 荧光笔：先铺底
    marker = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    md = ImageDraw.Draw(marker)
    meas = ImageDraw.Draw(marker)
    idx = 0
    y = top
    for line in lines:
        x = MARGIN
        for ch in line:
            tw = meas.textlength(ch, font=font)
            if any(a <= idx < b for a, b in hl) and ch.strip():
                md.rounded_rectangle(
                    [x - 5, y + size * 0.30, x + tw + 5, y + size * 0.98],
                    radius=7, fill=HILITE + (120,),
                )
            idx += 1
            x += tw
        y += int(size * 1.24)
    img.alpha_composite(marker)

    # 手写字
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    y = top
    for line in lines:
        x = MARGIN
        for ch in line:
            tw = d.textlength(ch, font=font)
            if ch.strip():
                tmp = Image.new("RGBA", (size * 2, size * 2), (0, 0, 0, 0))
                ImageDraw.Draw(tmp).text((size * 0.5, size * 0.5), ch, font=font, fill=INK + (255,))
                tmp = tmp.rotate(rnd.uniform(-0.9, 0.9), resample=Image.BICUBIC)
                layer.alpha_composite(tmp, (int(x) - int(size * 0.5), int(y) - int(size * 0.5)))
            x += tw
        y += int(size * 1.24)
    img.alpha_composite(layer)
    return y


def short_rule(img: Image.Image, x: int, y: int, w: int, color, h: int = 6):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle([x, y, x + w, y + h], radius=h // 2, fill=color)
    img.alpha_composite(layer)


def draw_sub(img: Image.Image, text: str, top: int, size: int = 42) -> int:
    font = _font(FONT_KAI, size)
    lines = wrap_tokens(text, font, W - MARGIN * 2 - 60)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    y = top
    for line in lines:
        d.text((MARGIN, y), line, font=font, fill=INK_SOFT + (255,))
        y += int(size * 1.52)
    img.alpha_composite(layer)
    return y


def sketchify(src: Path, max_w: int, max_h: int) -> Image.Image:
    im = Image.open(src).convert("RGB")
    im.thumbnail((max_w, max_h), Image.LANCZOS)
    gray = im.convert("L").filter(ImageFilter.FIND_EDGES)
    gray = Image.eval(gray, lambda v: 255 - min(255, int(v * 2.6))).filter(ImageFilter.GaussianBlur(0.5))
    out = Image.new("RGB", im.size, (253, 251, 246))
    ep, sp, op = gray.load(), im.load(), out.load()
    for y in range(im.height):
        for x in range(im.width):
            e = ep[x, y] / 255.0
            if e < 0.9:
                s = min(1.0, (0.9 - e) / 0.72)
                b = sp[x, y]
                op[x, y] = (
                    int(253 * (1 - s) + (b[0] * 0.2 + 52) * s),
                    int(251 * (1 - s) + (b[1] * 0.2 + 64) * s),
                    int(246 * (1 - s) + (b[2] * 0.2 + 84) * s),
                )
    return out


def paste_figure(img: Image.Image, fig: Path, top: int, max_h: int) -> int:
    art = sketchify(fig, W - MARGIN * 2 - 96, max_h)
    pad = 24
    card = Image.new("RGBA", (art.width + pad * 2, art.height + pad * 2), (0, 0, 0, 0))
    cd = ImageDraw.Draw(card)
    cd.rounded_rectangle([0, 0, card.width - 1, card.height - 1], 4, fill=(253, 252, 248, 255))
    cd.rounded_rectangle([0, 0, card.width - 1, card.height - 1], 4, outline=(224, 218, 206, 255), width=2)
    card.alpha_composite(art.convert("RGBA"), (pad, pad))

    card = card.rotate(-1.1, resample=Image.BICUBIC, expand=True)
    sh = Image.new("RGBA", card.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle(
        [10, 14, card.width - 8, card.height - 4], 6, fill=(96, 86, 72, 58))
    sh = sh.filter(ImageFilter.GaussianBlur(11))
    cx = (W - card.width) // 2
    img.alpha_composite(sh, (cx, top + 8))
    img.alpha_composite(card, (cx, top))
    return cx, top + card.height, card.width


def draw_stamp(img: Image.Image, x: int, y: int):
    stamp = Image.new("RGBA", (256, 108), (0, 0, 0, 0))
    d = ImageDraw.Draw(stamp)
    d.rounded_rectangle([2, 2, 253, 105], 4, outline=ACCENT + (205,), width=4)
    f1 = _font(FONT_TITLE, 34)
    f2 = _font(FONT_KAI, 26)
    d.text((22, 16), "arXiv", font=f1, fill=ACCENT + (225,))
    d.text((22, 62), "新论文速读", font=f2, fill=ACCENT + (225,))
    stamp = stamp.rotate(-6, resample=Image.BICUBIC, expand=True)
    img.alpha_composite(stamp, (x, y))


def hairline_frame(img: Image.Image):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rectangle([40, 40, W - 40, H - 40], outline=(214, 206, 192, 190), width=2)
    img.alpha_composite(layer)


# ---------------------------------------------------------------- 主函数


def make(out: Path, title: str, sub: str, kicker: str, footer_left: str, footer_right: str,
         fig: Path | None = None, fig_caption: str = "", arxiv_id: str = "",
         with_frame: bool = True, with_hand: bool = False) -> Path:
    rnd = random.Random(17)
    img = paper_base().convert("RGBA")

    hl: list[tuple[int, int]] = []
    clean, pos, i = [], 0, 0
    while i < len(title):
        if title[i] in "【[":
            j = title.find("】" if title[i] == "【" else "]", i + 1)
            if j < 0:
                clean.append(title[i]); pos += 1; i += 1; continue
            inner = title[i + 1:j]
            hl.append((pos, pos + len(inner)))
            clean.append(inner); pos += len(inner); i = j + 1
        else:
            clean.append(title[i]); pos += 1; i += 1
    title = "".join(clean)
    if not hl and title:
        hl = [(0, min(4, len(title)))]

    # 顶部
    d0 = ImageDraw.Draw(img)
    d0.text((MARGIN, 104), kicker, font=_font(FONT_KAI, 26), fill=(158, 118, 66, 255))
    draw_stamp(img, W - 256 - 78, 88)

    # 标题（无图时整体下移并放大，避免下半页空）
    has_fig = bool(fig and fig.exists())
    t_size = 112 if has_fig else 132
    t_top = 236 if has_fig else 372
    y = draw_title(img, title, t_top, t_size, hl, rnd)
    short_rule(img, MARGIN, y + 30, 168, ACCENT + (230,), 7)
    y += 84

    # 副标题
    if sub:
        y = draw_sub(img, sub, y + (0 if has_fig else 26), 46 if not has_fig else 42) + 16

    # 图
    if has_fig:
        fig_top = max(y + 44, 742)
        cx, cy, cw = paste_figure(img, fig, fig_top, H - fig_top - 300)
        if fig_caption or arxiv_id:
            cd = ImageDraw.Draw(img)
            cf = _font(FONT_SANS, 20)
            cap = (fig_caption[:56] + "…") if len(fig_caption) > 56 else fig_caption
            if cap:
                cd.text((cx + 4, cy + 26), cap, font=cf, fill=GREY + (255,))
            if arxiv_id:
                tag = f"arXiv:{arxiv_id}"
                tw = cd.textlength(tag, font=cf)
                cd.text((cx + cw - tw - 4, cy + 26), tag, font=cf, fill=(158, 118, 66, 255))

    if with_hand:
        try:
            from hand_art import paste_hand
            paste_hand(img, (W - 430, H - 640), angle=-18, scale=0.74)
        except Exception as e:
            print("hand skipped:", e)

    if with_frame:
        hairline_frame(img)

    # 页脚
    d = ImageDraw.Draw(img)
    f = _font(FONT_SANS, 22)
    d.text((MARGIN, H - 108), footer_left, font=f, fill=GREY + (255,))
    tw = d.textlength(footer_right, font=f)
    d.text((W - MARGIN - tw, H - 108), footer_right, font=f, fill=GREY + (255,))
    short_rule(img, MARGIN, H - 138, W - MARGIN * 2, (216, 208, 194, 200), 2)

    out.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out, quality=95)
    return out


def latest_context() -> dict:
    mds = sorted((ROOT / "data" / "xhs").glob("*-arxiv.md"))
    if not mds:
        return {}
    from collector.paper_figs import fetch_figures
    from collector.xhs_cards import parse_post

    text = mds[-1].read_text(encoding="utf-8")
    pid = ""
    m = re.search(r"arxiv\.org/abs/([0-9.]+)", text)
    if m:
        pid = m.group(1)
    figs = fetch_figures(pid) if pid else []
    post = parse_post(mds[-1])
    cover = post.get("cover") or []
    return {
        "title": cover[0] if cover else "",
        "sub": "｜".join(cover[1:3]),
        "fig": Path(figs[0]["path"]) if figs else None,
        "fig_caption": figs[0].get("caption", "") if figs else "",
        "arxiv_id": pid,
        "date": post.get("date", ""),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fig", default=None)
    ap.add_argument("--no-fig", action="store_true")
    ap.add_argument("--text", default=None)
    ap.add_argument("--sub", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--hand", action="store_true")
    ap.add_argument("--no-frame", action="store_true")
    a = ap.parse_args()

    ctx = latest_context()
    title = a.text or ctx.get("title") or "今日论文"
    sub = a.sub if a.sub is not None else (ctx.get("sub") or "")
    sub = sub.replace("｜", "\n")
    fig = None if a.no_fig else (Path(a.fig) if a.fig else ctx.get("fig"))
    out = Path(a.out) if a.out else ROOT / "data" / "xhs" / "cover-hand.png"

    p = make(out, title, sub, "AI × DRUG DISCOVERY", "信息雷达 · arXiv 精读",
             ctx.get("date", ""), fig=fig, fig_caption=ctx.get("fig_caption", ""),
             arxiv_id=ctx.get("arxiv_id", ""), with_frame=not a.no_frame, with_hand=a.hand)
    print(p)


if __name__ == "__main__":
    main()
