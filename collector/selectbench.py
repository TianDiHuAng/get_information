"""标注台：在页面上给今天的条目打「选 / 不选 / 两可」，存成金标文件。

**它只写一个文件**：`data/gold.jsonl`。这和你自己用编辑器改完全等价 ——
不碰提示词、不碰门槛、不改数据库。所以它没有额外的破坏面：
标错了重新标就是，文件本身也在 `.gitignore` 里。

为什么值得做页面上点：
`tools/make_gold.py` 生成的样本是 JSON，一条一条改 `gold.decision` 很痛苦；
标 120 条大约要一小时，改成点按钮能压到二十分钟。标注是这个项目里
**唯一必须由人来做**的事，降低它的摩擦比加功能更值。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from . import store
from .identity import item_identity

DATA = Path(__file__).parent.parent / "data"
DECISIONS = ("select", "reject", "either")


def path() -> Path:
    return DATA / "gold.jsonl"


def case_id(identity: str) -> str:
    """稳定的编号：同一个身份永远同一个 caseId，重复标注不会产生两条。"""
    return "gold-" + hashlib.sha1(identity.encode("utf-8")).hexdigest()[:10]


def load() -> list[dict[str, Any]]:
    """读现有金标。坏行跳过，不让一行脏数据毁掉整个文件。"""
    target = path()
    if not target.exists():
        return []
    out = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("caseId"):
            out.append(row)
    return out


def by_identity() -> dict[str, dict[str, Any]]:
    return {r.get("identity") or "": r for r in load() if r.get("identity")}


def _write(rows: list[dict[str, Any]]) -> None:
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
    target.write_text(text + ("\n" if text else ""), encoding="utf-8")


def _tier(layer: str) -> str:
    """信源层级：评测里用来决定用哪个门槛（和 RL 的门槛表对齐）。"""
    return {"primary": "T1", "rank": "T1_5", "broad": "T2", "search": "T2", "social": "T2"}.get(layer, "T2")


def _row_for(item: dict[str, Any], split: str = "development",
             stratum: str = "") -> dict[str, Any]:
    """把条目压成评测脚本认的那一行。

    比最简版多了两组字段，对应 AIHOT 的 `sourceFacts` 与 `samplingContext`：
    - `sourceFacts`：信源层级、语言 —— 决定这条用哪个门槛；
    - `samplingContext`：开发集/留出集、分层 —— 决定怎么看错例。

    没有这两组，"按层看错"和"留出集验收"都做不了。
    """
    identity = item.get("identity") or item_identity(item.get("url") or "")
    layer = item.get("layer") or "broad"
    return {
        "caseId": case_id(identity),
        "identity": identity,
        "material": {
            "title": item.get("title") or "",
            "originalTitle": None,
            "publishedAt": item.get("published") or "",
            "sourceName": item.get("source") or "",
            "bodyZh": (item.get("body") or "")[:1200],
            "bodyOriginal": None,
        },
        "sourceFacts": {
            "sourceKind": "site",
            "sourceTier": _tier(layer),
            "firstParty": layer == "primary",
            "language": item.get("lang") or "zh",
        },
        "samplingContext": {
            "benchmarkSplit": split if split in ("development", "holdout") else "development",
            "samplingStratum": (stratum or (item.get("structure") or {}).get("category")
                                or item.get("category") or "未分层"),
        },
        "item": {   # 兼容旧字段，评测脚本两种都能读
            "title": item.get("title") or "",
            "summary": item.get("summary") or "",
            "body": (item.get("body") or "")[:1200],
            "url": item.get("url") or "",
            "source": item.get("source") or "",
            "layer": layer,
            "published": item.get("published") or "",
        },
        "model_hint": {
            "score": (item.get("attention") or {}).get("score"),
            "legacy": (item.get("extra") or {}).get("score"),
        },
        "gold": {"decision": ""},
    }


def candidates(day: str | None = None, limit: int = 300) -> list[dict[str, Any]]:
    """今天的条目 + 现有标注。按"没标的先出现"排，标完的自然沉下去。"""
    day = day or store.today_str()
    existing = by_identity()
    rows = []
    for it in store.all_items(day, limit=limit):
        detail = store.item_detail(int(it["id"])) or {}
        identity = detail.get("identity") or item_identity(it.get("url") or "")
        row = existing.get(identity) or {}
        decision = str(((row.get("gold") or {}).get("decision")) or "")
        split = ((row.get("samplingContext") or {}).get("benchmarkSplit")) or ""
        att = it.get("attention") or {}
        rows.append({
            "id": it["id"], "identity": identity,
            "title": it.get("title") or "", "source": it.get("source") or "",
            "category": (it.get("structure") or {}).get("category") or "",
            "published": (it.get("published") or "")[:10],
            "score": att.get("score"), "threshold": att.get("threshold"),
            "reason": att.get("reason") or att.get("label") or "",
            "decision": decision, "split": split,
        })
    rows.sort(key=lambda r: (bool(r["decision"]), -(r["score"] or 0)))
    return rows


def row_for_item(item: dict[str, Any], split: str = "development",
                 stratum: str = "") -> dict[str, Any]:
    """对外暴露的一行格式（make_gold 也用它，保证两种入口写出的文件一模一样）。"""
    return _row_for(item, split=split, stratum=stratum)


def stratified_sample(items: list[dict[str, Any]], per_stratum: int = 8,
                      band: tuple[float, float] = (40.0, 90.0)) -> list[dict[str, Any]]:
    """按分类分层抽样，每层最多 `per_stratum` 条，层内优先取门槛附近的难例。

    为什么要分层：只按分数挑难例，会让"发布类"样本占满 —— 那样分层统计没有意义，
    某些分类（论文、教程、羊毛）一条样本都没有，改这些类的提示词时毫无依据。
    """
    groups: dict[str, list[tuple[float, dict[str, Any]]]] = {}
    for it in items:
        score = (it.get("extra") or {}).get("score")
        if score is None and (it.get("attention") or {}).get("score") is None:
            continue
        value = float((it.get("attention") or {}).get("score") or score or 0)
        stratum = (it.get("structure") or {}).get("category") or "未分层"
        groups.setdefault(stratum, []).append((value, it))

    picked: list[dict[str, Any]] = []
    for stratum in sorted(groups):
        pool = groups[stratum]
        inside = [x for x in pool if band[0] <= x[0] <= band[1]]
        outside = [x for x in pool if not (band[0] <= x[0] <= band[1])]
        # 难例优先；不够再用同层的其它样本补，保证每层都有代表
        inside.sort(key=lambda x: abs(x[0] - (band[0] + band[1]) / 2))
        outside.sort(key=lambda x: -x[0])
        chosen = (inside + outside)[:per_stratum]
        picked.extend(it for _s, it in chosen)
    return picked


def label(item_id: int, decision: str, split: str = "development",
          stratum: str = "") -> dict[str, Any]:
    """给一条打标并落盘。`decision` 必须是 select / reject / either。

    `split` 决定这条进开发集还是留出集 —— 调提示词只看开发集，最后用留出集验收。
    """
    if decision not in DECISIONS:
        return {"ok": False, "error": f"unknown decision: {decision}"}
    item = store.item_detail(int(item_id))
    if not item:
        return {"ok": False, "error": "unknown item"}

    rows = load()
    identity = item.get("identity") or item_identity(item.get("url") or "")
    new = _row_for(item, split=split, stratum=stratum)
    new["gold"]["decision"] = decision

    replaced = False
    for i, row in enumerate(rows):
        ident = row.get("identity")
        if ident is None:  # 老文件没有 identity 时按 caseId 认
            ident = (row.get("item") or {}).get("url") and item_identity(
                (row.get("item") or {}).get("url") or "")
        if ident == identity or row.get("caseId") == new["caseId"]:
            rows[i] = new
            replaced = True
            break
    if not replaced:
        rows.append(new)
    _write(rows)
    return {"ok": True, "caseId": new["caseId"], "decision": decision,
            "split": new["samplingContext"]["benchmarkSplit"],
            "labelled": sum(1 for r in rows if (r.get("gold") or {}).get("decision") in DECISIONS),
            "total": len(rows)}


def clear(item_id: int) -> dict[str, Any]:
    """撤销一条标注（把这一行从金标文件里去掉）。"""
    item = store.item_detail(int(item_id))
    if not item:
        return {"ok": False, "error": "unknown item"}
    identity = item.get("identity") or item_identity(item.get("url") or "")
    rows = load()
    kept = [r for r in rows
            if (r.get("identity") or item_identity((r.get("item") or {}).get("url") or "")) != identity]
    _write(kept)
    return {"ok": True, "removed": len(rows) - len(kept)}


def stats() -> dict[str, Any]:
    rows = load()
    counts = {d: 0 for d in DECISIONS}
    for row in rows:
        decision = str(((row.get("gold") or {}).get("decision")) or "")
        if decision in counts:
            counts[decision] += 1
    counts["total"] = len(rows)
    counts["unlabelled"] = len([r for r in rows if not ((r.get("gold") or {}).get("decision"))])
    splits = {"development": 0, "holdout": 0, "": 0}
    for row in rows:
        split = (row.get("samplingContext") or {}).get("benchmarkSplit") or ""
        splits[split if split in splits else ""] += 1
    counts["split_development"] = splits["development"]
    counts["split_holdout"] = splits["holdout"]
    return counts
