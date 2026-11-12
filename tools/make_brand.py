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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(BRAND_DIR / "logo-src.png"))
    ap.add_argument("--bands", nargs="*", default=None,
                    help="手填行范围，形如 41-318；不给就自动切")
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

    # 2) 主站字标（第二条）
    if len(bands) > 1:
        text = cut(bands[1])
        text.thumbnail((720, 720), Image.LANCZOS)
        text.save(BRAND_DIR / "logo-text.png", optimize=True)

    # 3) 子站字标（第三条，可选）
    if len(bands) > 2:
        sub = cut(bands[2])
        sub.thumbnail((720, 720), Image.LANCZOS)
        sub.save(BRAND_DIR / "logo-text-aidd.png", optimize=True)

    # 4) 图标：徽标放白底圆角方块上（标签栏底色各不相同，白底最稳）
    def icon(size: int) -> Image.Image:
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        ImageDraw.Draw(canvas).rounded_rectangle(
            (0, 0, size - 1, size - 1), radius=max(2, int(size * 0.22)), fill=(255, 255, 255, 255))
        inner = int(size * 0.84)
        scaled = square.copy()
        scaled.thumbnail((inner, inner), Image.LANCZOS)
        canvas.alpha_composite(scaled, ((size - scaled.size[0]) // 2,
                                        (size - scaled.size[1]) // 2))
        return canvas

    icon(512).save(BRAND_DIR / "icon-512.png", optimize=True)
    icon(192).save(BRAND_DIR / "icon-192.png", optimize=True)
    icon(180).save(BRAND_DIR / "apple-icon.png", optimize=True)
    icon(64).save(BRAND_DIR / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])

    for name in ("logo-mark.png", "logo-text.png", "logo-text-aidd.png",
                 "icon-512.png", "icon-192.png", "apple-icon.png", "favicon.ico"):
        p = BRAND_DIR / name
        if p.is_file():
            print(f"  {name:<20}{p.stat().st_size // 1024:>5} KB  {Image.open(p).size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
