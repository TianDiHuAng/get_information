"""价格提取：判定一条福利「要花多少钱」，用于「最高愿意支付」筛选。

来自 freebie-radar 的 `enrich/pricing.ts`。返回：

    price     归一化到人民币的金额；None 表示未知（不等于 0）
    currency  原始币种，便于展示
    is_free   明确免费 / 白嫖

两个关键防误判（照搬原实现的意图）：

1. `is_free` 只看标题——摘要里的「免费」多半在讲别的事
   （「京东 plus 准备不用了」不该被标成白嫖）。
2. `NEGATIVE` 上下文——「省 30 块」「原价 200」「股价」「满 100」里的数字不是售价。

价格取所有命中里**最小**的那个（最低门槛），USD 按固定汇率折算人民币。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

USD_TO_CNY = 7.2

_FREE = re.compile(
    r"免费|白嫖|(?:^|[^\d.])0(?:\.0+)?\s*元|零元|限免|白送|白给|免单|不要钱|"
    r"免费领|报名领|免费送|每天送|每日送|\bfree(?:bie)?\b",
    re.I,
)
_FAKE_FREE = re.compile(
    r"\bfree\s+(?:shipping|delivery|returns?|pickup|update)\b|"
    r"免运费|免邮|包邮|免费更新|免费升级",
    re.I,
)

# 只有这几种表达才是「你要付的钱」
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"[¥￥]\s*(\d+(?:\.\d+)?)"), "CNY"),
    (re.compile(r"(?:最低|仅需|只需|只要|低至|原价\s*)?\s*(\d+(?:\.\d+)?)\s*元\s*(?:起|购|入手|到手|拿下|带走)"), "CNY"),
    (re.compile(r"(?:最低|仅需|只需|只要|低至)\s*(\d+(?:\.\d+)?)\s*元"), "CNY"),
    (re.compile(r"\$\s*(\d+(?:\.\d+)?)"), "USD"),
)

_NEGATIVE = re.compile(
    r"省|贵|涨|降|价值|原价|满|返|抵|券|优惠|股价|市值|卖掉|售价为|售价约|"
    r"收入|亏|送|赠|抽|奖|赢|领取|获得|累计|最高"
)


@dataclass(frozen=True)
class PriceInfo:
    price: float | None
    currency: str | None
    is_free: bool


def _context_is_negative(text: str, index: int) -> bool:
    return bool(_NEGATIVE.search(text[max(0, index - 8):index]))


def extract_price(title: str = "", summary: str | None = None) -> PriceInfo:
    """从标题/摘要抽取价格；is_free 只看清洗后的标题。"""
    text = f"{title or ''} {summary or ''}"
    stripped_title = _FAKE_FREE.sub(" ", title or "")
    is_free = bool(_FREE.search(stripped_title))

    best: tuple[float, str] | None = None
    for pattern, currency in _PATTERNS:
        for m in pattern.finditer(text):
            try:
                raw = float(m.group(1))
            except (TypeError, ValueError):
                continue
            if not 0 < raw <= 1_000_000:
                continue
            if _context_is_negative(text, m.start()):
                continue
            cny = raw * USD_TO_CNY if currency == "USD" else raw
            if best is None or cny < best[0]:
                best = (cny, currency)

    if is_free:
        return PriceInfo(0.0, best[1] if best else "CNY", True)
    if best is None:
        return PriceInfo(None, None, False)
    return PriceInfo(round(best[0], 2), best[1], False)
