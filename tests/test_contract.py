"""阶段之间的数据形状：Item 对象 vs dict。

这条测试来自一次真实事故：`pipeline.run()` 曾经在返回前就把条目转成了 dict，
于是 run.py 里后面三个阶段（评分 / 结构化 / 事件）拿到的都是 dict ——
`getattr(dict, "extra")` 得到 None，评分**静默地跑了 0 条**，另外两个直接抛异常，
而整轮仍然"成功"出了一份日报。

教训：阶段之间必须传同一种东西，而且传错了要炸，不能悄悄降级。
"""

import pytest

from collector import events, rating, structure
from collector.model import Item


def mk() -> Item:
    it = Item(source="thebatch", title="某模型发布新闻标题足够长",
              url="https://a/1", layer="primary", summary="摘要")
    it.extra["score"] = 70
    return it


def test_item_round_trips_through_dict():
    it = mk()
    it.extra["structure"] = {"category": "model_release"}
    back = Item.from_dict(it.to_dict())
    assert back == it
    assert back.extra["structure"]["category"] == "model_release"


def test_from_dict_tolerates_missing_fields():
    got = Item.from_dict({"title": "只有标题"})
    assert got.title == "只有标题"
    assert got.layer == "broad" and got.extra == {}


@pytest.mark.parametrize("stage", [rating.rate_items, structure.structure_items, events.cluster_items])
def test_stages_refuse_dicts_loudly(stage):
    """传 dict 必须抛错，而不是"跑完了 0 条"。"""
    with pytest.raises(TypeError):
        stage([{"title": "t", "url": "u", "extra": {}}])
