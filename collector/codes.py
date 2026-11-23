"""兑换码 / 邀请码提取：从标题与正文里抽出可直接使用的凭据。

来自 freebie-radar 的 `enrich/codes.ts`。只认三类，避免把普通英文单词当码：

    explicit    显式标注（邀请码 / 兑换码 / 激活码 / code ...）
    dashed      带连字符的分段码（ABCD-EFGH-IJKL）
    long_upper  超长大写串（10–40 位）

`plausible()` 是共用闸门：排除停用词、URL 片段、纯数字、无字母的串。
重复值去重，最多返回 limit 个。

用法：item 落库前调一次，结果写进 `codes` 字段，前台可一键复制。
"""

from __future__ import annotations

import re

_EXPLICIT = re.compile(
    r"(?:邀请码|兑换码|激活码|优惠码|注册码|礼品码|口令|code|invite\s*code)"
    r"[\s:：=是]{0,4}([A-Za-z0-9][A-Za-z0-9_\-]{3,39})",
    re.I,
)
_DASHED = re.compile(r"\b([A-Z0-9]{4}(?:-[A-Z0-9]{4}){2,5})\b")
_LONG_UPPER = re.compile(r"\b([A-Z0-9]{10,40})\b")
_URLISH = re.compile(r"^(?:https?|www|linux|topic|app|store|game)", re.I)

_STOP = frozenset({
    "FREE", "WINNER", "HTTP", "HTTPS", "HTML", "NULL", "TRUE", "FALSE", "LOGIN",
    "REGISTER", "STEAM", "EPIC", "GAMES", "GIVEAWAY", "BONUS", "COUPON", "WELCOME",
    "SUPPORT", "ACCOUNT", "DOWNLOAD", "PASSWORD", "USERNAME", "VERIFY", "PLEASE",
    "THANKS", "UPDATE", "VERSION",
})


def _plausible(code: str) -> bool:
    if not 4 <= len(code) <= 40:
        return False
    if code.upper() in _STOP:
        return False
    if _URLISH.match(code):
        return False
    if code.isdigit():  # 纯数字多半是价格或数量
        return False
    if not re.search(r"[A-Za-z]", code):  # 至少含一个字母
        return False
    return True


def extract_codes(title: str = "", content: str | None = None, limit: int = 6) -> list[str]:
    """返回去重后的凭据列表（最多 limit 个）。"""
    text = f"{title or ''} {content or ''}"
    found: list[str] = []

    def push(raw: str | None) -> None:
        value = re.sub(r"[.,;:)]}\"']+$", "", (raw or "").strip())
        if _plausible(value) and value not in found:
            found.append(value)

    for m in _EXPLICIT.finditer(text):
        push(m.group(1))
    for m in _DASHED.finditer(text):
        push(m.group(1))
    for m in _LONG_UPPER.finditer(text):
        push(m.group(1))

    return found[:limit]
