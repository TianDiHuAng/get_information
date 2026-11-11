"""改完门槛后，把「哪些算入选」重新算一遍 —— 不用重跑模型。

门槛是纯粹的阈值判断，分数已经在库里了。改一次门槛就重跑一次评分，
是浪费（虽然回执不花钱，但要几分钟）。

用法：
    python tools/reselect.py            # 按当前门槛重算，打印变化
    python tools/reselect.py --dry-run  # 只看会变多少，不写库
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector import rating, store  # noqa: E402


class _Item:
    """threshold_for 只读 source / layer，用这个替身即可。"""

    def __init__(self, source: str, layer: str):
        self.source = source
        self.layer = layer


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conf = rating.config()
    day = store.content_day()
    rows = store.all_items(day, limit=5000, include_archived=True, include_undated=True)
    before = after = 0
    changed = []
    updates = []
    for row in rows:
        att = row.get("attention") or {}
        score = att.get("score")
        if score is None:
            continue
        threshold = rating.threshold_for(_Item(row.get("source") or "", row.get("layer") or ""), conf)
        was = bool(att.get("selected"))
        now = int(score) >= threshold
        before += 1 if was else 0
        after += 1 if now else 0
        if was != now:
            changed.append((row.get("title") or "", score, threshold, was, now))
            att = dict(att)
            att["selected"] = now
            att["threshold"] = threshold
            updates.append((row["id"], att))

    print(f"{day}：{len(rows)} 条有评分")
    print(f"入选：{before} → {after}（变化 {len(changed)} 条）")
    for title, score, threshold, was, now in changed[:12]:
        arrow = "入选" if now else "落选"
        print(f"  {score:>3} ≥ {threshold}? {arrow:<4} {title[:46]}")

    if args.dry_run:
        print("\n（--dry-run，没有写库）")
        return 0

    with store.db() as conn:
        for item_id, att in updates:
            rec = conn.execute("SELECT extra FROM items WHERE id = ?", (item_id,)).fetchone()
            if not rec:
                continue
            try:
                extra = json.loads(rec["extra"] or "{}")
            except Exception:
                extra = {}
            extra["attention"] = att
            conn.execute("UPDATE items SET extra = ? WHERE id = ?",
                         (json.dumps(extra, ensure_ascii=False), item_id))
    print(f"\n已更新 {len(updates)} 条。下一步：python run.py --skip-rate 重建页面")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
