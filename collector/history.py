"""每日快照：给"近 7 天趋势"图积累数据。

每次运行追加一行到 data/history.jsonl；同一天重复运行只保留最新一条，
所以 watchdog 每 6 小时跑一次也不会把文件刷爆。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

PATH = Path(__file__).parent.parent / "data" / "history.jsonl"


def _today() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")


def append(stats: dict) -> None:
    row = {
        "date": _today(),
        "raw": int(stats.get("raw", 0)),
        "sources_ok": int(stats.get("sources_ok", 0)),
        "errors": len(stats.get("errors", [])),
        "by_layer": stats.get("by_layer", {}),
    }
    rows = [r for r in load(365) if r.get("date") != row["date"]]
    rows.append(row)
    rows.sort(key=lambda r: r["date"])
    PATH.parent.mkdir(exist_ok=True)
    PATH.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )


def load(days: int = 7) -> list[dict]:
    if not PATH.exists():
        return []
    out: list[dict] = []
    for line in PATH.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except Exception:
            continue  # 半行损坏不影响其余历史
    return out[-days:]
