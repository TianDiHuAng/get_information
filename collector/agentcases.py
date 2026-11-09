"""agentusecases.ai：每天自动收集"别人怎么用 AI Agent"的实战案例。

站点本地直连不通（000），只有 r.jina.ai 中转能拿到；所以走
https://r.jina.ai/https://agentusecases.ai/feed.xml，返回的是 markdown 化的 RSS。

结构（实测）：
### [标题](https://agentusecases.ai/use-case/slug)
一句话描述
链接
Sun, 08 Nov 2026 09:00:00 GMT
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .model import Item
from .net import get_text

FEED = "https://r.jina.ai/https://agentusecases.ai/feed.xml"
SEEN = Path(__file__).parent.parent / "data" / "agentcases_seen.json"


def _seen() -> dict:
    try:
        return json.loads(SEEN.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_seen(d: dict) -> None:
    SEEN.parent.mkdir(exist_ok=True)
    SEEN.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


def fetch(limit: int = 10) -> list[Item]:
    try:
        text = get_text(FEED, use_proxy=True, timeout=90)
    except Exception as e:
        print(f"  [agentcases] 拉取失败: {type(e).__name__}: {e}")
        return []

    seen = _seen()
    items: list[Item] = []
    # 按 "### [title](url)" 切块
    parts = re.split(r"^### \[", text, flags=re.M)[1:]
    for part in parts:
        m = re.match(r"(.+?)\]\((https://agentusecases\.ai/use-case/[^)]+)\)\s*\n(.*)", part, re.S)
        if not m:
            continue
        title, url, rest = m.group(1).strip(), m.group(2).strip(), m.group(3)
        lines = [ln.strip() for ln in rest.splitlines() if ln.strip()]
        summary = lines[0] if lines else ""
        # 找日期行
        published = ""
        for ln in lines[:6]:
            dm = re.search(r"(\w{3}, \d{2} \w{3} \d{4} \d{2}:\d{2}:\d{2} GMT)", ln)
            if dm:
                try:
                    published = datetime.strptime(dm.group(1), "%a, %d %b %Y %H:%M:%S %Z").replace(
                        tzinfo=timezone.utc
                    ).isoformat(timespec="seconds")
                except Exception:
                    pass
                break
        if not title or url in seen:
            continue
        items.append(
            Item(
                source="agentcases",
                layer="broad",
                region="overseas",
                title=title[:120],
                url=url,
                published=published,
                summary=summary[:240],
                lang="en",
            )
        )
        if len(items) >= limit:
            break

    for it in items:
        seen[it.url] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    _save_seen(seen)
    return items


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for it in fetch():
        print(f"{it.published[:16]} | {it.title[:70]}")
