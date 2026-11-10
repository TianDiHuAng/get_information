"""安全阀：只决定"发不发出去"，不决定走哪套逻辑。

对齐 AIHOT 架构文档：

> `COLLECT_ENABLED`、`MODEL_CALLS_ENABLED`、`FEISHU_CONTENT_PUSH_ENABLED` ……
> 只决定"发不发出去"，不决定走哪套逻辑；只有设成 `true` 才打开，没写就是关。

为什么需要：调页面、改样式、跑测试的时候，不该抓一次真实网络、烧一次模型钱、
给群里推一条消息。以前只能靠 `--skip-rate` 和 `--no-mail`，覆盖不全。

三个开关（环境变量）：

| 变量 | 关掉之后 |
|---|---|
| `RADAR_COLLECT` | 不抓网络，直接返回空（流水线其余阶段照跑，页面用旧数据） |
| `RADAR_MODEL` | 不调模型，评分/结构化/翻译静默降级 |
| `RADAR_PUSH` | 不发邮件、不推告警、不推突发 |

**默认值**：采集与模型默认开（否则日常运行要记着开），推送默认关 ——
推送是最不该误触的，必须显式打开。
"""

from __future__ import annotations

import os
from typing import Any

DEFAULTS = {
    "collect": True,
    "model": True,
    "push": False,
}

_ENV = {
    "collect": "RADAR_COLLECT",
    "model": "RADAR_MODEL",
    "push": "RADAR_PUSH",
}

_TRUE = {"1", "true", "yes", "on", "y"}
_FALSE = {"0", "false", "no", "off", "n"}


def enabled(name: str) -> bool:
    """这个阀门开着吗。认 1/true/yes/on 与 0/false/no/off，写别的按默认值。"""
    raw = os.environ.get(_ENV.get(name, ""), "").strip().lower()
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    return bool(DEFAULTS.get(name, True))


def state() -> dict[str, Any]:
    """全部阀门的状态 + 它们读的环境变量名（启动时打印用）。"""
    return {name: {"enabled": enabled(name), "env": _ENV[name],
                   "default": DEFAULTS[name]} for name in DEFAULTS}


def describe() -> str:
    parts = []
    for name, info in state().items():
        mark = "开" if info["enabled"] else "关"
        parts.append(f"{name}={mark}({info['env']})")
    return " · ".join(parts)
