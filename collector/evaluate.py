"""评测：把"选得准不准"变成几个能算的数字。

吸收自 AIHOT 的 `scripts/eval-selection.ts`，保留它最有价值的三处定义：

1. **有效输出准确率** vs **完整准确率**：
   前者只在"模型答出来了"的样本上算，后者把"调用失败 / 格式不合规"也算作错。
   只看前者的模型会作弊——答不出来的样本被从分母里藏掉。
2. **覆盖率**：成功得到判断的样本占比。它和准确率必须一起看。
3. **门槛扫描**：同一批样本，把门槛从 40 扫到 90，看每一档的准召。
   "该不该改门槛"这个问题只有扫描能回答。

`either`（两可）样本始终不进分母 —— 它们本来就不该被算对或算错。

这里只做统计，不碰网络；跑模型的逻辑在 `tools/eval_selection.py`。
"""

from __future__ import annotations

from typing import Any, Iterable


def prf(true_pos: int, false_pos: int, false_neg: int) -> dict[str, Any]:
    """查准 / 查全 / F1。分母为 0 时给 0 而不是崩。"""
    precision = true_pos / (true_pos + false_pos) if (true_pos + false_pos) else 0.0
    recall = true_pos / (true_pos + false_neg) if (true_pos + false_neg) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}


def _confusion(results: Iterable[dict[str, Any]]) -> dict[str, int]:
    tp = fp = fn = tn = 0
    for r in results:
        predicted = r.get("predicted")
        if predicted is None:
            continue
        gold = bool(r.get("gold"))
        if predicted and gold:
            tp += 1
        elif predicted and not gold:
            fp += 1
        elif not predicted and gold:
            fn += 1
        else:
            tn += 1
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn}


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    """一份评测报告的核心数字。

    `results` 每项：`{case_id, gold: bool|None, predicted: bool|None, avg: float|None}`。
    `gold is None` 表示标注为 either，整条不计入任何分母。
    """
    scored = [r for r in results if r.get("gold") is not None]
    valid = [r for r in scored if r.get("predicted") is not None]
    failed = len(scored) - len(valid)
    correct = sum(1 for r in valid if bool(r["predicted"]) == bool(r["gold"]))
    matrix = _confusion(valid)
    out = {
        "total": len(results),
        "labelled": len(scored),
        "either": len(results) - len(scored),
        "valid": len(valid),
        "failed": failed,
        "correct": correct,
        # 只在答出来的样本上算：衡量"答出来的时候有多准"
        "accuracy": round(correct / len(valid), 4) if valid else 0.0,
        # 覆盖 + 完整准确率必须一起看，否则模型可以靠"少答"刷分
        "coverage": round(len(valid) / len(scored), 4) if scored else 0.0,
        "complete_accuracy": round(correct / len(scored), 4) if scored else 0.0,
        "select_rate_gold": round(sum(1 for r in scored if r["gold"]) / len(scored), 4) if scored else 0.0,
        "select_rate_pred": round(sum(1 for r in valid if r["predicted"]) / len(valid), 4) if valid else 0.0,
        **matrix,
        **prf(matrix["tp"], matrix["fp"], matrix["fn"]),
    }
    return out


def sweep(results: list[dict[str, Any]], lo: int = 40, hi: int = 90, step: int = 2) -> list[dict[str, Any]]:
    """同一批样本上把门槛从 lo 扫到 hi，看每一档的准召。

    用的是**平均分**而不是信源分层门槛 —— 扫描回答的是"门槛该定在哪"，
    所以必须让所有样本走同一个门槛。
    """
    usable = [r for r in results if r.get("gold") is not None and r.get("avg") is not None]
    if not usable:
        return []
    out: list[dict[str, Any]] = []
    for threshold in range(lo, hi + 1, step):
        rows = [dict(r, predicted=(r["avg"] >= threshold)) for r in usable]
        matrix = _confusion(rows)
        correct = matrix["tp"] + matrix["tn"]
        out.append({
            "threshold": threshold,
            "selected": sum(1 for r in rows if r["predicted"]),
            "accuracy": round(correct / len(rows), 4),
            **matrix,
            **prf(matrix["tp"], matrix["fp"], matrix["fn"]),
        })
    return out


def best_threshold(report: list[dict[str, Any]], key: str = "f1") -> dict[str, Any] | None:
    if not report:
        return None
    return max(report, key=lambda row: (row.get(key) or 0, -row["threshold"]))


def diff_report(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """两版口径的差异 —— "这一版比上一版好在哪，好多少"。"""
    keys = ("accuracy", "complete_accuracy", "coverage", "precision", "recall", "f1")
    out = {}
    for key in keys:
        a = float(before.get(key) or 0)
        b = float(after.get(key) or 0)
        out[key] = {"before": round(a, 4), "after": round(b, 4), "delta": round(b - a, 4)}
    return out


def sample_for_gold(items: Iterable[dict[str, Any]], n: int = 120,
                    band: tuple[float, float] = (40.0, 90.0)) -> list[dict[str, Any]]:
    """挑"难例"来标注：分数落在门槛附近的样本，比随手抽的更有信息量。

    一眼就能判断的样本占比太高会让准确率虚高 —— 这点 AIHOT 的文档里也强调过。

    难例不够时才用区间外的样本补，而且**只补有分数的**：没有分数的样本
    进不了门槛扫描，标了也用不上。
    """
    scored = []
    for it in items:
        score = (it.get("extra") or {}).get("score")
        if score is None:
            continue
        scored.append((float(score), it))

    pool = [it for s, it in scored if band[0] <= s <= band[1]]
    if len(pool) < n:
        chosen = {id(i) for i in pool}
        rest = [it for _s, it in scored if id(it) not in chosen]
        pool += rest[: n - len(pool)]

    pool.sort(key=lambda i: float((i.get("extra") or {}).get("score") or 0))
    # 均匀抽样，避免全集中在某个分数段
    if len(pool) > n:
        step = len(pool) / n
        pool = [pool[int(i * step)] for i in range(n)]
    return pool


def gold_line(case_id: str, item: dict[str, Any]) -> dict[str, Any]:
    """生成一行待标注的金标样本（`gold.decision` 留空，等人填）。

    正文一起存下来（如果有）：没有正文时评分器几乎只会给 20–40 分，
    标注的人也会被"只有标题"误导。
    """
    extra = item.get("extra") or {}
    return {
        "caseId": case_id,
        "item": {
            "title": item.get("title") or "",
            "summary": item.get("summary") or "",
            "body": extra.get("body") or "",
            "url": item.get("url") or "",
            "source": item.get("source") or "",
            "layer": item.get("layer") or "broad",
            "published": item.get("published") or "",
        },
        # 模型现在的判断，标注时只看一眼，别被它锚定
        "model_hint": {
            "score": extra.get("score"),
            "attention": (extra.get("attention") or {}).get("score")
            if isinstance(extra.get("attention"), dict) else None,
        },
        "gold": {"decision": ""},  # select | reject | either
    }
