"""从今天抓到的条目里挑"难例"，生成待标注的金标文件。

用法：
    python tools/make_gold.py            # 默认 120 条，写 data/gold.jsonl
    python tools/make_gold.py --n 60 --lo 45 --hi 80

为什么默认挑"分数落在门槛附近"的：一眼就该选 / 一眼就该扔的样本，
标了也测不出差别；准确率会被这类简单样本撑得很高（AIHOT 的文档里也强调这点）。

生成后请手动把每行的 `gold.decision` 改成 `select` / `reject` / `either`，
然后跑 `python tools/eval_selection.py`。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector import evaluate  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="生成待标注的金标样本")
    ap.add_argument("--src", default=str(ROOT / "data" / "items.json"))
    ap.add_argument("--out", default=str(ROOT / "data" / "gold.jsonl"))
    ap.add_argument("--n", type=int, default=120, help="要生成多少条")
    ap.add_argument("--lo", type=float, default=40.0, help="难例区间下界（排序分）")
    ap.add_argument("--hi", type=float, default=90.0, help="难例区间上界")
    ap.add_argument("--force", action="store_true", help="覆盖已有文件")
    args = ap.parse_args()

    src = Path(args.src)
    out = Path(args.out)
    if not src.exists():
        print(f"找不到 {src}，先跑一次 python run.py")
        return 1
    if out.exists() and not args.force:
        print(f"{out} 已存在（{sum(1 for _ in out.open(encoding='utf-8'))} 行）。"
              f"要覆盖请加 --force")
        return 1

    payload = json.loads(src.read_text(encoding="utf-8"))
    items = payload.get("items") or []
    picked = evaluate.sample_for_gold(items, args.n, (args.lo, args.hi))
    if not picked:
        print("没有可用的条目（items.json 里的条目缺少排序分？）")
        return 1

    lines = [evaluate.gold_line(f"case-{i:03d}", it) for i, it in enumerate(picked, 1)]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(json.dumps(l, ensure_ascii=False) for l in lines) + "\n",
                   encoding="utf-8")
    print(f"已写 {len(lines)} 条到 {out}")
    print("下一步：把每行的 gold.decision 改成 select / reject / either，然后")
    print("        python tools/eval_selection.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
