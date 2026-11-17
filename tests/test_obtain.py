"""获取方式（obtain）判定：把「看着像白嫖」和「真能白拿」分开。

用例取自 freebie-radar 的 docs/obtain.md 正反例。
"""

from collector import obtain


def test_lottery_beats_free():
    assert obtain.guess("抽 200 份 Plus 会员") == obtain.LOTTERY
    assert obtain.guess("抽奖送一年会员") == obtain.LOTTERY
    assert obtain.guess("随机送 100 个激活码") == obtain.LOTTERY


def test_promo_beats_trial_and_free():
    # 「免费体验我们的服务」既是免费也是推广 —— 必须判推广
    assert obtain.guess("免费体验我们的服务") == obtain.PROMO
    assert obtain.guess("招募代理，注册送 $5") == obtain.PROMO


def test_trial():
    assert obtain.guess("7 天免费试用") == obtain.TRIAL
    assert obtain.guess("Azure 免费体验 30 天") == obtain.TRIAL
    assert obtain.guess("Free trial available now") == obtain.TRIAL


def test_conditional():
    assert obtain.guess("回帖送 $1 体验金") == obtain.CONDITIONAL
    assert obtain.guess("关注并转发即可领取") == obtain.CONDITIONAL
    assert obtain.guess("邀请好友注册送额度") == obtain.CONDITIONAL


def test_clean_free():
    assert obtain.guess("Epic 本周免费游戏") == obtain.FREE
    assert obtain.guess("Termini 永久 Pro 限免") == obtain.FREE


def test_labels_and_counts():
    assert obtain.label(obtain.LOTTERY) == "抽奖"
    assert obtain.hint(obtain.TRIAL)
    items = [
        {"title": "抽 200 份会员"},
        {"title": "Epic 免费游戏"},
        {"title": "Epic 免费游戏二"},
    ]
    c = obtain.counts(items)
    assert c[obtain.LOTTERY] == 1 and c[obtain.FREE] == 2
