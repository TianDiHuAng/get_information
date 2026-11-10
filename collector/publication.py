"""公开读取层：范围、席位、证据条件，只在这里定义。

对齐 AIHOT 的 `publication/`：**所有机器出口**（RSS / API / llms.txt）读同一份规则，
不在每个出口里各写一遍。

三条规则：

1. **范围**：交给 `collector/scope.py`（旧文归档、无日期不公开）；
2. **席位**：机器出口每条新闻只出一条 —— 同一个事件的多篇报道合并成一条，
   取分最高那篇（同分时取一手源）。网页上仍然并列展示，因为人要多方对照；
3. **证据**：没有 url、没有来源、没有标题的不出口（订阅方拿到空壳没有意义）。
"""

from __future__ import annotations

from typing import Any, Iterable


def _rank(item: dict[str, Any]) -> tuple[int, int, str]:
    """排序：分高的优先，一手源优先，然后按时间倒序（字符串比较够用）。"""
    att = (item.get("extra") or {}).get("attention") or {}
    score = att.get("score")
    if score is None:
        score = (item.get("extra") or {}).get("score") or 0
    first_party = 1 if item.get("layer") == "primary" else 0
    return (int(score or 0), first_party, str(item.get("published") or ""))


def _event_of(item: dict[str, Any]) -> Any:
    extra = item.get("extra") or {}
    return extra.get("event_id") or (extra.get("structure") or {}).get("event_id")


def has_evidence(item: dict[str, Any]) -> bool:
    """出口的最低条件：有标题、有可点的地址、有来源。"""
    return bool(str(item.get("title") or "").strip()
                and str(item.get("url") or "").strip()
                and str(item.get("source") or "").strip())


def for_export(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """机器出口用：去掉没证据的，同一事件只留一条代表稿。"""
    best: dict[Any, dict[str, Any]] = {}
    loose: list[dict[str, Any]] = []
    for item in items:
        if not has_evidence(item):
            continue
        event = _event_of(item)
        if event is None:
            loose.append(item)
            continue
        current = best.get(event)
        if current is None or _rank(item) > _rank(current):
            best[event] = item
    out = list(best.values()) + loose
    out.sort(key=lambda i: _rank(i), reverse=True)
    return out


def summary(items: Iterable[dict[str, Any]]) -> dict[str, int]:
    """给了多少条、出口多少条、合并掉几个事件（日志用）。"""
    rows = list(items)
    out = for_export(rows)
    return {"in": len(rows), "out": len(out), "merged": len(rows) - len(out)}
