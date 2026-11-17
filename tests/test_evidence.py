"""分类证据校验：新闻不能因为来源是导购站就被当成促销。

用例取自 freebie-radar 的 docs/classification.md 正反例。
"""

from collector import evidence


def test_news_is_not_a_deal():
    # 航班停飞是新闻，不是促销 —— 即使出现在导购源里
    assert not evidence.is_deal_like("全美航班停飞4小时，普通旅客当天实际遇到了什么")
    # 财报里的金额不是售价
    assert not evidence.is_deal_like("某公司财报收入 $500 亿，同比增长 20%")
    # 期货/合约
    assert not evidence.is_deal_like("AI 算力开启金融化时代：芝商所拟推出两项期货合约")


def test_real_deal_passes():
    assert evidence.is_deal_like("航空公司限时特价机票，单程99元")
    assert evidence.is_deal_like("Epic 游戏免费入库")
    assert evidence.is_deal_like("黑五 VPS 年付 12 美元")


def test_freebie_needs_an_object():
    # 只有「免费」两个字不算福利
    assert not evidence.is_freebie("免费 AI 工具盘点：我用了三个月")
    assert evidence.is_freebie("Termini 永久 Pro 限免")
    assert evidence.is_freebie("GitHub 学生认证免费领开发者礼包")


def test_repository_signal():
    s = evidence.content_signals("开源项目 freebie-radar", "github.com/zi/freebie-radar")
    assert s["repository"]


def test_editorial_beats_sale_words():
    # 有「涨价」这类价格词，但整体是新闻
    assert not evidence.is_deal_like("某云厂商宣布涨价，套餐下架")
