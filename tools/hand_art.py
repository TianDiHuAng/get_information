"""封面用的「握笔的手」矢量绘制（线稿风，与手绘封面同一套笔触）。

坐标在本地 600×760 画布内绘制，再整体旋转贴到封面右下角。
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw, ImageFilter

INK = (44, 52, 48)
SKIN = (243, 219, 198)
SKIN_SHADE = (226, 196, 172)
PEN_BODY = (58, 68, 92)
PEN_CAP = (198, 62, 46)


def _wobbly_line(d: ImageDraw.ImageDraw, pts, color, width=4, rnd=None, amp=1.2):
    rnd = rnd or random.Random(3)
    path = []
    for i in range(len(pts) - 1):
        (x0, y0), (x1, y1) = pts[i], pts[i + 1]
        seg = max(2, int(math.hypot(x1 - x0, y1 - y0) / 14))
        for s in range(seg):
            t = s / seg
            path.append((
                x0 + (x1 - x0) * t + rnd.uniform(-amp, amp),
                y0 + (y1 - y0) * t + rnd.uniform(-amp, amp),
            ))
    path.append(pts[-1])
    d.line(path, fill=color, width=width, joint="curve")


def draw_hand(size=(600, 760), rnd: random.Random | None = None) -> Image.Image:
    """一只从右下伸入、握马克笔向左上书写的手。"""
    rnd = rnd or random.Random(9)
    S = 2  # 超采样
    img = Image.new("RGBA", (size[0] * S, size[1] * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def p(x, y):
        return (x * S, y * S)

    # ---------- 前臂 ----------
    forearm = [p(392, 760), p(360, 500), p(596, 470), p(600, 760)]
    d.polygon(forearm, fill=SKIN + (255,))

    # ---------- 手掌 ----------
    palm = [p(300, 470), p(292, 380), p(330, 330), p(430, 316),
            p(520, 330), p(560, 400), p(548, 480), p(470, 512), p(360, 512)]
    d.polygon(palm, fill=SKIN + (255,))

    # ---------- 马克笔 ----------
    pen_poly = [p(200, 150), p(246, 132), p(392, 372), p(346, 396)]
    d.polygon(pen_poly, fill=PEN_BODY + (255,))
    # 笔尖
    tip = [p(200, 150), p(176, 118), p(214, 128), p(246, 132)]
    d.polygon(tip, fill=PEN_CAP + (255,))
    # 笔帽
    d.polygon([p(330, 316), p(376, 292), p(408, 344), p(362, 368)], fill=PEN_CAP + (255,))

    # ---------- 手指（握笔姿态）----------
    # 食指
    d.polygon([p(322, 330), p(352, 300), p(392, 316), p(378, 366), p(340, 372)],
              fill=SKIN + (255,))
    # 中指
    d.polygon([p(340, 392), p(392, 366), p(432, 386), p(414, 436), p(356, 442)],
              fill=SKIN_SHADE + (255,))
    # 无名/小指
    d.polygon([p(378, 440), p(432, 424), p(462, 448), p(440, 486), p(390, 486)],
              fill=SKIN_SHADE + (255,))
    # 拇指
    d.polygon([p(392, 300), p(438, 268), p(470, 306), p(430, 372), p(392, 356)],
              fill=SKIN + (255,))

    # ---------- 线稿 ----------
    _wobbly_line(d, [p(392, 760), p(360, 500), p(596, 470)], INK + (255,), 5 * S, rnd)
    _wobbly_line(d, [p(596, 470), p(600, 760)], INK + (255,), 5 * S, rnd)
    _wobbly_line(d, [p(360, 500), p(348, 452)], INK + (255,), 5 * S, rnd)
    _wobbly_line(d, [p(300, 470), p(292, 380), p(330, 330), p(430, 316)], INK + (255,), 5 * S, rnd)
    _wobbly_line(d, [p(430, 316), p(520, 330), p(560, 400)], INK + (255,), 5 * S, rnd)
    _wobbly_line(d, [p(560, 400), p(548, 480), p(470, 512), p(360, 512), p(300, 470)], INK + (255,), 5 * S, rnd)

    # 笔的轮廓
    _wobbly_line(d, [p(200, 150), p(246, 132), p(392, 372), p(346, 396), p(200, 150)], INK + (255,), 5 * S, rnd)
    _wobbly_line(d, [p(200, 150), p(176, 118), p(214, 128), p(246, 132)], INK + (255,), 4 * S, rnd)
    _wobbly_line(d, [p(330, 316), p(376, 292), p(408, 344), p(362, 368), p(330, 316)], INK + (255,), 4 * S, rnd)

    # 手指线
    for poly in (
        [p(322, 330), p(352, 300), p(392, 316), p(378, 366), p(340, 372), p(322, 330)],
        [p(340, 392), p(392, 366), p(432, 386), p(414, 436), p(356, 442), p(340, 392)],
        [p(378, 440), p(432, 424), p(462, 448), p(440, 486), p(390, 486), p(378, 440)],
        [p(392, 300), p(438, 268), p(470, 306), p(430, 372), p(392, 356), p(392, 300)],
    ):
        _wobbly_line(d, poly, INK + (240,), 4 * S, rnd, amp=0.8)

    # 关节小褶
    for (x, y) in ((356, 372), (404, 422), (428, 466)):
        _wobbly_line(d, [p(x, y), p(x + 16, y + 10)], INK + (200,), 3 * S, rnd, amp=0.6)

    return img.resize(size, Image.LANCZOS)


def paste_hand(base: Image.Image, anchor: tuple[int, int], angle: float = -16.0,
               scale: float = 1.0, shadow: bool = True) -> Image.Image:
    hand = draw_hand()
    if scale != 1.0:
        hand = hand.resize((int(hand.width * scale), int(hand.height * scale)), Image.LANCZOS)
    hand = hand.rotate(angle, resample=Image.BICUBIC, expand=True)
    if shadow:
        sh = Image.new("RGBA", hand.size, (0, 0, 0, 0))
        alpha = hand.split()[3].point(lambda v: int(v * 0.22))
        sh.putalpha(alpha)
        sh = sh.filter(ImageFilter.GaussianBlur(10))
        base.alpha_composite(sh, (anchor[0] + 12, anchor[1] + 16))
    base.alpha_composite(hand, anchor)
    return base


if __name__ == "__main__":
    from PIL import Image as I

    paper = I.new("RGB", (1080, 1440), (242, 239, 232)).convert("RGBA")
    out = paste_hand(paper, (520, 700), -16, 1.0)
    out.convert("RGB").save("data/xhs/_hand_test.png")
    print("ok")
