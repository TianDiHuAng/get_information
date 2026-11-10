"""周报与月报：从日报汇编，不调模型。

吸收自 AIHOT 的做法：**日报是"今天读什么"，周报是"这周读过什么"**。
所以它不是重新判断一遍，而是把近 N 天进过日报的条目重新编排一次：

- 同一件事跨天只算一件（按事件合并）；
- 排在前面的是"报道面广 + 连续几天还在说 + 分数高"的，不是"某天分最高"的；
- 按分类分栏，让人能看出这周偏了哪个方向。

编排完全由规则决定，可复现。模型要写综述另说 —— 这里刻意不写，
因为"这周发生了什么"读起来最舒服的形态是条目本身，不是一段润色过的散文。
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from . import edition, store

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"

# 周报取前 20 件、月报取前 30 件（AIHOT 同样的量级）
LIMITS = {"weekly": 20, "monthly": 30}
KINDS = {"weekly": 7, "monthly": 30}


def _score(item: dict[str, Any]) -> float:
    """一件事实在周报里的分量：报道面 + 持续天数 + 分数，官方一手再加。

    空标题（「太疯狂了」这类）复用日报的罚分规则 —— 周报同样不该让没信息量的标题占前排。
    """
    att = (item.get("attention") or {}).get("score")
    base = float(att if att is not None else (item.get("score") or 0))
    sources = int(item.get("event_sources") or 0) or 1
    days = int(item.get("days_seen") or 1)
    official = 5.0 if (item.get("layer") or "") == "primary" else 0.0
    # 连续几天还在说，说明它是持续性的而不是一次性刷屏
    persist = 3.0 * math.log2(1 + max(0, days - 1))
    weight = base * 0.5 + 5 * math.log2(1 + max(0, sources - 1)) + persist + official
    return round(weight + edition.title_penalty(item), 2)


def _key(item: dict[str, Any]) -> str:
    """同一件事一个键：优先事件 id，其次身份。"""
    event_id = item.get("event_id")
    return f"event:{event_id}" if event_id else f"item:{item.get('identity')}"


def group(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """把条目按事件合并，留下最强的代表稿。"""
    buckets: dict[str, dict[str, Any]] = {}
    for item in items:
        key = _key(item)
        cur = buckets.get(key)
        if cur is None:
            buckets[key] = dict(item, members=[item])
            continue
        cur["members"].append(item)
        cur["days_seen"] = max(int(cur.get("days_seen") or 1), int(item.get("days_seen") or 1))
        cur["event_sources"] = max(int(cur.get("event_sources") or 0),
                                   int(item.get("event_sources") or 0))
        # 代表稿：分高的赢；同分留更早出现的那条（先被读者看到的）
        if _score(item) > _score(cur):
            members = cur["members"]
            buckets[key] = dict(item, members=members)
            buckets[key]["days_seen"] = max(int(cur.get("days_seen") or 1),
                                            int(item.get("days_seen") or 1))
            buckets[key]["event_sources"] = max(int(cur.get("event_sources") or 0),
                                                int(item.get("event_sources") or 0))
    out = []
    for bucket in buckets.values():
        bucket["weight"] = _score(bucket)
        out.append(bucket)
    out.sort(key=lambda b: (-b["weight"], b.get("first_day") or "", b.get("url") or ""))
    return out


def compose(kind: str = "weekly", day: str | None = None) -> dict[str, Any]:
    """编一期周报/月报。返回结构供渲染与测试使用。"""
    days = KINDS.get(kind, 7)
    day = day or store.today_str()
    rows = store.reported_items(days=days, day=day)
    events = group(rows)

    end = datetime.strptime(day, "%Y-%m-%d")
    start = end - timedelta(days=days - 1)
    limit = LIMITS.get(kind, 20)

    # 和日报一样：空标题（「太疯狂了」）不当前排，只降到后面，不删
    strong = [e for e in events if edition.headline_eligible(e)]
    weak = [e for e in events if not edition.headline_eligible(e)]
    top = (strong + weak)[:limit]

    sections: dict[str, list[dict[str, Any]]] = {}
    for item in top:
        label = item.get("category") or "其他"
        sections.setdefault(label, []).append(item)

    sources = {r.get("source") for r in rows if r.get("source")}
    return {
        "kind": kind,
        "day": day,
        "range": (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")),
        "reports": len(rows),
        "events": len(events),
        "sources": len(sources),
        "top": top,
        "sections": sections,
        "days": days,
    }


def render_md(data: dict[str, Any]) -> str:
    label = "周报" if data["kind"] == "weekly" else "月报"
    start, end = data["range"]
    lines = [
        f"# Z-Bit · {label}（{start} ~ {end}）",
        "",
        f"> {data['reports']} 条报道 · {data['events']} 个事件 · {data['sources']} 个源",
        "",
    ]
    if not data["top"]:
        return "\n".join(lines + ["本期没有进过日报的内容。", ""])

    lines += ["## 本期要闻", ""]
    for i, item in enumerate(data["top"], 1):
        crowd = []
        if item.get("event_sources"):
            crowd.append(f"{item['event_sources']} 家")
        if int(item.get("days_seen") or 1) > 1:
            crowd.append(f"{item['days_seen']} 天")
        tail = f" `{item.get('source') or ''}`" + (f" · {'/'.join(crowd)}" if crowd else "")
        summary = " ".join(str(item.get("summary") or "").split())[:140]
        lines.append(f"{i}. **[{item.get('title') or ''}]({item.get('url') or ''})**{tail}")
        if summary:
            lines.append(f"   {summary}")
    lines.append("")

    for category, items in data["sections"].items():
        lines.append(f"## {category}")
        lines.append("")
        for item in items:
            lines.append(f"- [{item.get('title') or ''}]({item.get('url') or ''})")
        lines.append("")
    return "\n".join(lines)


def build(kind: str = "weekly", day: str | None = None,
          out_dir: Path | None = None) -> dict[str, Any]:
    data = compose(kind, day)
    target_dir = out_dir or DATA
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{kind}-{data['day']}.md"
    target.write_text(render_md(data), encoding="utf-8")
    # 记一期，缺期检测与看板都能用
    try:
        store.save_edition(kind, data["day"], entries=len(data["top"]))
    except Exception:
        pass
    return {"file": str(target), "kind": kind, "events": len(data["top"]),
            "reports": data["reports"], "range": data["range"]}


def build_all(day: str | None = None, out_dir: Path | None = None) -> dict[str, Any]:
    """两期一起出。规则编排很便宜，没必要等周一或月初。"""
    return {"weekly": build("weekly", day, out_dir), "monthly": build("monthly", day, out_dir)}


__all__ = ["compose", "group", "render_md", "build", "build_all", "edition"]
