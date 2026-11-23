"""福利信号词与噪音标题判定：给羊毛/开源/促销条目分流用。

来自 freebie-radar 的 `enrich/noise.ts`。五套信号 + 一个综合判断：

    DEAL_HINT        真白嫖福利（领取/注册送/代金券…）
    PROMO_HINT       特价/黑五/VPS 优惠
    OPENSOURCE_HINT  开源项目/自托管工具
    NON_FREEBIE_HINT 纯资讯/测评（严格白嫖模式下排除）
    WIDE_AI_TRIGGER  泛资讯源进 AI 一审前的超宽松门禁
    URGENT           手慢无信号（命中即值得即时推）

为什么不直接复用 config/topics.yaml 的 deal_keywords：那份是给全站打标签用的，
口径偏「宽松覆盖」；这里的四套是给羊毛专线做「形态分流」用的，需要互斥且带反例。
两者用途不同，分开维护。

对位 freebie-radar 的 blocklist.ts：屏蔽词规则由后台配置驱动，
本项目在 `collector/blocklist.py`  providing 预设词表与匹配函数。
"""

from __future__ import annotations

import re

# 仅拦社区求助/抱怨水帖/常规补丁说明；不误杀重大新闻、财报、黑五、开源盘点
_NOISE_TITLE = re.compile(
    r"^(怎样|怎么|如何|哪里|哪个|为什么|为何)|请问|有没有|求推荐|求一个|哪里(?:有|能)|"
    r"值得买吗|怎么样\?|不够用|用完了|失效了|吐槽|踩坑|后悔|失望|谁有|求个|求购|哪有|"
    r"哪里有|多少钱|求助|求带|大佬|老哥|有人吗|有人知道|怎么弄|能白嫖吗|"
    r"免费更新|内容更新|版本更新|免费升级|更新公告|更新补丁|补丁说明|patch\s*notes|free\s+update",
    re.I,
)

# 显式 how-to 不被当成求助：带教程/攻略/步骤且有可领取对象
_HOWTO = re.compile(r"^(?:如何|怎么|怎样)")
_GUIDE = re.compile(r"教程|攻略|步骤|指南")
_ASK = re.compile(r"请问|求助|有没有|失效|[?？]")


def is_noise_title(title: str = "") -> bool:
    """社区求助/水帖/补丁说明才算噪音；显式教程不算。"""
    t = title or ""
    if _HOWTO.match(t) and _GUIDE.search(t) and not _ASK.search(t):
        # 有实际可领取/仓库信号时放行
        from .evidence import content_signals
        s = content_signals(t)
        if s["claim"] or s["repository"]:
            return False
    return bool(_NOISE_TITLE.search(t))


# 真白嫖福利（含「报名领/领积分/算力/代金券」等活动）
DEAL_HINT = re.compile(
    r"免费|领取|报名领|领积分|领额度|赠送|白嫖|白送|白给|零元|0\.01|试用|体验金|兑换|"
    r"激活码|注册送|限时|开放注册|额度|代金券|算力券|抵扣券|学生包|公测|内测|礼包|优惠券|"
    r"包邮|:free\b|(?:领|送)\s*\d+\s*(?:积分|算力|额度|tokens?|天|元|刀|美元)|"
    r"giveaway|coupon|free|credits|tokens",
    re.I,
)

# 特价/黑五/史低/VPS 优惠信号
PROMO_HINT = re.compile(
    r"黑五|black\s*friday|cyber\s*monday|双十一|双11|618|周年庆|特价|特惠|促销|折扣|史低|"
    r"最低价|优惠码|promo\s*code|年付|月付|折上折|\d+\s*折|%\s*off|clearance|flash\s*sale|"
    r"\$\d+(?:\.\d+)?/(?:yr|year|mo|month)|[¥￥]\d+|拼车|合租|车位|发车|明盘|出鸡|转让|"
    r"\b(?:vps|kvm|nat)\b.*(?:优惠|特价|折扣|促销|年付|\$\d)",
    re.I,
)

# 开源项目/自托管工具信号
OPENSOURCE_HINT = re.compile(
    r"开源|open\s*source|opensource|github\.com|gitlab\.com|self-?host(?:ed)?|自托管|自建服务|"
    r"mit\s*协议|apache\s*协议|gpl|开源项目|开源工具|开源软件|开源库|\bv\d+\.\d+\.\d+\b",
    re.I,
)

# 纯资讯/测评（严格白嫖模式下排除）
NON_FREEBIE_HINT = re.compile(
    r"盘点|评测|测评|涨价|降价|权益价|发布会|宣布|组建|规划|白皮书|开发者大会",
    re.I,
)

# 泛资讯源进 AI 一审前的超宽松触发门禁
WIDE_AI_TRIGGER = re.compile(
    r"免费|白嫖|限免|喜加一|赠送|送|领|白送|白给|抽奖|兑换|激活|邀请|体验|试用|优惠|特价|"
    r"促销|折扣|黑五|史低|年付|代金券|算力|积分|额度|token|credits|:free\b|0元|零元|0\.01|"
    r"\bfree\b|giveaway|coupon|promo|black\s*friday|开源|open\s*source|github|self-?host",
    re.I,
)

# 手慢无信号：命中就值得立刻推，不等攒批
URGENT = re.compile(
    r"先到先得|手慢无|名额有限|限量\s*\d|还剩\s*\d|仅剩|库存告急|cdk|cdkey|兑换码|激活码|"
    r"邀请码|免费领|白嫖|送码|送\s*\d+\s*(?:个|份|张|枚|次)|送体验金|送额度|赠送\s*\d|"
    r"抽\s*\d+\s*份|限时免费|限免"
)


def has_value_signal(title: str = "", kind: str | None = None) -> bool:
    """综合判断一条内容是否具备任一兴趣频道的价值信号。"""
    t = title or ""
    if kind == "deal":
        return bool(PROMO_HINT.search(t) or DEAL_HINT.search(t))
    if kind == "opensource":
        return bool(OPENSOURCE_HINT.search(t) or DEAL_HINT.search(t))
    if kind in ("news", "info"):
        return not is_noise_title(t)
    return bool(DEAL_HINT.search(t) or PROMO_HINT.search(t) or OPENSOURCE_HINT.search(t))
