"""断点续跑：把"抓取那一轮"的成果存下来，失败了不用从头再抓。

为什么只续"抓取"这一段：
- 抓取 + 补正文是整轮里最贵的**网络**部分（几分钟，还受站点限速影响）；
- 后面的模型阶段本身已经被回执保护 —— 同一输入再问一次不花钱，重跑很快；
- 渲染 / 日报 / 出口是纯 CPU，几秒钟的事，重做没有风险。

所以状态只存一份"抓完的条目"，不存中间渲染结果：少一份状态，少一类不一致。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .model import Item

ROOT = Path(__file__).parent.parent
DEFAULT_KEEP = 3


def path(day: str, root: Path | None = None) -> Path:
    return (root or ROOT) / "data" / f"state-{day}.json"


def save(payload: dict[str, Any], day: str, root: Path | None = None) -> Path:
    """把抓取结果写成状态文件。条目统一转成 dict，读回来再还原成 Item。"""
    target = path(day, root)
    target.parent.mkdir(parents=True, exist_ok=True)
    items = payload.get("items") or []
    data = {
        "day": day,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "stats": payload.get("stats") or {},
        "items": [i.to_dict() if isinstance(i, Item) else dict(i) for i in items],
    }
    target.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return target


def load(day: str, root: Path | None = None) -> dict[str, Any] | None:
    """读回状态；没有或坏了都返回 None（调用方应当照常重新抓）。"""
    target = path(day, root)
    if not target.exists():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return None
    if data.get("day") != day:
        return None
    items = [Item.from_dict(raw) for raw in (data.get("items") or [])]
    if not items:
        return None
    return {"items": items, "stats": data.get("stats") or {}}


def prune(root: Path | None = None, keep: int = DEFAULT_KEEP) -> int:
    """只留最近几天的状态文件，别让 data/ 无限长。"""
    folder = (root or ROOT) / "data"
    if not folder.exists():
        return 0
    files = sorted(folder.glob("state-*.json"), key=lambda p: p.name, reverse=True)
    removed = 0
    for old in files[max(0, keep):]:
        try:
            old.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def discard(day: str, root: Path | None = None) -> bool:
    """成功跑完之后清掉当天状态：下次跑必须是新的一轮。"""
    target = path(day, root)
    if not target.exists():
        return False
    try:
        target.unlink()
        return True
    except OSError:
        return False


def ensure_stats(stats: dict[str, Any] | None, *, items: int = 0) -> dict[str, Any]:
    """补齐渲染与日报需要的最小字段。

    续跑时读回的是上一次的 stats，字段可能比现在的代码少（比如后来才加的
    `registry`）；旧状态文件也不该让整页崩掉。缺什么补什么，有就用原值。
    """
    stats = dict(stats or {})
    stats.setdefault("generated_at", datetime.now().isoformat(timespec="seconds"))
    stats.setdefault("registry", [])
    stats.setdefault("errors", [])
    stats.setdefault("by_region", {})
    stats.setdefault("by_layer", {})
    stats.setdefault("sources_ok", 0)
    stats.setdefault("raw", items)
    stats.setdefault("new_today", 0)
    stats.setdefault("repeats", 0)
    return stats


def is_stale(day: str, root: Path | None = None, hours: int = 12) -> bool:
    """状态太旧就别用了 —— 半天的行情已经变了，接着旧数据出报会误导人。"""
    target = path(day, root)
    if not target.exists():
        return True
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        saved = datetime.fromisoformat(str(data.get("saved_at")))
    except Exception:
        return True
    return datetime.now() - saved > timedelta(hours=hours)
