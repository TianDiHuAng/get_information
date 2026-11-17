"""OpenRouter 免费模型：只取近期上线、且 prompt/completion 都为 0 的模型。

为什么值得单独抓：这是「真白嫖」里最硬的一类 —— 不用抽奖、不用绑卡、
不用注册送体验金，模型就在那儿，API 直接能调。freebie-radar 的
openrouter.ts 就是这么做的，这里按同样的口径移植。

OpenRouter 的公开接口不需要 key，但国内直连会 SSL 断开，固定走代理。
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from .model import Item
from .net import UA, get_json

MODELS_URL = "https://openrouter.ai/api/v1/models"


def _models() -> list[dict[str, Any]]:
    """取模型清单。

    openrouter 对 TLS 指纹敏感：socks5h 与直连都可能 SSL 断，
    实测 http 代理最稳。三条路依次试，每条重试两次。
    """
    import time as _t

    import requests

    proxies = [
        {"http": "http://127.0.0.1:10808", "https": "http://127.0.0.1:10808"},
        None,
    ]
    for attempt in range(2):
        for px in proxies:
            try:
                r = requests.get(MODELS_URL, headers={"User-Agent": UA}, timeout=40,
                                 proxies=px)
                if r.status_code == 200:
                    rows = (r.json() or {}).get("data") or []
                    if rows:
                        return rows
            except Exception:
                continue
        try:
            data = get_json(MODELS_URL, use_proxy=True, timeout=40)
            rows = (data or {}).get("data") or []
            if rows:
                return rows
        except Exception:
            pass
        _t.sleep(1.5)
    return []


def _price_zero(value: Any) -> bool:
    try:
        return float(value) == 0.0
    except (TypeError, ValueError):
        return False


def fetch(days: int = 45, limit: int = 20, **_: object) -> list[Item]:
    rows = _models()
    if not rows:
        return []

    cutoff = time.time() - days * 86_400
    picked: list[tuple[float, dict[str, Any]]] = []
    for m in rows:
        mid = str(m.get("id") or "")
        if not mid:
            continue
        pricing = m.get("pricing") or {}
        is_free = mid.endswith(":free") or (
            _price_zero(pricing.get("prompt")) and _price_zero(pricing.get("completion")))
        if not is_free:
            continue
        created = float(m.get("created") or 0)
        if created and created < cutoff:
            continue
        picked.append((created, m))
    picked.sort(key=lambda x: -x[0])

    items: list[Item] = []
    for created, m in picked[:limit]:
        mid = str(m.get("id"))
        ctx = m.get("context_length")
        bits = []
        if ctx:
            bits.append(f"{round(ctx / 1024)}K 上下文")
        desc = " ".join(str(m.get("description") or "").split())
        if desc:
            bits.append(desc[:200])
        published = (datetime.fromtimestamp(created, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
                     if created else "")
        items.append(Item(
            source="openrouter_free",
            layer="rank",
            region="overseas",
            title=f"OpenRouter 新免费模型：{m.get('name') or mid}",
            url=f"https://openrouter.ai/{mid}",
            published=published,
            summary=" · ".join(bits) or "OpenRouter 免费 API 模型",
            heat=0.0,
            lang="zh",
            author="OpenRouter",
            extra={"model_id": mid, "context": ctx, "free": True},
        ))
    return items
