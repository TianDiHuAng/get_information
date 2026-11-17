"""分类证据校验：从**内容本身**判断它是不是促销/福利，而不是相信来源名。

来自 freebie-radar 的 `enrich/evidence.ts`。核心是三组正交信号：

    claim       有可领取/免费使用的对象（「免费领」「限免」「兑换码」）
    promotion   有价格/促销证据（「99 元」「5 折」「黑五」）
    editorial   是新闻/评论（「财报」「营收」「股价」「停飞」「发布会」）

`editorial` 一旦成立且没有 claim/sale，就不能算促销。
新闻里出现的金额（营收、亏损、成交额）**不是售价** —— 这是最容易错判的一类。

为什么不直接相信来源：导购站也会发新闻，新闻站也会发真促销。
所以只认标题/摘要里的证据。
"""

from __future__ import annotations

import re

_CLAIM = re.compile(
    r"免费(?:领|送|获|拿|使用|开放|下载|入库)|领取|报名领|白嫖|白送|白给|白拿|薅羊毛|"
    r"羊毛线报|BOGO|零元|0\s*元|限免|喜加一|赠送|激活码|兑换码|公益额度|"
    r"(?:领|送)\s*\d+(?:[-~至]\d+)?\s*(?:元|话费|积分|额度|tokens?)|"
    r"(?:免费|赠|送|领).{0,16}(?:额度|积分|token|credits|授权|礼包|券)|"
    r"free\s+(?:trial|game|software|license|credits|tier|model)|giveaway|coupon",
    re.I)

_SPECIFIC_FREE = re.compile(
    r"free\s+to\s+keep|is\s+free.{0,20}(?:Epic|Steam|GOG)|"
    r"(?:游戏|软件|授权|会员|模型).{0,10}免费|免费.{0,10}(?:游戏|软件|授权|会员|模型)",
    re.I)

_SALE = re.compile(
    r"特价|特惠|促销|折扣|史低|优惠券|优惠码|黑五|black\s*friday|cyber\s*monday|"
    r"%\s*off|(?:sale|clearance)|\d+(?:\.\d+)?\s*折|年付|月付|元[/每](?:月|年)|"
    r"美元[/每](?:月|年)|\d+(?:\.\d+)?\s*元(?:起|购|到手|包邮)|"
    r"(?:仅需|只要|低至|现价)\s*\d+|[$¥￥]\s*\d|"
    r"拼车|合租|车位|发车|明盘|出鸡|转让|出个|出售",
    re.I)

# 新闻/评论特征：出现这些词基本可以确定不是促销
_EDITORIAL = re.compile(
    r"停飞|停航|航班.{0,8}(?:取消|延误)|空难|坠机|遇难|伤亡|地震|战争|爆炸|罢工|"
    r"旅客.{0,8}(?:遭遇|遇到)|财报|营收|净利润|股价|通胀|降息|政策|新规|召回|事故|"
    r"发布会|新闻|报道|记者|宣布涨价|套餐下架|机房动态|月度汇总|活动回顾|"
    r"为什么|到底|实际遇到|期货|合约|上市|融资|估值|裁员|高管|离职|"
    # 分析/盘点类：讲的是"怎么算账"，不是"哪里能领"
    r"成本账|成本结构|抽成|变现|商业模式|行业分析|盘点|测评|拆解|解读|白皮书|研究报告")

# 强特征：这些词一出现，基本可以断定是分析/评论而不是福利
# （即使标题里带「免费 Token」，那也常常是在讨论成本，不是在发福利）
_STRONG_EDITORIAL = re.compile(
    r"成本账|成本结构|抽成|变现|商业模式|行业分析|白皮书|研究报告|"
    r"财报|营收|净利润|股价|期货|合约|裁员|高管|离职|召回|事故")

_REPOSITORY = re.compile(
    r"github\.com/[^/\s]+/[^/\s]+|gitlab\.com/[^/\s]+/[^/\s]+|开源|open[\s-]*source|"
    r"自托管|self-?host|源码|MIT\s*协议|Apache\s*协议",
    re.I)


def _clean(value: str) -> str:
    return re.sub(r"https?://\S+", " ", value or "")[:2000]


def content_signals(title: str = "", summary: str = "") -> dict[str, bool]:
    t = _clean(title)
    text = f"{t} {_clean(summary)}"
    title_claim = bool(_CLAIM.search(t) or _SPECIFIC_FREE.search(t))
    title_sale = bool(_SALE.search(t))
    editorial = bool(_STRONG_EDITORIAL.search(t)) or (
        bool(_EDITORIAL.search(t)) and not title_claim)
    promotion = (not editorial) and (title_sale or bool(_SALE.search(text)))
    return {
        "claim": title_claim or (not editorial and bool(_CLAIM.search(text))),
        "promotion": promotion,
        "editorial": editorial,
        "repository": bool(_REPOSITORY.search(text)),
    }


def is_deal_like(title: str = "", summary: str = "") -> bool:
    """有福利或促销证据，且不是新闻/评论。"""
    s = content_signals(title, summary)
    return (s["claim"] or s["promotion"]) and not s["editorial"]


def is_freebie(title: str = "", summary: str = "") -> bool:
    """明确有可领取的对象（不是只有「免费」两个字）。"""
    s = content_signals(title, summary)
    return s["claim"] and not s["editorial"]
