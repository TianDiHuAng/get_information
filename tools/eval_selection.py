"""跑金标评测：预筛 + 两次评分，出一份能对比的报告。

用法：
    python tools/eval_selection.py                       # 跑 data/gold.jsonl
    python tools/eval_selection.py --limit 40            # 只跑前 40 条（先看效果）
    python tools/eval_selection.py --gold other.jsonl --lo 50 --hi 85

输出：
- 终端：准确率 / 覆盖率 / 完整准确率 / 查准查全 / 门槛扫描表
- 文件：`data/eval/selection-<时间戳>.json`（完整逐条结果，便于下轮对比）

几个口径先说清楚（和 AIHOT 一致）：
- `gold.decision = either` 的样本不进任何分母；
- 模型调用失败 / 输出不合规 **算作没答对**，会拉低"完整准确率"，但不影响"准确率"
  —— 只看后者的模型可以靠少答来刷分，所以两个必须一起看。
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

from collector import evaluate, llm, rating, store  # noqa: E402
from collector.model import Item  # noqa: E402

LABELS = {"select": True, "reject": False, "either": None}


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
        decision = str((row.get("gold") or {}).get("decision") or "").strip().lower()
        if decision not in LABELS:
            continue  # 还没标注
        cases.append({"case_id": row.get("caseId") or f"line-{lineno}",
                      "item": row.get("item") or {}, "gold": LABELS[decision]})
    return cases


def to_item(raw: dict) -> Item:
    item = Item(
        source=str(raw.get("source") or "unknown"),
        title=str(raw.get("title") or ""),
        url=str(raw.get("url") or f"https://gold.local/{hash(raw.get('title')) & 0xFFFF}"),
        layer=str(raw.get("layer") or "broad"),
        region=str(raw.get("region") or "overseas"),
        published=str(raw.get("published") or ""),
        summary=str(raw.get("summary") or ""),
    )
    if raw.get("body"):
        item.extra["body"] = str(raw["body"])
    return item


def ensure_body(item: Item, url: str) -> None:
    """金标文件里没存正文时，现抓一次。

    没有正文时评分器几乎只会给 20–40 分（实测），拿这种结果调门槛毫无意义。
    """
    if item.extra.get("body") or not url.startswith("http"):
        return
    try:
        from collector import extract

        got = extract.enrich_item(item, {"timeout": 20, "max_chars": 4000, "skip_hosts": []})
        if got.get("body"):
            item.extra["body"] = got["body"]
    except Exception:
        pass


def judge(case: dict, enrich: bool = False) -> dict:
    item = to_item(case["item"])
    if enrich:
        ensure_body(item, item.url)
    label = rating.prefilter(item)
    if label == "BLOCK":
        # 预筛判为无关：直接算"不选"，不花评分的钱
        return {"case_id": case["case_id"], "gold": case["gold"], "predicted": False,
                "avg": None, "label": label, "calls": 1}
    runs = [rating.score_once(item, n) for n in (1, 2)]
    ok = [r for r in runs if r]
    if len(ok) < 2:
        return {"case_id": case["case_id"], "gold": case["gold"], "predicted": None,
                "avg": None, "label": label, "calls": 1 + len(runs)}
    avg = int(sum(r["score"] for r in ok) // len(ok))
    threshold = rating.threshold_for(item, rating.config())
    return {"case_id": case["case_id"], "gold": case["gold"], "avg": avg,
            "predicted": avg >= threshold, "threshold": threshold, "label": label,
            "axes": ok[0]["axes"], "itype": ok[0]["itype"], "reason": ok[0]["reason"],
            "calls": 3}


def main() -> int:
    ap = argparse.ArgumentParser(description="金标评测")
    ap.add_argument("--gold", default=str(ROOT / "data" / "gold.jsonl"))
    ap.add_argument("--limit", type=int, default=0, help="最多跑多少条（0 = 全部）")
    ap.add_argument("--lo", type=int, default=40)
    ap.add_argument("--hi", type=int, default=90)
    ap.add_argument("--step", type=int, default=2)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--enrich", action="store_true",
                    help="金标里没存正文时现抓（强烈建议开：没有正文的评分不可信）")
    ap.add_argument("--out-dir", default=str(ROOT / "data" / "eval"))
    args = ap.parse_args()

    gold = Path(args.gold)
    if not gold.exists():
        print(f"找不到 {gold}；先跑 python tools/make_gold.py 并完成标注")
        return 1
    if not llm.available():
        print("模型不可用（config/llm.yaml 里没配 api_key 或 model），无法评测")
        return 1
    try:
        store.migrate()
    except Exception:
        pass

    cases = load_cases(gold)
    if not cases:
        print(f"{gold} 里没有已标注（select/reject/either）的样本")
        return 1
    if args.limit:
        cases = cases[: args.limit]

    print(f"评测 {len(cases)} 条（模型 {llm.settings()['model']}）…")
    started = time.time()
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(judge, c, args.enrich): c for c in cases}
        for done, fut in enumerate(as_completed(futures), 1):
            try:
                results.append(fut.result())
            except Exception as e:
                case = futures[fut]
                results.append({"case_id": case["case_id"], "gold": case["gold"],
                                "predicted": None, "avg": None, "error": f"{type(e).__name__}: {e}"})
            if done % 10 == 0 or done == len(cases):
                print(f"  …{done}/{len(cases)}")

    report = evaluate.summarize(results)
    sweep = evaluate.sweep(results, args.lo, args.hi, args.step)
    best = evaluate.best_threshold(sweep, "f1")

    print("\n=== 结果 ===")
    print(f"样本 {report['total']}（已标注 {report['labelled']}，两可 {report['either']}）")
    print(f"有效输出 {report['valid']}，失败 {report['failed']}")
    print(f"准确率（只算答出来的） {report['accuracy']:.1%}")
    print(f"覆盖率                 {report['coverage']:.1%}")
    print(f"完整准确率（失败也算错） {report['complete_accuracy']:.1%}")
    print(f"查准 {report['precision']:.3f} / 查全 {report['recall']:.3f} / F1 {report['f1']:.3f}")
    print(f"金标选中率 {report['select_rate_gold']:.1%} vs 预测选中率 {report['select_rate_pred']:.1%}")

    if sweep:
        print("\n=== 门槛扫描 ===")
        print(f"{'门槛':>4} {'选中':>5} {'准确':>7} {'查准':>7} {'查全':>7} {'F1':>7}")
        for row in sweep:
            mark = " ←" if best and row["threshold"] == best["threshold"] else ""
            print(f"{row['threshold']:>4} {row['selected']:>5} {row['accuracy']:>7.3f} "
                  f"{row['precision']:>7.3f} {row['recall']:>7.3f} {row['f1']:>7.3f}{mark}")
        if best:
            print(f"\nF1 最高的门槛：{best['threshold']}（F1 {best['f1']:.3f}）")

    wrong = [r for r in results if r.get("predicted") is not None and r["predicted"] != r["gold"]]
    if wrong:
        print(f"\n=== 判错 {len(wrong)} 条（前 8 条）===")
        for r in wrong[:8]:
            print(f"  [{r['case_id']}] 金标={'选' if r['gold'] else '不选'} "
                  f"模型={'选' if r['predicted'] else '不选'} 分={r.get('avg')} "
                  f"{r.get('itype') or ''} {r.get('reason') or ''}")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = out_dir / f"selection-{stamp}.json"
    out.write_text(json.dumps({
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "model": llm.settings()["model"],
        "gold": str(gold),
        "seconds": round(time.time() - started, 1),
        "report": report,
        "sweep": sweep,
        "results": results,
        "llm": llm.stats(),
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n完整报告：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
