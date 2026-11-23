"""价格提取：把「要付多少钱」和「新闻里的金额」分开。

用例取自 freebie-radar 的 enrich/pricing.ts 正负例。
"""

from collector import pricing


def test_free_only_from_title():
    r = pricing.extract_price("Termini 永久 Pro 限免", "原价 200 元，现在免费")
    assert r.is_free and r.price == 0.0
    # 摘要里的免费不算：标题没说免费
    r2 = pricing.extract_price("京东 plus 准备不用了", "虽然免费但没用")
    assert not r2.is_free


def test_fake_free():
    assert not pricing.extract_price("免运费的耳机 99 元").is_free
    assert not pricing.extract_price("Free shipping on all orders").is_free


def test_extracts_minimum_price():
    r = pricing.extract_price("VPS 年付 $12", "原价 200 元")
    assert r.currency == "USD" and r.price == 12 * pricing.USD_TO_CNY
    r2 = pricing.extract_price("特价机票，仅需 99 元")
    assert r2.currency == "CNY" and r2.price == 99.0


def test_negative_context():
    # 省 30 元、股价 500、满 100 —— 都不是售价
    assert pricing.extract_price("省 30 元的耳机").price is None
    assert pricing.extract_price("某公司股价 500 元").price is None
    assert pricing.extract_price("满 100 元可用券").price is None


def test_unknown():
    r = pricing.extract_price("开源项目发布新版本")
    assert r.price is None and not r.is_free and r.currency is None
