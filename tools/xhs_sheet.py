"""把卡片拼成一张总览图，便于一次看完整套版式。"""

import sys
from pathlib import Path

from PIL import Image

root = Path(__file__).resolve().parent.parent
theme = sys.argv[1] if len(sys.argv) > 1 else "editorial"
src = root / "data" / "xhs" / "cards" / theme
files = sorted(src.glob("*.png"))
if not files:
    raise SystemExit("没有卡片")

THUMB_W = 360
cols = 5
rows = (len(files) + cols - 1) // cols
pad = 18
thumb_h = int(THUMB_W * 1440 / 1080)

sheet = Image.new("RGB", (cols * (THUMB_W + pad) + pad, rows * (thumb_h + pad) + pad), (238, 239, 241))
for i, f in enumerate(files):
    im = Image.open(f).convert("RGB").resize((THUMB_W, thumb_h), Image.LANCZOS)
    r, c = divmod(i, cols)
    sheet.paste(im, (pad + c * (THUMB_W + pad), pad + r * (thumb_h + pad)))

dst = root / "data" / "xhs" / f"sheet-{theme}.png"
sheet.save(dst, quality=92)
print(f"{dst}  ({len(files)} 张)")
