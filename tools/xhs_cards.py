"""把小红书笔记渲染成 3:4 PNG 卡片（1080×1440）。

用法：
    python tools/xhs_cards.py                       # 默认 editorial 风格
    python tools/xhs_cards.py --theme dark
    python tools/xhs_cards.py --theme swiss --file data/xhs/2026-11-10-arxiv.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from collector.paper_figs import fetch_figures
from collector.xhs_cards import CARD_H, CARD_W, build_cards, card_html, parse_post  # noqa: E402

FIT_JS = """
const el = document.getElementById('content');
const inner = document.getElementById('inner');
if (el && inner) {
  let fs = parseFloat(getComputedStyle(el).fontSize);
  const H = () => inner.getBoundingClientRect().height;
  const fits = () => H() <= el.clientHeight;
  let guard = 0;
  while (H() < el.clientHeight * 0.86 && fs < 52 && guard++ < 16) {
    fs *= 1.05; el.style.fontSize = fs + 'px';
  }
  guard = 0;
  while (!fits() && fs > 24 && guard++ < 14) {
    fs *= 0.94; el.style.fontSize = fs + 'px';
  }
}
"""

WRAP = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<style>
 *{{margin:0;padding:0;box-sizing:border-box}}
 html,body{{width:{w}px;height:{h}px;overflow:hidden}}
 .no-lig{{font-feature-settings:"liga" 0}}
</style></head><body class="no-lig">{inner}</body></html>"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=None)
    ap.add_argument("--theme", default="editorial", choices=["editorial", "dark", "swiss"])
    ap.add_argument("--max-chars", type=int, default=150)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    src = Path(a.file) if a.file else sorted((ROOT / "data" / "xhs").glob("*-arxiv.md"))[-1]
    post = parse_post(src)
    figs = []
    m = __import__('re').search(r'主打：[^\n]*', src.read_text(encoding='utf-8'))
    pid = __import__('re').search(r'arxiv\.org/abs/([0-9.]+)', src.read_text(encoding='utf-8'))
    if pid:
        figs = fetch_figures(pid.group(1))
    cards = build_cards(post, a.max_chars, figs)
    pages = [card_html(c, a.theme, len(cards)) for c in cards]
    if not pages:
        raise SystemExit("没有可渲染的卡片")

    outdir = Path(a.out) if a.out else ROOT / "data" / "xhs" / "cards" / a.theme
    outdir.mkdir(parents=True, exist_ok=True)
    for old in outdir.glob("*.png"):
        old.unlink()

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": CARD_W, "height": CARD_H}, device_scale_factor=1)
        for i, inner in enumerate(pages, 1):
            html = WRAP.format(w=CARD_W, h=CARD_H, inner=inner)
            page.set_content(html, wait_until="load")
            page.wait_for_timeout(120)
            page.evaluate(FIT_JS)
            page.wait_for_timeout(60)
            dst = outdir / f"{i:02d}.png"
            page.screenshot(path=str(dst), clip={"x": 0, "y": 0, "width": CARD_W, "height": CARD_H})
        browser.close()

    print(f"共 {len(pages)} 张 → {outdir}")
    for p in sorted(outdir.glob("*.png")):
        print(f"  {p.name}  {p.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
