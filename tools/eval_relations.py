"""跑归组评测：两两关系判断的准召 + 置信度门槛扫描。

用法：
    python tools/eval_relations.py                    # 跑 data/relation-gold.jsonl
    python tools/eval_relations.py --limit 40
    python tools/eval_relations.py --lo 0.6 --hi 0.95 --step 0.05

输出：
- 4×4 混淆表（每种金标关系被判成了什么）
- 每类的准召 + macro-F1 + 覆盖率 + 完整准确率
- 「连进同一个事件」在不同置信度门槛下的准召 —— 决定"宁可错合还是错分"

口径和精选评测一致：模型没给出结构化判断的样本，进覆盖率的分母、算作没答对，
但不进准确率 —— 否则多失败几次反而让数字更好看。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector import evaluate, events, llm, store  # noqa: E402


def load_cases(path: Path) -> list[dict]:
    cases = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as e:
            print(f"  第 {lineno} 行不是合法 JSON，跳过：{e}")
            continue
        gold = str((row.get("gold") or {}).get("relation") or "").upper()
        if gold not in evaluate.RELATIONS:
            continue
        cases.append({"case_id": row.get("caseId") or f"line-{lineno}",
                      "a": row.get("a") or {}, "b": row.get("b") or {}, "gold": gold})
    return cases


def _view(raw: dict, tag: str) -> dict:
    """评测试图，形状要和 events.judge 内部用的一致（含正文）。"""
    return {
        "identity": str(raw.get("url") or f"gold:{tag}"),
        "title": str(raw.get("title") or ""),
        "summary": str(raw.get("summary") or ""),
        "body": str(raw.get("body") or ""),
        "source": str(raw.get("source") or ""),
        "layer": str(raw.get("layer") or "broad"),
        "published": str(raw.get("published") or ""),
    }


def judge(case: dict) -> dict:
    conf = events.config()
    got = events.judge(_view(case["a"], f"{case['case_id']}-a"),
                       _view(case["b"], f"{case['case_id']}-b"), conf)
    if not got:
        return {"case_id": case["case_id"], "gold": case["gold"],
                "predicted": None, "confidence": None}
    return {"case_id": case["case_id"], "gold": case["gold"],
            "predicted": got.get("relation"), "confidence": got.get("confidence"),
            "difference": got.get("difference"), "reviewed": bool(got.get("reviewed"))}


def main() -> int:
    ap = argparse.ArgumentParser(description="归组评测")
    ap.add_argument("--gold", default=str(ROOT / "data" / "relation-gold.jsonl"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--lo", type=float, default=0.5)
    ap.add_argument("--hi", type=float, default=0.95)
    ap.add_argument("--step", type=float, default=0.05)
    ap.add_argument("--out-dir", default=str(ROOT / "data" / "eval"))
    args = ap.parse_args()

    gold = Path(args.gold)
    if not gold.exists():
        print(f"找不到 {gold}；先跑 python tools/make_relation_gold.py 并完成标注")
        return 1
    if not llm.available():
        print("模型不可用（config/llm.yaml 里没配 api_key 或 model）")
        return 1
    try:
        store.migrate()
    except Exception:
        pass

    cases = load_cases(gold)
    if not cases:
        print(f"{gold} 里没有已标注的样本")
        return 1
    if args.limit:
        cases = cases[: args.limit]

    print(f"评测 {len(cases)} 对（模型 {llm.settings()['model']}）…")
    started = time.time()
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(judge, c): c for c in cases}
        for done, fut in enumerate(as_completed(futures), 1):
            try:
                results.append(fut.result())
            except Exception as e:
                case = futures[fut]
                results.append({"case_id": case["case_id"], "gold": case["gold"],
                                "predicted": None, "confidence": None,
                                "error": f"{type(e).__name__}: {e}"})
            if done % 10 == 0 or done == len(cases):
                print(f"  …{done}/{len(cases)}")

    report = evaluate.relation_matrix(results)
    sweep = evaluate.merge_sweep(results, args.lo, args.hi, args.step)

    print("\n=== 结果 ===")
    print(f"样本 {report['total']}，有效输出 {report['valid']}（覆盖率 {report['coverage']:.1%}）")
    print(f"准确率（只算答出来的） {report['accuracy']:.1%} ｜ "
          f"完整准确率（失败也算错） {report['complete_accuracy']:.1%}")
    print(f"macro-F1 {report['macro_f1']:.3f}")

    print("\n=== 混淆表（行=金标，列=模型）===")
    head = "            " + "".join(f"{c[:13]:>14}" for c in evaluate.RELATIONS)
    print(head)
    for g in evaluate.RELATIONS:
        row = report["matrix"][g]
        print(f"{g[:12]:<12}" + "".join(f"{row[p]:>14}" for p in evaluate.RELATIONS))

    print("\n=== 每类 ===")
    for cls, s in report["per_class"].items():
        if not s["support"]:
            continue
        print(f"  {cls:<17} 支持 {s['support']:>3} ｜ 查准 {s['precision']:.2f} "
              f"查全 {s['recall']:.2f} F1 {s['f1']:.2f}")

    if sweep:
        print("\n=== 「连进同一事件」的置信度门槛 ===")
        print(f"{'门槛':>5} {'合并':>5} {'准确':>7} {'查准':>7} {'查全':>7} {'F1':>7}")
        for r in sweep:
            print(f"{r['threshold']:>5.2f} {r['merged']:>5} {r['accuracy']:>7.3f} "
                  f"{r['precision']:>7.3f} {r['recall']:>7.3f} {r['f1']:>7.3f}")

    wrong = [r for r in results if r.get("predicted") and r["predicted"] != r["gold"]]
    if wrong:
        print(f"\n=== 判错 {len(wrong)} 对（前 8）===")
        for r in wrong[:8]:
            print(f"  [{r['case_id']}] 金标 {r['gold']} → 模型 {r['predicted']} "
                  f"（{r.get('confidence')}） {r.get('difference') or ''}")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = out_dir / f"relations-{stamp}.json"
    out.write_text(json.dumps({
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "model": llm.settings()["model"],
        "gold": str(gold),
        "seconds": round(time.time() - started, 1),
        "report": report,
        "sweep": sweep,
        "results": results,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n完整报告：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
