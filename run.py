"""一次跑完：抓取 → 去重 → 打分 → 输出 JSON + 静态站。"""

import json
import sys
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from collector.archive import save as save_archive
from collector.digest import build as build_digest
from collector.health import update as update_health
from collector.history import append as append_history
from collector.history import load as load_history
from collector.leaderboards import fetch as fetch_lmarena
from collector.leaderboards import fetch_aa, update_aa
from collector.leaderboards import update as update_lmarena
from collector.pipeline import run
from collector.papers import run as papers_weekly
from collector.pushmail import send as send_mail
from collector.render import render
from collector.translate import translate_items

ROOT = Path(__file__).parent


def main() -> None:
    payload = run()
    payload["stats"]["translate"] = translate_items(payload["items"])
    payload["stats"]["health"] = update_health(payload["stats"])
    append_history(payload["stats"])  # 当日快照，喂给趋势图
    lmarena = update_lmarena(fetch_lmarena())  # 榜单快照（官方 HF 镜像，失败用缓存）
    aa = update_aa(fetch_aa())  # AA 智能指数快照（免费 API，失败用缓存）
    data_dir = ROOT / "data"
    data_dir.mkdir(exist_ok=True)
    (data_dir / "items.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    out = render(payload, ROOT / "site" / "index.html", history=load_history(7),
                 lmarena=lmarena, aa=aa)
    arch = save_archive(payload, out, ROOT, datetime.now().strftime("%Y-%m-%d"))
    digest = build_digest(payload, lmarena=lmarena, aa=aa)
    print(f"[4/4] 已生成 {out}  ({len(payload['items'])} 条)")
    print(f"      日报: {digest}")
    if arch.get("page"):
        print(f"      归档: {arch['page']}")
    try:
        print(f"      推送: {send_mail(digest, payload['stats'], payload=payload, lmarena=lmarena, aa=aa)}")
    except Exception as e:  # 推送失败不影响采集
        print(f"      推送失败: {type(e).__name__}: {e}")

    try:
        print(f"      周报: {papers_weekly()}")
    except Exception as e:
        print(f"      周报失败: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
