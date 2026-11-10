"""突发即时推：够格就叫醒你，不必等到第二天早上。

判定标准（都在 `config/push.yaml` 里，可调）：
- **注意力分够高**（默认 ≥85）：宁缺勿滥；
- **够新**（默认 12 小时内）：旧闻不算突发；
- **只推官方一手**：媒体的转述不值得叫醒人；
- **永久去重**：同一条内容只推一次（`pushes` 表），重启、重跑都不会重复响；
- **免打扰时段**：默认 23:00–08:00 攒着不发。

和日报的分工：日报负责"今天的全貌"，这里只负责"现在就得知道的那一条"。
所以它刻意不看精选门槛、也不做编排 —— 一条就是一条。
"""

from __future__ import annotations

import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml

from . import push, store
from .identity import item_identity

ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / "config" / "push.yaml"

_lock = threading.Lock()
_cache: dict[str, Any] = {"mtime": 0.0, "value": {}}


def config() -> dict[str, Any]:
    try:
        mtime = CONFIG_PATH.stat().st_mtime
    except OSError:
        return {}
    with _lock:
        if _cache["mtime"] == mtime:
            return _cache["value"]
        try:
            value = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        except Exception:
            value = {}
        _cache.update(mtime=mtime, value=value)
        return value


def rules() -> dict[str, Any]:
    return dict(config().get("breaking") or {})


def in_quiet_hours(now: datetime | None = None) -> bool:
    """免打扰时段判断。支持跨零点（23 → 8）。"""
    span = rules().get("quiet_hours") or []
    if len(span) != 2:
        return False
    start, end = int(span[0]), int(span[1])
    hour = (now or datetime.now()).hour
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def _host(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url or "")
    return (m.group(1) if m else "").lower()


def is_official(item: dict[str, Any], conf: dict[str, Any]) -> bool:
    """是不是"官方一手"。

    两种情况都算：
    - 信源本身就是一手（layer == primary）；
    - 原文落在官方域名上 —— HN / X 上转的官方博客也常常是最该推的那条。
    """
    if (item.get("layer") or "") == "primary":
        return True
    host = _host(item.get("url") or "")
    if not host:
        return False
    for allowed in conf.get("official_hosts") or []:
        allowed = str(allowed).lower().lstrip(".")
        if host == allowed or host.endswith("." + allowed):
            return True
    return False


def _age_hours(published: str, now: datetime) -> float | None:
    if not published:
        return None
    try:
        dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (now - dt).total_seconds() / 3600


def select(items: Iterable[dict[str, Any]], *, now: datetime | None = None,
           pushed: set[str] | None = None) -> list[dict[str, Any]]:
    """挑出这一轮该立刻推的条目。纯函数，方便测。"""
    conf = rules()
    if not conf.get("enabled", True):
        return []
    now = now or datetime.now(timezone.utc)
    min_score = float(conf.get("min_score") or 85)
    max_age = float(conf.get("max_age_hours") or 12)
    only_primary = bool(conf.get("only_primary", True))
    limit = int(conf.get("max_per_run") or 2)
    seen = pushed if pushed is not None else store.pushed_identities("breaking")

    out: list[dict[str, Any]] = []
    for it in items:
        extra = it.get("extra") or {}
        att = extra.get("attention") or {}
        if not att.get("available"):
            continue
        if (att.get("score") or 0) < min_score:
            continue
        if extra.get("deal"):
            continue
        if only_primary and not is_official(it, conf):
            continue
        age = _age_hours(it.get("published") or "", now)
        if age is None or age > max_age:
            continue  # 没有可信时间就不叫"突发"；太旧也不推
        identity = item_identity(it.get("url") or "")
        if identity in seen:
            continue
        out.append(it)

    out.sort(key=lambda i: ((i.get("extra") or {}).get("attention") or {}).get("score") or 0,
             reverse=True)
    return out[:limit]


def render(items: list[dict[str, Any]]) -> tuple[str, str]:
    subject = f"[信息雷达] 突发 {len(items)} 条" if len(items) > 1 else "[信息雷达] 突发"
    lines = []
    for it in items:
        att = (it.get("extra") or {}).get("attention") or {}
        axes = att.get("axes") or {}
        axis_text = " ".join(f"{k}{v}" for k, v in axes.items()) if axes else ""
        lines.append(f"【{att.get('score')} 分 · {att.get('itype') or ''}】{it.get('title')}")
        if it.get("summary"):
            lines.append(str(it["summary"])[:200])
        if att.get("reason"):
            lines.append(f"为什么算突发：{att['reason']}")
        if axis_text:
            lines.append(f"五轴：{axis_text}")
        lines.append(it.get("url") or "")
        lines.append("")
    return subject, "\n".join(lines).strip()


def run(items: Iterable[dict[str, Any]], *, now: datetime | None = None,
        notify: bool = True) -> dict[str, Any]:
    """挑选 → 推送 → 记已推。任何异常都不影响主流程。"""
    if not rules().get("enabled", True):
        return {"skipped": "disabled"}
    if in_quiet_hours(now):
        return {"skipped": "quiet-hours"}
    try:
        picked = select(items, now=now)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    if not picked:
        return {"picked": 0}

    subject, text = render(picked)
    sent: dict[str, str] = {"status": "skipped"}
    if notify:
        sent = push.send(subject, text)
    # 只在至少一个通道成功时才记「已推」，否则下轮还能重试
    ok = any(str(v).endswith(("sent", "-sent")) or v == "sent" for v in sent.values())
    if ok:
        store.mark_pushed([item_identity(i.get("url") or "") for i in picked], "breaking")
    return {"picked": len(picked), "sent": sent, "marked": bool(ok),
            "titles": [i.get("title") for i in picked]}
