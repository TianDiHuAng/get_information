"""从今天抓到的条目里挑样本，生成待标注的金标文件。

用法：
    python tools/make_gold.py                          # 每层 8 条，写 data/gold.jsonl
    python tools/make_gold.py --per-stratum 12         # 每层 12 条
    python tools/make_gold.py --split holdout          # 这批标进留出集
    python tools/make_gold.py --n 120                  # 不分层，总共 120 条（按难例挑）

为什么要**分层**：只按分数挑难例，样本会被"模型发布"这类占满 —— 论文、教程、
羊毛这些分类一条都没有，改它们的提示词时毫无依据。分层抽样保证每类都有代表。

层内仍然优先取门槛附近的难例：一眼就能判断的样本测不出差别，准确率会虚高。

生成的格式和后台「标注」写出来的是同一份（`material` / `sourceFacts` /
`samplingContext` / `gold`），所以两种入口可以混着用。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector import evaluate, selectbench  # noqa: E402
from collector.identity import item_identity  # noqa: E402


def adapt(raw: dict) -> dict:
    """把 items.json 里的一条改成 selectbench 认的形状。"""
    extra = raw.get("extra") or {}
    return {
        "identity": item_identity(raw.get("url") or ""),
        "title": raw.get("title") or "",
        "summary": raw.get("summary") or "",
        "body": extra.get("body") or "",
        "url": raw.get("url") or "",
        "source": raw.get("source") or "",
        "layer": raw.get("layer") or "broad",
        "published": raw.get("published") or "",
        "lang": raw.get("lang") or "zh",
        "structure": extra.get("structure") or {},
        "attention": extra.get("attention") or {},
        "extra": extra,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="生成待标注的金标样本")
    ap.add_argument("--src", default=str(ROOT / "data" / "items.json"))
    ap.add_argument("--out", default=str(ROOT / "data" / "gold.jsonl"))
    ap.add_argument("--per-stratum", type=int, default=8, help="每个分类取几条（0 = 不分层）")
    ap.add_argument("--n", type=int, default=0, help="不分层时总共取几条（0 = 用 --per-stratum）")
    ap.add_argument("--split", default="development", choices=("development", "holdout"))
    ap.add_argument("--lo", type=float, default=40.0, help="难例区间下界")
    ap.add_argument("--hi", type=float, default=90.0, help="难例区间上界")
    ap.add_argument("--force", action="store_true", help="覆盖已有文件")
    args = ap.parse_args()

    src = Path(args.src)
    out = Path(args.out)
    if not src.exists():
        print(f"找不到 {src}，先跑一次 python run.py")
        return 1
    if out.exists() and not args.force:
        print(f"{out} 已存在。要覆盖请加 --force（已有标注会被冲掉）")
        return 1

    payload = json.loads(src.read_text(encoding="utf-8"))
    items = [adapt(r) for r in (payload.get("items") or [])]

    if args.n:
        picked = evaluate.sample_for_gold(
            [{"extra": {"score": (it["attention"].get("score") or it["extra"].get("score"))},
              "_ref": it} for it in items], args.n, (args.lo, args.hi))
        chosen = [x["_ref"] for x in picked]
    elif args.per_stratum > 0:
        chosen = selectbench.stratified_sample(items, args.per_stratum, (args.lo, args.hi))
    else:
        chosen = items

    if not chosen:
        print("没有可用的条目（items.json 里缺少分数？）")
        return 1

    rows = []
    for it in chosen:
        row = selectbench.row_for_item(it, split=args.split)
        rows.append(row)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                   encoding="utf-8")

    strata: dict[str, int] = {}
    for row in rows:
        key = row["samplingContext"]["samplingStratum"]
        strata[key] = strata.get(key, 0) + 1
    print(f"已写 {len(rows)} 条到 {out}（{args.split}）")
    print("  分层：" + " · ".join(f"{k} {v}" for k, v in sorted(strata.items(), key=lambda kv: -kv[1])))
    print("下一步：在后台「标注」里点按钮，或手改每行的 gold.decision，然后")
    print(f"        python tools/eval_selection.py --enrich --split {args.split}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
