"""公开读取层：哪些内容可以出现在"今天"。

对齐 AIHOT 架构文档里那条**旧文不刷屏**：

> 发现时已发布超过 48 小时的资料、新信源第一次导入的存量、回灌的推送，
> 按原文时间归档，不进"今天"、不推送；第一次导入之后不再收列表里更早的存量。
> 没有可信发布时间的资料先不公开，读到日期后再判断新旧。

这条规则解决的是一个具体问题：我第一轮实跑 175 条里，**71 条早于 3 天、21 条没有发布时间** ——
40% 的"今天"其实是旧文。它们该留在库里（可检索、可归档），但不该占今天的版面。

三种状态：
- `today`    正常公开
- `archive`  太旧：按原文时间归档，不进今天、不推送
- `undated`  没有可信发布时间：先不公开，等抓到日期再判断

配置在 `config/scope.yaml`。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

import yaml

ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / "config" / "scope.yaml"

_DEFAULTS = {"max_age_hours": 48, "require_date": True}


def settings() -> dict[str, Any]:
    data = dict(_DEFAULTS)
    try:
        raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        if isinstance(raw, dict):
            data.update(raw)
    except Exception:
        pass
    return data


def _parse(raw: str) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:len(datetime.now().strftime(fmt))], fmt)
        except Exception:
            continue
    try:
        return datetime.fromisoformat(text)
    except Exception:
        return None


def classify(published: str, seen_day: str, *, conf: dict[str, Any] | None = None) -> tuple[str, str]:
    """返回 `(状态, 原因)`。`seen_day` 是这条被发现的日期（YYYY-MM-DD）。"""
    conf = conf or settings()
    when = _parse(published)
    if when is None:
        if conf.get("require_date", True):
            return "undated", "没有可信发布时间"
        return "today", "允许无日期"
    try:
        seen = datetime.strptime(str(seen_day)[:10], "%Y-%m-%d")
    except Exception:
        return "today", "无法判断发现时间"
    try:
        age = (seen.date() - when.date()).days
    except Exception:
        return "today", ""
    limit = int(conf.get("max_age_hours") or 48) / 24
    if age > limit:
        return "archive", f"发布已 {age} 天（上限 {conf.get('max_age_hours')} 小时）"
    return "today", ""


def public(rows: Iterable[dict[str, Any]], day: str,
           *, include_archived: bool = False) -> list[dict[str, Any]]:
    """过滤出可以公开的行。`include_archived=True` 时只去掉无日期的。"""
    conf = settings()
    out = []
    for row in rows:
        status, _reason = classify(row.get("published") or "", day, conf=conf)
        if status == "today":
            out.append(row)
        elif status == "archive" and include_archived:
            out.append(row)
    return out


def summary(rows: Iterable[dict[str, Any]], day: str) -> dict[str, int]:
    """统计三种状态各多少条（给日志与看板用）。"""
    conf = settings()
    counts = {"today": 0, "archive": 0, "undated": 0}
    for row in rows:
        status, _ = classify(row.get("published") or "", day, conf=conf)
        counts[status] = counts.get(status, 0) + 1
    return counts
