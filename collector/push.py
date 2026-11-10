"""推送通道：邮件 / Telegram / 通用 webhook。

为什么单独一层而不是直接调 `pushmail`：
- 日报是"一天一封"，突发是"随时一条"，两者的去重与状态不一样；
- 以后加通道（飞书、Bark、Server 酱）只改这里，不碰业务；
- 任何通道失败都不能影响其他通道，也不能让整轮跑挂掉。

`config/push.yaml` 里没配的通道默认关闭；全都没配时 `send` 返回 `no-channel`，静默跳过。
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import requests
import yaml

ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / "config" / "push.yaml"

TIMEOUT = 15
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


def channels() -> list[str]:
    """当前真正可用的通道。空列表表示没配，调用方应当静默跳过。"""
    conf = config().get("channels") or {}
    out: list[str] = []
    if conf.get("email"):
        out.append("email")
    tg = conf.get("telegram") or {}
    if tg.get("enabled") and tg.get("bot_token") and tg.get("chat_id"):
        out.append("telegram")
    hook = conf.get("webhook") or {}
    if hook.get("enabled") and hook.get("url"):
        out.append("webhook")
    return out


# --------------------------------------------------------------------------- #
# 单通道
# --------------------------------------------------------------------------- #

def _send_email(subject: str, text: str) -> str:
    from . import pushmail

    return pushmail.send_text(subject, text)


def _send_telegram(subject: str, text: str) -> str:
    tg = (config().get("channels") or {}).get("telegram") or {}
    token = str(tg.get("bot_token") or "")
    chat_id = str(tg.get("chat_id") or "")
    if not token or not chat_id:
        return "telegram-not-configured"
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": f"{subject}\n\n{text}",
                  "disable_web_page_preview": True},
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            return f"telegram-http-{r.status_code}"
        return "telegram-sent"
    except Exception as e:
        return f"telegram-failed: {type(e).__name__}"


def _send_webhook(subject: str, text: str) -> str:
    hook = (config().get("channels") or {}).get("webhook") or {}
    url = str(hook.get("url") or "")
    if not url:
        return "webhook-not-configured"
    try:
        r = requests.post(url, json={"subject": subject, "text": text}, timeout=TIMEOUT)
        return "webhook-sent" if r.status_code < 300 else f"webhook-http-{r.status_code}"
    except Exception as e:
        return f"webhook-failed: {type(e).__name__}"


_SENDERS = {"email": _send_email, "telegram": _send_telegram, "webhook": _send_webhook}


def send(subject: str, text: str, *, only: list[str] | None = None) -> dict[str, str]:
    """逐个通道发。一个失败不影响其他，返回 `{通道: 结果}`。"""
    targets = [c for c in (only or channels()) if c in _SENDERS]
    if not targets:
        return {"status": "no-channel"}
    results: dict[str, str] = {}
    for name in targets:
        try:
            results[name] = _SENDERS[name](subject, text)
        except Exception as e:  # 单通道异常不能拖垮整轮
            results[name] = f"error: {type(e).__name__}"
    return results
