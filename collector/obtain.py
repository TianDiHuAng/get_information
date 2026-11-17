"""获取方式（obtain）：把「不算完全白嫖」的东西单独隔离。

来自 freebie-radar 的一个正交维度。价格只回答「要不要钱」，回答不了
「能不能确定拿到」——「抽 200 份会员」「免费试用 7 天」「注册送体验金但充值才用」
在价格上都写 0 元，但一个是抽签、一个到期收费、一个是广告。

判定顺序有意为之：抽奖 > 推广 > 试用 > 有条件 > free。
「免费体验我们的服务」既匹配免费也匹配推广，必须判 promo。
"""

from __future__ import annotations

import re

FREE = "free"
CONDITIONAL = "conditional"
LOTTERY = "lottery"
TRIAL = "trial"
PROMO = "promo"
PAID = "paid"

ORDER = (FREE, CONDITIONAL, LOTTERY, TRIAL, PROMO, PAID)

LABEL = {
    FREE: "直接白嫖",
    CONDITIONAL: "有条件",
    LOTTERY: "抽奖",
    TRIAL: "试用",
    PROMO: "推广",
    PAID: "需付费",
}

HINT = {
    FREE: "点开就能领，不需要附加动作",
    CONDITIONAL: "要回帖/转发/关注/邀请/绑卡",
    LOTTERY: "抽名额，不一定轮到你",
    TRIAL: "免费试用 N 天，到期收费",
    PROMO: "福利只是引流钩子",
    PAID: "需要实付",
}

#: 只有这一种算「完全白嫖」。
CLEAN = (FREE,)

_LOTTERY = re.compile(
    r"抽奖|抽\s*\d+\s*(份|个|名|位)|抽取|随机送|开奖|中奖|摇号|锦鲤|"
    r"抽\s*\d+|名额有限.*抽|抽名额")
_PROMO = re.compile(
    r"招募|代理|加盟|官方旗舰|我们的服务|自营|软广|推广位|商务合作|招商|诚招|"
    r"带货|优惠码.*分成")
_TRIAL = re.compile(
    r"试用|免费体验\s*\d+\s*天|首月免费|首月\s*\d|体验期|试用期|免费体验卡|"
    r"7\s*天免费|30\s*天免费|\bfree\s+trial\b|\bdemo\b.*\bfree\b|\bfree\b.*\bdemo\b",
    re.I)
_CONDITIONAL = re.compile(
    r"回帖|盖楼|转发|关注.*领取|邀请|拉新|实名|绑卡|下单|首单|充值|发帖|"
    r"评论.*领取|签到.*领|分享.*得")
_PRICE = re.compile(
    r"[$¥￥]\s*\d|\d+\s*元|\d+\s*美元|价格|售价|原价|现价|到手价|折扣|特价")


def guess(title: str = "", summary: str = "") -> str:
    """规则兜底：AI 没结论时按关键词粗分。"""
    t = f"{title} {summary}"
    if _LOTTERY.search(t):
        return LOTTERY
    if _PROMO.search(t):
        return PROMO
    if _TRIAL.search(t):
        return TRIAL
    if _CONDITIONAL.search(t):
        return CONDITIONAL
    return FREE


def label(value: str) -> str:
    return LABEL.get(value or "", LABEL[FREE])


def hint(value: str) -> str:
    return HINT.get(value or "", "")


def counts(items: list[dict]) -> dict[str, int]:
    """按获取方式统计条数（给页面顶部的小结用）。"""
    out = {k: 0 for k in ORDER}
    for it in items:
        key = it.get("obtain") or guess(str(it.get("title") or ""), str(it.get("summary") or ""))
        out[key] = out.get(key, 0) + 1
    return out
