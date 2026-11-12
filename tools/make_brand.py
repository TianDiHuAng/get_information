"""从一张品牌组合图生成站点要用的全部资源。

输入图约定：**透明背景**，从上到下若干条横向组合，每条之间留白。
按墨迹自动切带，不靠手填坐标：

    第 1 条  只有 Z 徽标          → logo-mark.png + 全部图标
    第 2 条  Z + 字标（主站）      → logo-text.png
    第 3 条  Z + 字标（子站，可选） → logo-text-aidd.png

用法：
    python tools/make_brand.py                     # 用 assets/brand/logo-src.png
    python tools/make_brand.py --src 新图.png
    python tools/make_brand.py --bands 41-318 405-632 734-950   # 手填行范围
"""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRAND_DIR = ROOT / "assets" / "brand"
# 当前这张组合图的字标列范围（量出来的；换图时用 --text-x 覆盖）：
#   第 2 条 677-1235 = 纯文字 "Z-bit"（图形 Z 在 330-639）
#   第 3 条 108-1456 = 整条组合（图形 Z + "-bit AIDD"），文字部分没有重复的 Z
# 两个字标都从第 3 条组合裁（同一条里的图形 Z 与 -bit 比例才一致）：
#   主站  108-839   = 图形 Z + "-bit"（丢掉末尾的 AIDD）
#   AIDD  108-1456  = 图形 Z + "-bit AIDD"
LOGO_FROM_BAND = 2          # 第 3 条（0 起）
LOGO_X = {"logo-text.png": (108, 839), "logo-text-aidd.png": (108, 1456)}

ALPHA_MIN = 16
PAD = 10


def trim(img):
    box = img.split()[-1].getbbox()
    return img.crop(box) if box else img


def detect_bands(img, min_gap: int = 8, min_ink: int = 3) -> list[tuple[int, int]]:
    """按行墨量切出横向组合带。"""
    mask = img.split()[-1].point(lambda v: 255 if v > ALPHA_MIN else 0)
    w, h = img.size
    px = mask.load()
    rows = []
    for y in range(h):
        n = 0
        for x in range(0, w, 2):          # 隔列采样，够用且快
            if px[x, y]:
                n += 1
        rows.append(n)

    bands, start = [], None
    for y, n in enumerate(rows):
        if n >= min_ink:
            start = y if start is None else start
        else:
            if start is not None and y - start > 8:
                bands.append((start, y - 1))
            start = None
    if start is not None:
        bands.append((start, len(rows) - 1))
    return bands



def clusters(img, band, min_gap: int = 6, min_ink: int = 2) -> list[tuple[int, int]]:
    """一条组合带里按列间隙切出字形簇（用来区分"图形 Z"和"文字"）。"""
    from PIL import Image as _I

    mask = img.split()[-1].point(lambda v: 255 if v > ALPHA_MIN else 0)
    w = img.size[0]
    strip = mask.crop((0, band[0], w, band[1] + 1))
    px = strip.load()
    h = strip.size[1]
    cols = []
    for x in range(w):
        n = 0
        for y in range(0, h, 2):
            if px[x, y]:
                n += 1
        cols.append(n)

    out, run = [], None
    for x, n in enumerate(cols):
        if n >= min_ink:
            run = x if run is None else run
        else:
            if run is not None and x - run > 4:
                out.append((run, x - 1))
            run = None
    if run is not None:
        out.append((run, len(cols) - 1))
    # 合并间距很小的簇（同一串文字的相邻字母）
    merged = []
    for c in out:
        if merged and c[0] - merged[-1][1] <= min_gap + 4:
            merged[-1] = (merged[-1][0], c[1])
        else:
            merged.append(list(c))
            merged[-1] = (c[0], c[1])
    return merged


def dark_variant(img):
    """把深色文字换成浅色，彩色部件保留 —— 深色模式下字标才看得见。"""
    import numpy as np
    from PIL import Image as _I

    a = np.array(img.convert("RGBA")).astype(int)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    sat = a[..., :3].max(axis=2) - a[..., :3].min(axis=2)
    mask = (lum < 118) & (sat < 95)        # 深且不鲜艳 = 文字
    a[..., 0] = np.where(mask, 241, r)
    a[..., 1] = np.where(mask, 240, g)
    a[..., 2] = np.where(mask, 236, b)
    return _I.fromarray(a.astype("uint8"), "RGBA")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(BRAND_DIR / "logo-src.png"))
    ap.add_argument("--bands", nargs="*", default=None,
                    help="手填行范围，形如 41-318；不给就自动切")
    ap.add_argument("--text-x", nargs="*", default=None,
                    help="手填字标的列范围（对应第 2、3 条），形如 677-1235")
    args = ap.parse_args()

    src = Path(args.src)
    if not src.is_file():
        print(f"找不到 {src}")
        return 1

    from PIL import Image, ImageDraw

    img = Image.open(src).convert("RGBA")
    w, h = img.size
    if args.bands:
        bands = []
        for spec in args.bands:
            a, b = spec.split("-")
            bands.append((int(a), int(b)))
    else:
        bands = detect_bands(img)
    if not bands:
        print("没在图上找到任何内容（alpha 全空？）")
        return 1
    print("切出 %d 条组合: %s" % (len(bands), bands))

    def cut(band):
        return trim(img.crop((0, band[0], w, band[1] + 1)))

    # 1) 徽标（第一条）→ 方形，四周留白
    mark = cut(bands[0])
    side = max(mark.size)
    square = Image.new("RGBA", (side + PAD * 2, side + PAD * 2), (0, 0, 0, 0))
    square.paste(mark, ((side - mark.size[0]) // 2 + PAD, (side - mark.size[1]) // 2 + PAD), mark)
    rail = square.copy()
    rail.thumbnail((240, 240), Image.LANCZOS)
    rail.save(BRAND_DIR / "logo-mark.png", optimize=True)

    # 2) 字标：从"图形 Z 之后的第一条列间隙"开始裁，
    #    否则图形 Z 和字标里的 Z 并排就成了 ZZ-bit。
    mark_w = mark.size[0]
    mask_full = img.split()[-1].point(lambda v: 255 if v > ALPHA_MIN else 0)

    def col_ink(band, x):
        strip = mask_full.crop((x, band[0], x + 1, band[1] + 1))
        return strip.getbbox() is not None

    def wordmark(band):
        width = img.size[0]
        ink = [col_ink(band, x) for x in range(width)]
        gap_start = None
        x = int(mark_w * 0.7)
        while x < width:
            if not ink[x]:
                if gap_start is None:
                    gap_start = x
            else:
                if gap_start is not None and x - gap_start >= 12:
                    piece = trim(img.crop((x, band[0], width, band[1] + 1)))
                    piece.thumbnail((720, 720), Image.LANCZOS)
                    return piece
                gap_start = None
            x += 1
        piece = trim(img.crop((0, band[0], width, band[1] + 1)))
        piece.thumbnail((720, 720), Image.LANCZOS)
        return piece

    def explicit(band, spec):
        """按显式列范围裁字标（图形 Z 之后到文字结束）。"""
        x0, x1 = (int(v) for v in spec.split("-"))
        piece = trim(img.crop((x0, band[0], x1 + 1, band[1] + 1)))
        piece.thumbnail((720, 720), Image.LANCZOS)
        return piece

    xs = args.text_x or []
    band = bands[LOGO_FROM_BAND] if len(bands) > LOGO_FROM_BAND else bands[1]
    for name, (x0, x1) in LOGO_X.items():
        if len(xs) >= 2:
            spec = xs[0] if name == "logo-text.png" else xs[1]
            x0, x1 = (int(v) for v in spec.split("-"))
        piece = trim(img.crop((x0, band[0], x1 + 1, band[1] + 1)))
        piece.thumbnail((720, 720), Image.LANCZOS)
        piece.save(BRAND_DIR / name, optimize=True)
        dark_variant(piece).save(
            BRAND_DIR / name.replace(".png", "-dark.png"), optimize=True)

    # 4) 图标：品牌青绿底 + 白色 Z 剪影
    #    16px 的标签页里，白底加渐变 Z 会糊成一团；纯色底 + 白剪影最清楚。
    from PIL import ImageChops

    silhouette = Image.new("RGBA", mark.size, (255, 255, 255, 255))
    silhouette.putalpha(mark.split()[-1])          # 用徽标的 alpha 当形状

    BRAND_TEAL = (23, 107, 117, 255)

    def icon(size: int) -> Image.Image:
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        ImageDraw.Draw(canvas).rounded_rectangle(
            (0, 0, size - 1, size - 1), radius=max(2, int(size * 0.22)), fill=BRAND_TEAL)
        inner = int(size * 0.82)                    # 留一点安全边，别顶到圆角
        piece = silhouette.copy()
        piece.thumbnail((inner, inner), Image.LANCZOS)
        canvas.alpha_composite(piece, ((size - piece.size[0]) // 2,
                                       (size - piece.size[1]) // 2))
        return canvas

    icon(512).save(BRAND_DIR / "icon-512.png", optimize=True)
    icon(192).save(BRAND_DIR / "icon-192.png", optimize=True)
    icon(180).save(BRAND_DIR / "apple-icon.png", optimize=True)
    # favicon 单独做一版：小尺寸用更粗的剪影（放大到 0.95），16px 才看得清
    small = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(small).rounded_rectangle((0, 0, 63, 63), radius=12, fill=BRAND_TEAL)
    big = silhouette.copy()
    big.thumbnail((60, 60), Image.LANCZOS)
    small.alpha_composite(big, ((64 - big.size[0]) // 2, (64 - big.size[1]) // 2))
    small.save(BRAND_DIR / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])

    for name in ("logo-mark.png", "logo-text.png", "logo-text-aidd.png",
                 "icon-512.png", "icon-192.png", "apple-icon.png", "favicon.ico"):
        p = BRAND_DIR / name
        if p.is_file():
            print(f"  {name:<20}{p.stat().st_size // 1024:>5} KB  {Image.open(p).size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
