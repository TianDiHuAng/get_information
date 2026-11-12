"""生成三套视觉风格的同内容页面，供挑选。

同一份内容（看板）套三套配色与排版参数，输出到 site/_style/{a,b,c}.html，
用 /_style/a.html 这种地址就能打开对比。

    python tools/style_options.py
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"

# 三套风格：只覆盖设计 token 与少数组件，不改结构，差异才看得清
VARIANTS = {
    "a": ("A · 密集仪表盘（BoardUI 风）", """
:root{
  --bg:#f2f2ef; --surface:#ffffff; --bg-sunk:#e9e9e5; --well:#eeeeea;
  --line:#dcdcd6; --line-soft:#e8e8e3; --line-strong:#c9c9c2;
  --ink:#111312; --ink-2:#2a2d2b; --ink-3:#5d625f; --ink-4:#8b918d;
  --accent:#0f766e; --r-card:10px; --r-tile:8px;
  --shadow-card:0 1px 0 rgba(0,0,0,.04), 0 1px 2px rgba(0,0,0,.05);
}
body{font-size:13.5px}
.page{max-width:1100px}
h1.title{font-size:22px;font-weight:800;letter-spacing:-.02em}
.card{padding:12px 14px}
.kpi{grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px}
.kpi .v{font-size:32px}
.bar{margin:2px 0}
.bar .bt{height:8px;border-radius:4px}
.bar .bl{width:74px;font-size:11.5px}
.side{background:#fafaf8}
"""),
    "b": ("B · 柔和组件（heroUI 风）", """
:root{
  --bg:#fbfaf8; --surface:#ffffff; --bg-sunk:#f4f2ee; --well:#f6f4f0;
  --line:#eeeae2; --line-soft:#f3f0ea; --line-strong:#e2ddd2;
  --ink:#1b1a17; --ink-2:#3b3833; --ink-3:#6b665e; --ink-4:#9a948a;
  --accent:#5b5bd6; --accent-soft:rgba(91,91,214,.09); --r-card:20px; --r-tile:14px;
  --shadow-card:0 1px 2px rgba(27,26,23,.03), 0 18px 40px -28px rgba(27,26,23,.22);
  --shadow-card-hover:0 2px 4px rgba(27,26,23,.04), 0 26px 50px -30px rgba(27,26,23,.28);
}
body{font-size:15px;line-height:1.65}
.page{max-width:960px;padding-top:26px}
h1.title{font-size:30px;font-weight:650;letter-spacing:-.02em;margin:8px 0 20px}
.card{padding:20px 22px;margin-bottom:14px}
.kpi{grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:14px}
.kpi .v{font-size:34px;font-weight:700;letter-spacing:-.03em}
h2.sec, h2{font-size:13px;font-weight:600;color:var(--ink-4);letter-spacing:.06em;
           text-transform:uppercase;border:0;margin:32px 0 12px}
.bar .bt{height:9px;border-radius:5px;background:var(--bg-sunk)}
.bar .bt i{border-radius:5px;background:linear-gradient(90deg,#7f7ff0,#5b5bd6)}
.side{background:#fff;border-right:1px solid var(--line)}
.tag,.chip{border-radius:999px;padding:3px 11px;background:var(--bg-sunk);border:0;font-size:12px}
"""),
    "c": ("C · 纸面编辑（衬线 + 细线）", """
:root{
  --bg:#fdfcf9; --surface:#ffffff; --bg-sunk:#f6f4ee; --well:#f7f5f0;
  --line:#d8d2c4; --line-soft:#e9e4d8; --line-strong:#c4bdab;
  --ink:#17150f; --ink-2:#332f26; --ink-3:#6a6252; --ink-4:#9a9280;
  --accent:#8a2f1f; --accent-soft:rgba(138,47,31,.07); --r-card:2px; --r-tile:2px;
  --shadow-card:none; --shadow-card-hover:none;
  --serif:"Iowan Old Style",Georgia,"Songti SC","Noto Serif CJK SC",serif;
}
body{font-size:15px;line-height:1.8}
.page{max-width:820px}
h1.title{font-family:var(--serif);font-size:34px;font-weight:600;letter-spacing:-.01em;
         border-bottom:2px solid var(--ink);padding-bottom:12px}
h2,h2.sec{font-family:var(--serif);font-size:20px;font-weight:600;text-transform:none;
          letter-spacing:0;border-bottom:1px solid var(--line);padding-bottom:8px;margin:36px 0 14px}
.card{border:0;border-top:1px solid var(--line);border-radius:0;padding:14px 0;background:transparent}
.kpi{grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:0 26px}
.kpi .card{border-top:0;border-left:2px solid var(--accent);padding-left:12px}
.kpi .v{font-family:var(--serif);font-size:36px;font-weight:600}
.bar .bt{height:5px;background:var(--line-soft);border-radius:0}
.bar .bt i{background:var(--accent);opacity:.75;border-radius:0}
.bar .bl{font-family:var(--serif)}
.side{background:#fbfaf6;border-right:1px solid var(--line)}
.tag,.chip{border-radius:0;border:0;border-bottom:1px solid var(--line);padding:2px 0;background:none}
"""),
}


def main() -> int:
    src = SITE / "board.html"
    if not src.is_file():
        print("先跑一次 build_sites.py 生成 board.html")
        return 1
    doc = src.read_text(encoding="utf-8")

    out_dir = SITE / "_style"
    out_dir.mkdir(parents=True, exist_ok=True)
    for key, (label, css) in VARIANTS.items():
        variant = doc.replace("</head>", f"<style>{css}</style></head>", 1)
        variant = variant.replace(
            '<div class="page">', f'<div class="page"><p class="muted small" style="margin:0 0 6px;">'
                                  f'风格 {label}</p>', 1)
        (out_dir / f"{key}.html").write_text(variant, encoding="utf-8")
        print(f"  /_style/{key}.html  {label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
