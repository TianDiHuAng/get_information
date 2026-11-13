"""重评：把已经入库的条目重新走一遍评分。

为什么需要它：`run.py` 只给**当轮新抓的条目**打分，
已经进过日报的条目不会再进评分流程。于是换了提示词、换了权重表、
换了行业包之后，旧条目的分数永远是老口径算出来的。

这个工具绕过那层过滤，直接从库里取条目重评。只动 `scores` 表，
不碰「已报过」标记，也不重写日报。

用法：
    RADAR_PACK=aidd python tools/rescore.py --day 2026-11-13 --limit 4
    RADAR_PACK=aidd python tools/rescore.py --day 2026-11-13
    python tools/rescore.py --days 3            # 最近三天
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector import rating, store  # noqa: E402
from collector.model import Item  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default="", help="只重评这一天（YYYY-MM-DD）")
    ap.add_argument("--days", type=int, default=0, help="重评最近 N 天")
    ap.add_argument("--limit", type=int, default=0, help="只评前 N 条（试跑用）")
    ap.add_argument("--dry-run", action="store_true", help="只统计，不调模型")
    args = ap.parse_args()

    days: list[str] = []
    if args.day:
        days = [args.day]
    elif args.days:
        days = [d for d in (store.content_day(i) for i in range(args.days)) if d]
    else:
        day = store.content_day()
        days = [day] if day else []
    if not days:
        print("没有可重评的日期")
        return 1

    total = 0
    for day in days:
        rows = store.all_items(day) or []
        items = []
        for raw in rows:
            try:
                it = Item.from_dict(raw)
            except Exception:
                continue
            it.extra = dict(it.extra or {})
            it.extra["item_id"] = raw.get("id")
            it.extra["score"] = (raw.get("attention") or {}).get("score") or 0
            items.append(it)
        if args.limit:
            items = items[: args.limit]
        if not items:
            print(f"{day}: 没有条目")
            continue

        print(f"{day}: 待重评 {len(items)} 条"
              + ("（dry-run）" if args.dry_run else "，开始调模型…"))
        if args.dry_run:
            total += len(items)
            continue

        stats = rating.rate_items(items, day=day)
        total += int(stats.get("scored") or 0)
        print(f"  打分 {stats.get('scored', 0)} / 过门槛 {stats.get('selected', 0)}"
              f" / 拦截 {stats.get('blocked', 0)} / 失败 {stats.get('failed', 0)}")

    print(f"\n合计重评 {total} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
