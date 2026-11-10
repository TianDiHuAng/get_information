"""评分器：权重合成、门槛、双次、降级。LLM 全部用假的，不联网、不花钱。"""

import pytest

from collector import rating
from collector.identity import item_identity
from collector.model import Item


def mk(source: str = "thebatch", layer: str = "primary", url: str = "https://a.com/1",
       title: str = "标题", summary: str = "摘要") -> Item:
    return Item(source=source, title=title, url=url, summary=summary, layer=layer)


@pytest.fixture(autouse=True)
def fake_llm(monkeypatch):
    """默认：预筛 PASS，两次评分都给高分。具体用例自己覆盖。"""
    monkeypatch.setattr(rating.llm, "available", lambda: True)

    def call_json(task, version, system, user, **kw):
        if task == "prefilter":
            return {"label": "PASS", "reason": "AI 相关"}
        return {"itype": "model_release", "sig": 9, "nov": 8, "cred": 7,
                "reson": 9, "act": 5, "reason": "正式发布新模型"}

    monkeypatch.setattr(rating.llm, "call_json", call_json)
    monkeypatch.setattr(rating.llm, "stats", lambda day=None: {"total": 3})
    return call_json


def test_weighted_score_uses_type_weights():
    weights = rating.config()["weights"]
    # model_release: 3*9+2*8+2*7+2*9+1*5 = 80
    assert rating.weighted_score({"sig": 9, "nov": 8, "cred": 7, "reson": 9, "act": 5},
                                 "model_release", weights) == 80
    # 同样的五轴按论文类型算：5*9+3*8+1*7+0*9+1*5 = 81（sig 与 nov 权重更高）
    assert rating.weighted_score({"sig": 9, "nov": 8, "cred": 7, "reson": 9, "act": 5},
                                 "research_paper", weights) == 81


def test_unknown_type_falls_back_instead_of_zero():
    weights = rating.config()["weights"]
    assert rating.weighted_score({"sig": 5, "nov": 5, "cred": 5, "reson": 5, "act": 5},
                                 "不存在的类型", weights) == 50


def test_axis_weights_sum_to_ten():
    for itype, table in rating.config()["weights"].items():
        assert sum(table.values()) == 10, itype


def test_threshold_by_layer_and_override():
    conf = rating.config()
    assert rating.threshold_for(mk(layer="primary"), conf) == conf["thresholds"]["primary"]
    assert rating.threshold_for(mk(layer="social"), conf) == conf["thresholds"]["social"]


def test_two_score_calls_use_distinct_receipt_variants(monkeypatch):
    """双次评分必须真的问两次。

    回执按"提示词+输入"去重，两次输入一模一样时第二次会直接命中第一次的回执
    —— 那就等于只问了一次，却按两次的门槛去判（实测 180 条里 147 条因此失败）。
    """
    seen = []
    monkeypatch.setattr(rating.llm, "available", lambda: True)

    def spy(task, version, system, user, **kw):
        seen.append(kw.get("variant"))
        return {"itype": "model_release", "sig": 8, "nov": 7, "cred": 6,
                "reson": 8, "act": 5, "reason": "x"}

    monkeypatch.setattr(rating.llm, "call_json", spy)
    item = mk()
    rating.score_once(item, 1)
    rating.score_once(item, 2)
    assert seen == ["call1", "call2"]


def test_rate_items_annotates_and_selects(tmpdb):
    item = mk()
    stats = rating.rate_items([item], ids={})
    assert stats["scored"] == 1 and stats["selected"] == 1
    att = item.extra["attention"]
    assert att["available"] is True
    assert att["score"] == 80
    assert att["calls"] == 2
    assert att["itype"] == "model_release"
    assert att["reason"] == "正式发布新模型"
    assert att["selected"] is True


def test_final_score_blends_attention_and_legacy(tmpdb):
    item = mk()
    item.extra["score"] = 50.0  # 老分
    rating.rate_items([item], ids={})
    # 0.8 * 80 + 0.2 * 50 = 74
    assert item.extra["score"] == 74.0
    assert item.extra["legacy_score"] == 50.0


def test_blocked_items_are_penalised_but_kept(tmpdb, monkeypatch):
    def blocked(task, version, system, user, **kw):
        return {"label": "BLOCK", "reason": "与 AI 无关"}

    monkeypatch.setattr(rating.llm, "call_json", blocked)
    item = mk()
    item.extra["score"] = 60.0
    stats = rating.rate_items([item], ids={})
    assert stats["blocked"] == 1
    assert item.extra["attention"]["label"] == "BLOCK"
    assert item.extra["score"] == 30.0  # 降权，但不出局（防预筛误杀）


def test_single_call_failure_keeps_legacy_score(tmpdb, monkeypatch):
    """两次里只成功一次 → 不算合格，保留老分。这是「宁可不评，也不能乱评」。"""
    calls = {"n": 0}

    def flaky(task, version, system, user, **kw):
        if task == "prefilter":
            return {"label": "PASS"}
        calls["n"] += 1
        if calls["n"] > 1:
            return None
        return {"itype": "model_release", "sig": 9, "nov": 8, "cred": 7,
                "reson": 9, "act": 5, "reason": "x"}

    monkeypatch.setattr(rating.llm, "call_json", flaky)
    item = mk()
    item.extra["score"] = 55.0
    stats = rating.rate_items([item], ids={})
    assert stats["failed"] == 1
    assert item.extra["attention"]["available"] is False
    assert item.extra["score"] == 55.0


def test_no_llm_means_no_change(tmpdb, monkeypatch):
    monkeypatch.setattr(rating.llm, "available", lambda: False)
    item = mk()
    item.extra["score"] = 47.0
    stats = rating.rate_items([item], ids={})
    assert stats["skipped"] == "no-llm"
    assert item.extra["score"] == 47.0
    assert "attention" not in item.extra


def test_malformed_axes_are_rejected_not_coerced(tmpdb, monkeypatch):
    def bad(task, version, system, user, **kw):
        if task == "prefilter":
            return {"label": "PASS"}
        return {"itype": "model_release", "sig": "很高", "nov": 8, "cred": 7, "reson": 9, "act": 5}

    monkeypatch.setattr(rating.llm, "call_json", bad)
    item = mk()
    item.extra["score"] = 40.0
    stats = rating.rate_items([item], ids={})
    assert stats["failed"] == 1
    assert item.extra["score"] == 40.0


def test_axes_are_clamped_to_0_10(tmpdb, monkeypatch):
    def wild(task, version, system, user, **kw):
        if task == "prefilter":
            return {"label": "PASS"}
        return {"itype": "model_release", "sig": 99, "nov": -5, "cred": 7, "reson": 9, "act": 5}

    monkeypatch.setattr(rating.llm, "call_json", wild)
    item = mk()
    rating.rate_items([item], ids={})
    axes = item.extra["attention"]["axes"]
    assert axes["sig"] == 10.0 and axes["nov"] == 0.0


def test_scores_are_written_to_store(tmpdb):
    item = mk()
    store_ids = None
    from collector import store
    store.upsert_items([item])
    store_ids = store.ids_for([item_identity(item.url)])
    stats = rating.rate_items([item], ids=store_ids)
    assert stats["scored"] == 1
    dist = store.score_distribution()
    assert dist["count"] == 2  # 两次调用各留一条痕
