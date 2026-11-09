"""源健康检查：每个源最后一次成功是什么时候、连续失败几次。

存在的原因：smol.ai 的 RSS 返回 200 但内容停在两个月前——
只看 HTTP 状态码会以为一切正常。所以按“这次抓到几条”记账。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

PATH = Path(__file__).parent.parent / "data" / "health.json"


def update(stats: dict) -> dict:
    prev: dict = {}
    if PATH.exists():
        try:
            prev = json.loads(PATH.read_text(encoding="utf-8"))
        except Exception:
            prev = {}

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ok_sources = set(stats.get("ok_sources") or [])
    out: dict = {}
    for sid, n in stats.get("per_source", {}).items():
        h = prev.get(sid) or {"fails": 0, "last_ok": None, "last_count": 0, "first_seen": now}
        # 抓取成功即算健康；0 条只说明本轮没有新内容（如 X 没有新推文）
        if sid in ok_sources or n > 0:
            h["last_ok"] = now
            h["fails"] = 0
            h["last_count"] = n
        else:
            h["fails"] = int(h.get("fails", 0)) + 1
            h["last_count"] = 0
        out[sid] = h

    for sid, h in prev.items():
        out.setdefault(sid, h)

    PATH.parent.mkdir(exist_ok=True)
    PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def stale_days(iso: str | None) -> float:
    if not iso:
        return 999.0
    try:
        dt = datetime.fromisoformat(iso)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 86400
    except Exception:
        return 999.0


def status_of(sid: str, health: dict) -> tuple[str, str]:
    """返回 (展示状态, 样式类)。"""
    h = health.get(sid) or {}
    fails = int(h.get("fails", 0))
    stale = stale_days(h.get("last_ok"))
    if fails >= 3:
        return f"连续失败 {fails} 次", "bad"
    if fails > 0:
        return f"失败 {fails} 次", "warn"
    if stale > 72:
        return f"{int(stale)} 天未更新", "bad"
    if stale > 36:
        return f"{int(stale)} 天前更新", "warn"
    return "ok", "on"
