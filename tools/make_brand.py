"""从一张品牌图生成站点要用的全部图标与字标。

输入：`assets/brand/logo-src.png`（透明 PNG，上半是 Z 徽标，下半是 Z-bit 字标）
输出（都在 assets/brand/）：

    logo-full.png    徽标 + 字标，侧栏宽屏用
    logo-mark.png    只有 Z 徽标（方形），窄侧栏与图标用
    icon-512.png / icon-192.png / apple-icon.png / favicon.ico

为什么用脚本而不是手动裁：换一张图、调一次留白，重跑一条命令就行；
手动裁的边界没人记得住。

用法：
    python tools/make_brand.py
    python tools/make_brand.py --src 另一张.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRAND_DIR = ROOT / "assets" / "brand"

# 输入图里徽标与字标的分界（按 alpha 墨量找出来的），换图时用 --split 覆盖
DEFAULT_SPLIT_Y = 750
ALPHA_MIN = 16
PAD = 8


def trim(img):
    """按 alpha 裁掉四周空白。"""
    box = img.split()[-1].getbbox()
    return img.crop(box) if box else img


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(BRAND_DIR / "logo-src.png"))
    ap.add_argument("--split", type=int, default=DEFAULT_SPLIT_Y,
                    help="徽标与字标的分界 y（像素）")
    args = ap.parse_args()

    src = Path(args.src)
    if not src.is_file():
        print(f"找不到 {src}")
        return 1

    from PIL import Image, ImageDraw

    img = Image.open(src).convert("RGBA")
    w, h = img.size

    # 1) 整幅（徽标 + 字标）
    full = trim(img)
    full.save(BRAND_DIR / "logo-full.png", optimize=True)

    # 2) 只有徽标：取分界以上部分，再裁成正方形（居中，四周留一点白）
    mark = trim(img.crop((0, 0, w, min(args.split, h))))
    side = max(mark.size)
    square = Image.new("RGBA", (side + PAD * 2, side + PAD * 2), (0, 0, 0, 0))
    square.paste(mark, ((side - mark.size[0]) // 2 + PAD,
                        (side - mark.size[1]) // 2 + PAD), mark)
    mark_small = square.copy()
    mark_small.thumbnail((240, 240), Image.LANCZOS)
    mark_small.save(BRAND_DIR / "logo-mark.png", optimize=True)

    # 3) 图标：徽标放在白底圆角方块上（浏览器标签页底色各不相同，
    #    白底能让珠光色的 Z 在深色/浅色标签栏都看得清）
    def icon(size: int) -> Image.Image:
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)
        radius = max(2, int(size * 0.22))
        draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=(255, 255, 255, 255))
        inner = int(size * 0.86)
        scaled = square.copy()
        scaled.thumbnail((inner, inner), Image.LANCZOS)
        canvas.alpha_composite(scaled, ((size - scaled.size[0]) // 2,
                                        (size - scaled.size[1]) // 2))
        return canvas

    icon(512).save(BRAND_DIR / "icon-512.png", optimize=True)
    icon(192).save(BRAND_DIR / "icon-192.png", optimize=True)
    icon(180).save(BRAND_DIR / "apple-icon.png", optimize=True)
    icon(64).save(BRAND_DIR / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    # 4) 单独裁出字标（下半部分），侧栏里和徽标横向并排，比竖版清楚
    text = trim(img.crop((0, min(args.split, h), w, h)))
    text.thumbnail((420, 420), Image.LANCZOS)
    text.save(BRAND_DIR / "logo-text.png", optimize=True)

    # 站点里用的字标（导航栏引用 /logo-full.png，比整幅小很多）
    full.thumbnail((360, 360), Image.LANCZOS)
    full.save(BRAND_DIR / "logo-nav.png", optimize=True)

    for name in ("logo-full.png", "logo-mark.png", "logo-text.png", "logo-nav.png",
                 "icon-512.png", "icon-192.png", "apple-icon.png", "favicon.ico"):
        p = BRAND_DIR / name
        print(f"  {name:<18}{p.stat().st_size // 1024:>5} KB  {Image.open(p).size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
