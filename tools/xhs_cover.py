"""手绘风封面：把论文图处理成"纸上手绘"的样子，配手写体标题。

不用生图模型，全部代码合成：
  纸纹底 → 论文图线稿化（边缘检测 + 蓝灰铅笔色）→ 略微倾斜贴上、投影
  → 手写体标题（逐字微抖）、手绘下划线、涂鸦箭头、页脚

用法：
  python tools/xhs_cover.py                # 默认第一张论文图
  python tools/xhs_cover.py --text "扩散模型学ESM-2激活" --sub "单个meta-neuron打赢SAE"
"""

from __future__ import annotations

import argparse
import json
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

PAPER = (242, 239, 232)
INK = (44, 52, 48)
PENCIL = (58, 72, 96)
RED = (198, 62, 46)
FONT_HAND = "C:/Windows/Fonts/FZSTK.TTF"      # 方正舒体：最像手写
FONT_HAND2 = "C:/Windows/Fonts/STXINGKA.TTF"  # 华文行楷：备选
FONT_SANS = "C:/Windows/Fonts/msyh.ttc"


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    for p in (path, FONT_HAND2):
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()



_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-+]*|\\s+|.")


def wrap_tokens(text: str, font, max_w: int) -> list[str]:
    """按语义 token 换行：英文/数字整体不拆，中文逐字可断。"""
    d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    tokens = _TOKEN.findall(text)
    lines, cur = [], ""
    for tok in tokens:
        if tok.strip() == "":
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
    """暖白纸底 + 细颗粒 + 四周压暗。"""
    rnd = random.Random(7)
    img = Image.new("RGB", (W, H), PAPER)
    px = img.load()
    for y in range(0, H, 2):
        for x in range(0, W, 2):
            n = rnd.randint(-6, 6)
            r, g, b = PAPER
            c = (max(0, min(255, r + n)), max(0, min(255, g + n)), max(0, min(255, b + n)))
            px[x, y] = c
            if x + 1 < W:
                px[x + 1, y] = c
            if y + 1 < H:
                px[x, y + 1] = c
                if x + 1 < W:
                    px[x + 1, y + 1] = c
    # 暗角
    vig = Image.new("L", (W, H), 0)
    dv = ImageDraw.Draw(vig)
    dv.ellipse([-W * 0.35, -H * 0.25, W * 1.35, H * 1.25], fill=42)
    vig = vig.filter(ImageFilter.GaussianBlur(160))
    img = Image.composite(Image.new("RGB", (W, H), (232, 226, 214)), img, vig)
    return img


def sketchify(src: Path, max_w: int, max_h: int) -> Image.Image:
    """论文图 → 蓝灰铅笔线稿（保留一点淡色）。"""
    im = Image.open(src).convert("RGB")
    im.thumbnail((max_w, max_h), Image.LANCZOS)

    gray = im.convert("L")
    edges = gray.filter(ImageFilter.FIND_EDGES)
    edges = Image.eval(edges, lambda v: 255 - min(255, int(v * 2.4)))
    edges = edges.filter(ImageFilter.GaussianBlur(0.6))

    # 线稿 = 边缘留下的深色，其余保持浅色
    line = Image.new("RGB", im.size, (252, 250, 245))
    lp = line.load()
    ep = edges.load()
    sp = im.load()
    w, h = im.size
    for y in range(h):
        for x in range(w):
            e = ep[x, y] / 255.0
            if e < 0.88:
                strength = min(1.0, (0.88 - e) / 0.74)
                base = sp[x, y]
                # 深色部分向铅笔色靠拢，色相保留一点
                r = int(base[0] * 0.18 + PENCIL[0] * 0.82)
                g = int(base[1] * 0.18 + PENCIL[1] * 0.82)
                b = int(base[2] * 0.18 + PENCIL[2] * 0.82)
                k = 1 - strength
                lp[x, y] = (
                    int(252 * k + r * strength),
                    int(250 * k + g * strength),
                    int(245 * k + b * strength),
                )
    return line


def hand_rect(draw: ImageDraw.ImageDraw, box, color, width=3, jitter=1.6, rnd=None):
    """手绘感的矩形框：分段微抖。"""
    rnd = rnd or random.Random()
    x0, y0, x1, y1 = box
    pts = []
    step = 18
    for x in range(int(x0), int(x1), step):
        pts.append((x + rnd.uniform(-jitter, jitter), y0 + rnd.uniform(-jitter, jitter)))
    for y in range(int(y0), int(y1), step):
        pts.append((x1 + rnd.uniform(-jitter, jitter), y + rnd.uniform(-jitter, jitter)))
    for x in range(int(x1), int(x0), -step):
        pts.append((x + rnd.uniform(-jitter, jitter), y1 + rnd.uniform(-jitter, jitter)))
    for y in range(int(y1), int(y0), -step):
        pts.append((x0 + rnd.uniform(-jitter, jitter), y + rnd.uniform(-jitter, jitter)))
    draw.line(pts + [pts[0]], fill=color, width=width, joint="curve")


def underlined_text(base: Image.Image, text: str, font, xy, fill, rnd, jitter=0.9, spacing=4):
    """逐字绘制，模拟手写的轻微不齐。"""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x, y = xy
    for ch in text:
        if ch == "\n":
            x = xy[0]
            y += int(font.size * 1.32)
            continue
        ch_layer = Image.new("RGBA", (font.size * 2, font.size * 2), (0, 0, 0, 0))
        cd = ImageDraw.Draw(ch_layer)
        cd.text((font.size // 2, font.size // 2), ch, font=font, fill=fill)
        ang = rnd.uniform(-jitter, jitter)
        ch_layer = ch_layer.rotate(ang, resample=Image.BICUBIC, expand=False)
        bbox = ch_layer.getbbox()
        if bbox:
            layer.alpha_composite(ch_layer, (int(x + rnd.uniform(-1, 1)) - font.size // 2 + 0,
                                             int(y + rnd.uniform(-1, 1)) - font.size // 2 + 0))
        x += (cd.textlength(ch, font=font) if hasattr(cd, "textlength") else font.size) + spacing
    base.alpha_composite(layer) if base.mode == "RGBA" else base.paste(
        Image.alpha_composite(base.convert("RGBA"), layer).convert("RGB"), (0, 0)
    )


def draw_headline(img: Image.Image, text: str, top: int, size: int, color, rnd) -> int:
    """手写体主标题（自动换行），返回占用高度。"""
    font = _font(FONT_HAND, size)
    lines = wrap_tokens(text, font, W - 176)

    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    y = top
    for line in lines:
        x = 88
        for ch in line:
            tw = d.textlength(ch, font=font)
            tmp = Image.new("RGBA", (size * 2, size * 2), (0, 0, 0, 0))
            td = ImageDraw.Draw(tmp)
            td.text((size // 2, size // 2), ch, font=font, fill=color)
            tmp = tmp.rotate(rnd.uniform(-1.3, 1.3), resample=Image.BICUBIC, expand=False)
            layer.alpha_composite(tmp, (int(x) - size // 2, int(y) - size // 2 + rnd.randint(-2, 2)))
            x += tw + 2
        y += int(size * 1.28)
    img.alpha_composite(layer)
    return y - top


def scribble_underline(img: Image.Image, y: int, x0: int, x1: int, color, rnd, width=7):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    pts = []
    x = x0
    while x < x1:
        pts.append((x, y + rnd.uniform(-3, 3) + math.sin(x / 90.0) * 4))
        x += 12
    d.line(pts, fill=color, width=width, joint="curve")
    img.alpha_composite(layer)


def make(base_fig: Path | None, out: Path, title: str, sub: str, kicker: str, footer_left: str, footer_right: str, with_hand: bool = False, fig_caption: str = "", arxiv_id: str = ""):
    rnd = random.Random(11)
    img = paper_base().convert("RGBA")

    top_text = 210
    hl_ranges: list[tuple[int, int]] = []
    plain_parts: list[str] = []
    pos = 0
    i = 0
    while i < len(title):
        if title[i] in "【[":
            j = title.find("】" if title[i] == "【" else "]", i + 1)
            if j < 0:
                plain_parts.append(title[i])
                i += 1
                continue
            inner = title[i + 1 : j]
            hl_ranges.append((pos, pos + len(inner)))
            plain_parts.append(inner)
            pos += len(inner)
            i = j + 1
        else:
            plain_parts.append(title[i])
            pos += 1
            i += 1
    plain_title = "".join(plain_parts)

    # 先算换行，再在字底下铺荧光笔
    font_h = _font(FONT_HAND, 104)
    meas = ImageDraw.Draw(img)
    max_w = W - 176
    lines = wrap_tokens(plain_title, font_h, max_w)

    if not hl_ranges and plain_title:
        # 没标记时自动高亮前 4 个字（通常是主语）
        hl_ranges = [(0, min(4, len(plain_title)))]
    if hl_ranges:
        marker = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        md = ImageDraw.Draw(marker)
        idx0 = 0
        yy = top_text
        for line in lines:
            x = 88
            for ch_i, ch in enumerate(line.replace(" ", "")):
                global_i = idx0 + ch_i
                tw = meas.textlength(ch, font=font_h)
                if any(a <= global_i < b for a, b in hl_ranges):
                    y0 = yy + int(font_h.size * 0.18)
                    y1 = yy + int(font_h.size * 1.02)
                    pts = [
                        (x - 4, y0 + rnd.uniform(-3, 3)),
                        (x + tw + 4, y0 + rnd.uniform(-3, 3)),
                        (x + tw + 4, y1 + rnd.uniform(-3, 3)),
                        (x - 4, y1 + rnd.uniform(-3, 3)),
                    ]
                    md.polygon(pts, fill=(247, 214, 96, 150))
                x += tw + 2
            idx0 += len(line)
            yy += int(104 * 1.3)
        img.alpha_composite(marker)

    used = draw_headline(img, plain_title, top_text, 104, INK + (255,), rnd)
    scribble_underline(img, top_text + used + 26, 92, 92 + min(660, int(used * 3.4)), RED + (235,), rnd)

    y_sub = top_text + used + 74
    if sub:
        f2 = _font(FONT_HAND, 52)
        d = ImageDraw.Draw(img)
        yy = y_sub
        for line in sub.split("\n")[:2]:
            layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            ld = ImageDraw.Draw(layer)
            ld.text((92, yy), line, font=f2, fill=(52, 66, 90, 255))
            img.alpha_composite(layer)
            yy += 74
        y_sub = yy

    if base_fig and base_fig.exists():
        card_top = max(y_sub + 60, 760)
        max_w, max_h = W - 260, H - card_top - 300
        art = sketchify(base_fig, max_w, max_h)
        pad = 26
        framed = Image.new("RGBA", (art.width + pad * 2, art.height + pad * 2), (0, 0, 0, 0))
        fd = ImageDraw.Draw(framed)
        fd.rounded_rectangle([0, 0, framed.width - 1, framed.height - 1], 6, fill=(252, 251, 246, 255))
        framed.alpha_composite(art.convert("RGBA"), (pad, pad))
        fd2 = ImageDraw.Draw(framed)
        hand_rect(fd2, [3, 3, framed.width - 4, framed.height - 4], (120, 130, 140, 220), width=3, rnd=rnd)

        rot = rnd.uniform(-1.8, -0.4)
        framed = framed.rotate(rot, resample=Image.BICUBIC, expand=True)
        shadow = Image.new("RGBA", framed.size, (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        sd.rounded_rectangle([8, 12, framed.width - 6, framed.height - 2], 8, fill=(90, 80, 70, 70))
        shadow = shadow.filter(ImageFilter.GaussianBlur(9))
        cx = (W - framed.width) // 2
        cy = card_top
        img.alpha_composite(shadow, (cx, cy + 6))
        img.alpha_composite(framed, (cx, cy))

        # 顶部两条半透明胶带
        for tx, ang in ((cx + int(framed.width * 0.18), -8), (cx + int(framed.width * 0.68), 6)):
            tape = Image.new("RGBA", (210, 62), (0, 0, 0, 0))
            td = ImageDraw.Draw(tape)
            td.rectangle([0, 0, 209, 61], fill=(226, 214, 188, 150))
            td.rectangle([0, 0, 209, 61], outline=(206, 192, 164, 130), width=2)
            tape = tape.rotate(ang, resample=Image.BICUBIC, expand=True)
            img.alpha_composite(tape, (tx, cy - 26))

        # 图注：用论文自己的 caption（有出处，不编造）
        if fig_caption:
            capf = _font(FONT_SANS, 22)
            cd = ImageDraw.Draw(img)
            cap = fig_caption[:58] + ("…" if len(fig_caption) > 58 else "")
            cd.text((cx + 6, cy + framed.height + 29), cap, font=capf, fill=(146, 142, 134, 255))
            if arxiv_id:
                tag = f"arXiv:{arxiv_id}"
                tw2 = cd.textlength(tag, font=capf)
                cd.text((W - 94 - tw2, cy + framed.height + 29), tag, font=capf, fill=(150, 110, 60, 255))

    # 握笔的手（从右下伸入，笔尖落在图上）
    if with_hand:
        try:
            from hand_art import paste_hand
            paste_hand(img, (W - 430, H - 640), angle=-18, scale=0.74)
        except Exception as e:
            print('hand skipped:', e)

    # 右上角印章
    stamp = Image.new("RGBA", (300, 132), (0, 0, 0, 0))
    sd2 = ImageDraw.Draw(stamp)
    hand_rect(sd2, [8, 8, 291, 123], RED + (215,), width=5, rnd=random.Random(5))
    sf = _font(FONT_HAND, 40)
    sd2.text((54, 26), "arXiv", font=sf, fill=RED + (235,))
    sf2 = _font(FONT_HAND, 34)
    sd2.text((44, 74), "新论文速读", font=sf2, fill=RED + (235,))
    stamp = stamp.rotate(-7, resample=Image.BICUBIC, expand=True)
    img.alpha_composite(stamp, (W - stamp.width - 52, 56))

    # 页脚
    d = ImageDraw.Draw(img)
    fk = _font(FONT_HAND2, 30)
    d.text((88, 96), kicker.replace(" ", "  "), font=fk, fill=(150, 110, 60, 255))
    ff = _font(FONT_SANS, 24)
    d.text((88, H - 108), footer_left, font=ff, fill=(140, 136, 128, 255))
    tw = d.textlength(footer_right, font=ff)
    d.text((W - 88 - tw, H - 108), footer_right, font=ff, fill=(140, 136, 128, 255))

    out.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out, quality=95)
    return out


def latest_context() -> dict:
    md = sorted((ROOT / "data" / "xhs").glob("*-arxiv.md"))
    if not md:
        return {}
    from collector.paper_figs import fetch_figures
    from collector.xhs_cards import parse_post

    post = parse_post(md[-1])
    pid = ""
    for line in md[-1].read_text(encoding="utf-8").splitlines():
        if "arxiv.org/abs/" in line:
            pid = line.split("arxiv.org/abs/")[1].split()[0].strip("）)")
            break
    figs = fetch_figures(pid) if pid else []
    cover = post.get("cover") or []
    return {
        "title": cover[0] if cover else "",
        "sub": "\n".join(cover[1:3]),
        "fig": Path(figs[0]["path"]) if figs else None,
        "fig_caption": (figs[0].get("caption", "") if figs else ""),
        "arxiv_id": pid,
        "date": post.get("date", ""),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fig", default=None)
    ap.add_argument("--text", default=None)
    ap.add_argument("--sub", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--hand", action="store_true", help="叠加握笔的手（线稿，效果一般）")
    a = ap.parse_args()

    ctx = latest_context()
    title = a.text or ctx.get("title") or "今日论文"
    sub = a.sub if a.sub is not None else (ctx.get("sub") or "")
    fig = Path(a.fig) if a.fig else ctx.get("fig")
    date = ctx.get("date", "")
    out = Path(a.out) if a.out else ROOT / "data" / "xhs" / "cover-hand.png"

    p = make(fig, out, title, sub, "AI × DRUG DISCOVERY", "信息雷达 · arXiv 精读", date,
             with_hand=a.hand, fig_caption=ctx.get("fig_caption", ""), arxiv_id=ctx.get("arxiv_id", ""))
    print(p)


if __name__ == "__main__":
    main()
