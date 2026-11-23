"""福利信号词与噪音判定（来自 freebie-radar 的 enrich/noise.ts）。"""

from collector import noise


def test_noise_title():
    assert noise.is_noise_title("请问这个怎么领？")
    assert noise.is_noise_title("求助！兑换码失效了")
    assert noise.is_noise_title("版本更新补丁说明")
    assert not noise.is_noise_title("黑五 VPS 年付 12 美元")
    assert not noise.is_noise_title("Epic 本周免费游戏")


def test_howto_exception():
    # 带教程/步骤且有领取信号 → 不算噪音
    assert not noise.is_noise_title("如何领取免费额度：三步教程")
    # 纯提问即使带「如何」也算
    assert noise.is_noise_title("如何领取？求教程")


def test_signals():
    assert noise.DEAL_HINT.search("报名领算力券")
    assert noise.PROMO_HINT.search("黑五 3 折")
    assert noise.OPENSOURCE_HINT.search("自托管工具 self-hosted")
    assert noise.NON_FREEBIE_HINT.search("AI 工具盘点")
    assert noise.URGENT.search("手慢无，仅剩 10 份")


def test_has_value_signal():
    assert noise.has_value_signal("限时免费领取会员", "deal")
    assert not noise.has_value_signal("请问有人知道吗", "news")
    assert noise.has_value_signal("开源项目 github.com/x/y", "opensource")
