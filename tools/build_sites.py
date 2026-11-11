"""把多个行业站构建到**同一个网站**下（AI 在根，AIDD 在 /aidd/）。

一次构建一个站，用环境变量决定读哪个库、哪个行业包、写到哪个目录。
两个站共用一个 serve.py、一个端口，左侧栏有 AI / AIDD 切换。

    python tools/build_sites.py                      # AI 站 → site/
    RADAR_PACK=aidd python tools/build_sites.py \\
        --site site/aidd --data data-aidd --db data/aidd.db --base /aidd
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="site")
    ap.add_argument("--data", default="data")
    ap.add_argument("--db", default="")
    ap.add_argument("--base", default="", help="URL 前缀，例如 /aidd")
    args = ap.parse_args()

    site_root = (ROOT / args.site).resolve()
    data_dir = (ROOT / args.data).resolve()
    if args.db:
        os.environ["RADAR_DB"] = str((ROOT / args.db).resolve())
    os.environ["RADAR_DATA"] = str(data_dir)

    from collector import (about, board, export, industry, modules, offline, site,
                           theme, timeline, topics)

    theme.set_base(args.base)
    site_root.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    payload = {"items": [], "stats": {"generated_at": ""}}
    items_json = data_dir / "items.json"
    if items_json.exists():
        try:
            payload = json.loads(items_json.read_text(encoding="utf-8"))
        except Exception:
            pass

    stats = {}
    jobs = {
        "site": lambda: site.build(payload, site_root),
        "board": lambda: board.build(payload, site_root),
        "timeline": lambda: timeline.build(site_root),
        "topics": lambda: topics.build(site_root),
        "offline": lambda: offline.build(payload, site_root),
        "about": lambda: about.build(site_root),
        "modules": lambda: modules.build_all(site_root, payload, None),
        "export": lambda: export.build(payload, site_root),
    }
    for name, job in jobs.items():
        try:
            stats[name] = job()
        except Exception as e:
            stats[name] = {"error": f"{type(e).__name__}: {e}"}

    pages = len(list(site_root.rglob("*.html")))
    conf = industry.settings(reload=True)
    print(f"[{conf.get('name')}] 前缀 {args.base or '/'} → {args.site}：{pages} 个页面")
    for name, value in stats.items():
        if isinstance(value, dict) and value.get("error"):
            print(f"  ! {name}: {value['error']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
