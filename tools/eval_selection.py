"""跑金标评测：预筛 + 两次评分，按模型并排比较，可只看开发集或留出集。

用法：
    python tools/eval_selection.py                        # 默认模型，全部样本
    python tools/eval_selection.py --split development     # 调提示词时只看开发集
    python tools/eval_selection.py --split holdout         # 改完用留出集验收
    python tools/eval_selection.py --models default,qwen   # 多模型并排
    python tools/eval_selection.py --limit 40 --enrich

为什么分开发集/留出集：调提示词时反复看同一批样本，会把它调成"只会做这几道题"。
留出集只在最后用一次，它掉下来的分数才是真的。

口径（和 AIHOT 一致）：
- `either` 不进任何分母；
- 模型没答出来算"没答对"，进覆盖率分母、进完整准确率，但不进准确率；
- 报告写成 `{meta, models}`，每个模型带 summary / sweep / perStratum / cases，
  和它 SelectBench 导入的结构一致，方便以后做对照页。
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
SPLITS = ("all", "development", "holdout")


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
            continue
        material = row.get("material") or {}
        item = row.get("item") or {}
        # 新格式读 material/sourceFacts/samplingContext，旧格式退回 item
        title = material.get("title") or item.get("title") or ""
        body = material.get("bodyZh") or item.get("body") or ""
        ctx = row.get("samplingContext") or {}
        facts = row.get("sourceFacts") or {}
        cases.append({
            "case_id": row.get("caseId") or f"line-{lineno}",
            "gold": LABELS[decision],
            "decision": decision,
            "item": {
                "title": title,
                "summary": item.get("summary") or "",
                "body": body,
                "url": item.get("url") or f"https://gold.local/{row.get('caseId') or lineno}",
                "source": item.get("source") or material.get("sourceName") or "gold",
                "layer": item.get("layer") or "broad",
                "published": item.get("published") or material.get("publishedAt") or "",
                "lang": facts.get("language") or item.get("lang") or "zh",
            },
            "split": ctx.get("benchmarkSplit") or "development",
            "stratum": ctx.get("samplingStratum") or "未分层",
            "tier": facts.get("sourceTier") or "",
        })
    return cases


def to_item(raw: dict, tier: str = "") -> Item:
    """把金标里的材料变成 Item。

    `tier`（T1 / T1_5 / T2）决定用哪个门槛 —— 金标材料本身没有"信源层"，
    不传的话会一律按默认层（68 分）判，官方一手的好稿会被自家门槛挡下来。
    """
    layer = {"T1": "primary", "T1_5": "rank", "T2": "broad"}.get(tier or "", None)
    item = Item(
        source=str(raw.get("source") or "gold"),
        title=str(raw.get("title") or ""),
        url=str(raw.get("url") or "https://gold.local/x"),
        layer=layer or str(raw.get("layer") or "broad"),
        region="overseas",
        published=str(raw.get("published") or ""),
        summary=str(raw.get("summary") or ""),
        lang=str(raw.get("lang") or "zh"),
    )
    if raw.get("body"):
        item.extra["body"] = str(raw["body"])
    return item


def ensure_body(item: Item) -> None:
    """金标里没存正文时现抓一次（没有正文时评分器几乎只会给 20–40 分）。"""
    if item.extra.get("body") or not item.url.startswith("http"):
        return
    try:
        from collector import extract

        got = extract.enrich_item(item, {"timeout": 20, "max_chars": 4000, "skip_hosts": []})
        if got.get("body"):
            item.extra["body"] = got["body"]
    except Exception:
        pass


def judge(case: dict, *, enrich: bool = False, model: str | None = None) -> dict:
    item = to_item(case["item"], tier=case.get("tier") or "")
    if enrich:
        ensure_body(item)
    label = rating.prefilter(item, model=model)
    if label == "BLOCK":
        return {"case_id": case["case_id"], "gold": case["gold"], "predicted": False,
                "avg": None, "label": label, "reason": "预筛拦截",
                "stratum": case["stratum"], "split": case["split"]}
    runs = [rating.score_once(item, n, model=model) for n in (1, 2)]
    ok = [r for r in runs if r]
    if len(ok) < 2:
        return {"case_id": case["case_id"], "gold": case["gold"], "predicted": None,
                "avg": None, "label": label, "reason": "评分失败",
                "stratum": case["stratum"], "split": case["split"]}
    avg = int(sum(r["score"] for r in ok) // len(ok))
    threshold = rating.threshold_for(item, rating.config())
    return {"case_id": case["case_id"], "gold": case["gold"], "avg": avg,
            "predicted": avg >= threshold, "threshold": threshold, "label": label,
            "itype": ok[0]["itype"], "reason": ok[0]["reason"],
            "stratum": case["stratum"], "split": case["split"]}


def per_stratum(results: list[dict]) -> dict[str, dict]:
    groups: dict[str, list[dict]] = {}
    for r in results:
        groups.setdefault(r.get("stratum") or "未分层", []).append(r)
    return {name: evaluate.summarize(rows) for name, rows in sorted(groups.items())}


def run_model(cases: list[dict], model: str, args) -> dict:
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(judge, c, enrich=args.enrich, model=model): c for c in cases}
        for done, fut in enumerate(as_completed(futures), 1):
            try:
                results.append(fut.result())
            except Exception as e:
                case = futures[fut]
                results.append({"case_id": case["case_id"], "gold": case["gold"],
                                "predicted": None, "avg": None,
                                "stratum": case["stratum"], "split": case["split"],
                                "reason": f"{type(e).__name__}: {e}"})
            if done % 20 == 0 or done == len(cases):
                print(f"    {model}: {done}/{len(cases)}")
    return {
        "summary": evaluate.summarize(results),
        "sweep": evaluate.sweep(results, args.lo, args.hi, args.step),
        "perStratum": per_stratum(results),
        "cases": results,
    }


def _row(name: str, s: dict) -> str:
    return (f"  {name[:22]:<22} {s['valid']:>4} {(s['accuracy'] or 0):>7.1%} "
            f"{(s['coverage'] or 0):>7.1%} {(s['complete_accuracy'] or 0):>9.1%} "
            f"{(s['f1'] or 0):>6.3f}")


def main() -> int:
    ap = argparse.ArgumentParser(description="金标评测（支持多模型与开发/留出集）")
    ap.add_argument("--gold", default=str(ROOT / "data" / "gold.jsonl"))
    ap.add_argument("--models", default="", help="逗号分隔；留空 = config/llm.yaml 里的默认模型")
    ap.add_argument("--split", default="all", choices=SPLITS)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--enrich", action="store_true", help="金标没存正文时现抓（强烈建议开）")
    ap.add_argument("--lo", type=int, default=40)
    ap.add_argument("--hi", type=int, default=90)
    ap.add_argument("--step", type=int, default=2)
    ap.add_argument("--out-dir", default=str(ROOT / "data" / "eval"))
    args = ap.parse_args()

    gold = Path(args.gold)
    if not gold.exists():
        print(f"找不到 {gold}；先在后台「标注」里标一批，或跑 tools/make_gold.py")
        return 1
    if not llm.available():
        print("模型不可用（config/llm.yaml 里没配 api_key 或 model）")
        return 1
    try:
        store.migrate()
    except Exception:
        pass

    cases = load_cases(gold)
    if args.split != "all":
        cases = [c for c in cases if c["split"] == args.split]
    if not cases:
        print(f"{gold} 里没有{'已标注的' if args.split == 'all' else args.split + ' 的'}样本")
        return 1
    if args.limit:
        cases = cases[: args.limit]

    models = [m.strip() for m in args.models.split(",") if m.strip()] or [llm.settings()["model"]]
    print(f"评测 {len(cases)} 条 · 模型 {', '.join(models)} · 划分 {args.split}")
    started = time.time()
    reports = {m: run_model(cases, m, args) for m in models}

    print("\n=== 各模型 ===")
    print(f"  {'模型':<22} {'有效':>4} {'准确率':>7} {'覆盖率':>7} {'完整准确':>9} {'F1':>6}")
    for name, rep in reports.items():
        print(_row(name, rep["summary"]))

    best = max(reports, key=lambda m: reports[m]["summary"]["f1"] or 0)
    print(f"\nF1 最高：{best}")

    for name, rep in reports.items():
        strata = rep["perStratum"]
        if len(strata) > 1:
            print(f"\n=== {name} 分层 ===")
            for label, s in strata.items():
                print(_row(label, s))

    sweep = reports[best]["sweep"]
    if sweep:
        print(f"\n=== {best} 门槛扫描 ===")
        print(f"  {'门槛':>4} {'选中':>5} {'准确':>7} {'查准':>7} {'查全':>7} {'F1':>7}")
        for row in sweep:
            print(f"  {row['threshold']:>4} {row['selected']:>5} {row['accuracy']:>7.3f} "
                  f"{row['precision']:>7.3f} {row['recall']:>7.3f} {row['f1']:>7.3f}")

    # gold 为 None 的是"两可"，不进任何分母，也不算判错
    wrong = [c for c in reports[best]["cases"]
             if c.get("gold") is not None and c.get("predicted") is not None
             and c["predicted"] != c["gold"]]
    if wrong:
        print(f"\n=== 判错 {len(wrong)} 条（前 8）===")
        for c in wrong[:8]:
            print(f"  [{c['case_id']}] 金标={'选' if c['gold'] else '不选'} "
                  f"模型={'选' if c['predicted'] else '不选'} 分={c.get('avg')} "
                  f"{c.get('stratum')} {c.get('reason') or ''}")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = out_dir / f"selection-{stamp}.json"
    out.write_text(json.dumps({
        "meta": {"generatedAt": datetime.now().isoformat(timespec="seconds"),
                 "gold": str(gold), "split": args.split, "n": len(cases),
                 "seconds": round(time.time() - started, 1)},
        "models": {m: {k: v for k, v in rep.items()} for m, rep in reports.items()},
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n完整报告：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
