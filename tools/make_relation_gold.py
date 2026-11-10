"""从已判过的关系对里挑样本，生成待标注的归组金标。

用法：
    python tools/make_relation_gold.py --n 120

生成的是**线上真实遇到的那批候选对**（不是随手编的例子），所以标出来的结论
能直接用来调 `config/prompts/group-pair.md` 与置信度门槛。

生成后把每行的 `gold.relation` 改成：
    SAME_OCCURRENCE（同一次发生）/ SAME_STORY（同一事件的后续）/ UNRELATED / ROUNDUP
然后跑 `python tools/eval_relations.py`。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector import store  # noqa: E402


def _side(prefix: str, row: dict) -> dict:
    return {
        "title": row.get(f"{prefix}_title") or "",
        "summary": row.get(f"{prefix}_summary") or "",
        # 正文一起带上：没有正文时模型会把"发布"和"发布后的评测"判成两件事
        "body": row.get(f"{prefix}_body") or "",
        "source": row.get(f"{prefix}_source") or "",
        "layer": row.get(f"{prefix}_layer") or "broad",
        "published": row.get(f"{prefix}_published") or "",
        "url": row.get(f"{prefix}_url") or "",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="生成待标注的归组金标")
    ap.add_argument("--out", default=str(ROOT / "data" / "relation-gold.jsonl"))
    ap.add_argument("--n", type=int, default=120)
    ap.add_argument("--force", action="store_true", help="覆盖已有文件")
    args = ap.parse_args()

    out = Path(args.out)
    if out.exists() and not args.force:
        print(f"{out} 已存在，要覆盖请加 --force")
        return 1

    try:
        store.migrate()
    except Exception:
        pass
    rows = store.pair_dump(limit=args.n * 3)
    if not rows:
        print("库里还没有判定过的关系对。先跑一次 python run.py（或至少让事件阶段跑起来）。")
        return 1

    # 同一个关系对可能被重判过多次，只留最新一条
    seen: set[tuple[str, str]] = set()
    lines = []
    for row in rows:
        key = (row["a"], row["b"])
        if key in seen:
            continue
        seen.add(key)
        lines.append({
            "caseId": f"rel-{len(lines) + 1:03d}",
            "a": _side("a", row),
            "b": _side("b", row),
            "model_hint": {"relation": row["relation"], "confidence": row["confidence"]},
            "gold": {"relation": ""},
        })
        if len(lines) >= args.n:
            break

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(json.dumps(l, ensure_ascii=False) for l in lines) + "\n",
                   encoding="utf-8")
    print(f"已写 {len(lines)} 对到 {out}")
    print("下一步：把每行的 gold.relation 改成 SAME_OCCURRENCE / SAME_STORY / UNRELATED / ROUNDUP，然后")
    print("        python tools/eval_relations.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
